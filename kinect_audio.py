"""Kinect v1 microphone array (4 mics) via libfreenect's audio API (ctypes).

The Kinect's audio chip needs Microsoft's firmware (firmware/audios.bin) uploaded
at every power-up; libfreenect does that when the audio device is opened.
Audio runs on its own libfreenect context and thread, so it never interferes
with the camera thread (kinect_device.py).

Output: 16 kHz, 4 channels (mic1..mic4, left to right along the Kinect bar),
kept in a ring buffer that the direction finder reads.
"""
import collections
import ctypes
import os
import threading
import time

import numpy as np

import kinect_device as kd   # reuses the loaded libfreenect + Timeval

_lib = kd._lib
vp = ctypes.c_void_p
I32P = ctypes.POINTER(ctypes.c_int32)
I16P = ctypes.POINTER(ctypes.c_int16)
AUDIO_IN_CB = ctypes.CFUNCTYPE(None, vp, ctypes.c_int, I32P, I32P, I32P, I32P, I16P, vp)

_lib.freenect_set_audio_in_callback.argtypes = [vp, AUDIO_IN_CB]
_lib.freenect_set_audio_in_callback.restype = None
_lib.freenect_start_audio.argtypes = [vp]
_lib.freenect_stop_audio.argtypes = [vp]
_lib.freenect_set_fw_address_nui.argtypes = [vp, ctypes.c_void_p, ctypes.c_uint]
_lib.freenect_set_fw_address_nui.restype = None

DEV_AUDIO = 0x04
RATE = 16000
FIRMWARE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "firmware", "audios.bin")


class KinectAudio(threading.Thread):
    def __init__(self, seconds=4.0):
        super().__init__(daemon=True, name="kinect-audio")
        self.buf = collections.deque(maxlen=int(seconds * RATE / 256) + 4)  # blocks of (n, 4)
        self.lock = threading.Lock()
        self.samples = 0
        self.restarts = 0
        self.state = "starting"
        self.error = None
        self.running = True
        self.stopped = threading.Event()
        self.log = collections.deque(maxlen=100)
        self._cb = AUDIO_IN_CB(self._on_audio)
        self._log_cb = kd.LOG_CB(self._on_log)
        self._fw = None
        self._ctx = vp()
        self._dev = vp()

    def _on_log(self, ctx, level, msg):
        self.log.append((time.time(), level, msg.decode(errors="replace").rstrip()))

    def _on_audio(self, dev, n, m1, m2, m3, m4, cancelled, unknown):
        if n <= 0:
            return
        block = np.empty((n, 4), np.float32)
        for i, m in enumerate((m1, m2, m3, m4)):
            block[:, i] = np.ctypeslib.as_array(m, shape=(n,))
        block *= 1.0 / 2147483648.0   # int32 -> [-1, 1)
        with self.lock:
            self.buf.append(block)
            self.samples += n

    def recent(self, n):
        """Last n samples as an (n, 4) array (or fewer if not available yet)."""
        with self.lock:
            blocks = list(self.buf)
        if not blocks:
            return np.zeros((0, 4), np.float32)
        a = np.concatenate(blocks)
        return a[-n:]

    def stop(self, timeout=3.0):
        self.running = False
        return self.stopped.wait(timeout)

    def run(self):
        try:
            if not os.path.exists(FIRMWARE):
                self.state, self.error = "no firmware", f"missing {FIRMWARE}"
                return
            with open(FIRMWARE, "rb") as f:
                fw = f.read()
            self._fw = ctypes.create_string_buffer(fw, len(fw))
            if _lib.freenect_init(ctypes.byref(self._ctx), None) < 0:
                self.state, self.error = "error", "freenect_init failed"
                return
            _lib.freenect_set_log_callback(self._ctx, self._log_cb)
            _lib.freenect_set_log_level(self._ctx, kd.LOG_NOTICE)
            _lib.freenect_set_fw_address_nui(self._ctx, ctypes.cast(self._fw, ctypes.c_void_p), len(fw))
            _lib.freenect_select_subdevices(self._ctx, DEV_AUDIO)
            self.state = "loading firmware"
            ok = False
            for attempt in range(3):
                if _lib.freenect_num_devices(self._ctx) > 0 and \
                        _lib.freenect_open_device(self._ctx, ctypes.byref(self._dev), 0) >= 0:
                    ok = True
                    break
                time.sleep(2.0)   # after a firmware upload the audio device re-enumerates
            if not ok:
                self.state, self.error = "error", "could not open the Kinect audio device"
                return
            _lib.freenect_set_audio_in_callback(self._dev, self._cb)
            if _lib.freenect_start_audio(self._dev) < 0:
                self.state, self.error = "error", "freenect_start_audio failed"
                return
            self.state = "streaming"
            tv = kd.Timeval(0, 50000)
            last_n, last_change = self.samples, time.time()
            while self.running:
                _lib.freenect_process_events_timeout(self._ctx, ctypes.byref(tv))
                now = time.time()
                if self.samples != last_n:
                    last_n, last_change = self.samples, now
                elif now - last_change > 1.5:
                    # The audio stream sometimes starts silent (macOS refuses its
                    # isochronous transfers: LIBUSB_ERROR_OTHER). Restarting the
                    # stream doesn't help; closing and reopening the device does.
                    self.restarts += 1
                    self.state = "reopening"
                    _lib.freenect_stop_audio(self._dev)
                    _lib.freenect_close_device(self._dev)
                    self._dev = vp()
                    for _ in range(6):
                        _lib.freenect_process_events_timeout(self._ctx, ctypes.byref(tv))
                    if _lib.freenect_open_device(self._ctx, ctypes.byref(self._dev), 0) >= 0:
                        _lib.freenect_set_audio_in_callback(self._dev, self._cb)
                        _lib.freenect_start_audio(self._dev)
                        self.state = "streaming"
                    else:
                        self._dev = vp()
                        time.sleep(1.0)
                        self._reopen_failures = getattr(self, "_reopen_failures", 0) + 1
                        if self._reopen_failures > 5:
                            self.state, self.error = "error", "audio device would not reopen"
                            return
                    last_change = time.time()
        finally:
            try:
                if self._dev:
                    _lib.freenect_stop_audio(self._dev)
                    _lib.freenect_close_device(self._dev)
                if self._ctx:
                    _lib.freenect_shutdown(self._ctx)
            finally:
                if self.state == "streaming":
                    self.state = "stopped"
                self.stopped.set()


if __name__ == "__main__":
    a = KinectAudio()
    a.start()
    t0 = time.time()
    while a.state not in ("streaming", "error", "no firmware") and time.time() - t0 < 30:
        time.sleep(0.1)
    print("state:", a.state, a.error or "", f"after {time.time() - t0:.1f}s")
    time.sleep(1.5)
    print("samples/s:", round(a.samples / max(1e-3, time.time() - t0 - 1.5)))
    x = a.recent(RATE)
    print("quiet RMS per mic (dBFS):", [round(20 * np.log10(np.sqrt(np.mean(x[:, i] ** 2)) + 1e-12), 1) for i in range(4)])
    for _, lvl, m in list(a.log)[-6:]:
        print("   log:", m[:100])
    a.stop()
