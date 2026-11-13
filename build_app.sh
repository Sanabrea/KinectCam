#!/bin/bash
# Build a self-contained KinectCam.app: its own Python 3.12, numpy, OpenCV,
# pyvirtualcam, libfreenect and libusb. Microsoft's Kinect audio firmware is NOT
# included: the app downloads it from Microsoft on first launch, with the user's OK.
# Nothing needs to be installed on the Mac that runs it (Apple Silicon, macOS 13+).
#
#   ./build_app.sh            -> dist/KinectCam.app, copied to ~/Applications
set -euo pipefail
cd "$(dirname "$0")"
SRC="$PWD"
PY_STANDALONE="$(uv python find --managed-python 3.12)"       # python-build-standalone (relocatable)
PY_HOME="$(cd "$(dirname "$PY_STANDALONE")/.." && pwd -P)"
SITE="$SRC/.venv/lib/python3.12/site-packages"
FREENECT="$(readlink -f /opt/homebrew/opt/libfreenect/lib/libfreenect.dylib)"
LIBUSB="$(readlink -f /opt/homebrew/opt/libusb/lib/libusb-1.0.0.dylib)"
APP="$SRC/dist/KinectCam.app"
C="$APP/Contents"

echo "== python:     $PY_HOME"
echo "== libfreenect: $FREENECT"
echo "== libusb:     $LIBUSB"

rm -rf "$APP"
mkdir -p "$C/MacOS" "$C/Resources/app" "$C/Frameworks"

# --- Python runtime (stdlib only; trimmed) + packages
rsync -a --exclude 'lib/python3.12/test' --exclude 'lib/python3.12/idlelib' \
      --exclude 'lib/python3.12/tkinter' --exclude 'lib/python3.12/turtledemo' \
      --exclude 'lib/python3.12/ensurepip' --exclude 'lib/python3.12/site-packages' \
      --exclude 'lib/tcl*' --exclude 'lib/tk*' --exclude 'lib/itcl*' --exclude 'lib/thread*' \
      --exclude 'lib/libtcl*' --exclude 'lib/python3.12/lib-dynload/_tkinter*' \
      --exclude 'include' --exclude 'share' --exclude 'BUILD' --exclude 'bin' \
      --exclude '__pycache__' "$PY_HOME/" "$C/Resources/python/"
cp "$PY_HOME/bin/python3.12" "$C/MacOS/kinectcam-python"
rsync -a --exclude '__pycache__' --exclude '*.dist-info' --exclude 'pip*' --exclude '_virtualenv*' \
      --exclude 'distutils-precedence.pth' "$SITE/" "$C/Resources/site-packages/"

# --- KinectCam code (no firmware: see mic_firmware.py)
cp kinectcam.py kinect_device.py kinect_audio.py sound.py usb_reset.py macquit.py mic_firmware.py fwfetcher.py "$C/Resources/app/"

# --- native Kinect libraries, rewired to load from inside the app
cp "$FREENECT" "$C/Frameworks/libfreenect.dylib"
cp "$LIBUSB" "$C/Frameworks/libusb-1.0.0.dylib"
ln -s libusb-1.0.0.dylib "$C/Frameworks/libusb-1.0.dylib"
chmod u+w "$C/Frameworks/"*.dylib
install_name_tool -id @rpath/libfreenect.dylib "$C/Frameworks/libfreenect.dylib" 2>/dev/null
install_name_tool -id @rpath/libusb-1.0.0.dylib "$C/Frameworks/libusb-1.0.0.dylib" 2>/dev/null
for dep in $(otool -L "$C/Frameworks/libfreenect.dylib" | awk '/libusb/ {print $1}'); do
    install_name_tool -change "$dep" @loader_path/libusb-1.0.0.dylib "$C/Frameworks/libfreenect.dylib" 2>/dev/null
done
if otool -L "$C/Frameworks/"*.dylib | grep -q '/opt/homebrew'; then
    echo "!! a bundled library still points at Homebrew"; otool -L "$C/Frameworks/"*.dylib; exit 1
