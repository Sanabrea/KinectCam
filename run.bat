@echo off
rem Run KinectCam from source on Windows, with the .venv and the DLLs / driver setup
rem from the package that windows\build_windows.ps1 builds (dist\KinectCam-Windows\runtime).
rem Extra arguments are passed through, e.g.  run.bat --mode night
cd /d "%~dp0"
set "KINECTCAM_RUNTIME=%~dp0dist\KinectCam-Windows\runtime"
if not exist "%KINECTCAM_RUNTIME%\lib\libfreenect.dll" (
  echo Build first:  powershell -ExecutionPolicy Bypass -File windows\build_windows.ps1
  pause
  exit /b 1
)
set "KINECTCAM_LIBDIR=%KINECTCAM_RUNTIME%\lib"
".venv\Scripts\python.exe" kinectcam.py %*
if errorlevel 1 pause
