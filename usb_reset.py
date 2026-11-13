"""Reset the Kinect v1 over USB (same effect as unplugging it), via libusb.

Fixes the "Bad tag" / "Bad cmd" / "Failed to fetch registration pad info"
state the Kinect gets into when a previous session ended mid-command.
"""
import ctypes
import os
import time

KINECT_VID = 0x045E
KINECT_PIDS = {0x02AE: "camera", 0x02B0: "motor", 0x02AD: "audio"}  # model 1414

_LIBDIR = os.environ.get("KINECTCAM_LIBDIR", "/nonexistent")
_lib_path = next((p for p in (os.path.join(_LIBDIR, "libusb-1.0.dll"),
                              os.path.join(_LIBDIR, "libusb-1.0.dylib"),
                              "/opt/homebrew/opt/libusb/lib/libusb-1.0.dylib",
                              "/usr/local/opt/libusb/lib/libusb-1.0.dylib") if os.path.exists(p)), None)


class _DevDesc(ctypes.Structure):
    _fields_ = [("bLength", ctypes.c_uint8), ("bDescriptorType", ctypes.c_uint8),
                ("bcdUSB", ctypes.c_uint16), ("bDeviceClass", ctypes.c_uint8),
                ("bDeviceSubClass", ctypes.c_uint8), ("bDeviceProtocol", ctypes.c_uint8),
                ("bMaxPacketSize0", ctypes.c_uint8), ("idVendor", ctypes.c_uint16),
                ("idProduct", ctypes.c_uint16), ("bcdDevice", ctypes.c_uint16),
                ("iManufacturer", ctypes.c_uint8), ("iProduct", ctypes.c_uint8),
                ("iSerialNumber", ctypes.c_uint8), ("bNumConfigurations", ctypes.c_uint8)]


def _list_kinect(usb, ctx):
    """Return {pid: device pointer} for Kinect sub-devices currently on the bus."""
    vp = ctypes.c_void_p
    found = {}
    devs = ctypes.POINTER(vp)()
    n = usb.libusb_get_device_list(ctx, ctypes.byref(devs))
    for i in range(max(n, 0)):
        d = _DevDesc()
        if usb.libusb_get_device_descriptor(devs[i], ctypes.byref(d)) == 0:
            if d.idVendor == KINECT_VID and d.idProduct in KINECT_PIDS:
                found[d.idProduct] = devs[i]
    return found, devs, n


def wait_for_kinect(timeout=15.0, verbose=True):
    """Block until the Kinect camera is on the USB bus (after a reset or replug)."""
    if _lib_path is None:
        return True
    usb = _load()
    ctx = ctypes.c_void_p()
    if usb.libusb_init(ctypes.byref(ctx)) != 0:
        return True
    t0, said = time.time(), False
    try:
        while time.time() - t0 < timeout:
            found, devs, n = _list_kinect(usb, ctx)
            if n > 0:
                usb.libusb_free_device_list(devs, 1)
            if 0x02AE in found:
                return True
            if verbose and not said:
                print("[..] waiting for the Kinect to reconnect on USB...")
                said = True
            time.sleep(0.5)
        return False
    finally:
        usb.libusb_exit(ctx)


def _load():
    usb = ctypes.CDLL(_lib_path)
    vp = ctypes.c_void_p
    usb.libusb_init.argtypes = [ctypes.POINTER(vp)]
    usb.libusb_get_device_list.argtypes = [vp, ctypes.POINTER(ctypes.POINTER(vp))]
    usb.libusb_get_device_list.restype = ctypes.c_ssize_t
    usb.libusb_get_device_descriptor.argtypes = [vp, ctypes.POINTER(_DevDesc)]
    usb.libusb_open.argtypes = [vp, ctypes.POINTER(vp)]
    usb.libusb_reset_device.argtypes = [vp]
    usb.libusb_close.argtypes = [vp]
    usb.libusb_free_device_list.argtypes = [ctypes.POINTER(vp), ctypes.c_int]
    usb.libusb_exit.argtypes = [vp]
    usb.libusb_claim_interface.argtypes = [vp, ctypes.c_int]
    usb.libusb_release_interface.argtypes = [vp, ctypes.c_int]
    usb.libusb_control_transfer.argtypes = [vp, ctypes.c_uint8, ctypes.c_uint8, ctypes.c_uint16,
                                            ctypes.c_uint16, ctypes.c_char_p, ctypes.c_uint16, ctypes.c_uint]
    return usb


