#!/bin/bash
# Build KinectCam for Windows (x64; also runs on Windows on ARM through x64 emulation)
# on this Mac, with the llvm-mingw cross compiler. Output:
#   dist/KinectCam-Windows/       portable folder (KinectCam.exe + runtime\)
#   dist/KinectCam-Windows-x64.zip
# Everything it needs is inside; the first launch asks Windows once for permission
# to set up the Kinect USB driver and the virtual camera.
set -euo pipefail
cd "$(dirname "$0")"
WIN="$PWD"
SRC="$(cd .. && pwd)"
DEPS="$WIN/_deps"
TC="$DEPS/llvm-mingw/llvm-mingw-20261104-ucrt-macos-universal/bin"
export PATH="$TC:/opt/homebrew/bin:$PATH"
CC=x86_64-w64-mingw32-clang
OUT="$SRC/dist/KinectCam-Windows"
R="$OUT/runtime"
BUILD="$WIN/build"
mkdir -p "$BUILD"

need() { [ -e "$1" ] || { echo "missing $1 - see windows/README-build.md"; exit 1; }; }
need "$TC/$CC"
need "$DEPS/python/python-3.12.10-embed-amd64.zip"
need "$SRC/firmware/audios.bin"

# ---------------------------------------------------------------- libusb
if [ ! -f "$DEPS/prefix-x64/bin/libusb-1.0.dll" ]; then
    echo "== libusb"
    (cd "$DEPS/libusb/libusb-1.0.30" && ./configure --host=x86_64-w64-mingw32 --prefix="$DEPS/prefix-x64" \
        --enable-shared --disable-static CFLAGS=-O2 >/dev/null && make -j8 >/dev/null && make install >/dev/null)
fi
# ------------------------------------------------------------ libfreenect
FN="$DEPS/libfreenect/libfreenect-0.7.5"
if [ ! -f "$FN/build-x64/lib/libfreenect.dll" ]; then
    echo "== libfreenect"
    grep -q 'static void sleep' "$FN/platform/windows/unistd.h" || \
        printf '\nstatic void sleep(unsigned int sec)\n{\n\tSleep(sec * 1000);\n}\n' >> "$FN/platform/windows/unistd.h"
    mkdir -p "$FN/build-x64"
    (cd "$FN/build-x64" && cmake .. -DCMAKE_SYSTEM_NAME=Windows -DCMAKE_C_COMPILER=$CC \
        -DCMAKE_CXX_COMPILER=x86_64-w64-mingw32-clang++ -DCMAKE_RC_COMPILER=x86_64-w64-mingw32-windres \
        -DLIBUSB_1_INCLUDE_DIR="$DEPS/prefix-x64/include/libusb-1.0" -DLIBUSB_1_LIBRARY="$DEPS/prefix-x64/lib/libusb-1.0.dll.a" \
        -DBUILD_EXAMPLES=OFF -DBUILD_FAKENECT=OFF -DBUILD_C_SYNC=OFF -DBUILD_CPP=OFF -DBUILD_PYTHON=OFF \
        -DBUILD_PYTHON3=OFF -DBUILD_OPENNI2_DRIVER=OFF -DBUILD_REDIST_PACKAGE=ON -DCMAKE_BUILD_TYPE=Release >/dev/null \
        && make -j8 freenect >/dev/null)
fi

# ------------------------------------------------------------- our exes
echo "== KinectCam.exe + kinect_setup.exe"
"$SRC/.venv/bin/python" "$SRC/tools/make_icon.py" "$BUILD/icon_1024.png"
"$SRC/.venv/bin/python" "$WIN/src/make_ico.py" "$BUILD/icon_1024.png" "$BUILD/KinectCam.ico"
cat > "$BUILD/launcher.manifest" <<'EOF'
<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<assembly xmlns="urn:schemas-microsoft-com:asm.v1" manifestVersion="1.0">
  <assemblyIdentity type="win32" name="KinectCam" version="1.0.0.0"/>
  <trustInfo xmlns="urn:schemas-microsoft-com:asm.v3"><security><requestedPrivileges>
    <requestedExecutionLevel level="asInvoker" uiAccess="false"/>
  </requestedPrivileges></security></trustInfo>
  <compatibility xmlns="urn:schemas-microsoft-com:compatibility.v1">
    <application><supportedOS Id="{8e0f7a12-bfb3-4fe8-b9a5-48fd50a15a9a}"/></application>
  </compatibility>
  <application xmlns="urn:schemas-microsoft-com:asm.v3"><windowsSettings>
    <activeCodePage xmlns="http://schemas.microsoft.com/SMI/2019/WindowsSettings">UTF-8</activeCodePage>
  </windowsSettings></application>
</assembly>
EOF
cat > "$BUILD/launcher.rc" <<EOF
#include <winuser.h>
#include <winver.h>
1 ICON "$BUILD/KinectCam.ico"
1 RT_MANIFEST "$BUILD/launcher.manifest"
1 VERSIONINFO
FILEVERSION 1,0,0,0
PRODUCTVERSION 1,0,0,0
BEGIN
  BLOCK "StringFileInfo"
  BEGIN
    BLOCK "040904b0"
    BEGIN
      VALUE "FileDescription", "KinectCam - Kinect v1 as a webcam"
      VALUE "ProductName", "KinectCam"
      VALUE "FileVersion", "1.0"
      VALUE "ProductVersion", "1.0"
      VALUE "OriginalFilename", "KinectCam.exe"
    END
  END
  BLOCK "VarFileInfo"
  BEGIN
    VALUE "Translation", 0x409, 1200
  END
