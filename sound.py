"""Sound direction finding with the Kinect v1's 4-microphone array.

Two estimators, both from the same FFT of the 4 channels:

* SRP-PHAT (steered response power, phase transform): for every candidate
  angle, align all 6 microphone pairs as if the sound came from there and
  measure how well they agree. Robust main direction.
* Per-frequency directions -> histogram: different talkers dominate different
  frequency bins at any moment, so estimating a direction per bin and
  collecting the votes over ~0.5 s shows several simultaneous sources as
  separate peaks. Those peaks become tracked "sources" (the dots in the UI).

A focus beam (delay-and-sum toward a chosen angle, e.g. the tracked face)
measures how loud it is *in that direction*, so "focus on me" ignores other
people and noises.

The mics sit on a straight line, so all of this is horizontal angle only.
"""
import math

import numpy as np

RATE = 16000
C = 343.0                                            # speed of sound, m/s
MIC_X = np.array([-0.113, 0.036, 0.076, 0.113])      # mic positions along the bar (m)
PAIRS = [(i, j) for i in range(4) for j in range(i + 1, 4)]
FOCAL_PX = 525.0                                     # Kinect RGB focal length at 640x480


# Calibration (set from settings by the app, measured by calibrate_mic.py):
# camera angle = GAIN * sign * mic angle + OFFSET  (degrees)
GAIN = 1.0
OFFSET = 0.0


def set_calibration(gain=1.0, offset=0.0):
    global GAIN, OFFSET
    GAIN = float(gain) if gain else 1.0
    OFFSET = float(offset or 0.0)


def angle_to_image_x(angle, sign=1.0, width=640):
    a = max(-80.0, min(80.0, GAIN * sign * angle + OFFSET))
    return width / 2 + FOCAL_PX * math.tan(math.radians(a)) * (width / 640)


def image_x_to_angle(x, sign=1.0, width=640):
    cam = math.degrees(math.atan((x - width / 2) / (FOCAL_PX * width / 640)))
    return sign * (cam - OFFSET) / GAIN


