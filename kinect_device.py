"""Kinect v1 driver layer on libfreenect's low-level (async) API, via ctypes.

Why not libfreenect's "sync" wrapper: when the Kinect is behind a hub/dock,
the commands that switch the camera's stream on are sometimes lost, so the
camera connects but never sends a frame. The sync wrapper then blocks
forever and can only be fixed by killing the process. Here one thread owns
the device and recovers in steps, cheapest first:

  1. restart the streams on the open device (re-sends the start commands)
  2. close and reopen the device
  3. USB-reset the Kinect and start over

All libfreenect calls happen on that one thread (libfreenect is not thread
safe); the app talks to it through a small command queue. libfreenect's log
goes to a ring buffer instead of the terminal.

It also exposes controls the sync wrapper hides: auto exposure / white
balance, hardware mirroring, and the 1280x1024 high-resolution RGB mode.
"""
import collections
import ctypes
import os
import queue
import threading
import time

import numpy as np

# Inside KinectCam.app the libraries ship in Contents/Frameworks (KINECTCAM_LIBDIR).
_LIBDIR = os.environ.get("KINECTCAM_LIBDIR", "")
if not _LIBDIR and os.name == "nt":       # Windows package: runtime\app\ (this file) -> runtime\lib
    _LIBDIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lib")
    os.environ["KINECTCAM_LIBDIR"] = _LIBDIR
if _LIBDIR and hasattr(os, "add_dll_directory"):      # Windows: let libfreenect.dll find libusb-1.0.dll
    os.add_dll_directory(_LIBDIR)
_CANDIDATES = [
    os.path.join(_LIBDIR, "libfreenect.dll") if _LIBDIR else "",
    os.path.join(_LIBDIR, "libfreenect.dylib") if _LIBDIR else "",
    "/opt/homebrew/opt/libfreenect/lib/libfreenect.dylib",
    "/usr/local/opt/libfreenect/lib/libfreenect.dylib",
]
_path = next((p for p in _CANDIDATES if os.path.exists(p)), None)
if _path is None:
    raise OSError("libfreenect not found (on a Mac: brew install libfreenect; on Windows it ships in runtime\\lib)")
_lib = ctypes.CDLL(_path)

# ----------------------------------------------------------------- constants
RES_MEDIUM, RES_HIGH = 1, 2
VIDEO_RGB, VIDEO_IR_8BIT = 0, 2
DEPTH_REGISTERED = 4
DEV_MOTOR, DEV_CAMERA = 0x01, 0x02
LOG_ERROR, LOG_WARNING, LOG_NOTICE = 1, 2, 3

LED_OFF, LED_GREEN, LED_RED, LED_YELLOW, LED_BLINK_GREEN, _, LED_BLINK_RED_YELLOW = range(7)
LED_NAMES = {LED_OFF: "off", LED_GREEN: "green", LED_RED: "red", LED_YELLOW: "yellow",
             LED_BLINK_GREEN: "blink green", LED_BLINK_RED_YELLOW: "blink red/yellow"}

FLAG_AUTO_EXPOSURE = 1 << 14
FLAG_AUTO_WHITE_BALANCE = 1 << 1
FLAG_MIRROR_DEPTH = 1 << 16
FLAG_MIRROR_VIDEO = 1 << 17

COUNTS_PER_G = 819.0


# -------------------------------------------------------------------- ctypes
class FrameMode(ctypes.Structure):
    _fields_ = [("reserved", ctypes.c_uint32), ("resolution", ctypes.c_int32), ("fmt", ctypes.c_int32),
                ("bytes", ctypes.c_int32), ("width", ctypes.c_int16), ("height", ctypes.c_int16),
                ("data_bits_per_pixel", ctypes.c_int8), ("padding_bits_per_pixel", ctypes.c_int8),
                ("framerate", ctypes.c_int8), ("is_valid", ctypes.c_int8)]


class RawTiltState(ctypes.Structure):
    _fields_ = [("accelerometer_x", ctypes.c_int16), ("accelerometer_y", ctypes.c_int16),
                ("accelerometer_z", ctypes.c_int16), ("tilt_angle", ctypes.c_int8),
                ("tilt_status", ctypes.c_int)]


class Timeval(ctypes.Structure):
    _fields_ = [("tv_sec", ctypes.c_long), ("tv_usec", ctypes.c_int32)]


vp = ctypes.c_void_p
FRAME_CB = ctypes.CFUNCTYPE(None, vp, vp, ctypes.c_uint32)
LOG_CB = ctypes.CFUNCTYPE(None, vp, ctypes.c_int, ctypes.c_char_p)