END
EOF
x86_64-w64-mingw32-windres "$BUILD/launcher.rc" -O coff -o "$BUILD/launcher_res.o"
$CC -O2 -municode -mwindows -D_WIN32_WINNT=0x0A00 "$WIN/src/launcher.c" "$BUILD/launcher_res.o" \
    -o "$BUILD/KinectCam.exe" -lshell32 -luser32
$CC -O2 -municode -mconsole -DKINECTCAM_CONSOLE -D_WIN32_WINNT=0x0A00 "$WIN/src/launcher.c" "$BUILD/launcher_res.o" \
    -o "$BUILD/KinectCam-debug.exe" -lshell32 -luser32
W="$DEPS/libwdi/libwdi-1.5.1/libwdi"
x86_64-w64-mingw32-windres "$WIN/src/kinect_setup.rc" -I"$WIN/src" -O coff -o "$BUILD/kinect_setup_res.o"
$CC -O2 -municode -I"$WIN/src/shim" -I"$W" -D_WIN32_WINNT=0x0A00 -Wno-everything -c "$W/pki.c" -o "$BUILD/pki.o"
$CC -O2 -municode -D_WIN32_WINNT=0x0A00 -c "$WIN/src/kinect_setup.c" -o "$BUILD/kinect_setup.o"
$CC -municode -o "$BUILD/kinect_setup.exe" "$BUILD/kinect_setup.o" "$BUILD/pki.o" "$BUILD/kinect_setup_res.o" \
    -lsetupapi -lnewdev -lcrypt32 -lshell32 -lole32 -luser32 -ladvapi32

# --------------------------------------------------------------- package
echo "== assembling $OUT"
rm -rf "$OUT"
mkdir -p "$R/python" "$R/site-packages" "$R/app/firmware" "$R/lib" "$R/vcam" "$OUT/licenses"
cp "$BUILD/KinectCam.exe" "$OUT/"
cp "$BUILD/KinectCam-debug.exe" "$OUT/"
cp "$BUILD/kinect_setup.exe" "$R/"

unzip -q "$DEPS/python/python-3.12.10-embed-amd64.zip" -d "$R/python"
printf 'python312.zip\r\n.\r\n..\\site-packages\r\n..\\app\r\n' > "$R/python/python312._pth"
for w in "$DEPS"/wheels/*.whl; do unzip -q -o "$w" -d "$R/site-packages"; done
rm -f "$R/site-packages"/cv2/opencv_videoio_ffmpeg*.dll          # video files are never used
# Microsoft C++ runtime for the virtual camera module (app-local copy from numpy's wheel)
cp "$R/site-packages"/numpy.libs/msvcp140-*.dll "$R/python/msvcp140.dll"

cp "$SRC"/{kinectcam,kinect_device,kinect_audio,sound,usb_reset,winsetup}.py "$R/app/"
cp "$SRC/firmware/audios.bin" "$R/app/firmware/"
cp "$DEPS/prefix-x64/bin/libusb-1.0.dll" "$R/lib/"
cp "$FN/build-x64/lib/libfreenect.dll" "$R/lib/"
cp "$DEPS/unitycapture/UnityCapture-master/Install/UnityCaptureFilter64.dll" "$R/vcam/"

# precompile (same bytecode as the bundled 3.12; hash-based so file times don't matter)
PY312="$(uv python find --managed-python 3.12)"
"$PY312" -m compileall -q -j0 --invalidation-mode unchecked-hash "$R/site-packages" "$R/app" >/dev/null || true

# licences
cp "$DEPS/python/x64/LICENSE.txt" "$OUT/licenses/Python.txt" 2>/dev/null || true
cp "$DEPS/libusb/libusb-1.0.30/COPYING" "$OUT/licenses/libusb-LGPL-2.1.txt"
cp "$FN/APACHE20" "$OUT/licenses/libfreenect-Apache-2.0.txt" 2>/dev/null || true
cp "$DEPS/libwdi/libwdi-1.5.1/COPYING-LGPL" "$OUT/licenses/libwdi-LGPL-3.txt" 2>/dev/null || true
printf 'Unity Capture (filter) - MIT License - https://github.com/schellingb/UnityCapture\r\n' > "$OUT/licenses/UnityCapture-MIT.txt"
cp "$WIN/README-Windows.txt" "$OUT/README.txt"
cp "$WIN/KinectCam diagnose.bat" "$OUT/"
printf '@echo off\r\ntitle KinectCam debug\r\nrem Runs KinectCam showing what it is doing (for troubleshooting).\r\n"%%~dp0KinectCam-debug.exe"\r\necho.\r\necho KinectCam finished with code %%errorlevel%%\r\npause\r\n' > "$OUT/KinectCam debug.bat"

(cd "$SRC/dist" && rm -f KinectCam-Windows-x64.zip && zip -qr -9 KinectCam-Windows-x64.zip KinectCam-Windows)
echo "== done: $(du -sh "$OUT" | cut -f1) folder, $(du -h "$SRC/dist/KinectCam-Windows-x64.zip" | cut -f1) zip"
