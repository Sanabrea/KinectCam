# Build KinectCam for Windows natively on Windows (x64), the counterpart of build_windows.sh.
# Output:
#   dist\KinectCam-Windows\       portable folder (KinectCam.exe + runtime\)
#   dist\KinectCam-Windows-x64.zip
#
# Run from anywhere:  powershell -ExecutionPolicy Bypass -File windows\build_windows.ps1
# Downloads what it needs into windows\_deps\ the first time (see README-build.md).
# Needs: Python 3.12 + the .venv (for the icon and the wheels), CMake (winget Kitware.CMake).
$ErrorActionPreference = 'Stop'
$WIN   = $PSScriptRoot
$SRC   = Split-Path $WIN -Parent
$DEPS  = "$WIN\_deps"
$BUILD = "$WIN\build"
$OUT   = "$SRC\dist\KinectCam-Windows"
$R     = "$OUT\runtime"
$PYVER = '3.12.10'
$LLVM  = '20261104'
$TC    = "$DEPS\llvm-mingw\llvm-mingw-$LLVM-ucrt-x86_64\bin"
$VPY   = "$SRC\.venv\Scripts\python.exe"
New-Item -ItemType Directory -Force $DEPS, $BUILD | Out-Null

function Get-Dep($name, $url) {
    $f = "$DEPS\$name"
    if (-not (Test-Path $f)) {
        Write-Host "== download $name"
        curl.exe -sSL --fail -o $f $url
        if ($LASTEXITCODE) { Remove-Item $f -ErrorAction SilentlyContinue; throw "download failed: $url" }
    }
    $f
}
function Expand-Dep($name, $url, $dir) {
    if (-not (Test-Path "$DEPS\$dir")) {
        $z = Get-Dep $name $url
        if ($name -like '*.7z') { New-Item -ItemType Directory -Force "$DEPS\$dir" | Out-Null; tar -xf $z -C "$DEPS\$dir" }
        else { Expand-Archive $z -DestinationPath "$DEPS\$dir" -Force }
    }
}
function Invoke-Native { param([string]$exe) & $exe @args; if ($LASTEXITCODE) { throw "$exe failed ($LASTEXITCODE)" } }

if (-not (Test-Path $VPY)) { throw "missing .venv - create it first: py -3.12 -m venv .venv; .venv\Scripts\pip install -r requirements.txt" }

# ---------------------------------------------------------------- deps
Expand-Dep 'llvm-mingw.zip' "https://github.com/mstorsjo/llvm-mingw/releases/download/$LLVM/llvm-mingw-$LLVM-ucrt-x86_64.zip" 'llvm-mingw'
Expand-Dep 'libusb-1.0.30.7z' 'https://github.com/libusb/libusb/releases/download/v1.0.30/libusb-1.0.30.7z' 'libusb'
Expand-Dep 'libfreenect-0.7.5.zip' 'https://codeload.github.com/OpenKinect/libfreenect/zip/refs/tags/v0.7.5' 'libfreenect-0.7.5'
Expand-Dep 'libwdi-1.5.1.zip' 'https://codeload.github.com/pbatard/libwdi/zip/refs/tags/v1.5.1' 'libwdi-1.5.1'
Expand-Dep 'UnityCapture-master.zip' 'https://codeload.github.com/schellingb/UnityCapture/zip/refs/heads/master' 'UnityCapture-master'
$PYZIP = Get-Dep "python-$PYVER-embed-amd64.zip" "https://www.python.org/ftp/python/$PYVER/python-$PYVER-embed-amd64.zip"
$WHEELS = "$DEPS\wheels"
if (-not (Get-ChildItem "$WHEELS\*.whl" -ErrorAction SilentlyContinue)) {
    Write-Host "== download wheels"
    Invoke-Native $VPY -m pip download -q --disable-pip-version-check -r "$SRC\requirements.txt" -d $WHEELS `
        --platform win_amd64 --python-version 3.12 --only-binary=:all:
}
$env:PATH = "$TC;$env:PATH"
if (-not (Get-Command cmake -ErrorAction SilentlyContinue)) {
    $cm = Get-ChildItem "$env:LOCALAPPDATA\Microsoft\WinGet\Packages\Kitware.CMake*", "$env:ProgramFiles\CMake" `
          -Recurse -Filter cmake.exe -ErrorAction SilentlyContinue | Select-Object -First 1
    if (-not $cm) { throw "CMake not found - winget install Kitware.CMake" }
    $env:PATH = "$(Split-Path $cm.FullName);$env:PATH"
}

