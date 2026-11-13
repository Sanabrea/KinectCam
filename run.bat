@echo off
rem Run KinectCam from source on Windows (dev setup: .venv + windows\build\runtime).
rem Extra arguments are passed through, e.g.  run.bat --mode night
cd /d "%~dp0"
set "KINECTCAM_RUNTIME=%~dp0windows\build\runtime"
set "KINECTCAM_LIBDIR=%KINECTCAM_RUNTIME%\lib"
set "MICARG="
if not exist "firmware\audios.bin" set "MICARG=--no-mic"
".venv\Scripts\python.exe" kinectcam.py %MICARG% %*
if errorlevel 1 pause
