# Building the Windows version

Two ways to build the same portable package (`dist/KinectCam-Windows/` and `dist/KinectCam-Windows-x64.zip`):

## On Windows: `build_windows.ps1`

```powershell
py -3.12 -m venv .venv
.venv\Scripts\pip install -r requirements.txt
powershell -ExecutionPolicy Bypass -File windows\build_windows.ps1
```

Needs Python 3.12 and CMake (`winget install Python.Python.3.12 Kitware.CMake`). Everything else is downloaded into
`windows/_deps/` the first time. The script also patches libfreenect 0.7.5 (`src/usb_libusb10.c`) for two bugs that
stop the microphones on Windows after the audio firmware upload: a leaked handle to the re-enumerated audio device
(WinUSB handles are exclusive), and a failed open that was reported as success.

## On a Mac: `build_windows.sh`

Cross-compiles with llvm-mingw. It expects these in `windows/_deps/` (downloaded once):

| What | From |
|---|---|
| llvm-mingw 20261104 (ucrt, macOS universal) | github.com/mstorsjo/llvm-mingw |
| libusb 1.0.30 source | github.com/libusb/libusb |
| libfreenect 0.7.5 source | github.com/OpenKinect/libfreenect (tag v0.7.5) |
| libwdi 1.5.1 source (only `pki.c` is used) | github.com/pbatard/libwdi |
| Unity Capture (filter DLL, MIT) | github.com/schellingb/UnityCapture |
| Python 3.12.10 embeddable (amd64) | python.org |
| numpy, opencv-python, pyvirtualcam win_amd64 wheels | `pip download --platform win_amd64 --python-version 3.12 --only-binary=:all:` |

Note: `build_windows.sh` doesn't apply the libfreenect patches yet; use the PowerShell build for releases.

Pieces we wrote: `src/launcher.c` (KinectCam.exe), `src/kinect_setup.c` (one-time
driver + virtual-camera setup, elevated), `../winsetup.py` (runs it from the app).
