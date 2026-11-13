KinectCam for Windows
=====================

Use an Xbox 360 Kinect (model 1414 / 1473) as a webcam on Windows 10 or 11.
Works on normal (Intel/AMD) PCs and on Windows on ARM (runs through Windows'
built-in x64 emulation).

START
  1. Unzip the whole KinectCam-Windows folder somewhere permanent
     (for example Documents\KinectCam). Don't run it from inside the zip.
  2. Plug in the Kinect: USB plus its power adapter.
  3. Double-click KinectCam.exe.

  The first time, Windows asks once for permission ("Do you want to allow
  this app to make changes...?"). Click Yes. KinectCam then:
    - gives the Kinect Microsoft's built-in WinUSB driver, so KinectCam can
      use the camera, the tilt motor and the 4 microphones;
    - registers the "KinectCam" virtual camera.
  If the picture doesn't appear after that, unplug the Kinect's USB cable,
  plug it back in, and open KinectCam.exe again.

  Nothing else needs to be installed. Everything KinectCam needs is in this
  folder (its own Python, OpenCV, numpy, libfreenect, libusb, the virtual
  camera and the Kinect audio firmware).

USE IT IN CALLS
  In Zoom, Teams, Meet (Chrome/Edge), OBS, Discord...: choose the camera
  named "KinectCam". Turn "Cam out" on in KinectCam (it is on by default).

  Note for Windows on ARM: the virtual camera is visible to apps that run as
  x64 or x86 (most of them). An app built natively for ARM can't load it.

FILES
  Settings:  %APPDATA%\KinectCam\settings.json
  Log:       %LOCALAPPDATA%\KinectCam\KinectCam.log
  Setup log: C:\ProgramData\KinectCam\setup.log
  Snapshots: your Pictures folder

GIVE THE KINECT BACK TO WINDOWS
  Run:  KinectCam.exe --restore-driver
  (for example from the Run box, Win+R, with the full path). This removes the
  WinUSB driver and the virtual camera; Windows uses its own Kinect driver
  again after you replug it.

If you move the KinectCam folder, it registers the virtual camera again at
the next start (one more Yes).

Windows "N" editions need Microsoft's free Media Feature Pack for OpenCV.
The Kinect audio firmware (runtime\app\firmware\audios.bin) belongs to
Microsoft and is included for your personal use only.
