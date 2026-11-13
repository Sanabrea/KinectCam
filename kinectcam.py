#!/usr/bin/env python3
"""KinectCam — use a Kinect v1 (Xbox 360) as a macOS webcam.

Video goes out through the OBS Virtual Camera, so it shows up as "OBS Virtual
Camera" in Zoom, Teams, Meet, FaceTime, OBS itself, etc.

Features
  * Auto-framing "follow" camera: digital pan/zoom that keeps you centred,
    plus the Kinect's tilt motor when you leave the vertical range.
  * Background blur / remove / replace using the depth sensor (no AI model).
  * Night-vision mode (the IR camera) and a colourised depth view.
  * Manual pan, zoom, tilt; LED control; auto-level from the accelerometer;
    low-light enhancement; mirror.

Run:  ./run.sh            (or .venv/bin/python kinectcam.py --help)
"""
import argparse
import json
import math
import os
import sys
import threading
import time

IS_WIN = sys.platform == "win32"
IS_MAC = sys.platform == "darwin"
if IS_WIN:
    print(f"[start] Python {sys.version.split()[0]} on Windows, app files: {os.path.dirname(os.path.abspath(__file__))}",
          flush=True)
if IS_WIN and not os.environ.get("KINECTCAM_RUNTIME"):
    # derive the package layout from this file if the launcher's variables didn't arrive
    _rt = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if os.path.isdir(os.path.join(_rt, "lib")):
        os.environ["KINECTCAM_RUNTIME"] = _rt
        os.environ.setdefault("KINECTCAM_LIBDIR", os.path.join(_rt, "lib"))
        os.environ.setdefault("KINECTCAM_APP", "1")
        if os.environ.get("APPDATA"):
            os.environ.setdefault("KINECTCAM_DATA", os.path.join(os.environ["APPDATA"], "KinectCam"))
if IS_WIN and os.environ.get("KINECTCAM_RUNTIME"):
    # bundled Microsoft C++ runtime (msvcp140.dll) and the Kinect libraries
    for _d in ("python", "lib"):
        _p = os.path.join(os.environ["KINECTCAM_RUNTIME"], _d)
        if os.path.isdir(_p):
            os.add_dll_directory(_p)

if IS_WIN:
    print("[start] loading OpenCV + numpy...", flush=True)
import cv2
import numpy as np
if IS_WIN:
    print(f"[start] OpenCV {cv2.__version__}, numpy {np.__version__} ok; loading the Kinect driver...", flush=True)

import kinect_device as fk
if IS_WIN:
    print("[start] libfreenect ok", flush=True)

HERE = os.path.dirname(os.path.abspath(__file__))
# Settings/lock live next to the code, or in ~/Library/Application Support/KinectCam
# when running as KinectCam.app (the app bundle itself must stay read-only).
DATA = os.environ.get("KINECTCAM_DATA") or HERE
os.makedirs(DATA, exist_ok=True)
SETTINGS_FILE = os.path.join(DATA, "settings.json")
IN_APP = bool(os.environ.get("KINECTCAM_APP"))


def app_alert(message, wait=True):
    """A pop-up (only when running as the app, where there is no terminal)."""
    if not IN_APP:
        return
    if IS_WIN:
        import ctypes
        box = lambda: ctypes.windll.user32.MessageBoxW(None, message, "KinectCam", 0x40 | 0x10000)  # noqa: E731
        box() if wait else threading.Thread(target=box, daemon=True).start()
        return
    import json as _json
    import subprocess
    script = f'display alert "KinectCam" message {_json.dumps(message)}'
    try:
        (subprocess.run if wait else subprocess.Popen)(["osascript", "-e", script])
    except Exception:  # noqa: BLE001
        pass


_splash_last = [[], (200, 200, 200)]


def ask_yes_no(message, yes="Download", no="Not now"):
    """Native Yes/No question. Returns True for yes."""
    try:
        if IS_WIN:
            import ctypes
            return ctypes.windll.user32.MessageBoxW(None, message, "KinectCam", 0x4 | 0x20 | 0x10000) == 6
        if IS_MAC:
            import json as _json
            import subprocess
            script = (f'button returned of (display dialog {_json.dumps(message)} with title "KinectCam" '
                      f'buttons {{{_json.dumps(no)}, {_json.dumps(yes)}}} default button {_json.dumps(yes)})')
            r = subprocess.run(["osascript", "-e", script], capture_output=True, text=True)
            return r.stdout.strip() == yes
    except Exception:  # noqa: BLE001
        pass
    return False


# microphone status shown on the button and in the status line
MIC_UI = {"state": "off", "text": "mic off"}

FW_QUESTION = ("Turn on the Kinect's microphones?\n\n"
               "The Kinect's 4-microphone array needs a small firmware file from Microsoft. "
               "KinectCam can download it now from Microsoft's official Xbox update "
               "(about 116 MB, once).\n\n"
               "Without it everything else works; only the sound features "
               "(sound dots, mic focus, voice steer) stay off. "
               "You can get it later with the \"Get mic support\" button.")