def drain_camera(verbose=True):
    """Read and discard stale replies waiting in the Kinect camera's command
    channel. libfreenect matches replies by tag; a leftover reply from a
    session that was cut off makes its init fail with "Bad tag", "Bad cmd" or
    "read N bytes (expected 8)". Returns the number of stale replies removed,
    or -1 if the camera could not be opened."""
    if _lib_path is None:
        return -1
    usb = _load()
    ctx = ctypes.c_void_p()
    if usb.libusb_init(ctypes.byref(ctx)) != 0:
        return -1
    drained = -1
    try:
        found, devs, n = _list_kinect(usb, ctx)
        dev = found.get(0x02AE)
        h = ctypes.c_void_p()
        if dev is not None and usb.libusb_open(dev, ctypes.byref(h)) == 0:
            if usb.libusb_claim_interface(h, 0) == 0:
                drained, empty = 0, 0
                buf = ctypes.create_string_buffer(512)
                t0 = time.time()
                # Same request libfreenect uses to poll for a reply (vendor IN, request 0).
                while empty < 5 and time.time() - t0 < 2.0:
                    r = usb.libusb_control_transfer(h, 0xC0, 0, 0, 0, buf, 512, 60)
                    if r > 0:
                        drained += 1
                        empty = 0
                    else:
                        empty += 1
                        time.sleep(0.01)
                usb.libusb_release_interface(h, 0)
            usb.libusb_close(h)
        if n > 0:
            usb.libusb_free_device_list(devs, 1)
    finally:
        usb.libusb_exit(ctx)
    if verbose and drained > 0:
        print(f"[..] cleared {drained} stale Kinect command repl{'y' if drained == 1 else 'ies'}")
    return drained


def reset_kinect(verbose=True, only=None):
    """Returns the list of sub-devices that were reset."""
    if _lib_path is None:
        return []
    usb = _load()
    vp = ctypes.c_void_p
    ctx = vp()
    if usb.libusb_init(ctypes.byref(ctx)) != 0:
        return []
    done = []
    devs = ctypes.POINTER(vp)()
    n = usb.libusb_get_device_list(ctx, ctypes.byref(devs))
    for i in range(max(n, 0)):
        d = _DevDesc()
        if usb.libusb_get_device_descriptor(devs[i], ctypes.byref(d)) != 0:
            continue
        if d.idVendor == KINECT_VID and d.idProduct in KINECT_PIDS and \
                (only is None or KINECT_PIDS[d.idProduct] in only):
            h = vp()
            if usb.libusb_open(devs[i], ctypes.byref(h)) == 0:
                rc = usb.libusb_reset_device(h)
                usb.libusb_close(h)
                name = KINECT_PIDS[d.idProduct]
                if verbose:
                    print(f"[..] USB reset of Kinect {name}: {'ok' if rc in (0, -4) else rc}")
                done.append(name)
    if n > 0:
        usb.libusb_free_device_list(devs, 1)
    usb.libusb_exit(ctx)
    if done:
        time.sleep(1.0)  # it drops off the bus first...
        wait_for_kinect(verbose=verbose)  # ...then wait for it to come back (slow through hubs)
        time.sleep(1.5)  # and give the firmware a moment after enumeration
    return done


if __name__ == "__main__":
    import sys
    if "--drain" in sys.argv:
        print("stale replies drained:", drain_camera())
    else:
        print(reset_kinect() or "No Kinect found")


def driver_status():
    """{"camera"|"motor"|"audio": "ok" | "no_driver" | "error N"} for the Kinect
    parts on the bus (empty dict: Kinect not plugged in). On Windows a part
    without the WinUSB driver can't be opened (LIBUSB_ERROR_NOT_SUPPORTED)."""
    if _lib_path is None:
        return {}
    usb = _load()
    ctx = ctypes.c_void_p()
    if usb.libusb_init(ctypes.byref(ctx)) != 0:
        return {}
    out = {}
    try:
        found, devs, n = _list_kinect(usb, ctx)
        for pid, dev in found.items():
            h = ctypes.c_void_p()
            r = usb.libusb_open(dev, ctypes.byref(h))
            if r == 0:
                usb.libusb_close(h)
                out[KINECT_PIDS[pid]] = "ok"
            elif r == -12:                       # LIBUSB_ERROR_NOT_SUPPORTED
                out[KINECT_PIDS[pid]] = "no_driver"
            else:
                out[KINECT_PIDS[pid]] = f"error {r}"
        if n > 0:
            usb.libusb_free_device_list(devs, 1)
    finally:
        usb.libusb_exit(ctx)
    return out
