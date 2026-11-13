# Building the Windows version (on this Mac)

`./build_windows.sh` cross-compiles and assembles `dist/KinectCam-Windows/` and
`dist/KinectCam-Windows-x64.zip`. It expects these in `windows/_deps/` (downloaded once):

| What | From |
|---|---|
| llvm-mingw 20261104 (ucrt, macOS universal) | github.com/mstorsjo/llvm-mingw |
| libusb 1.0.30 source | github.com/libusb/libusb |
| libfreenect 0.7.5 source | github.com/OpenKinect/libfreenect (tag v0.7.5) |
| libwdi 1.5.1 source (only `pki.c` is used) | github.com/pbatard/libwdi |
| Unity Capture (filter DLL, MIT) | github.com/schellingb/UnityCapture |
| Python 3.12.10 embeddable (amd64) | python.org |
| numpy, opencv-python, pyvirtualcam win_amd64 wheels | `pip download --platform win_amd64 --python-version 3.12 --only-binary=:all:` |

Pieces we wrote: `src/launcher.c` (KinectCam.exe), `src/kinect_setup.c` (one-time
driver + virtual-camera setup, elevated), `../winsetup.py` (runs it from the app).