def splash(win, lines, color=(200, 200, 200)):
    """Full-window message while starting. lines=None just repaints (keeps the window alive)."""
    if lines is None:
        lines, color = _splash_last
    else:
        _splash_last[:] = [lines, color]
    img = np.full((PREVIEW_H + PANEL_H, PREVIEW_W, 3), 26, np.uint8)
    cv2.putText(img, "KinectCam", (PREVIEW_W // 2 - 150, 230), cv2.FONT_HERSHEY_SIMPLEX, 1.8,
                (110, 240, 110), 3, cv2.LINE_AA)
    for i, line in enumerate(lines):
        (tw, _), _ = cv2.getTextSize(line, cv2.FONT_HERSHEY_SIMPLEX, 0.7, 1)
        cv2.putText(img, line, ((PREVIEW_W - tw) // 2, 300 + i * 38), cv2.FONT_HERSHEY_SIMPLEX, 0.7,
                    color, 1, cv2.LINE_AA)
    cv2.imshow(win, img)
    cv2.waitKey(1)

SRC_W, SRC_H = 640, 480
MODES = ["color", "night", "depth"]
BACKGROUNDS = ["none", "blur", "solid", "image"]
LEDS = [fk.LED_GREEN, fk.LED_YELLOW, fk.LED_RED, fk.LED_BLINK_GREEN, fk.LED_OFF]

# arrow keys as reported by cv2.waitKeyEx
if IS_WIN:
    K_UP, K_DOWN, K_LEFT, K_RIGHT = 0x260000, 0x280000, 0x250000, 0x270000
else:
    K_UP, K_DOWN, K_LEFT, K_RIGHT = 63232, 63233, 63234, 63235


DEFAULTS = {
    "mode": "color",
    "follow": True,
    "background": "none",
    "bg_color": [40, 120, 40],  # BGR
    "bg_image": "",
    "zoom": 1.0,
    "enhance": False,
    "level": False,
    "mirror": False,
    "tilt": 0,
    "led": fk.LED_GREEN,
    "follow_tightness": 1.0,  # >1 zooms in more on you
    "hd": False,              # 1280x1024 colour camera (sharper, 10 fps)
    "voice_steer": False,     # follow whoever is talking (mic array)
    "auto_exposure": True,
    "auto_wb": True,
    "grid": False,            # angle grid + rule of thirds on the preview
    "sound_dots": True,       # mark sound sources on the preview
    "mic_focus": "all",       # "all": every sound around; "me": only sound from the tracked person
    "mic_sign": -1,           # -1: positive voice angles are on the LEFT of the image (Kinect 1414)
    "mic_gain": 1.0,          # angle scale/offset from the Calibrate mic wizard
    "mic_offset": 0.0,
    "mic_fw_declined": False, # said "Not now" to downloading the mic firmware from Microsoft
}


def load_settings():
    s = dict(DEFAULTS)
    try:
        with open(SETTINGS_FILE) as f:
            s.update({k: v for k, v in json.load(f).items() if k in DEFAULTS})
    except (OSError, ValueError):
        pass
    return s


def save_settings(s):
    try:
        with open(SETTINGS_FILE, "w") as f:
            json.dump(s, f, indent=2)
    except OSError:
        pass


# ---------------------------------------------------------------- capture ---
class Capture:
    """Frames from the Kinect device thread (kinect_device.py), converted to BGR.

    The device thread owns libfreenect and recovers on its own when the camera
    stops streaming, so the UI never blocks on the hardware."""

    # A 640x480 frame is the top 1280x960 of the HD frame at half size (measured
    # on this Kinect: scale 0.5002, offset -1.27/-0.51 px).
    HD_OFFSET = (1.27, 0.51)

    def __init__(self, mode, hd=False):
        self.hd = hd
        self.dev = fk.start("night" if mode == "night" else "color", high_res=hd)
        self._mode = mode

    @property
    def mode(self):
        return self._mode

    @mode.setter
    def mode(self, m):
        self._mode = m
        # depth view still shows the colour camera underneath (for tracking)
        self.dev.set_mode("night" if m == "night" else "color", high_res=self.hd)

    def set_hd(self, on):
        self.hd = on
        self.dev.set_mode("night" if self._mode == "night" else "color", high_res=on)

    @property
    def state(self):
        return self.dev.state

    def latest(self):
        """-> (full-res BGR frame, 640x480 BGR frame, depth, timestamp).
        Tracking, depth and masks work at 640x480; the output is cropped from
        the full-res frame (the same frame unless HD is on)."""
        v, d, t = self.dev.latest()
        if v is None:
            return None, None, d, t
        if v.ndim == 2:
            # IR is 640x488; the bottom 8 rows have no matching depth/colour pixels
            v = cv2.cvtColor(v[:SRC_H], cv2.COLOR_GRAY2BGR)
            return v, v, d, t
        v = cv2.cvtColor(v, cv2.COLOR_RGB2BGR)
        if v.shape[1] == SRC_W:
            return v, v, d, t
        vga = cv2.resize(v[: v.shape[1] * 3 // 4], (SRC_W, SRC_H), interpolation=cv2.INTER_AREA)
        return v, vga, d, t


# ---------------------------------------------------------------- tracker ---
class Tracker:
    """Finds the person to follow: face detector first, depth blob fallback."""

    def __init__(self):
        path = os.path.join(cv2.data.haarcascades, "haarcascade_frontalface_default.xml")
        self.face = cv2.CascadeClassifier(path)
        self.profile = cv2.CascadeClassifier(os.path.join(cv2.data.haarcascades, "haarcascade_profileface.xml"))
        self.head_cut = False  # True when the person's head is above the sensor's view
        self.last = None  # (cx, cy, size, depth_mm) in source pixels
        self.last_seen_t = 0.0
        self.last_face = None
        self.last_face_t = 0.0
        self.prefer_x = None   # set by voice steering
        self.faces = []

    FACE_HOLD_S = 0.8   # keep the last face this long when the detector misses a frame
    LOST_HOLD_S = 2.5   # keep the last target this long when nothing is found at all

    def detect(self, bgr, depth, now=None):
        now = time.time() if now is None else now
        gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
        gray = cv2.equalizeHist(gray)
        faces = list(self.face.detectMultiScale(gray, scaleFactor=1.15, minNeighbors=6, minSize=(40, 40)))
        if not faces:  # side view: the profile cascade only finds left-facing, so try both flips
            faces = list(self.profile.detectMultiScale(gray, scaleFactor=1.15, minNeighbors=5, minSize=(40, 40)))
            for x, y, w, h in self.profile.detectMultiScale(cv2.flip(gray, 1), scaleFactor=1.15,
                                                            minNeighbors=5, minSize=(40, 40)):
                faces.append((SRC_W - x - w, y, w, h))
        self.head_cut = False
        self.faces = [tuple(map(float, f)) for f in faces]
        target = None
        if len(faces):
            # Prefer the face nearest to the previous target, else the largest.
            def score(f):
                x, y, w, h = f
                if self.prefer_x is not None:          # voice steering: who is talking?
                    return abs(x + w / 2 - self.prefer_x)
                if self.last is None:
                    return -w * h
                return math.hypot(x + w / 2 - self.last[0], y + h / 2 - self.last[1]) - w
            x, y, w, h = min(faces, key=score)
            dmm = _median_depth(depth, x, y, w, h)
            target = (x + w / 2, y + h / 2, float(w), dmm)
            self.last_face, self.last_face_t = target, now
        elif self.last_face is not None and now - self.last_face_t < self.FACE_HOLD_S:
            # The cascade misses the odd frame; don't flip to the (offset) depth
            # estimate for a single frame, that is what made the framing twitch.
            target = self.last_face
        else:
            target = self._depth_head(depth)
        if target is None:
            if self.last is not None and now - self.last_seen_t > self.LOST_HOLD_S:
                self.last = None
            return self.last
        self.last_seen_t = now
        self.last = target
        return target

    def shift(self, dy):
        """The motor moved the sensor: move remembered positions with the scene."""
        if self.last is not None:
            self.last = (self.last[0], self.last[1] + dy) + tuple(self.last[2:])
        if self.last_face is not None:
            self.last_face = (self.last_face[0], self.last_face[1] + dy) + tuple(self.last_face[2:])

    def _depth_head(self, depth):
        """Nearest sizeable blob in the upper part of the image = a person."""
        if depth is None:
            return None
        small = depth[::4, ::4]
        valid = (small > 500) & (small < 3500)
        if valid.mean() < 0.05:
            return None
        # Ignore the bottom fifth (desk / keyboard is usually nearest).
        h = small.shape[0]
        top = small[: int(h * 0.8)]
        vt = valid[: int(h * 0.8)]
        if not vt.any():
            return None
        near = np.percentile(top[vt], 8)
        mask = (vt & (np.abs(top.astype(np.int32) - int(near)) < 450)).astype(np.uint8)
        n, labels, stats, cent = cv2.connectedComponentsWithStats(mask, connectivity=8)
        if n <= 1:
            return None
        i = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
        if stats[i, cv2.CC_STAT_AREA] < 150:
            return None
        ys, xs = np.nonzero(labels == i)
        ytop = ys.min()
        head = xs[ys < ytop + 12]  # the top band of the blob ~ the head
        cx = float(np.median(head)) * 4
        # Approximate a face size from distance (a ~16 cm face at 525 px focal length).
        size = 525 * 160 / max(near, 400)
        self.head_cut = ytop <= 1
        cy = 0.0 if self.head_cut else ytop * 4 + size * 0.7
        return (cx, cy, float(size), float(near))


def _median_depth(depth, x, y, w, h):
    if depth is None:
        return 0.0
    roi = depth[int(y + h * 0.25): int(y + h * 0.75), int(x + w * 0.25): int(x + w * 0.75)]
    v = roi[roi > 0]
    return float(np.median(v)) if v.size else 0.0


# ---------------------------------------------------------------- framing ---
def smooth_damp(cur, target, vel, smooth_time, max_speed, dt):
    """Critically damped spring (as used for game cameras): eases in AND out,
    never overshoots, and never jumps, however the target moves."""
    smooth_time = max(1e-4, smooth_time)
    omega = 2.0 / smooth_time
    x = omega * dt
    decay = 1.0 / (1.0 + x + 0.48 * x * x + 0.235 * x * x * x)
    change = cur - target
    max_change = max_speed * smooth_time
    change = max(-max_change, min(max_change, change))
    goal = cur - change
    temp = (vel + omega * change) * dt
    vel = (vel - omega * temp) * decay
    out = goal + (change + temp) * decay
    if (target - cur > 0) == (out > target):  # don't overshoot
        out, vel = target, 0.0
    return out, vel


class SubjectFilter:
    """Low-pass filter for the tracked head, with outlier rejection: a sudden
    jump (detector picking the chair for a frame) must persist before it is
    believed."""

    def __init__(self):
        self.x = self.y = self.size = None
        self.cand, self.cand_n = None, 0

    def update(self, target, dt):
        if target is None:
            return None if self.x is None else (self.x, self.y, self.size)
        tx, ty, ts = target[0], target[1], target[2]
        if self.x is None:
            self.x, self.y, self.size = tx, ty, ts
        else:
            jump = math.hypot(tx - self.x, ty - self.y)
            if jump > max(90.0, self.size * 1.2):
                # big jump: wait ~0.25 s of agreeing detections before moving there
                if self.cand is not None and math.hypot(tx - self.cand[0], ty - self.cand[1]) < 60:
                    self.cand_n += 1
                else:
                    self.cand, self.cand_n = (tx, ty), 1
                if self.cand_n < 8:
                    return (self.x, self.y, self.size)
            self.cand, self.cand_n = None, 0
            kp = 1 - math.exp(-dt / 0.18)   # position: ~0.2 s time constant
            ks = 1 - math.exp(-dt / 0.9)    # size (zoom): slow, it is noisy
            self.x += (tx - self.x) * kp
            self.y += (ty - self.y) * kp
            self.size += (ts - self.size) * ks
        return (self.x, self.y, self.size)

    def shift(self, dy):
        if self.y is not None:
            self.y += dy

    def reset(self):
        self.x = self.y = self.size = None


class Framer:
    """Virtual camera: centre (cx, cy) and crop width w, in sensor pixels.

    It moves toward a goal with a critically damped spring, so every move
    (follow, pan buttons, zoom, reset) eases in and out instead of jumping.
    In follow mode the goal only starts to move once you leave a small dead
    zone, then tracks you until you are re-centred (hysteresis), which avoids
    constant micro-wobble.
    """

    ASPECT = 16 / 9
    ENTER_DZ, EXIT_DZ = 0.07, 0.02   # fractions of the crop width
    ZOOM_DZ = 0.10                   # re-zoom only for a >10 % size change

    def __init__(self):
        self.cx, self.cy, self.w = SRC_W / 2, SRC_H / 2, float(SRC_W)
        self.gx, self.gy, self.gw = self.cx, self.cy, self.w
        self.vx = self.vy = self.vw = 0.0
        self.tracking = False

    def set_goal(self, cx, cy, w, follow):
        if not follow:
            self.gx, self.gy, self.gw = cx, cy, w
            self.tracking = False
            return
        err = math.hypot(cx - self.gx, cy - self.gy)
        if not self.tracking and err > self.ENTER_DZ * self.w:
            self.tracking = True
        if self.tracking:
            self.gx, self.gy = cx, cy
            if math.hypot(cx - self.cx, cy - self.cy) < self.EXIT_DZ * self.w:
                self.tracking = False
        if abs(w - self.gw) > self.ZOOM_DZ * self.gw:
            self.gw = w

    def step(self, dt, follow):
        pos_t, zoom_t = (0.55, 1.1) if follow else (0.3, 0.35)
        self._clamp_goal()
        self.cx, self.vx = smooth_damp(self.cx, self.gx, self.vx, pos_t, 420.0, dt)
        self.cy, self.vy = smooth_damp(self.cy, self.gy, self.vy, pos_t, 420.0, dt)
        self.w, self.vw = smooth_damp(self.w, self.gw, self.vw, zoom_t, 500.0, dt)
        self._clamp()

    def shift(self, dy):
        """Sensor tilted: the scene moved dy px in the image. Move the crop with
        it so the output stays steady while the motor turns."""
        self.cy += dy
        self.gy += dy
        self._clamp()

    def _clamp_goal(self):
        self.gw = float(np.clip(self.gw, 160, SRC_W))
        gh = self.gw / self.ASPECT
        self.gx = float(np.clip(self.gx, self.gw / 2, SRC_W - self.gw / 2))
        self.gy = float(np.clip(self.gy, gh / 2, SRC_H - gh / 2))

    def _clamp(self):
        self.w = float(np.clip(self.w, 160, SRC_W))
        h = self.w / self.ASPECT
        cx = float(np.clip(self.cx, self.w / 2, SRC_W - self.w / 2))
        cy = float(np.clip(self.cy, h / 2, SRC_H - h / 2))
        if cx != self.cx:
            self.vx = 0.0
        if cy != self.cy:
            self.vy = 0.0
        self.cx, self.cy = cx, cy

    def rect(self):
        h = self.w / self.ASPECT
        return (self.cx - self.w / 2, self.cy - h / 2, self.w, h)


# ------------------------------------------------------------------ motor ---
class SceneMotion:
    """Global vertical shift of the image between frames (phase correlation on
    a small greyscale copy). Used only while the tilt motor is turning."""

    def __init__(self):
        self.prev = None
        self.win = cv2.createHanningWindow((160, 120), cv2.CV_32F)

    def measure(self, bgr):
        g = cv2.cvtColor(cv2.resize(bgr, (160, 120), interpolation=cv2.INTER_AREA), cv2.COLOR_BGR2GRAY)
        g = g.astype(np.float32)
        prev, self.prev = self.prev, g
        if prev is None:
            return 0.0
        (dx, dy), resp = cv2.phaseCorrelate(prev, g, self.win)
        if resp < 0.08 or abs(dy) > 8:      # not confident / implausible
            return 0.0
        return float(dy) * (SRC_H / 120)    # back to sensor pixels


class TiltController:
    """Vertical follow with the Kinect's tilt motor.

    Keeps your head near HEAD_Y of the *sensor* image, so the digital crop always
    has room to move both ways. Moves are small and only after you have been off
    for a moment. While the motor turns, the scene's vertical slide is measured
    from the video (see SceneMotion) and the crop moves with it, so the output
    stays steady instead of lurching.
    """

    PX_PER_DEG = SRC_H / 43.0   # Kinect v1 vertical field of view ~43 deg
    HEAD_Y = 0.40 * SRC_H       # where we want the head in the sensor image
    DEADBAND_DEG = 3.5
    SETTLE_S = 0.6              # how long you must be off-centre before moving
    COOLDOWN_S = 1.2            # pause between moves (the motor is slow and noisy)
    MAX_STEP = 6.0
    LIMIT = 26

    def __init__(self, tilt):
        self.cmd = float(tilt)
        self.off_since = None
        self.last_cmd_t = 0.0
        self.last_move = None    # for the HUD
        self.last_moving_t = 0.0

    def motor_active(self, now, tilt_state):
        """True while the motor is (or may still be) turning. The Kinect reports
        no angle while moving (-64), so we go by status and command time."""
        if tilt_state and tilt_state.get("status", 0) == 4:
            self.last_moving_t = now
        return now - self.last_cmd_t < 0.5 or now - self.last_moving_t < 0.4

    def update(self, now, head_y, head_cut, tilt_state):
        moving = tilt_state.get("status", 0) == 4 if tilt_state else False
        if head_y is None or moving or now - self.last_cmd_t < self.COOLDOWN_S:
            self.off_since = None if head_y is None else self.off_since
            return None
        if head_cut:
            err = 6.0
        else:
            err = (self.HEAD_Y - head_y) / self.PX_PER_DEG   # + = head too high -> tilt up
        if abs(err) < self.DEADBAND_DEG:
            self.off_since = None
            return None
        self.off_since = self.off_since or now
        if now - self.off_since < self.SETTLE_S:
            return None
        step = float(np.clip(err * 0.8, -self.MAX_STEP, self.MAX_STEP))
        new = float(np.clip(self.cmd + step, -self.LIMIT, self.LIMIT))
        if abs(new - self.cmd) < 1:
            return None   # at the end of travel
        self.cmd = fk.set_tilt(new)
        self.last_cmd_t, self.off_since, self.last_move = now, None, now
        return self.cmd

    def manual(self, deg):
        self.cmd = fk.set_tilt(deg)
        self.last_cmd_t = time.time()
        return self.cmd


def crop_to(frame, rect, out_w, out_h):
    x, y, w, h = rect
    # Sub-pixel crop via an affine warp keeps slow pans perfectly smooth.
    sx, sy = out_w / w, out_h / h
    M = np.float32([[sx, 0, -x * sx], [0, sy, -y * sy]])
    return cv2.warpAffine(frame, M, (out_w, out_h), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)


# ------------------------------------------------------------- background ---
def person_mask(depth, person_mm, seed=None):
    """Soft 0..1 mask of everything at roughly the person's distance."""
    if depth is None or person_mm <= 0:
        return None
    small = cv2.resize(depth, (SRC_W // 2, SRC_H // 2), interpolation=cv2.INTER_NEAREST).astype(np.int32)
    m = ((small > 0) & (small > person_mm - 600) & (small < person_mm + 450)).astype(np.uint8)
    # Depth has shadows (0) at silhouette edges; close them up.
    m = cv2.morphologyEx(m, cv2.MORPH_CLOSE, np.ones((7, 7), np.uint8))
    n, labels, stats, _ = cv2.connectedComponentsWithStats(m, connectivity=8)
    if n > 1:
        if seed is not None:
            sx = int(np.clip(seed[0] / 2, 0, m.shape[1] - 1))
            sy = int(np.clip(seed[1] / 2, 0, m.shape[0] - 1))
            lbl = labels[sy, sx]
        else:
            lbl = 0
        if lbl == 0:
            lbl = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
        # keep the person blob and anything large touching it (arms, chair edge)
        m = (labels == lbl).astype(np.uint8)
    m = cv2.dilate(m, np.ones((5, 5), np.uint8))
    m = cv2.resize(m.astype(np.float32), (SRC_W, SRC_H), interpolation=cv2.INTER_LINEAR)
    m = cv2.GaussianBlur(m, (0, 0), 4)
    return np.clip(m, 0, 1)


def apply_background(frame, mask, kind, color, bg_image):
    if mask is None or kind == "none":
        return frame
    if kind == "blur":
        bg = cv2.GaussianBlur(cv2.resize(frame, (160, 120)), (0, 0), 6)
        bg = cv2.resize(bg, (frame.shape[1], frame.shape[0]))
    elif kind == "image" and bg_image is not None:
        bg = bg_image
    else:
        bg = np.empty_like(frame)
        bg[:] = color
    m = mask[..., None]
    return (frame * m + bg * (1 - m)).astype(np.uint8)


def load_bg_image(path):
    if not path:
        return None
    img = cv2.imread(os.path.expanduser(path))
    if img is None:
        print(f"[warn] could not read background image {path}")
        return None
    return cv2.resize(img, (SRC_W, SRC_H), interpolation=cv2.INTER_AREA)


# ------------------------------------------------------------------- misc ---
_clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))


def enhance(frame):
    lab = cv2.cvtColor(frame, cv2.COLOR_BGR2LAB)
    lab[..., 0] = _clahe.apply(lab[..., 0])
    return cv2.cvtColor(lab, cv2.COLOR_LAB2BGR)


def colorize_depth(depth):
    d = depth.astype(np.float32)
    v = np.clip((d - 500) / 3500, 0, 1)
    img = cv2.applyColorMap((255 - v * 255).astype(np.uint8), cv2.COLORMAP_TURBO)
    img[depth == 0] = 0
    return img


def level_image(frame, roll_deg):
    if abs(roll_deg) < 0.8:
        return frame
    h, w = frame.shape[:2]
    M = cv2.getRotationMatrix2D((w / 2, h / 2), roll_deg, 1 + abs(math.radians(roll_deg)) * 0.8)
    return cv2.warpAffine(frame, M, (w, h), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)


def to_full_res(rect, frame_w):
    """640x480 crop rect -> the same region in the full-res frame."""
    if frame_w == SRC_W:
        return rect
    k = frame_w / SRC_W
    ox, oy = Capture.HD_OFFSET
    x, y, w, h = rect
    return ((x + ox) * k, (y + oy) * k, w * k, h * k)


def mask_to_full_res(mask, shape):
    if mask is None or mask.shape[:2] == shape[:2]:
        return mask
    h, w = shape[:2]
    m = cv2.resize(mask, (w, w * 3 // 4), interpolation=cv2.INTER_LINEAR)
    if m.shape[0] < h:   # HD has a few rows below what the 640x480 view covers
        m = np.vstack([m, np.repeat(m[-1:], h - m.shape[0], axis=0)])
    return m


def open_virtual_cam(w, h, fps):
    try:
        import pyvirtualcam
        if IS_WIN:   # bundled Unity Capture filter, registered as "KinectCam" by the one-time setup
            cam = pyvirtualcam.Camera(width=w, height=h, fps=fps, fmt=pyvirtualcam.PixelFormat.BGR,
                                      backend="unitycapture", device="KinectCam")
        else:
            cam = pyvirtualcam.Camera(width=w, height=h, fps=fps, fmt=pyvirtualcam.PixelFormat.BGR, backend="obs")
        print(f"[ok] virtual camera: {cam.device}  ({w}x{h} @ {fps} fps)")
        return cam
    except Exception as e:  # noqa: BLE001
        print("[warn] virtual camera not available:", e)
        if IS_WIN:
            print("       The KinectCam virtual camera isn't registered. Start KinectCam.exe again to run the setup.")
            return None
        print("       Open OBS once, click 'Start Virtual Camera', approve the system extension")
        print("       in System Settings > General > Login Items & Extensions, then quit OBS and press C here.")
        return None


# ------------------------------------------------------------- preview UI ---
PREVIEW_W, PREVIEW_H = 960, 540
STATUS_H, BTN_H, BTN_GAP = 30, 46, 6
BUTTON_ROWS = [
    ["follow", "mode", "background", "bgcolor", "zoom_out", "zoom_in", "pan_left", "pan_right", "reset"],
    ["tilt_up", "tilt_down", "enhance", "level", "mirror", "led", "vcam", "snapshot", "quit"],
    ["hd", "voice_steer", "mic_focus", "sound_dots", "grid", "calibrate", "auto_exposure", "auto_wb"],
]
PANEL_H = STATUS_H + len(BUTTON_ROWS) * (BTN_H + BTN_GAP) + BTN_GAP

KEYMAP = {
    "f": "follow", "m": "mode", "b": "background", "g": "bgcolor", "+": "zoom_in", "=": "zoom_in",
    "-": "zoom_out", "_": "zoom_out", K_LEFT: "pan_left", K_RIGHT: "pan_right", K_UP: "tilt_up",
    K_DOWN: "tilt_down", "0": "reset", "e": "enhance", "v": "level", "r": "mirror", "o": "led",
    "c": "vcam", "s": "snapshot", "q": "quit", "\x1b": "quit",
    "h": "hd", "t": "voice_steer", "a": "auto_exposure", "w": "auto_wb",
    "x": "grid", "d": "sound_dots", "u": "mic_focus", "k": "calibrate",
}

# Scripted clicks used by --test to exercise every button: (frame number, action)
TEST_CLICKS = [(int(f), a) for f, a in (x.split(":") for x in
               os.environ.get("KINECTCAM_TEST_CLICKS", "").split(",") if ":" in x)]


def button_label(act, S, vcam, calib=None):
    onoff = lambda b: "ON" if b else "off"  # noqa: E731
    return {
        "follow": ("Follow  " + onoff(S["follow"]), S["follow"]),
        "mode": ("Mode: " + S["mode"], S["mode"] != "color"),
        "background": ("BG: " + S["background"], S["background"] != "none"),
        "bgcolor": ("BG colour", False),
        "zoom_out": ("Zoom -", False),
        "zoom_in": ("Zoom +", False),
        "pan_left": ("< Pan", False),
        "pan_right": ("Pan >", False),
        "reset": ("Reset", False),
        "tilt_up": ("Tilt up", False),
        "tilt_down": ("Tilt down", False),
        "enhance": ("Enhance " + onoff(S["enhance"]), S["enhance"]),
        "level": ("Level " + onoff(S["level"]), S["level"]),
        "mirror": ("Mirror " + onoff(S["mirror"]), S["mirror"]),
        "led": ("LED: " + fk.LED_NAMES.get(S["led"], "?"), False),
        "vcam": ("Cam out " + onoff(vcam is not None), vcam is not None),
        "snapshot": ("Snapshot", False),
        "quit": ("Quit", False),
        "hd": ("HD 10fps " + onoff(S["hd"]), S["hd"]),
        "voice_steer": ("Voice steer " + onoff(S["voice_steer"]), S["voice_steer"]),
        "mic_focus": ("Mic: " + ("me" if S["mic_focus"] == "me" else "all around"), S["mic_focus"] == "me"),
        "sound_dots": ("Sound dots " + onoff(S["sound_dots"]), S["sound_dots"]),
        "grid": ("Grid " + onoff(S["grid"]), S["grid"]),
        "auto_exposure": ("Auto exp. " + onoff(S["auto_exposure"]), S["auto_exposure"]),
        "auto_wb": ("Auto WB " + onoff(S["auto_wb"]), S["auto_wb"]),
        "calibrate": ((("Stop calib." if calib and calib.active else "Calibrate mic"), bool(calib and calib.active))
                      if MIC_UI["state"] == "ok" else
                      ((MIC_UI["text"].replace("mic support: ", "Mic ") if MIC_UI["state"] == "fetching"
                        else "Get mic support"), MIC_UI["state"] == "fetching")),
    }[act]


def layout_buttons(ui):
    if ui["rects"]:
        return ui["rects"]
    for r, row in enumerate(BUTTON_ROWS):
        w = (PREVIEW_W - BTN_GAP * (len(row) + 1)) / len(row)
        y = PREVIEW_H + STATUS_H + BTN_GAP + r * (BTN_H + BTN_GAP)
        for i, act in enumerate(row):
            x = BTN_GAP + i * (w + BTN_GAP)
            ui["rects"][act] = (int(x), int(y), int(w), BTN_H)
    return ui["rects"]


def hit(ui, x, y):
    for act, (bx, by, bw, bh) in layout_buttons(ui).items():
        if bx <= x < bx + bw and by <= y < by + bh:
            return act
    return None


def on_mouse(ui, event, x, y):
    if event == cv2.EVENT_MOUSEMOVE:
        ui["hover"] = hit(ui, x, y)
    elif event == cv2.EVENT_LBUTTONUP:
        act = hit(ui, x, y)
        if act:
            ui["pending"].append(act)


def click_button(ui, act):
    """Simulate a mouse click in the centre of a button (used by --test)."""
    bx, by, bw, bh = layout_buttons(ui)[act]
    on_mouse(ui, cv2.EVENT_LBUTTONUP, bx + bw // 2, by + bh // 2)


FOCUS_WIDTH = 12.0   # degrees either side of you that "Mic: me" listens to
SOURCE_COLORS = [(0, 200, 255), (255, 120, 255), (120, 255, 120), (255, 200, 80), (80, 160, 255)]


def _to_preview(x, y, rect, mirror):
    rx, ry, rw, rh = rect
    px = (x - rx) / rw * PREVIEW_W
    py = (y - ry) / rh * PREVIEW_H
    return (PREVIEW_W - px if mirror else px), py


def _source_height(x, faces, depth):
    """Best guess for the height (640x480 y) of a sound coming from column x.

    The mic array only knows left/right. If a face is in that direction the
    sound is put on its mouth; otherwise on the top part of the nearest object
    in that direction (where a head would be), not its middle (a chest)."""
    best = None
    for fx, fy, fw, fh in faces:
        d = abs(fx + fw / 2 - x)
        if d < max(fw * 1.3, 55.0) and (best is None or d < best[0]):
            best = (d, fy + fh * 0.78)
    if best is not None:
        return best[1]
    if depth is not None and 0 <= x < SRC_W:
        x0, x1 = int(max(0, x - 8)), int(min(SRC_W, x + 8))
        band = depth[:, x0:x1].astype(np.float32)
        band[(band < 400) | (band > 4500)] = np.nan
        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            rows = np.nanmedian(band, axis=1)                  # distance per image row
        valid = ~np.isnan(rows)
        if valid.sum() > 20:
            bg = float(np.percentile(rows[valid], 90))         # the wall / room behind
            fg = valid & (rows < min(bg * 0.8, bg - 400))      # things standing out from it
            # contiguous foreground pieces (small gaps allowed); the nearest big one is
            # the talker (or the thing making the noise); its top is head height
            segs, start, gap = [], None, 0
            for y in range(SRC_H + 1):
                on = y < SRC_H and fg[y]
                if on:
                    start, gap = (y if start is None else start), 0
                elif start is not None:
                    gap += 1
                    if gap > 4 or y == SRC_H:
                        end = y - gap + 1
                        if end - start >= 12:
                            segs.append((float(np.nanmedian(rows[start:end])), start))
                        start, gap = None, 0
            if segs:
                z_mm, top = min(segs)
                # The column may only cross a shoulder or arm: look a bit to each side
                # for the top of the same body (same distance, or a little further back)
                w = int(525.0 * 0.30 / max(z_mm / 1000.0, 0.3))
                wx0, wx1 = int(max(0, x - w)), int(min(SRC_W, x + w))
                win = depth[:, wx0:wx1]
                body = ((win > z_mm - 300) & (win < z_mm + 500)).sum(axis=1) >= 4
                run = np.convolve(body.astype(int), np.ones(4, int), mode="valid") == 4
                if run.any():
                    top = min(top, int(np.argmax(run)))
                    sel = win[top:top + 30]
                    sel = sel[(sel > z_mm - 300) & (sel < z_mm + 500)]
                    z_mm = float(np.median(sel)) if sel.size else z_mm
                head_px = 525.0 * 0.23 / max(z_mm / 1000.0, 0.3)    # ~23 cm head at that distance
                return float(min(top + head_px * 0.75, SRC_H - 1))
    return SRC_H / 2


class FaceMemory:
    """Faces seen in the last second: the detector misses frames (more so when
    you turn to the side), and without this the dot would drop to your chest."""
    HOLD_S = 1.2

    def __init__(self):
        self.items = []   # [(t, (x, y, w, h))]

    def update(self, faces, now):
        for f in faces:
            fx = f[0] + f[2] / 2
            self.items = [(t, g) for t, g in self.items if abs(g[0] + g[2] / 2 - fx) > max(f[2], g[2]) * 0.6]
            self.items.append((now, tuple(f)))
        self.items = [(t, g) for t, g in self.items if now - t < self.HOLD_S]
        return [g for _, g in self.items]


def _label(img, text, org, color, scale=0.45):
    cv2.putText(img, text, org, cv2.FONT_HERSHEY_SIMPLEX, scale, (0, 0, 0), 3, cv2.LINE_AA)
    cv2.putText(img, text, org, cv2.FONT_HERSHEY_SIMPLEX, scale, color, 1, cv2.LINE_AA)


def draw_grid(prev, rect, S):
    """Rule-of-thirds lines + vertical lines every 15 deg of horizontal angle
    (the same angles the microphones report)."""
    over = prev.copy()
    for k in (1, 2):
        cv2.line(over, (PREVIEW_W * k // 3, 0), (PREVIEW_W * k // 3, PREVIEW_H), (255, 255, 255), 1, cv2.LINE_AA)
        cv2.line(over, (0, PREVIEW_H * k // 3), (PREVIEW_W, PREVIEW_H * k // 3), (255, 255, 255), 1, cv2.LINE_AA)
    cv2.addWeighted(over, 0.35, prev, 0.65, 0, prev)
    from sound import angle_to_image_x
    for a in range(-75, 76, 15):
        px, _ = _to_preview(angle_to_image_x(a, S["mic_sign"]), 0, rect, S["mirror"])
        if 0 <= px < PREVIEW_W:
            px = int(px)
            for y in range(0, PREVIEW_H, 14):   # dashed
                cv2.line(prev, (px, y), (px, min(PREVIEW_H, y + 7)), (255, 230, 120), 1)
            _label(prev, f"{a:+d}" if a else "0", (px + 4, 18), (255, 230, 120))


def draw_sound(prev, rect, S, sound, faces, depth, now):
    """Dots on sound sources; arrows at the edge for sources outside the view."""
    from sound import angle_to_image_x
    if sound.get("focus") is not None:
        # shade the direction the mics are focused on
        a, w = sound["focus"], sound["focus_width"]
        xs = [_to_preview(angle_to_image_x(a + d, S["mic_sign"]), 0, rect, S["mirror"])[0] for d in (-w, w)]
        x0, x1 = int(np.clip(min(xs), 0, PREVIEW_W)), int(np.clip(max(xs), 0, PREVIEW_W))
        if x1 > x0:
            over = prev.copy()
            cv2.rectangle(over, (x0, 0), (x1, PREVIEW_H), (255, 200, 0), -1)
            cv2.addWeighted(over, 0.10, prev, 0.90, 0, prev)
            _label(prev, "mic focus", (x0 + 4, PREVIEW_H - 10), (255, 220, 120))
    for src in sound.get("sources", []):
        fade = max(0.0, 1.0 - (now - src["t"]) / 1.2)
        col = SOURCE_COLORS[src["id"] % len(SOURCE_COLORS)]
        col = tuple(int(c * (0.35 + 0.65 * fade)) for c in col)
        xv = angle_to_image_x(src["angle"], S["mic_sign"])
        yv = _source_height(xv, faces, depth)
        prev_y = src.get("y_draw")
        src["y_draw"] = yv if prev_y is None or abs(yv - prev_y) > 120 else prev_y + (yv - prev_y) * 0.35
        yv = src["y_draw"]
        px, py = _to_preview(xv, yv, rect, S["mirror"])
        label = f"{src['angle']:+.0f}"
        # The microphones only give the horizontal direction; the height is a
        # guess, so keep the dot inside the view rather than calling it "outside".
        py = float(np.clip(py, 24, PREVIEW_H - 24))
        if 0 <= px < PREVIEW_W:
            r = int(7 + 12 * min(1.0, src["strength"]))
            cv2.circle(prev, (int(px), int(py)), r + 3, (0, 0, 0), 2, cv2.LINE_AA)
            cv2.circle(prev, (int(px), int(py)), r, col, -1, cv2.LINE_AA)
            _label(prev, label, (int(px) + r + 5, int(py) + 5), col)
        else:
            # outside the picture: arrow on the edge it is beyond
            y = int(np.clip(py, 40, PREVIEW_H - 40))
            if px < 0:
                pts = np.array([[6, y], [26, y - 14], [26, y + 14]], np.int32)
                tx = 32
            else:
                pts = np.array([[PREVIEW_W - 6, y], [PREVIEW_W - 26, y - 14], [PREVIEW_W - 26, y + 14]], np.int32)
                tx = PREVIEW_W - 80
            cv2.fillPoly(prev, [pts], col, cv2.LINE_AA)
            cv2.polylines(prev, [pts], True, (0, 0, 0), 1, cv2.LINE_AA)
            _label(prev, label, (tx, y + 5), col)


class MicCalibration:
    """In-window wizard: you talk from three spots, the face tracker gives the
    true direction of your mouth, the mic array gives the sound angle, and the
    fitted correction (scale + offset) makes the sound dots land on mouths."""
    ZONES = [("YOUR RIGHT", 130.0), ("the CENTRE", 320.0), ("YOUR LEFT", 510.0)]   # 640x480 x
    ZONE_HALF = 55.0
    MOVE_MIN, MOVE_MAX, IN_ZONE_S, TALK_S = 2.0, 20.0, 1.0, 8.0
    SHOW_RESULT_S = 9.0

    def __init__(self, now, gain, offset, sign):
        self.old = (gain, offset)
        self.sign = sign or -1
        self.phase, self.stage, self.t = 0, "move", now
        self.in_zone_since = None
        self.pairs, self.results = [], []
        self.face = None          # (x, y, w, h) of your face, 640x480
        self.heard = False
        self.angle = None
        self.result = None        # (gain, offset)
        self.report = []
        self.error = None
        self.applied = False

    @property
    def active(self):
        return self.stage in ("move", "talk")

    def finished(self, now):
        return self.stage in ("done", "failed", "cancelled") and now - self.t > self.SHOW_RESULT_S

    def cancel(self, now):
        self.stage, self.t, self.error = "cancelled", now, "Calibration cancelled - nothing changed."

    @staticmethod
    def _x(angle, sign, gain, offset):
        a = max(-80.0, min(80.0, gain * sign * angle + offset))
        return SRC_W / 2 + 525.0 * math.tan(math.radians(a))

    def update(self, now, faces, angle, above_db):
        self.face = max(faces, key=lambda f: f[2] * f[3]) if faces else None
        face_x = self.face[0] + self.face[2] / 2 if self.face else None
        self.angle = angle
        self.heard = angle is not None and above_db > 5.0
        if self.stage == "move":
            zx = self.ZONES[self.phase][1]
            if face_x is not None and abs(face_x - zx) < self.ZONE_HALF:
                self.in_zone_since = self.in_zone_since or now
            else:
                self.in_zone_since = None
            el = now - self.t
            if (el > self.MOVE_MIN and self.in_zone_since and now - self.in_zone_since > self.IN_ZONE_S) \
                    or el > self.MOVE_MAX:
                self.stage, self.t, self.pairs = "talk", now, []
        elif self.stage == "talk":
            if face_x is not None and self.heard:
                self.pairs.append((angle, face_x))
            if now - self.t > self.TALK_S:
                if len(self.pairs) >= 10:
                    p = np.array(self.pairs)
                    self.results.append((self.ZONES[self.phase][0], float(np.median(p[:, 0])),
                                         float(np.median(p[:, 1]))))
                self.phase += 1
                self.t, self.in_zone_since = now, None
                if self.phase >= len(self.ZONES):
                    self._finish(now)
                else:
                    self.stage = "move"

    def _finish(self, now):
        self.t = now
        if len(self.results) < 2:
            self.stage = "failed"
            self.error = "Not enough voice was heard - nothing changed. Try again and talk a bit louder."
            return
        cam = lambda x: math.degrees(math.atan((x - SRC_W / 2) / 525.0))  # noqa: E731
        m = np.array([self.sign * r[1] for r in self.results])
        t = np.array([cam(r[2]) for r in self.results])
        gain, off = 1.0, float(np.mean(t - m))
        if np.ptp(m) > 10:
            g, o = np.polyfit(m, t, 1)
            if 0.5 <= g <= 2.0:
                gain, off = float(g), float(o)
        self.result = (round(gain, 4), round(off, 2))
        for name, a, x in self.results:
            before = self._x(a, self.sign, *self.old) - x
            after = self._x(a, self.sign, *self.result) - x
            self.report.append((name, before, after))
            print(f"[calib] {name}: mouth x={x:.0f}  dot off by {before:+.0f} px before, {after:+.0f} px after")
        print(f"[ok] mic calibration saved: scale {gain:.3f}, offset {off:+.1f} deg")
        self.stage = "done"

    def draw(self, prev, rect, S, now):
        mirror = S["mirror"]
        if self.active:
            zx = self.ZONES[self.phase][1]
            x0 = _to_preview(zx - self.ZONE_HALF, 0, rect, mirror)[0]
            x1 = _to_preview(zx + self.ZONE_HALF, 0, rect, mirror)[0]
            x0, x1 = int(max(0, min(x0, x1))), int(min(PREVIEW_W, max(x0, x1)))
            if x1 > x0:
                ok = self.in_zone_since is not None or self.stage == "talk"
                band = prev[:, x0:x1].astype(np.float32)
                tint = np.array((60, 200, 60) if ok else (60, 200, 230), np.float32)
                prev[:, x0:x1] = (band * 0.65 + tint * 0.35).astype(np.uint8)
                cv2.rectangle(prev, (x0, 0), (x1 - 1, PREVIEW_H - 1), (255, 255, 255), 2)
                _label(prev, "stand here", (x0 + 6, 24), (255, 255, 255), 0.6)
            if self.face is not None:
                fx, fy, fw, fh = self.face
                mx, my = _to_preview(fx + fw / 2, fy + fh * 0.78, rect, mirror)
                cv2.circle(prev, (int(mx), int(my)), 9, (80, 255, 80), 2)
                if self.heard:
                    sx, _ = _to_preview(self._x(self.angle, self.sign, *self.old), 0, rect, mirror)
                    if 0 <= sx < PREVIEW_W:
                        cv2.circle(prev, (int(sx), int(my)), 7, (0, 170, 255), -1)

        # instruction banner at the bottom of the picture
        top = PREVIEW_H - 112
        shade = prev[top:].astype(np.float32) * 0.25
        prev[top:] = shade.astype(np.uint8)
        white, green, orange, red = (255, 255, 255), (110, 240, 110), (0, 170, 255), (90, 90, 255)
        if self.active:
            name = self.ZONES[self.phase][0]
            _label(prev, f"MIC CALIBRATION  -  step {self.phase + 1} of {len(self.ZONES)}", (16, top + 24), green, 0.6)
            if self.stage == "move":
                msg = f"Move to {name} into the green zone and face the camera"
                sub = ("hold still..." if self.in_zone_since else
                       ("your face isn't found yet - look at the camera" if self.face is None
                        else "a little further..."))
            else:
                left = max(0.0, self.TALK_S - (now - self.t))
                msg = f"Now count out loud: 1, 2, 3, 4...   ({left:.0f} s)"
                sub = "keep facing the camera and stay in the zone"
                frac = min(1.0, len(self.pairs) / 120.0)
                cv2.rectangle(prev, (16, top + 96), (PREVIEW_W - 16, top + 104), (80, 80, 80), -1)
                cv2.rectangle(prev, (16, top + 96), (16 + int((PREVIEW_W - 32) * frac), top + 104), green, -1)
            _label(prev, msg, (16, top + 54), white, 0.75)
            _label(prev, sub, (16, top + 80), (200, 200, 200), 0.5)
            fx = PREVIEW_W - 330
            _label(prev, "face: " + ("found" if self.face is not None else "not found"), (fx, top + 80),
                   green if self.face is not None else red, 0.5)
            _label(prev, "voice: " + ("heard" if self.heard else "quiet"), (fx + 150, top + 80),
                   green if self.heard else orange, 0.5)
        elif self.stage == "done":
            _label(prev, "MIC CALIBRATION SAVED", (16, top + 28), green, 0.7)
            parts = [f"{n.replace('the ', '').lower()}: {abs(b):.0f} -> {abs(a):.0f} px" for n, b, a in self.report]
            _label(prev, "distance from your mouth to the dot   " + "   ".join(parts), (16, top + 60), white, 0.5)
            _label(prev, f"scale {self.result[0]:.3f}, offset {self.result[1]:+.1f} deg", (16, top + 88),
                   (200, 200, 200), 0.5)
        else:
            _label(prev, "MIC CALIBRATION", (16, top + 28), orange, 0.7)
            _label(prev, self.error or "", (16, top + 62), white, 0.55)


def render_preview(out, src, framer, target, S, tilt_state, vcam, fps, ui, sound=None, faces=(), depth=None,
                   calib=None):
    prev = cv2.resize(out, (PREVIEW_W, PREVIEW_H))
    now = time.time()
    if S.get("grid"):
        draw_grid(prev, framer.rect(), S)
    if sound is not None and S.get("sound_dots") and not (calib and calib.active):
        draw_sound(prev, framer.rect(), S, sound, faces, depth, now)
    if calib is not None:
        calib.draw(prev, framer.rect(), S, now)
    # inset: full sensor view with the virtual-camera crop
    inset = cv2.resize(src[: src.shape[1] * 3 // 4], (192, 144))
    x, y, w, h = framer.rect()
    s = 192 / SRC_W
    cv2.rectangle(inset, (int(x * s), int(y * s)), (int((x + w) * s), int((y + h) * s)), (0, 255, 255), 1)
    if target:
        cv2.circle(inset, (int(target[0] * s), int(target[1] * s)), 3, (0, 0, 255), -1)
    if sound is not None and S.get("sound_dots"):
        from sound import angle_to_image_x
        for so in sound.get("sources", []):
            xv = angle_to_image_x(so["angle"], S["mic_sign"])
            col = SOURCE_COLORS[so["id"] % len(SOURCE_COLORS)]
            if 0 <= xv < SRC_W:
                cv2.circle(inset, (int(xv * s), int(_source_height(xv, faces, depth) * s)), 4, col, -1)
            else:
                cv2.drawMarker(inset, (2 if xv < 0 else 189, 72), col, cv2.MARKER_DIAMOND, 8, 2)
    prev[8:152, PREVIEW_W - 200:PREVIEW_W - 8] = inset
    cv2.rectangle(prev, (PREVIEW_W - 201, 7), (PREVIEW_W - 8, 152), (255, 255, 255), 1)

    panel = np.full((PANEL_H, PREVIEW_W, 3), 32, np.uint8)
    if sound is None:
        mic = MIC_UI["text"]
    else:
        lvl = int(np.clip(((sound["level"] if sound["level"] is not None else -120) + 70) / 50 * 10, 0, 10))
        where = f"{sound['angle']:+.0f} deg" if (sound["speaking"] and sound["angle"] is not None) else "-"
        n_src = len(sound.get("sources", []))
        mic = (f"mic({'me' if sound.get('focus') is not None else 'all'}) [{'|' * lvl}{'.' * (10 - lvl)}] "
               f"voice {where}  sources {n_src}")
    status = (f"zoom {S['zoom']:.2f}x   tilt {tilt_state.get('angle', 0):+.0f} deg   "
              f"{'tracking you' if target else 'no person found'}   {fps:4.1f} fps   {mic}")
    cv2.putText(panel, status, (10, 20), cv2.FONT_HERSHEY_SIMPLEX, 0.48, (140, 230, 140), 1, cv2.LINE_AA)
    img = np.vstack([prev, panel])

    flash_act, flash_t = ui["flash"]
    for act, (bx, by, bw, bh) in layout_buttons(ui).items():
        label, active = button_label(act, S, vcam, calib)
        if flash_act == act and time.time() - flash_t < 0.15:
            fill = (255, 255, 255)
        elif act == "quit":
            fill = (60, 60, 170)
        elif active:
            fill = (70, 150, 60)
        else:
            fill = (75, 75, 75)
        if ui["hover"] == act and fill != (255, 255, 255):
            fill = tuple(min(255, c + 35) for c in fill)
        cv2.rectangle(img, (bx, by), (bx + bw, by + bh), fill, -1)
        cv2.rectangle(img, (bx, by), (bx + bw, by + bh), (120, 120, 120), 1)
        color = (20, 20, 20) if fill == (255, 255, 255) else (240, 240, 240)
        scale = 0.45
        (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, scale, 1)
        while tw > bw - 8 and scale > 0.3:
            scale -= 0.03
            (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, scale, 1)
        cv2.putText(img, label, (bx + (bw - tw) // 2, by + (bh + th) // 2),
                    cv2.FONT_HERSHEY_SIMPLEX, scale, color, 1, cv2.LINE_AA)
    return img


# ------------------------------------------------------------------- main ---
_lock_file = None


def shutdown_kinect(timeout=4.0):
    """Stop the device thread; it finishes the current libfreenect command,
    stops the streams and closes the device, so the next start is clean."""
    return fk.stop(timeout)


def main():
    ap = argparse.ArgumentParser(description="Use a Kinect v1 as a webcam.")
    ap.add_argument("--width", type=int, default=1280)
    ap.add_argument("--height", type=int, default=720)
    ap.add_argument("--fps", type=int, default=30)
    ap.add_argument("--no-preview", action="store_true", help="run without the preview window")
    ap.add_argument("--no-vcam", action="store_true", help="don't send to the virtual camera")
    ap.add_argument("--bg-image", help="image file for the 'image' background mode")
    ap.add_argument("--mode", choices=MODES, help="start in this mode (color, night, depth)")
    ap.add_argument("--background", choices=BACKGROUNDS, help="start with this background effect")
    ap.add_argument("--follow", choices=["on", "off"], help="start with follow camera on/off")
    ap.add_argument("--no-mic", action="store_true", help="don't use the Kinect's microphone array")
    ap.add_argument("--reset", action="store_true", help="USB-reset the Kinect before starting (rarely needed)")
    ap.add_argument("--test", type=int, metavar="N", help="process N frames headless, save snapshots, exit")
    args = ap.parse_args()

    S = load_settings()
    import sound as sound_mod
    sound_mod.set_calibration(S["mic_gain"], S["mic_offset"])
    if args.bg_image:
        S["bg_image"] = args.bg_image
        S["background"] = "image"
    if args.mode:
        S["mode"] = args.mode
    if args.background:
        S["background"] = args.background
    if args.follow:
        S["follow"] = args.follow == "on"
    headless = args.no_preview or args.test
    out_w, out_h = args.width, args.height

    # Only one KinectCam may drive the Kinect; a second one would fight over the
    # USB device (and its USB resets would knock the first one offline).
    global _lock_file
    _lock_file = open(os.path.join(DATA, ".kinectcam.lock"), "w")
    try:
        if IS_WIN:
            import msvcrt
            msvcrt.locking(_lock_file.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(_lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        print("[error] KinectCam is already running (check your other Terminal tabs/windows).")
        print("        Quit that one first (Quit button or Q), then start again.")
        app_alert("KinectCam is already running (maybe from Terminal). Quit that one first.")
        sys.exit(1)

    if args.reset:
        from usb_reset import reset_kinect
        reset_kinect()

    win = "KinectCam (preview - not sent to the call)"
    ui = {"pending": [], "hover": None, "flash": (None, 0.0), "rects": {}}
    if not headless:
        cv2.namedWindow(win, cv2.WINDOW_AUTOSIZE)
        cv2.setMouseCallback(win, lambda ev, x, y, flags, _: on_mouse(ui, ev, x, y))
        import signal
        if IS_MAC:
            import macquit
            macquit.install()                                    # Dock / menu "Quit"
        else:
            macquit = None
        signal.signal(signal.SIGTERM, signal.default_int_handler)  # logout, kill
        splash(win, ["Starting the Kinect...", "usually 5-15 seconds"])
        if IS_WIN:
            import winsetup
            winsetup.set_window_icon(win)
            if IN_APP:
                problem = winsetup.ensure(lambda lines: splash(win, lines))
                if problem:
                    splash(win, ["Setup is not complete."], (90, 90, 255))
                    app_alert(problem)
                    os._exit(3)
                splash(win, ["Starting the Kinect...", "usually 5-15 seconds"])

    try:
        cap = Capture(S["mode"], hd=S["hd"])
    except Exception as e:  # noqa: BLE001
        print("[error]", e)
        app_alert(f"Could not start the Kinect driver: {e}")
        os._exit(2)
    print("[..] starting the Kinect (usually 5-10 s)...")
    t0, last_state = time.time(), None
    while cap.latest()[0] is None or cap.dev.depth is None:
        if cap.state != last_state:
            last_state = cap.state
            print(f"     {cap.state}")
        if not headless:
            el = time.time() - t0
            hint = "Is the Kinect plugged in (USB + its power adapter)?" if el > 20 else "usually 5-15 seconds"
            if IS_WIN and el > 20:
                hint = "Is the Kinect plugged in (USB + its power adapter)?  Unplug and replug it once after setup."
            splash(win, [f"Starting the Kinect...  {cap.state}  ({el:.0f} s)", hint])
            if cv2.getWindowProperty(win, cv2.WND_PROP_VISIBLE) < 1 or (macquit and macquit.requested()):
                print("[quit] closed during startup")
                cap.dev.stop(4)
                os._exit(0)
        if time.time() - t0 > 60:
            print("[error] The Kinect didn't start within 60 s.")
            for _, _, msg in cap.dev.recent_log(6):
                print("        libfreenect:", msg)
            print("        Unplug the Kinect's power adapter for 5 s, plug it back in, and retry.")
            if not headless:
                splash(win, ["The Kinect didn't start.", "Check the USB cable and the Kinect's power adapter,",
                             "unplug the power for 5 s, plug it back in, and open KinectCam again."], (90, 90, 255))
            app_alert("The Kinect didn't start within 60 seconds.\n\nCheck that it is plugged into USB and "
                      "into its power adapter. Unplug the power for 5 s, plug it back in, and open KinectCam again.")
            cap.dev.stop(4)
            os._exit(2)
        time.sleep(0.05)
    rec = dict(cap.dev.recoveries)
    print(f"[ok] Kinect streaming ({time.time() - t0:.1f} s{', recovered: ' + str(rec) if rec else ''})")

    fk.set_tilt(S["tilt"])
    fk.set_led(S["led"])

    cap.dev.set_flag(fk.FLAG_AUTO_EXPOSURE, S["auto_exposure"])
    cap.dev.set_flag(fk.FLAG_AUTO_WHITE_BALANCE, S["auto_wb"])

    # ---- microphone array (needs Microsoft's audio firmware, downloaded on request)
    import mic_firmware
    audio = locator = fetcher = None

    def start_mic():
        try:
            from kinect_audio import KinectAudio
            from sound import SoundLocator
            a, loc = KinectAudio(), SoundLocator()
            a.start()
            MIC_UI.update(state="ok", text="mic on")
            print("[ok] microphone array starting")
            return a, loc
        except Exception as e:  # noqa: BLE001
            MIC_UI.update(state="off", text="mic unavailable")
            print("[warn] mic array unavailable:", e)
            return None, None

    def start_fetch():
        f = mic_firmware.Fetcher()
        f.start()
        MIC_UI.update(state="fetching", text="mic support: 0%")
        print("[..] downloading the microphone firmware from Microsoft")
        return f

    if args.no_mic:
        MIC_UI.update(state="off", text="mic off")
    elif mic_firmware.find():
        audio, locator = start_mic()
    else:
        MIC_UI.update(state="missing", text="mic off (no firmware)")
        print("[info] mic array off: the Kinect audio firmware isn't here yet")
        if not headless and not S["mic_fw_declined"]:
            if ask_yes_no(FW_QUESTION):
                fetcher = start_fetch()
            else:
                S["mic_fw_declined"] = True
                save_settings(S)
    mic_votes = 0
    calib = None
    face_mem = FaceMemory()
    recent_faces = []
    focus_angle = 0.0          # where "focus on me" points before you are found
    smooth_prev = None
    from sound import image_x_to_angle

    if not headless:
        splash(win, ["Kinect ready - opening the camera..."])
    vcam = None if args.no_vcam else open_virtual_cam(out_w, out_h, args.fps)
    if vcam is None and not args.no_vcam:
        app_alert("The preview works, but other apps can't see the Kinect yet: \"Cam out\" needs the "
                  "OBS Virtual Camera, which comes with the free OBS Studio app (obsproject.com). "
                  "Open OBS once, click Start Virtual Camera, then press Cam out in KinectCam.", wait=False)
    tracker = Tracker()
    subject = SubjectFilter()
    framer = Framer()
    tilt = TiltController(S["tilt"])
    motion = SceneMotion()
    bg_image = load_bg_image(S["bg_image"])
    tilt_state = fk.get_tilt_state() or {}
    last_tilt_poll = 0.0
    manual_cx, manual_cy = SRC_W / 2, SRC_H / 2
    target = None
    fps_avg, last_t = 0.0, time.time()
    n = 0
    try:
        while True:
            full, frame, depth, ft = cap.latest()
            now = time.time()
            dt = min(0.1, now - last_t)
            last_t = now
            stalled = now - ft > 2.0

            if now - last_tilt_poll > 0.06:   # ~15 Hz: needed for smooth motor compensation
                tilt_state = fk.get_tilt_state() or tilt_state
                last_tilt_poll = now
            # ---- keep the picture steady while the motor turns (follow mode only:
            # a manual tilt should visibly move the picture)
            shift = motion.measure(frame) if frame is not None else 0.0
            if S["follow"] and tilt.motor_active(now, tilt_state) and abs(shift) > 0.3:
                framer.shift(shift)
                subject.shift(shift)
                tracker.shift(shift)

            # ---- source image for the selected mode (full resolution)
            if S["mode"] == "depth" and depth is not None:
                src = colorize_depth(depth)
            else:
                src = full.copy()
                if S["enhance"] or S["mode"] == "night":
                    src = enhance(src)

            # ---- microphone firmware download in the background
            if fetcher is not None:
                if fetcher.state == "done":
                    fetcher = None
                    audio, locator = start_mic()
                elif fetcher.state == "failed":
                    MIC_UI.update(state="missing", text="mic download failed")
                    app_alert("Couldn't download the microphone firmware:\n" + str(fetcher.error) +
                              "\n\nCheck the internet connection and press \"Get mic support\" to try again.",
                              wait=False)
                    fetcher = None
                else:
                    MIC_UI["text"] = (f"mic support: {fetcher.progress * 100:.0f}%" if fetcher.state == "downloading"
                                      else "mic support: unpacking")

            # ---- sound: where is the voice coming from?
            sound = None
            if locator is not None and audio.state == "streaming":
                focus = None
                if S["mic_focus"] == "me" and not (calib and calib.active):
                    if smooth_prev is not None:
                        focus_angle = image_x_to_angle(smooth_prev[0], S["mic_sign"])
                    focus = focus_angle        # last known direction of you (0 = straight ahead)
                locator.update(audio.recent(locator.N), now, focus_angle=focus, focus_width=FOCUS_WIDTH)
                level = locator.focus_level_db if (focus is not None and locator.focus_level_db is not None) else locator.level_db
                sound = {"angle": locator.angle, "speaking": locator.speaking, "level": level,
                         "x": locator.image_x(S["mic_sign"] or 1.0), "sources": locator.sources,
                         "focus": focus, "focus_width": FOCUS_WIDTH}

            # ---- find the person (on colour/IR image + depth)
            tracker.prefer_x = (sound["x"] if (S["voice_steer"] and sound and sound["speaking"]
                                               and sound["x"] is not None) else None)
            calibrating = calib is not None and calib.active
            dots = S["sound_dots"] and sound is not None
            if S["follow"] or S["background"] != "none" or calibrating or dots:
                target = tracker.detect(frame, depth, now)
                recent_faces = face_mem.update(tracker.faces, now)
                if not (S["follow"] or S["background"] != "none" or calibrating):
                    target = None          # faces only needed to place the sound dots
            else:
                target, recent_faces = None, []
            if calibrating:
                above = (locator.level_db - locator.floor_db) if locator.floor_db is not None else 0.0
                calib.update(now, tracker.faces, locator.angle if sound else None, above)
                if calib.stage == "done" and not calib.applied:
                    S["mic_gain"], S["mic_offset"] = calib.result
                    sound_mod.set_calibration(*calib.result)
                    save_settings(S)
                    calib.applied = True
            if calib is not None and calib.finished(now):
                calib = None
            # Learn which side of the image the mic array's "+" angles are on:
            # while one face is talking off-centre, voice and face must agree.
            if (S["mic_sign"] == 0 and sound and sound["speaking"] and sound["angle"] is not None
                    and abs(sound["angle"]) > 12 and target and abs(target[0] - SRC_W / 2) > 70):
                mic_votes += 1 if (sound["angle"] > 0) == (target[0] > SRC_W / 2) else -1
                if abs(mic_votes) >= 15:
                    S["mic_sign"] = 1 if mic_votes > 0 else -1
                    print(f"[ok] learned mic-array orientation (sign {S['mic_sign']:+d})")
            smooth = subject.update(target, dt)
            if tracker.last is None:
                subject.reset()
                smooth = None
            smooth_prev = smooth

            # ---- background effects
            if S["background"] != "none" and S["mode"] != "depth":
                person_mm = target[3] if target else 0
                if person_mm <= 0 and depth is not None:
                    v = depth[(depth > 500) & (depth < 3500)]
                    person_mm = float(np.percentile(v, 10)) if v.size else 0
                mask = person_mask(depth, person_mm, seed=target[:2] if target else None)
                mask = mask_to_full_res(mask, src.shape)
                bgi = bg_image if (bg_image is None or bg_image.shape[:2] == src.shape[:2]) else \
                    cv2.resize(bg_image, (src.shape[1], src.shape[0]))
                src = apply_background(src, mask, S["background"], S["bg_color"], bgi)

            if S["level"] and tilt_state:
                roll = math.degrees(math.atan2(tilt_state.get("ax", 0), tilt_state.get("ay", 1) or 1e-6))
                src = level_image(src, float(np.clip(roll, -20, 20)))

            # ---- framing (digital pan/zoom)
            if calib is not None and calib.active:   # calibration: show the whole view, keep still
                framer.set_goal(SRC_W / 2, SRC_H / 2, SRC_W, follow=False)
            elif S["follow"] and smooth:
                cx, cy, size = smooth
                crop_w = float(np.clip(size * 4.5 / S["follow_tightness"], 240, SRC_W))
                # Eyes about 38 % down the output frame.
                framer.set_goal(cx, cy + (crop_w / Framer.ASPECT) * 0.12, crop_w, follow=True)
            elif S["follow"]:
                pass  # nobody found yet / briefly lost: hold the current shot
            else:
                framer.set_goal(manual_cx, manual_cy, SRC_W / S["zoom"], follow=False)
            framer.step(dt, S["follow"] and not (calib and calib.active))

            # ---- motor (vertical follow)
            if S["follow"] and not (calib and calib.active):
                moved = tilt.update(now, smooth[1] if smooth else None, tracker.head_cut, tilt_state)
                if moved is not None:
                    S["tilt"] = int(moved)

            out = crop_to(src, to_full_res(framer.rect(), src.shape[1]), out_w, out_h)
            if S["mirror"]:
                out = cv2.flip(out, 1)
            if stalled:
                cv2.putText(out, "Kinect reconnecting...", (40, 80),
                            cv2.FONT_HERSHEY_SIMPLEX, 1.2, (0, 0, 255), 3, cv2.LINE_AA)

            if vcam is not None:
                vcam.send(out)

            fps_avg = fps_avg * 0.95 + (1 / max(dt, 1e-3)) * 0.05
            n += 1

            if args.test:
                if n in (1, args.test // 2, args.test) or n % 60 == 0:
                    sp = os.environ.get("KINECTCAM_SNAPDIR", HERE)
                    cv2.imwrite(os.path.join(sp, f"snap_{n:04d}_out.jpg"), out)
                    cv2.imwrite(os.path.join(sp, f"snap_{n:04d}_src.jpg"), src)
                    print(f"frame {n}: target={smooth} rect={tuple(round(v) for v in framer.rect())}"
                          f" tilt={tilt_state.get('angle')} fps={fps_avg:.1f} src={src.shape[1]}x{src.shape[0]}"
                          f" sound={None if not sound else (sound['angle'] and round(sound['angle']), sound['speaking'], round(sound['level']), [round(x['angle']) for x in sound['sources']])}")
                for k_frame, act in TEST_CLICKS:
                    if n == k_frame:
                        click_button(ui, act)

            if headless and not args.test:
                if vcam is not None:
                    vcam.sleep_until_next_frame()
                else:
                    time.sleep(1 / args.fps)
                continue

            # ---- preview with HUD + buttons (none of this is sent to the call)
            preview = render_preview(out, src, framer, smooth, S, tilt_state, vcam, fps_avg, ui, sound,
                                     recent_faces, depth, calib)
            if args.test:
                pass
            else:
                cv2.imshow(win, preview)
                key = cv2.waitKeyEx(1)
                if key != -1:
                    ch = chr(key).lower() if 0 <= key < 256 else ""
                    act = KEYMAP.get(ch) or KEYMAP.get(key)
                    if act:
                        ui["pending"].append(act)
                if macquit and macquit.requested():
                    print("[quit] Quit from the Dock/menu")
                    ui["pending"].append("quit")
                elif cv2.getWindowProperty(win, cv2.WND_PROP_VISIBLE) < 1:
                    print("[quit] preview window closed (visible =", cv2.getWindowProperty(win, cv2.WND_PROP_VISIBLE), ")")
                    ui["pending"].append("quit")

            # ---- run actions from keys and button clicks
            offer_mic = False
            while ui["pending"]:
                act = ui["pending"].pop(0)
                ui["flash"] = (act, now)
                if args.test:
                    print(f"[click] {act}", flush=True)
                if act == "quit":
                    print("[quit] quit requested")
                    raise KeyboardInterrupt
                elif act == "follow":
                    S["follow"] = not S["follow"]
                    manual_cx, manual_cy = framer.cx, framer.cy
                elif act == "mode":
                    S["mode"] = MODES[(MODES.index(S["mode"]) + 1) % len(MODES)]
                    cap.mode = S["mode"]
                elif act == "background":
                    S["background"] = BACKGROUNDS[(BACKGROUNDS.index(S["background"]) + 1) % len(BACKGROUNDS)]
                    if S["background"] == "image" and bg_image is None:
                        S["background"] = "none"
                        print("[info] start with --bg-image /path/to/picture.jpg to use the image background")
                elif act == "bgcolor":
                    S["bg_color"] = [int(c) for c in np.random.randint(0, 256, 3)]
                    if S["background"] in ("none", "blur"):
                        S["background"] = "solid"
                elif act == "zoom_in":
                    S["zoom"] = min(4.0, S["zoom"] + 0.25)
                    if S["follow"]:
                        S["follow_tightness"] = min(2.5, S["follow_tightness"] + 0.15)
                elif act == "zoom_out":
                    S["zoom"] = max(1.0, S["zoom"] - 0.25)
                    if S["follow"]:
                        S["follow_tightness"] = max(0.5, S["follow_tightness"] - 0.15)
                elif act in ("pan_left", "pan_right"):
                    if S["follow"]:
                        S["follow"] = False
                        manual_cx, manual_cy = framer.cx, framer.cy
                    manual_cx += -30 if act == "pan_left" else 30
                    manual_cx = float(np.clip(manual_cx, 0, SRC_W))
                elif act == "tilt_up":
                    S["tilt"] = tilt.manual(tilt.cmd + 3)
                elif act == "tilt_down":
                    S["tilt"] = tilt.manual(tilt.cmd - 3)
                elif act == "reset":
                    S["zoom"], S["follow_tightness"] = 1.0, 1.0
                    manual_cx, manual_cy = SRC_W / 2, SRC_H / 2
                    S["tilt"] = tilt.manual(0)
                    if S["follow"]:
                        framer.set_goal(SRC_W / 2, SRC_H / 2, SRC_W, follow=False)
                elif act in ("enhance", "level", "mirror"):
                    S[act] = not S[act]
                elif act == "led":
                    S["led"] = LEDS[(LEDS.index(S["led"]) + 1) % len(LEDS)] if S["led"] in LEDS else LEDS[0]
                    fk.set_led(S["led"])
                elif act == "vcam":
                    if vcam:
                        vcam.close()
                        vcam = None
                    else:
                        vcam = open_virtual_cam(out_w, out_h, args.fps)
                elif act == "hd":
                    S["hd"] = not S["hd"]
                    cap.set_hd(S["hd"])
                elif act in ("voice_steer", "mic_focus", "sound_dots") and locator is None and S.get("_mic_offer", True):
                    offer_mic = True            # a sound feature without microphones: offer the firmware
                    S["_mic_offer"] = False     # once per session, then the buttons just toggle
                    ui["pending"].insert(0, act)
                elif act == "voice_steer":
                    S["voice_steer"] = not S["voice_steer"]
                    if S["voice_steer"] and locator is None:
                        print("[info] voice steer needs the mic array (firmware/audios.bin)")
                elif act in ("grid", "sound_dots"):
                    S[act] = not S[act]
                elif act == "mic_focus":
                    S["mic_focus"] = "all" if S["mic_focus"] == "me" else "me"
                elif act == "calibrate":
                    if calib is not None and calib.active:
                        calib.cancel(now)
                    elif locator is None or audio is None:
                        offer_mic = True
                    else:
                        calib = MicCalibration(now, S["mic_gain"], S["mic_offset"], S["mic_sign"])
                        print("[..] mic calibration started")
                elif act == "auto_exposure":
                    S["auto_exposure"] = not S["auto_exposure"]
                    cap.dev.set_flag(fk.FLAG_AUTO_EXPOSURE, S["auto_exposure"])
                elif act == "auto_wb":
                    S["auto_wb"] = not S["auto_wb"]
                    cap.dev.set_flag(fk.FLAG_AUTO_WHITE_BALANCE, S["auto_wb"])
                elif act == "snapshot":
                    folder = os.path.expanduser("~/Pictures")
                    path = os.path.join(folder if os.path.isdir(folder) else HERE,
                                        time.strftime("KinectCam %Y-%m-%d %H.%M.%S.jpg"))
                    cv2.imwrite(path, out)
                    print("[ok] snapshot saved:", path)

            # ---- microphone wanted but no firmware yet: ask, then download automatically
            if offer_mic and fetcher is None and not args.no_mic:
                if mic_firmware.find():
                    audio, locator = start_mic()
                elif args.test or ask_yes_no(FW_QUESTION):
                    S["mic_fw_declined"] = False
                    fetcher = start_fetch()

            if args.test:
                if n in (1, args.test // 2, args.test) or n % 30 == 0:
                    cv2.imwrite(os.path.join(os.environ.get("KINECTCAM_SNAPDIR", HERE), f"snap_{n:04d}_preview.jpg"),
                                preview)
                if n >= args.test:
                    break
                time.sleep(max(0, 1 / args.fps - (time.time() - now)))
    except KeyboardInterrupt:
        pass
    except Exception as e:  # noqa: BLE001
        import traceback
        traceback.print_exc()
        app_alert(f"KinectCam stopped because of an error:\n{type(e).__name__}: {e}\n\n"
                  f"Details: {os.environ.get('KINECTCAM_LOG', '~/Library/Logs/KinectCam.log')}")
    finally:
        save_settings(S)
        if vcam:
            vcam.close()
        cv2.destroyAllWindows()
        if audio is not None:
            audio.stop(3)
        shutdown_kinect()
        os._exit(0)


if __name__ == "__main__":
    main()