class SoundLocator:
    N = 1024                 # 64 ms analysis window
    BAND = (300.0, 4000.0)   # speech band
    MIN_COHERENCE = 0.08
    HIST_DECAY = 0.86        # per update (~30/s): votes fade over ~0.3 s
    SOURCE_TIMEOUT = 1.2     # s a source stays on screen after it goes quiet
    MAX_SOURCES = 4
    PEAK_REL = 0.5           # a source must reach this fraction of the strongest one
    PEAK_SEP = 15.0          # degrees between separate sources

    def __init__(self):
        self.angles_deg = np.arange(-90, 91, 1.0)
        self.angles = np.radians(self.angles_deg)
        freqs = np.fft.rfftfreq(self.N, 1.0 / RATE)
        self.band = (freqs >= self.BAND[0]) & (freqs <= self.BAND[1])
        self.f = freqs[self.band]
        dx = np.array([MIC_X[i] - MIC_X[j] for i, j in PAIRS])
        # steering[p, a, f]: undo the delay pair p would see from angle a
        self.steer = np.exp(-2j * np.pi * self.f[None, None, :] * dx[:, None, None] *
                            np.sin(self.angles)[None, :, None] / C)
        self.win = np.hanning(self.N).astype(np.float32)[:, None]
        k = np.exp(-0.5 * (np.arange(-8, 9) / 3.0) ** 2)
        self.smooth_k = k / k.sum()
        self.acc = np.zeros(len(self.angles))
        self.hist = np.zeros(len(self.angles))
        self.floor_db = None
        self.focus_floor_db = None
        self.level_db = -120.0
        self.focus_level_db = None
        self.speaking = False
        self.angle = None          # main direction, degrees; + = toward mic 4
        self.confidence = 0.0
        self.sources = []          # [{"id", "angle", "strength", "t"}]
        self._next_id = 1
        self._quiet_frames = 99

    # ------------------------------------------------------------------ core
    def _pair_phat(self, X):
        G = np.empty((len(PAIRS), X.shape[0]), complex)
        for p, (i, j) in enumerate(PAIRS):
            g = X[:, i] * np.conj(X[:, j])
            G[p] = g / (np.abs(g) + 1e-12)
        return G

    def spectrum(self, x):
        """Normalised SRP-PHAT response over self.angles for one window (N, 4)."""
        X = np.fft.rfft(x * self.win, axis=0)[self.band]
        G = self._pair_phat(X)
        return np.einsum("paf,pf->a", self.steer, G).real / (len(PAIRS) * len(self.f))

    def _per_bin_votes(self, X, G):
        """Direction of every frequency bin, weighted by how clearly it points somewhere."""
        R = np.einsum("paf,pf->af", self.steer, G).real / len(PAIRS)     # (A, F), max 1
        best = np.argmax(R, axis=0)
        coh = R[best, np.arange(R.shape[1])]
        energy = (np.abs(X) ** 2).sum(axis=1)
        w = np.clip(coh, 0, 1) ** 3 * np.log1p(energy / (np.median(energy) + 1e-20))
        return np.bincount(best, weights=w, minlength=len(self.angles))

    def _beam_db(self, X, angle_deg):
        """Delay-and-sum beam toward angle: level of sound coming from there."""
        t = -MIC_X * math.sin(math.radians(angle_deg)) / C              # arrival times
        Y = (X * np.exp(2j * np.pi * self.f[:, None] * t[None, :])).sum(axis=1) / 4
        return 10 * math.log10(float(np.mean(np.abs(Y) ** 2)) / self.N + 1e-20)

    @staticmethod
    def _track_floor(floor, level):
        if floor is None:
            return level
        rate = 0.3 if level < floor else 0.002   # follows quiet fast, loud very slowly
        return floor + (level - floor) * rate

    # ---------------------------------------------------------------- update
    def update(self, x, now, focus_angle=None, focus_width=12.0):
        """Feed the most recent audio (shape (n, 4), n >= N).

        focus_angle: if given (degrees, mic convention), only sound from within
        +-focus_width of it counts as speech and as a source ("focus on me")."""
        if x is None or len(x) < self.N:
            return
        x = x[-self.N:]
        rms = float(np.sqrt(np.mean(x ** 2)) + 1e-12)
        self.level_db = 20 * math.log10(rms)
        self.floor_db = self._track_floor(self.floor_db, self.level_db)
        X = np.fft.rfft(x * self.win, axis=0)[self.band]

        if focus_angle is not None:
            self.focus_level_db = self._beam_db(X, focus_angle)
            self.focus_floor_db = self._track_floor(self.focus_floor_db, self.focus_level_db)
            loud = self.focus_level_db > self.focus_floor_db + 8.0
        else:
            self.focus_level_db = None
            loud = self.level_db > self.floor_db + 8.0

        if loud or (focus_angle is not None and self.level_db > self.floor_db + 8.0):
            G = self._pair_phat(X)
            resp = np.einsum("paf,pf->a", self.steer, G).real / (len(PAIRS) * len(self.f))
            votes = self._per_bin_votes(X, G)
        else:
            resp = votes = None

        if loud and resp is not None:
            self.acc = 0.7 * self.acc + 0.3 * resp
            self._quiet_frames = 0
        else:
            self.acc *= 0.93
            self._quiet_frames += 1
        self.hist *= self.HIST_DECAY
        if votes is not None:
            self.hist += votes

        peak = int(np.argmax(self.acc))
        self.confidence = float(self.acc[peak])
        self.speaking = loud or self._quiet_frames < 8      # hold ~0.25 s through pauses
        self.angle = float(self.angles_deg[peak]) if self.confidence > self.MIN_COHERENCE else None
        if focus_angle is not None and self.angle is not None and abs(self.angle - focus_angle) > focus_width:
            self.angle = None
        self._update_sources(now, focus_angle, focus_width)

    def _peaks(self):
        h = np.convolve(self.hist, self.smooth_k, mode="same")
        top = float(h.max())
        if top < 0.6:          # not enough votes for anything
            return []
        cand = [i for i in range(1, len(h) - 1) if h[i] >= h[i - 1] and h[i] > h[i + 1] and h[i] > self.PEAK_REL * top]
        cand.sort(key=lambda i: -h[i])
        out = []
        for i in cand:
            if all(abs(self.angles_deg[i] - self.angles_deg[j]) >= self.PEAK_SEP for j, _ in out):
                out.append((i, h[i] / top))
            if len(out) >= self.MAX_SOURCES:
                break
        return [(float(self.angles_deg[i]), float(s)) for i, s in out]

    def _update_sources(self, now, focus_angle, focus_width):
        peaks = self._peaks()
        if focus_angle is not None:
            peaks = [(a, s) for a, s in peaks if abs(a - focus_angle) <= focus_width]
        used = set()
        for a, strength in peaks:
            best, bd = None, 10.0
            for src in self.sources:
                d = abs(src["angle"] - a)
                if d < bd and src["id"] not in used:
                    best, bd = src, d
            if best is None:
                best = {"id": self._next_id, "angle": a, "strength": strength, "t": now, "born": now}
                self._next_id += 1
                self.sources.append(best)
            else:
                best["angle"] += (a - best["angle"]) * 0.35
                best["strength"] += (strength - best["strength"]) * 0.4
                best["t"] = now
            used.add(best["id"])
        if focus_angle is not None:
            self.sources = [s for s in self.sources if abs(s["angle"] - focus_angle) <= focus_width + 4]
        self.sources = [s for s in self.sources if now - s["t"] < self.SOURCE_TIMEOUT]

    # --------------------------------------------------------------- helpers
    def image_x(self, sign=1.0, width=640):
        """Where the main sound comes from in the colour image (x pixel), or None."""
        return None if self.angle is None else angle_to_image_x(self.angle, sign, width)
