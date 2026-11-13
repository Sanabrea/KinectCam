# KinectCam: Kinect v1 as a webcam (Mac and Windows)

Turns an Xbox 360 Kinect (model 1414/1473) into a webcam for Zoom, Teams, Meet, FaceTime, Discord, OBS and other apps.
It follows you with auto-framing and the tilt motor, blurs or replaces your background using the depth sensor,
works in total darkness with the infrared camera, and uses the Kinect's 4 microphones to show where sounds come from.

**Everything is included.** The downloads carry their own Python, OpenCV, libfreenect, libusb and (on Windows) the
virtual camera and USB driver setup. Nothing else needs to be installed. The one thing that can't be included is
Microsoft's microphone firmware: on first launch the app offers to fetch it from Microsoft's official Xbox update with one click.

- [Download and use](#download-and-use): for everyone
- [Using KinectCam](#using-kinectcam): controls, microphones, HD
- [Build from source](#build-from-source): for developers
- [How it works](#how-it-works) and [Troubleshooting](#troubleshooting)

## What you need

- An Xbox 360 **Kinect v1** (model 1414 or 1473) **with its power/USB adapter**. The Kinect needs the adapter's power; a USB port alone isn't enough.
- **Mac:** Apple Silicon (M1 or newer), macOS 13 or newer.
- **Windows:** Windows 10 or 11, 64-bit. Intel/AMD PCs run it natively; Windows on ARM runs it through x64 emulation.
- Plug the Kinect straight into the computer if you can. It doesn't work well behind hubs and docks.

## Download and use

### Windows

1. Download **[KinectCam-Windows-x64.zip](https://github.com/Sanabrea/KinectCam/releases/latest/download/KinectCam-Windows-x64.zip)**.
2. Right-click the zip, choose **Extract All**, and put the **KinectCam-Windows** folder somewhere permanent (for example `Documents`). Don't run it from inside the zip.
3. Plug in the Kinect: USB plus its power adapter.
4. Double-click **KinectCam.exe**.
   - If Windows shows "Windows protected your PC", click **More info**, then **Run anyway**. The app isn't signed with a paid certificate, so Windows asks once.
   - **First time only:** Windows asks "Do you want to allow this app to make changes to your device?". Click **Yes**. KinectCam gives the Kinect Microsoft's built-in WinUSB driver (for the camera, tilt motor and microphones) and registers the **KinectCam** virtual camera.
5. KinectCam asks whether to turn on the microphones. Click **Yes**: it fetches the Kinect's microphone firmware from Microsoft (about 116 MB, once).

**In your video app** (Zoom, Teams, Meet in Chrome/Edge, Discord, OBS...), choose the camera named **KinectCam**. No OBS needed.

If the picture doesn't appear after the first-time setup, unplug the Kinect's USB cable, plug it back in, and open KinectCam again.
To give the Kinect back to Windows' own driver, run `KinectCam.exe --restore-driver`.

### Mac

1. Download **[KinectCam-mac.zip](https://github.com/Sanabrea/KinectCam/releases/latest/download/KinectCam-mac.zip)** and double-click it to unzip.
2. Drag **KinectCam** into your **Applications** folder.
3. Plug in the Kinect: USB plus its power adapter.
4. **First time only:** right-click KinectCam and choose **Open**, then **Open** again.
   The app isn't signed with a paid Apple developer certificate, so macOS asks once.
   On newer macOS: if it only offers "Done"/"Move to Trash", open **System Settings → Privacy & Security**, scroll down, click **Open Anyway** next to KinectCam, and confirm.
5. KinectCam asks whether to turn on the microphones. Click **Download**: it fetches the Kinect's microphone firmware from Microsoft (about 116 MB, once).

**In your video app:** macOS only lets signed apps add a camera, so KinectCam sends its picture through OBS's virtual camera.
Install the free [OBS Studio](https://obsproject.com) once, open it, click **Start Virtual Camera**, and allow the system extension.
Then choose **OBS Virtual Camera** as the camera in Zoom, Teams, Meet, FaceTime and others. Without OBS, everything else (preview, snapshots) still works.

### Where things are kept

| | Windows | Mac |
|---|---|---|
| Settings | `%APPDATA%\KinectCam\settings.json` | `~/Library/Application Support/KinectCam/settings.json` |
| Mic firmware (downloaded) | `%APPDATA%\KinectCam\firmware\` | `~/Library/Application Support/KinectCam/firmware/` |
| Log | `%LOCALAPPDATA%\KinectCam\KinectCam.log` | `~/Library/Logs/KinectCam.log` |
| Driver setup log | `C:\ProgramData\KinectCam\setup.log` | – |
| Snapshots | your Pictures folder | `~/Pictures` |

Settings are saved when you quit, and the app picks up where you left off.

## Using KinectCam

A preview window opens with a **button bar** under the video. The on-screen HUD and inset appear only in the preview; they are never sent to the call.
Toggles that are on turn green. Every button also has a keyboard shortcut (click the preview window first).

| Button / key | What it does |
|---|---|
| **Follow / F** | **Follow camera** on/off. Auto-framing digitally pans and zooms to keep you centred, and drives the **tilt motor** when you move above or below the sensor's view. |
| **Mode / M** | Mode: **color**, **night** (IR camera, works in total darkness), **depth** (colour-coded distance) |
| **BG / B** | Background: none, **blur**, **solid colour**, **image**. This uses the depth sensor, so it needs no AI model. |
| **BG colour / G** | Pick a random solid background colour (switches BG to solid) |
| **Zoom +/- · + / -** | Zoom in/out (with follow on, framing gets tighter or looser) |
| **< Pan / Pan > · ← / →** | Manual pan (turns follow off) |
| **Tilt up/down · ↑ / ↓** | Tilt motor up/down (±27°) |
| **Reset / 0** | Reset zoom, pan and tilt |
| **Enhance / E** | Low-light enhance |
| **Level / V** | Auto-level from the Kinect's accelerometer |
| **Mirror / R** | Mirror the output |
| **LED / O** | Cycle LED colour (green, yellow, red, blinking, off) |
| **Cam out / C** | Stop or start sending to the virtual camera |
| **Snapshot / S** | Save a photo of the output to your Pictures folder |
| **Quit / Q / Esc** | Quit (settings are saved) |
| **HD / H** | 1280×1024 colour camera (sharper, 10 fps) |
| **Voice steer / T** | Follow whoever is talking (mic array) |
| **Auto exposure / A** | Camera auto exposure on/off |
| **Auto white balance / W** | Camera auto white balance on/off |
| **Mic: all around / me · U** | Listen to everything, or only in your direction |
| **Sound dots / D** | Mark sound sources on the preview |
| **Calibrate mic / K** | Guided calibration so the sound dots land on mouths (shows **Get mic support** until the firmware is downloaded) |
| **Grid / X** | Angle grid and rule-of-thirds lines on the preview |

### Microphone array: sound dots, mic focus, voice steer

The Kinect has 4 microphones in a row. KinectCam uses all 4 to work out where sounds come from. Everything below is drawn only on the preview, never on the call.

- **Sound dots (button or D):** each sound source gets a coloured dot, and several at once are tracked separately. A dot's size shows how loud the source is, and it fades about a second after the sound stops. The dot sits on a mouth if there's a face in that direction, otherwise on the nearest object.
  - Sounds outside the picture get an arrow on that edge with their angle, for example a speaker off to your left.
  - The microphones only measure the left/right direction, so a dot's height is an educated guess.
- **Calibrating dot positions:** press **Calibrate mic** (or K). The picture zooms out and shows a "stand here" zone. Stand in it facing the camera; when your face is found, count out loud for 8 s. Repeat for your right, the centre and your left. The result is saved right away and shows how far the dots were from your mouth before and after. Press the button again to cancel.
- **Mic focus (button or U):**
  - **All around:** every sound in the image and its surroundings.
  - **Me:** a narrow listening beam (±12°) aimed at you, shaded on the preview. Other people and noises are ignored for the meter, the dots and Voice steer. The beam follows you as you move.
  - This changes what KinectCam listens to. Your call still uses your computer's normal microphone.
- **Grid (button or X):** rule-of-thirds lines, plus dashed lines every 15° labelled with the same angles the microphones report.
- **Voice steer (button or T):** with Follow on, the camera follows whichever face the voice is coming from.
- **Status line:** shows the mic mode, a level meter, the voice angle and the number of sources.
- **First start after plugging in the Kinect:** the app uploads the firmware to the Kinect's audio chip, which then reconnects. On Windows the microphones come on about 15 seconds after the picture.
- **How well it works:** in testing, voices from the left, center and right read about -40°, 0° and +41°. Two simultaneous talkers 50° apart were separated cleanly.

### HD mode

**HD (button or H)** switches the colour camera to its native **1280×1024** resolution. The picture is much sharper, but the camera only delivers **10 fps**. The output stays at 30 fps, with each camera frame shown 3 times.
Tracking, depth and background effects keep working, because the app maps the 640×480 coordinates onto the HD frame. Night mode always uses 640×480.

**Auto exposure (A)** and **Auto white balance (W)** switch the camera's automatic adjustments. Turn them off to lock the picture's brightness and colour.

The output sent to video apps is 1280×720 by default (`--width` / `--height` change it). On a Mac, apps may report 1920×1080: that is OBS's canvas size, which scales the same picture up.

## Build from source

```bash
git clone https://github.com/Sanabrea/KinectCam.git
cd KinectCam
```

### Windows

Needs [Python 3.12](https://www.python.org) and CMake (`winget install Python.Python.3.12 Kitware.CMake`).

```powershell
py -3.12 -m venv .venv
.venv\Scripts\pip install -r requirements.txt
powershell -ExecutionPolicy Bypass -File windows\build_windows.ps1
```

`build_windows.ps1` downloads its build tools into `windows\_deps\` the first time (llvm-mingw, libusb, libfreenect, libwdi, Unity Capture,
the embeddable Python and the wheels), builds `libfreenect.dll`, `KinectCam.exe` and `kinect_setup.exe`, and writes
`dist\KinectCam-Windows\` plus `dist\KinectCam-Windows-x64.zip`. It also patches two libfreenect bugs that break the microphones on Windows (see the script).

To run from source after a build, use `run.bat`: it runs `kinectcam.py` with `.venv` and the DLLs from `dist\KinectCam-Windows\runtime`.
The Kinect needs the WinUSB driver once: open `dist\KinectCam-Windows\KinectCam.exe` once and click **Yes**.
`windows/build_windows.sh` cross-builds the same package on a Mac (see [windows/README-build.md](windows/README-build.md)).

### macOS (Apple Silicon)

```bash
brew install libfreenect libusb uv
uv venv --python 3.12 .venv && uv pip install --python .venv -r requirements.txt
./run.sh                 # run from source
./build_app.sh           # or build the self-contained KinectCam.app (dist/, copied to ~/Applications)
```

### Microphone firmware

Run from source, the app asks to download the firmware just like the release builds (`mic_firmware.py`). You can also fetch it yourself with
`python mic_firmware.py`, or put `audios.bin` in `firmware/` (see [firmware/README.md](firmware/README.md)). It's never committed: it belongs to Microsoft.

### Options

```bash
./run.sh --mode night --background blur --follow on      # Windows: run.bat --mode night ...
./run.sh --background image --bg-image ~/Pictures/office.jpg
./run.sh --no-preview          # run in the background, no window
./run.sh --no-mic              # don't use the microphones
./run.sh --width 1920 --height 1080
./run.sh --test 60             # headless: process 60 frames, save snapshots, exit
```

Tools: `calibrate_mic.py` (Terminal version of the mic calibration), `mic_probe.py SECONDS` (prints the direction of whatever it hears),
`usb_reset.py` (USB-reset the Kinect).

## How it works

- `kinect_device.py`: Kinect driver layer on **libfreenect's low-level API** (ctypes). One thread owns the device and keeps it healthy:
  - On this Kinect, the first stream start after opening never delivers frames, so the app sends a short priming start and then restarts the stream right away.
  - If video or depth stops, it restarts just that stream in place. If that keeps failing, it closes and reopens the device, and as a last resort it resets the Kinect over USB.
  - libfreenect's messages go to an in-app log instead of the terminal.
- `kinect_audio.py`: the 4-microphone stream. It uploads the audio firmware, waits for the audio chip to reconnect (retrying with a fresh libfreenect context on Windows), and if the audio starts silent, it reopens the audio device.
- `mic_firmware.py`: downloads Microsoft's official Xbox 360 system update with the user's OK, unpacks `audios.bin` with libfreenect's `fwfetcher.py` and checks its SHA-256.
- `sound.py`: sound directions. SRP-PHAT (combining all 6 microphone pairs) finds the main direction. A direction is also estimated separately for each frequency, and those votes are collected into a histogram, which separates several simultaneous sources. A delay-and-sum beam handles "Mic: me".
- `usb_reset.py`: libusb helpers that clear stale command replies, reset the Kinect over USB, and wait for it to reconnect.
- `kinectcam.py`: the app. It handles tracking (face detector, with a fallback to the depth map), smooth framing and motor follow, background effects, and the button UI, and sends the output to the virtual camera.
- Windows only:
  - `windows/src/launcher.c` → `KinectCam.exe`: runs the bundled Python inside its own process, so the taskbar shows KinectCam.
  - `windows/src/kinect_setup.c` → `kinect_setup.exe`: the one-time elevated setup. It installs Microsoft's WinUSB driver for the Kinect's camera, motor and audio (signed locally, the same method as Zadig) and registers the [Unity Capture](https://github.com/schellingb/UnityCapture) filter as the **KinectCam** camera.
  - `winsetup.py`: runs that setup from the app when it's needed.

## Troubleshooting

- **Startup** normally takes 4–10 s. The app shows each step: connecting, starting streams, streaming. If the Kinect is stuck, it recovers on its own. If it still hasn't started after 60 s, unplug the Kinect's **power adapter** for 5 seconds and plug it back in.
- **No picture at all:** check the power adapter is plugged in and switched on. With USB power only, the computer sees just the Kinect's motor, not its camera. Plug its USB straight into the computer instead of a hub or dock.
- **A video app doesn't list the camera:** fully quit and reopen that app after KinectCam starts.
- **Windows: "setup could not install the USB driver":** see `C:\ProgramData\KinectCam\setup.log`. Run **KinectCam diagnose.bat** (in the KinectCam folder) to collect details into a file on the Desktop.
- **Windows: something goes wrong at start:** run **KinectCam debug.bat** to see what the app is doing.
- **Windows "N" editions** need Microsoft's free Media Feature Pack for OpenCV.
- **Windows on ARM:** the virtual camera is visible to apps that run as x64 or x86 (most of them). An app built natively for ARM can't load it.
- **Mac: virtual camera not available:** open OBS, click *Start Virtual Camera* once, and approve the extension in System Settings › General › Login Items & Extensions. Then quit OBS and press **C**.
- **Microphones:** if the download failed or you said "Not now", press **Get mic support**. Mic features need the firmware; everything else works without it.
- The Kinect's camera is 640×480 (1280×1024 in HD mode), so the picture looks softer than a modern webcam.