# ------------------------------------------------------------ libfreenect
$FN = "$DEPS\libfreenect-0.7.5\libfreenect-0.7.5"
# Two libfreenect 0.7.5 bugs that only bite on Windows, right after the audio firmware upload
# (first start after the Kinect is powered on):
#  1. While looking for the re-enumerated audio device it opens it, reads a serial that
#     doesn't match, and never closes the handle. WinUSB handles are exclusive, so the audio
#     device can't be opened again until the process exits (LIBUSB_ERROR_ACCESS).
#  2. When a requested subdevice doesn't open, fnusb_open_subdevices still returns 0, and
#     starting audio on the unopened device aborts the app in libusb (assert transfer->dev_handle).
$usbc = "$FN\src\usb_libusb10.c"
$code = Get-Content $usbc -Raw
$orig = $code
if ($code -notmatch 'KinectCam patch 1') {
    $new = $code -replace '(FN_SPEW\("Got serial %s, expected serial %s\\n", \(char\*\)string_desc, audio_serial\);)',
        "`$1`n`t`t`t`t`t`t`tlibusb_close(new_dev_handle); /* KinectCam patch 1: don't leak the handle */"
    if ($new -eq $code) { throw "could not apply patch 1 to $usbc" }
    $code = $new
}
if ($code -notmatch 'KinectCam patch 2') {
    $new = $code -replace '(?m)^failure:\r?\n(\s*)(?:if \(res >= 0\) res = -1; /\* KinectCam patch: report the failure \*/\r?\n\s*)?fnusb_close_subdevices\(dev\);',
        "failure:`n`$1if (res >= 0) res = -1; /* KinectCam patch 2: report the failure */`n`$1fnusb_close_subdevices(dev);"
    if ($new -eq $code) { throw "could not apply patch 2 to $usbc" }
    $code = $new
}
if ($code -ne $orig) {
    [IO.File]::WriteAllText($usbc, $code)
    Remove-Item "$FN\build-x64\lib\libfreenect.dll" -ErrorAction SilentlyContinue
}
if (-not (Test-Path "$FN\build-x64\lib\libfreenect.dll")) {
    Write-Host "== libfreenect"
    $u = "$FN\platform\windows\unistd.h"
    if (-not (Select-String -Path $u -Pattern 'static void sleep' -Quiet)) {
        Add-Content $u "`nstatic void sleep(unsigned int sec)`n{`n`tSleep(sec * 1000);`n}"
    }
    New-Item -ItemType Directory -Force "$FN\build-x64" | Out-Null
    Push-Location "$FN\build-x64"
    try {
        Invoke-Native cmake .. -G "MinGW Makefiles" "-DCMAKE_POLICY_VERSION_MINIMUM=3.5" `
            -DCMAKE_C_COMPILER=x86_64-w64-mingw32-clang -DCMAKE_CXX_COMPILER=x86_64-w64-mingw32-clang++ `
            -DCMAKE_RC_COMPILER=x86_64-w64-mingw32-windres "-DLIBUSB_1_INCLUDE_DIR=$DEPS\libusb\include" `
            "-DLIBUSB_1_LIBRARY=$DEPS\libusb\MinGW64\static\libusb-1.0.dll.a" -DBUILD_EXAMPLES=OFF `
            -DBUILD_FAKENECT=OFF -DBUILD_C_SYNC=OFF -DBUILD_CPP=OFF -DBUILD_PYTHON=OFF -DBUILD_PYTHON3=OFF `
            -DBUILD_OPENNI2_DRIVER=OFF -DBUILD_REDIST_PACKAGE=ON -DCMAKE_BUILD_TYPE=Release | Out-Null
        cmd /c "mingw32-make -j8 freenect >nul 2>&1"
        if ($LASTEXITCODE) { throw "libfreenect build failed" }
    } finally { Pop-Location }
}

# ------------------------------------------------------------- our exes
Write-Host "== KinectCam.exe + kinect_setup.exe"
Invoke-Native $VPY "$SRC\tools\make_icon.py" "$BUILD\icon_1024.png"
Invoke-Native $VPY "$WIN\src\make_ico.py" "$BUILD\icon_1024.png" "$BUILD\KinectCam.ico"
@'
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
'@ | Set-Content -Encoding ascii "$BUILD\launcher.manifest"
$b = $BUILD -replace '\\', '/'
@"
#include <winuser.h>
#include <winver.h>
1 ICON "$b/KinectCam.ico"
1 RT_MANIFEST "$b/launcher.manifest"
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
"@ | Set-Content -Encoding ascii "$BUILD\launcher.rc"
$CC = 'x86_64-w64-mingw32-clang'
Invoke-Native x86_64-w64-mingw32-windres "$BUILD\launcher.rc" -O coff -o "$BUILD\launcher_res.o"
Invoke-Native $CC -O2 -municode -mwindows -D_WIN32_WINNT=0x0A00 "$WIN\src\launcher.c" "$BUILD\launcher_res.o" `
    -o "$BUILD\KinectCam.exe" -lshell32 -luser32
Invoke-Native $CC -O2 -municode -mconsole -DKINECTCAM_CONSOLE -D_WIN32_WINNT=0x0A00 "$WIN\src\launcher.c" "$BUILD\launcher_res.o" `
    -o "$BUILD\KinectCam-debug.exe" -lshell32 -luser32
$W = "$DEPS\libwdi-1.5.1\libwdi-1.5.1\libwdi"
Invoke-Native x86_64-w64-mingw32-windres "$WIN\src\kinect_setup.rc" "-I$WIN\src" -O coff -o "$BUILD\kinect_setup_res.o"
Invoke-Native $CC -O2 -municode "-I$WIN\src\shim" "-I$W" -D_WIN32_WINNT=0x0A00 -Wno-everything -c "$W\pki.c" -o "$BUILD\pki.o"
Invoke-Native $CC -O2 -municode -D_WIN32_WINNT=0x0A00 -c "$WIN\src\kinect_setup.c" -o "$BUILD\kinect_setup.o"
Invoke-Native $CC -municode -o "$BUILD\kinect_setup.exe" "$BUILD\kinect_setup.o" "$BUILD\pki.o" "$BUILD\kinect_setup_res.o" `
    -lsetupapi -lnewdev -lcrypt32 -lshell32 -lole32 -luser32 -ladvapi32

# --------------------------------------------------------------- package
Write-Host "== assembling $OUT"
if (Test-Path $OUT) {
    # Any app that lists cameras (browsers, Zoom, Teams...) keeps the registered virtual-camera
    # DLL loaded. A loaded DLL can't be deleted but can be renamed, so move it aside first.
    $vc = "$R\vcam\UnityCaptureFilter64.dll"
    if (Test-Path $vc) {
        New-Item -ItemType Directory -Force "$BUILD\stale" | Out-Null
        Get-ChildItem "$BUILD\stale" -File | Remove-Item -ErrorAction SilentlyContinue   # old ones no longer in use
        Move-Item $vc "$BUILD\stale\UnityCaptureFilter64-$([DateTime]::Now.Ticks).dll"
    }
    Remove-Item -Recurse -Force $OUT
}
New-Item -ItemType Directory -Force "$R\python", "$R\site-packages", "$R\app\firmware", "$R\lib", "$R\vcam", "$OUT\licenses" | Out-Null
Copy-Item "$BUILD\KinectCam.exe", "$BUILD\KinectCam-debug.exe" $OUT
Copy-Item "$BUILD\kinect_setup.exe" $R

Expand-Archive $PYZIP -DestinationPath "$R\python"
[IO.File]::WriteAllText("$R\python\python312._pth", "python312.zip`r`n.`r`n..\site-packages`r`n..\app`r`n")
foreach ($w in Get-ChildItem "$WHEELS\*.whl") {      # a wheel is a zip
    Copy-Item $w.FullName "$BUILD\wheel.zip" -Force
    Expand-Archive "$BUILD\wheel.zip" -DestinationPath "$R\site-packages" -Force
}
Remove-Item "$BUILD\wheel.zip"
Remove-Item "$R\site-packages\cv2\opencv_videoio_ffmpeg*.dll" -ErrorAction SilentlyContinue   # video files are never used
# Microsoft C++ runtime for the virtual camera module (app-local copy from numpy's wheel)
$msvcp = Get-ChildItem "$R\site-packages\numpy.libs\msvcp140*.dll" -ErrorAction SilentlyContinue | Select-Object -First 1
if ($msvcp) { Copy-Item $msvcp.FullName "$R\python\msvcp140.dll" } else { Write-Warning "msvcp140.dll not found in numpy.libs" }

foreach ($f in 'kinectcam', 'kinect_device', 'kinect_audio', 'sound', 'usb_reset', 'winsetup') { Copy-Item "$SRC\$f.py" "$R\app\" }
if (Test-Path "$SRC\firmware\audios.bin") { Copy-Item "$SRC\firmware\audios.bin" "$R\app\firmware\" }
else { Write-Warning "firmware\audios.bin missing - the package works, but without the microphone features" }
Copy-Item "$DEPS\libusb\MinGW64\dll\libusb-1.0.dll" "$R\lib\"
Copy-Item "$FN\build-x64\lib\libfreenect.dll" "$R\lib\"
Copy-Item (Get-ChildItem "$DEPS\UnityCapture-master" -Recurse -Filter UnityCaptureFilter64.dll | Select-Object -First 1).FullName "$R\vcam\"

# precompile with the same Python 3.12 (hash-based, so file times don't matter)
& $VPY -m compileall -q -j0 --invalidation-mode unchecked-hash "$R\site-packages" "$R\app" | Out-Null

# licences
Copy-Item "$R\python\LICENSE.txt" "$OUT\licenses\Python.txt" -ErrorAction SilentlyContinue
[IO.File]::WriteAllText("$OUT\licenses\libusb-LGPL-2.1.txt", "libusb 1.0.30 - GNU LGPL 2.1 or later - https://github.com/libusb/libusb (source and COPYING)`r`n")
Copy-Item "$FN\APACHE20" "$OUT\licenses\libfreenect-Apache-2.0.txt" -ErrorAction SilentlyContinue
Copy-Item "$DEPS\libwdi-1.5.1\libwdi-1.5.1\COPYING-LGPL" "$OUT\licenses\libwdi-LGPL-3.txt" -ErrorAction SilentlyContinue
[IO.File]::WriteAllText("$OUT\licenses\UnityCapture-MIT.txt", "Unity Capture (filter) - MIT License - https://github.com/schellingb/UnityCapture`r`n")
Copy-Item "$WIN\README-Windows.txt" "$OUT\README.txt"
Copy-Item "$WIN\KinectCam diagnose.bat" $OUT
[IO.File]::WriteAllText("$OUT\KinectCam debug.bat", "@echo off`r`ntitle KinectCam debug`r`nrem Runs KinectCam showing what it is doing (for troubleshooting).`r`n`"%~dp0KinectCam-debug.exe`"`r`necho.`r`necho KinectCam finished with code %errorlevel%`r`npause`r`n")

$zip = "$SRC\dist\KinectCam-Windows-x64.zip"
if (Test-Path $zip) { Remove-Item $zip }
Compress-Archive -Path $OUT -DestinationPath $zip -CompressionLevel Optimal
$size = "{0:N0} MB" -f ((Get-ChildItem $OUT -Recurse -File | Measure-Object Length -Sum).Sum / 1MB)
Write-Host ("== done: $size folder, {0:N0} MB zip" -f ((Get-Item $zip).Length / 1MB))