_sig = {
    "freenect_init": (ctypes.c_int, [ctypes.POINTER(vp), vp]),
    "freenect_shutdown": (ctypes.c_int, [vp]),
    "freenect_set_log_level": (None, [vp, ctypes.c_int]),
    "freenect_set_log_callback": (None, [vp, LOG_CB]),
    "freenect_select_subdevices": (None, [vp, ctypes.c_int]),
    "freenect_num_devices": (ctypes.c_int, [vp]),
    "freenect_open_device": (ctypes.c_int, [vp, ctypes.POINTER(vp), ctypes.c_int]),
    "freenect_close_device": (ctypes.c_int, [vp]),
    "freenect_process_events_timeout": (ctypes.c_int, [vp, ctypes.POINTER(Timeval)]),
    "freenect_set_video_callback": (None, [vp, FRAME_CB]),
    "freenect_set_depth_callback": (None, [vp, FRAME_CB]),
    "freenect_find_video_mode": (FrameMode, [ctypes.c_int, ctypes.c_int]),
    "freenect_find_depth_mode": (FrameMode, [ctypes.c_int, ctypes.c_int]),
    "freenect_set_video_mode": (ctypes.c_int, [vp, FrameMode]),
    "freenect_set_depth_mode": (ctypes.c_int, [vp, FrameMode]),
    "freenect_start_video": (ctypes.c_int, [vp]),
    "freenect_stop_video": (ctypes.c_int, [vp]),
    "freenect_start_depth": (ctypes.c_int, [vp]),
    "freenect_stop_depth": (ctypes.c_int, [vp]),
    "freenect_update_tilt_state": (ctypes.c_int, [vp]),
    "freenect_get_tilt_state": (ctypes.POINTER(RawTiltState), [vp]),
    "freenect_get_tilt_degs": (ctypes.c_double, [ctypes.POINTER(RawTiltState)]),
    "freenect_set_tilt_degs": (ctypes.c_int, [vp, ctypes.c_double]),
    "freenect_set_led": (ctypes.c_int, [vp, ctypes.c_int]),
    "freenect_set_flag": (ctypes.c_int, [vp, ctypes.c_int, ctypes.c_int]),
}
for _name, (_res, _args) in _sig.items():
    _f = getattr(_lib, _name)
    _f.restype, _f.argtypes = _res, _args