fi

# --- precompile so the read-only app starts fast
"$C/MacOS/kinectcam-python" -c pass 2>/dev/null || true
PYTHONHOME="$C/Resources/python" "$C/MacOS/kinectcam-python" -m compileall -q -j0 \
    "$C/Resources/python/lib/python3.12" "$C/Resources/site-packages" "$C/Resources/app" >/dev/null || true

# --- launcher
cat > "$C/MacOS/KinectCam" <<'EOF'
#!/bin/bash
C="$(cd "$(dirname "$0")/.." && pwd)"
export KINECTCAM_APP=1
export KINECTCAM_LIBDIR="$C/Frameworks"
export KINECTCAM_DATA="$HOME/Library/Application Support/KinectCam"
export PYTHONHOME="$C/Resources/python"
export PYTHONPATH="$C/Resources/site-packages"
export PYTHONNOUSERSITE=1 PYTHONDONTWRITEBYTECODE=1
mkdir -p "$KINECTCAM_DATA" "$HOME/Library/Logs"
LOG="$HOME/Library/Logs/KinectCam.log"
cd "$KINECTCAM_DATA"
exec "$C/MacOS/kinectcam-python" -u "$C/Resources/app/kinectcam.py" >"$LOG" 2>&1
EOF
chmod +x "$C/MacOS/KinectCam"

# --- icon
ICONSET="$(mktemp -d)/AppIcon.iconset"; mkdir -p "$ICONSET"
"$SRC/.venv/bin/python" "$SRC/tools/make_icon.py" "$ICONSET/icon_512x512@2x.png"
for s in 16 32 128 256 512; do
    sips -z $s $s "$ICONSET/icon_512x512@2x.png" --out "$ICONSET/icon_${s}x${s}.png" >/dev/null
    d=$((s * 2)); [ $d -le 1024 ] && sips -z $d $d "$ICONSET/icon_512x512@2x.png" --out "$ICONSET/icon_${s}x${s}@2x.png" >/dev/null
done
iconutil -c icns "$ICONSET" -o "$C/Resources/AppIcon.icns"

# --- Info.plist
cat > "$C/Info.plist" <<'EOF'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleName</key><string>KinectCam</string>
  <key>CFBundleDisplayName</key><string>KinectCam</string>
  <key>CFBundleIdentifier</key><string>local.kinectcam</string>
  <key>CFBundleVersion</key><string>1.0</string>
  <key>CFBundleShortVersionString</key><string>1.0</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleExecutable</key><string>KinectCam</string>
  <key>CFBundleIconFile</key><string>AppIcon</string>
  <key>LSMinimumSystemVersion</key><string>13.0</string>
  <key>LSArchitecturePriority</key><array><string>arm64</string></array>
  <key>NSHighResolutionCapable</key><true/>
  <key>LSApplicationCategoryType</key><string>public.app-category.video</string>
</dict>
</plist>
EOF

# --- sign (ad-hoc) so Apple Silicon accepts the rewired libraries
find "$C" -type f \( -name '*.dylib' -o -name '*.so' \) -exec codesign --force -s - {} \; 2>/dev/null
codesign --force -s - "$C/MacOS/kinectcam-python"
codesign --force --deep -s - "$APP" 2>&1 | grep -v 'replacing existing' || true

# --- carry over the current settings once
mkdir -p "$HOME/Library/Application Support/KinectCam"
[ -f "$HOME/Library/Application Support/KinectCam/settings.json" ] || \
    cp "$SRC/settings.json" "$HOME/Library/Application Support/KinectCam/" 2>/dev/null || true

mkdir -p "$HOME/Applications"
rm -rf "$HOME/Applications/KinectCam.app"
cp -R "$APP" "$HOME/Applications/"
echo "== built $(du -sh "$APP" | cut -f1)  ->  ~/Applications/KinectCam.app"
