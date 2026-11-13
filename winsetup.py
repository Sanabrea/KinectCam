"""Windows only: the one-time setup KinectCam runs itself on first launch.

Windows won't let a program talk to a USB device that has no suitable driver,
and a virtual camera has to be registered with the system. Both need
administrator rights once, so KinectCam starts runtime/kinect_setup.exe with
the normal Windows "Allow" (UAC) prompt. See windows/src/kinect_setup.c.
"""
import ctypes
import os
import time
from ctypes import wintypes

RUNTIME = os.environ.get("KINECTCAM_RUNTIME", "")
SETUP_EXE = os.path.join(RUNTIME, "kinect_setup.exe")
VCAM_NAME = "KinectCam"
VCAM_CLSID = "{5C2CD55C-92AD-4999-8666-912BD3E70010}"     # Unity Capture filter, first device


def vcam_registered():
    import winreg
    try:
        key = rf"SOFTWARE\Classes\CLSID\{VCAM_CLSID}"
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, key) as k:
            name = winreg.QueryValueEx(k, "")[0]
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, key + r"\InprocServer32") as k:
            dll = winreg.QueryValueEx(k, "")[0]
        here = os.path.normcase(os.path.join(RUNTIME, "vcam", "UnityCaptureFilter64.dll"))
        return name == VCAM_NAME and os.path.normcase(dll) == here
    except OSError:
        return False


def driver_status():
    from usb_reset import driver_status as ds
    return ds()


def needs_setup():
    """(needs_it, reason) - reason is for the log."""
    st = driver_status()
    if any(v == "no_driver" for v in st.values()):
        return True, f"Kinect USB driver missing ({st})"
    if not vcam_registered():
        return True, "virtual camera not registered (or KinectCam was moved)"
    return False, f"ok ({st or 'Kinect not plugged in'})"


class _SHELLEXECUTEINFOW(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("fMask", ctypes.c_ulong), ("hwnd", wintypes.HWND),
                ("lpVerb", wintypes.LPCWSTR), ("lpFile", wintypes.LPCWSTR), ("lpParameters", wintypes.LPCWSTR),
                ("lpDirectory", wintypes.LPCWSTR), ("nShow", ctypes.c_int), ("hInstApp", wintypes.HINSTANCE),
                ("lpIDList", ctypes.c_void_p), ("lpClass", wintypes.LPCWSTR), ("hkeyClass", wintypes.HKEY),
                ("dwHotKey", wintypes.DWORD), ("hIconOrMonitor", wintypes.HANDLE), ("hProcess", wintypes.HANDLE)]


def run_setup(uninstall=False, pump=None):
    """Run kinect_setup.exe elevated and wait. Returns its exit code,
    or "cancelled" if the user said No to the Windows prompt."""
    params = (f'--uninstall "{RUNTIME}"' if uninstall
              else f'--install "{RUNTIME}" /i:UnityCaptureName={VCAM_NAME}')
    info = _SHELLEXECUTEINFOW()
    info.cbSize = ctypes.sizeof(info)
    info.fMask = 0x00000040            # SEE_MASK_NOCLOSEPROCESS
    info.lpVerb = "runas"
    info.lpFile = SETUP_EXE
    info.lpParameters = params
    info.nShow = 0
    if not ctypes.windll.shell32.ShellExecuteExW(ctypes.byref(info)):
        err = ctypes.GetLastError()
        return "cancelled" if err == 1223 else f"error {err}"
    k32 = ctypes.windll.kernel32
    while k32.WaitForSingleObject(info.hProcess, 100) == 0x102:     # WAIT_TIMEOUT
        if pump:
            pump()
    code = wintypes.DWORD()
    k32.GetExitCodeProcess(info.hProcess, ctypes.byref(code))
    k32.CloseHandle(info.hProcess)
    return int(code.value)


def ensure(splash=None):
    """Called at startup. Runs the setup if needed; returns a message for the
    user if something is still not right, else None."""
    need, why = needs_setup()
    print("[setup]", why)
    if not need:
        return None
    if splash:
        splash(["One-time setup", "Windows will ask for permission to set up the Kinect",
                "(USB driver + KinectCam virtual camera). Please click Yes."])
    rc = run_setup(pump=(lambda: splash(None)) if splash else None)
    print("[setup] kinect_setup.exe ->", rc)
    if rc == "cancelled":
        return ("KinectCam needs to set up the Kinect once, and Windows asked for permission but it "
                "was declined. Open KinectCam again and click Yes.")
    if rc != 0:
        log = os.path.join(os.environ.get("PROGRAMDATA", r"C:\ProgramData"), "KinectCam", "setup.log")
        what = {1: "the Kinect USB driver", 2: "the virtual camera", 3: "the USB driver and the virtual camera"}
        return (f"The one-time setup could not install {what.get(rc, 'everything')} (code {rc}).\n\n"
                f"Details: {log}")
    if splash:
        splash(["Setup done - waiting for the Kinect to reconnect..."])
    t0 = time.time()                       # Windows re-attaches the devices with the new driver
    while time.time() - t0 < 10:
        st = driver_status()
        if st and all(v == "ok" for v in st.values()):
            break
        if splash:
            splash(None)
        time.sleep(0.3)
    return None


def set_window_icon(title):
    """Give the OpenCV window KinectCam's icon (from KinectCam.exe), so the
    taskbar doesn't show a generic one."""
    try:
        u32 = ctypes.windll.user32
        hwnd = u32.FindWindowW(None, title)
        if not hwnd:
            return
        hinst = ctypes.windll.kernel32.GetModuleHandleW(None)
        for size, which in ((16, 0), (32, 1)):                   # ICON_SMALL, ICON_BIG
            icon = u32.LoadImageW(hinst, 1, 1, size, size, 0)     # resource 1, IMAGE_ICON
            if icon:
                u32.SendMessageW(hwnd, 0x0080, which, icon)       # WM_SETICON
    except Exception:  # noqa: BLE001
        pass