# -------------------------------------------------------------------- device
class KinectDevice(threading.Thread):
    START_TIMEOUT = 4.0   # s without a first video frame after (re)starting streams
    STALL_TIMEOUT = 2.0   # s without frames while streaming
    DEPTH_TIMEOUT = 2.5   # s without a depth frame (after starting depth) before restarting it
    FIRST_START_TIMEOUT = 1.0  # the first start after opening is only a primer (see run())
    STREAM_RESTARTS = 3   # in-place restarts before reopening the device
    REOPENS = 2           # reopens before a USB reset

    def __init__(self, mode="color", high_res=False):
        super().__init__(daemon=True, name="kinect")
        self.mode = mode
        self.high_res = high_res
        self.cmds = queue.Queue()
        self.lock = threading.Lock()
        self.video = None
        self.depth = None
        self.video_t = 0.0
        self.depth_t = 0.0
        self.video_frames = 0
        self.tilt = {}
        self.state = "starting"
        self.recoveries = collections.Counter()
        self.log = collections.deque(maxlen=200)
        self.running = True
        self.stopped = threading.Event()
        self._ctx = vp()
        self._dev = vp()
        # keep the C callbacks alive for the lifetime of the device
        self._video_cb = FRAME_CB(self._on_video)
        self._depth_cb = FRAME_CB(self._on_depth)
        self._log_cb = LOG_CB(self._on_log)
        self._video_shape = None
        self._last_flags = {}
        self._depth_started_t = 0.0
        self._depth_starts = 0

    # ---- public API (any thread) -------------------------------------------
    def latest(self):
        with self.lock:
            return self.video, self.depth, self.video_t

    def set_mode(self, mode, high_res=None):
        self.cmds.put(("mode", mode, self.high_res if high_res is None else high_res))

    def set_tilt(self, degrees):
        degrees = int(max(-27, min(27, round(degrees))))
        self.cmds.put(("tilt", degrees))
        return degrees

    def set_led(self, option):
        self.cmds.put(("led", option))

    def set_flag(self, flag, on):
        self.cmds.put(("flag", flag, bool(on)))

    def get_tilt_state(self):
        return dict(self.tilt) if self.tilt else None

    def stop(self, timeout=4.0):
        self.running = False
        return self.stopped.wait(timeout)

    def recent_log(self, n=10):
        return list(self.log)[-n:]

    # ---- callbacks (device thread) -----------------------------------------
    def _on_video(self, dev, data, ts):
        shape = self._video_shape
        if not data or shape is None:
            return
        n = int(np.prod(shape))
        a = np.ctypeslib.as_array(ctypes.cast(data, ctypes.POINTER(ctypes.c_uint8)), shape=(n,))
        frame = a.reshape(shape).copy()
        with self.lock:
            self.video = frame
            self.video_t = time.time()
            self.video_frames += 1

    def _on_depth(self, dev, data, ts):
        if not data:
            return
        a = np.ctypeslib.as_array(ctypes.cast(data, ctypes.POINTER(ctypes.c_uint16)), shape=(480 * 640,))
        d = a.reshape(480, 640).copy()
        with self.lock:
            self.depth = d
            self.depth_t = time.time()

    def _on_log(self, ctx, level, msg):
        try:
            self.log.append((time.time(), level, msg.decode(errors="replace").rstrip()))
        except Exception:  # noqa: BLE001
            pass

    # ---- device thread -----------------------------------------------------
    def _events(self, seconds):
        tv = Timeval(0, int(min(seconds, 0.05) * 1e6))
        end = time.time() + seconds
        while True:
            _lib.freenect_process_events_timeout(self._ctx, ctypes.byref(tv))
            if time.time() >= end:
                break

    def _init_ctx(self):
        self._ctx = vp()
        if _lib.freenect_init(ctypes.byref(self._ctx), None) < 0:
            raise RuntimeError("freenect_init failed")
        _lib.freenect_set_log_callback(self._ctx, self._log_cb)
        _lib.freenect_set_log_level(self._ctx, LOG_NOTICE)
        _lib.freenect_select_subdevices(self._ctx, DEV_MOTOR | DEV_CAMERA)

    def _open(self):
        if _lib.freenect_num_devices(self._ctx) < 1:
            return False
        self._dev = vp()
        if _lib.freenect_open_device(self._ctx, ctypes.byref(self._dev), 0) < 0:
            self._dev = vp()
            return False
        _lib.freenect_set_video_callback(self._dev, self._video_cb)
        _lib.freenect_set_depth_callback(self._dev, self._depth_cb)
        return True

    def _close(self):
        if self._dev:
            self._stop_streams()
            _lib.freenect_close_device(self._dev)
            self._dev = vp()

    def _shutdown_ctx(self):
        self._close()
        if self._ctx:
            _lib.freenect_shutdown(self._ctx)
            self._ctx = vp()

    def _apply_video_mode(self):
        res = RES_HIGH if (self.high_res and self.mode != "night") else RES_MEDIUM
        fmt = VIDEO_IR_8BIT if self.mode == "night" else VIDEO_RGB
        m = _lib.freenect_find_video_mode(res, fmt)
        if not m.is_valid:
            m = _lib.freenect_find_video_mode(RES_MEDIUM, fmt)
        _lib.freenect_set_video_mode(self._dev, m)
        self._video_shape = (m.height, m.width) if fmt == VIDEO_IR_8BIT else (m.height, m.width, 3)

    def _stop_streams(self):
        _lib.freenect_stop_depth(self._dev)
        _lib.freenect_stop_video(self._dev)
        self._events(0.15)

    def _start_streams(self, timeout=None):
        """Video first, then depth once video flows: starting depth first is
        what most often leaves the RGB stream dead on macOS."""
        self._apply_video_mode()
        _lib.freenect_set_depth_mode(self._dev, _lib.freenect_find_depth_mode(RES_MEDIUM, DEPTH_REGISTERED))
        with self.lock:
            self.video_frames = 0
        _lib.freenect_start_video(self._dev)
        t0 = time.time()
        timeout = self.START_TIMEOUT if timeout is None else timeout
        while self.running and time.time() - t0 < timeout:
            self._events(0.05)
            self._handle_cmds()
            if self.video_frames > 0:
                self._start_depth()
                for flag, on in self._last_flags.items():
                    _lib.freenect_set_flag(self._dev, flag, int(on))
                return True
        return False

    def _start_depth(self):
        _lib.freenect_start_depth(self._dev)
        self._depth_started_t = time.time()
        self._depth_starts += 1

    def _restart_depth(self):
        """Depth sometimes doesn't start (same lost-command problem as video);
        restart just the depth stream, video keeps running."""
        _lib.freenect_stop_depth(self._dev)
        self._events(0.1)
        self._start_depth()

    def _handle_cmds(self):
        while True:
            try:
                cmd = self.cmds.get_nowait()
            except queue.Empty:
                return
            kind = cmd[0]
            if kind == "tilt":
                _lib.freenect_set_tilt_degs(self._dev, float(cmd[1]))
            elif kind == "led":
                _lib.freenect_set_led(self._dev, cmd[1])
            elif kind == "flag":
                self._last_flags[cmd[1]] = cmd[2]
                _lib.freenect_set_flag(self._dev, cmd[1], int(cmd[2]))
            elif kind == "mode":
                if (cmd[1], cmd[2]) != (self.mode, self.high_res):
                    self.mode, self.high_res = cmd[1], cmd[2]
                    _lib.freenect_stop_video(self._dev)
                    self._events(0.1)
                    self._apply_video_mode()
                    _lib.freenect_start_video(self._dev)
                    with self.lock:
                        self.video_t = time.time()  # give the new mode time to start

    def _poll_tilt(self):
        if _lib.freenect_update_tilt_state(self._dev) < 0:
            return
        p = _lib.freenect_get_tilt_state(self._dev)
        if not p:
            return
        s = p.contents
        self.tilt = {
            "angle": s.tilt_angle / 2.0,
            "status": s.tilt_status,  # 0 stopped, 1 at limit, 4 moving
            "ax": s.accelerometer_x / COUNTS_PER_G,
            "ay": s.accelerometer_y / COUNTS_PER_G,
            "az": s.accelerometer_z / COUNTS_PER_G,
        }

    def _note(self, what):
        self.recoveries[what] += 1
        self.log.append((time.time(), -1, f"recovery: {what}"))

    def run(self):
        from usb_reset import drain_camera, reset_kinect, wait_for_kinect
        reopen_failures = 0
        try:
            while self.running:
                # ---- connect
                self.state = "connecting"
                if not wait_for_kinect(timeout=5, verbose=False):
                    self.state = "not on USB"
                    continue
                drain_camera(verbose=False)
                try:
                    self._init_ctx()
                except RuntimeError:
                    time.sleep(1)
                    continue
                if not self._open():
                    self._note("open failed")
                    self._shutdown_ctx()
                    reopen_failures += 1
                    if reopen_failures > self.REOPENS:
                        self.state = "resetting USB"
                        reset_kinect(verbose=False)
                        self._note("usb reset")
                        reopen_failures = 0
                    time.sleep(0.5)
                    continue

                # ---- start streams, restarting them in place if the camera stays silent
                self.state = "starting streams"
                self._depth_starts = 0
                ok = False
                for i in range(self.STREAM_RESTARTS + 1):
                    if not self.running:
                        break
                    # On this Kinect the very first stream start after opening never
                    # delivers frames (measured: 0 of 15 starts, even after 12 s),
                    # while a restart works within ~2 s. So the first try is only a
                    # short "priming" start.
                    if self._start_streams(self.FIRST_START_TIMEOUT if i == 0 else None):
                        ok = True
                        break
                    if i > 0:
                        self._note("stream restart")
                    self._stop_streams()
                if not ok:
                    self._shutdown_ctx()
                    reopen_failures += 1
                    self._note("reopen")
                    if reopen_failures > self.REOPENS:
                        self.state = "resetting USB"
                        reset_kinect(verbose=False)
                        self._note("usb reset")
                        reopen_failures = 0
                    continue
                reopen_failures = 0

                # ---- stream
                self.state = "streaming"
                last_tilt = 0.0
                while self.running:
                    self._events(0.02)
                    self._handle_cmds()
                    now = time.time()
                    if now - last_tilt > 0.066:
                        self._poll_tilt()
                        last_tilt = now
                    depth_wait = self.FIRST_START_TIMEOUT if self._depth_starts == 1 else self.DEPTH_TIMEOUT
                    if now - max(self.depth_t, self._depth_started_t) > depth_wait:
                        if self._depth_starts > 1:
                            self._note("depth restart")
                        self._restart_depth()
                    if now - self.video_t > self.STALL_TIMEOUT:
                        # stalled mid-session: restart streams on the same device
                        self.state = "recovering"
                        self._note("stall restart")
                        self._stop_streams()
                        if self._start_streams():
                            self.state = "streaming"
                            continue
                        break   # -> reopen
                if self.running:
                    self._shutdown_ctx()
        finally:
            try:
                if self._dev:
                    _lib.freenect_set_led(self._dev, LED_BLINK_GREEN)
                    self._events(0.05)
                self._shutdown_ctx()
            finally:
                self.state = "stopped"
                self.stopped.set()


# --------------------------------------------- module-level convenience API ---
_device = None


def start(mode="color", high_res=False):
    global _device
    _device = KinectDevice(mode, high_res)
    _device.start()
    return _device


def device():
    return _device


def set_tilt(degrees, index=0):
    return _device.set_tilt(degrees) if _device else int(degrees)


def set_led(option, index=0):
    if _device:
        _device.set_led(option)


def get_tilt_state(index=0):
    return _device.get_tilt_state() if _device else None


def stop(timeout=4.0):
    return _device.stop(timeout) if _device else True
