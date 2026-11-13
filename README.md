# KinectCam: Kinect v1 as a Mac webcam

Turns an Xbox 360 Kinect (model 1414/1473) into a webcam for Zoom, Teams, Meet, FaceTime, OBS and other apps.
It shows up in those apps as **"OBS Virtual Camera"**.

## Download (no technical knowledge needed)

**Mac (Apple Silicon: M1 or newer, macOS 13+):**

1. Download **[KinectCam-mac.zip](https://github.com/Sanabrea/KinectCam/releases/latest/download/KinectCam-mac.zip)** and double-click it to unzip.
2. Drag **KinectCam** into your **Applications** folder.
3. Plug in the Kinect (USB and its power adapter).
4. **The first time only,** right-click KinectCam and choose **Open**, then **Open** again.
   The app isn't signed with a paid Apple developer certificate, so macOS asks once.
   On newer macOS: if it only offers "Done"/"Move to Trash", open **System Settings → Privacy & Security**, scroll down, click **Open Anyway** next to KinectCam, and confirm.
5. KinectCam asks whether to turn on the microphones. Click **Download**: it fetches the Kinect's microphone firmware from Microsoft (about 116 MB, once).

To use it in Zoom, Teams, Meet and others, install the free [OBS Studio](https://obsproject.com) once. Open it, click **Start Virtual Camera**, and allow the system extension. Then choose **OBS Virtual Camera** as the camera in your video app.

**Windows:** coming soon (the driver setup is still being finished).

Developers: see [Build from source](#build-from-source).

## Start

Plug in the Kinect (USB and its power adapter), then open **KinectCam** from `~/Applications`, Launchpad or Spotlight.
You can also drag it to the Dock.

**KinectCam.app is self-contained.** It carries its own Python 3.12, numpy, OpenCV, pyvirtualcam,
libfreenect and libusb, so nothing needs to be installed (Apple Silicon Mac, macOS 13+). The Kinect's microphone firmware belongs to Microsoft, so it isn't included: the app downloads it from Microsoft's official Xbox update on first launch, after asking.
The one exception is **Cam out**. The OBS Virtual Camera is a macOS camera extension that only a signed app can install,
so other apps can see the Kinect only if OBS Studio is installed. Without it, the preview, snapshots and everything else still work.

- Settings: `~/Library/Application Support/KinectCam/settings.json`
- Log: `~/Library/Logs/KinectCam.log` (the app has no terminal; errors also appear as pop-ups)
- Rebuild after changing the code: `./build_app.sh` (writes `dist/KinectCam.app` and copies it to `~/Applications`)

**Windows:** `dist/KinectCam-Windows-x64.zip` is a portable Windows 10/11 version. It runs natively on Intel/AMD PCs and on ARM PCs through x64 emulation. Unzip it and double-click `KinectCam.exe`.
On first launch Windows asks once for permission, and KinectCam then gives the Kinect Microsoft's WinUSB driver and registers the "KinectCam" virtual camera (no OBS needed).
See `windows/README-Windows.txt` (included in the zip). To rebuild it, run `windows/build_windows.sh`.

For development you can still run it from Terminal. This uses the `.venv` and the `settings.json` in this folder:

```bash
~/Downloads/KinectCam/run.sh
```

A preview window opens. In your video app, choose **OBS Virtual Camera** as the camera.
The on-screen HUD and inset appear only in the preview. They are never sent to the call.
Settings are saved when you quit, and the app picks up where you left off next time.

## Build from source

```bash
git clone https://github.com/Sanabrea/KinectCam.git && cd KinectCam
```

**macOS (Apple Silicon):**

```bash
brew install libfreenect libusb uv
uv venv --python 3.12 .venv && uv pip install --python .venv -r requirements.txt
# optional, for the microphones: see firmware/README.md
./run.sh                 # run from source
./build_app.sh           # or build the self-contained KinectCam.app
```

**Windows:** `windows/build_windows.sh` cross-builds a portable Windows package on a Mac (see `windows/README-build.md`).
To work on Windows directly, you need Python 3.12 and `pip install -r requirements.txt`. You also need `libfreenect.dll` and `libusb-1.0.dll` in a folder named by the `KINECTCAM_LIBDIR` environment variable, and a WinUSB driver on the Kinect (Zadig, or `windows/src/kinect_setup.c`).
The Windows version is still being brought up. On the first test PC the WinUSB driver install was failing.

## Controls

The preview window has a **button bar** under the video. Click a button to use it.
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
| **Snapshot / S** | Save a photo of the output to `~/Pictures` |
| **Quit / Q / Esc** | Quit (settings are saved) |
| **HD / H** | 1280×1024 colour camera (sharper, 10 fps) |
| **Voice steer / T** | Follow whoever is talking (mic array) |
| **Auto exposure / A** | Camera auto exposure on/off |
| **Auto white balance / W** | Camera auto white balance on/off |
| **Mic: all around / me · U** | Listen to everything, or only in your direction |
| **Sound dots / D** | Mark sound sources on the preview |
| **Calibrate mic / K** | Guided calibration so the sound dots land on mouths |
| **Grid / X** | Angle grid and rule-of-thirds lines on the preview |

## Microphone array: sound dots, mic focus, voice steer

The Kinect has 4 microphones in a row. KinectCam uses all 4 to work out where sounds come from. Everything below is drawn only on the preview, never on the call.

- **Sound dots (button or D):** each sound source gets a coloured dot, and several at once are tracked separately. A dot's size shows how loud the source is, and it fades about a second after the sound stops. The dot sits on a mouth if there's a face in that direction, otherwise on the nearest object.
- **Calibrating dot positions:** press **Calibrate mic** (or K). The picture zooms out and shows a "stand here" zone. Stand in it facing the camera; when your face is found, count out loud for 8 s. Repeat for your right, the centre and your left. The result is saved right away and shows how far the dots were from your mouth before and after. Press the button again to cancel.
  The older Terminal version: close KinectCam and run `.venv/bin/python calibrate_mic.py`. You talk from your right, the centre and your left. It matches the sound angle to your mouth and saves `mic_gain` / `mic_offset` in `settings.json`. `mic_sign: -1` means positive sound angles are on the left of the picture. `mic_probe.py SECONDS` prints the direction of whatever it hears.
  - Sounds outside the picture get an arrow on that edge with their angle, for example a speaker off to your left.
  - The microphones only measure the left/right direction, so a dot's height is an educated guess.
- **Mic focus (button or U):**
  - **All around:** every sound in the image and its surroundings.
  - **Me:** a narrow listening beam (±12°) aimed at you, shaded on the preview. Other people and noises are ignored for the meter, the dots and Voice steer. The beam follows you as you move.
  - This changes what KinectCam listens to. Your call still uses your normal Mac microphone.
- **Grid (button or X):** rule-of-thirds lines, plus dashed lines every 15° labelled with the same angles the microphones report.
- **Voice steer (button or T):** with Follow on, the camera follows whichever face the voice is coming from.
- **Status line:** shows the mic mode, a level meter, the voice angle and the number of sources.
- **Firmware:** the Kinect's audio chip needs Microsoft's firmware at every power-up. On first launch the app asks to download it from Microsoft's official Xbox 360 system update and unpacks it with libfreenect's `fwfetcher.py` (`mic_firmware.py`; the result is checked against a known SHA-256). It's kept in the app's data folder; a `firmware/audios.bin` next to the code also works. If the file is missing, the mic features turn off and everything else keeps working. Start with `--no-mic` to disable them.
- **How well it works:** in testing, voices from the left, center and right read about -40°, 0° and +41°. Two simultaneous talkers 50° apart were separated cleanly. About 6% of audio packets are lost through the dock, which doesn't affect direction finding.

## HD mode

**HD (button or H)** switches the colour camera to its native **1280×1024** resolution. The picture is much sharper, but the camera only delivers **10 fps**. The output stays at 30 fps, with each camera frame shown 3 times.

Tracking, depth and background effects keep working, because the app maps the 640×480 coordinates onto the HD frame. Night mode always uses 640×480.

**Auto exposure (A)** and **Auto white balance (W)** switch the camera's automatic adjustments. Turn them off to lock the picture's brightness and colour.

## Options

```bash
./run.sh --mode night --background blur --follow on
./run.sh --background image --bg-image ~/Pictures/office.jpg
./run.sh --no-preview          # run in the background, no window
./run.sh --width 1920 --height 1080
```

## How it works

- `kinect_device.py`: Kinect driver layer on **libfreenect's low-level API** (ctypes). One thread owns the device and keeps it healthy:
  - On this Kinect, the first stream start after opening never delivers frames, so the app sends a short priming start and then restarts the stream right away.
  - If video or depth stops, it restarts just that stream in place. If that keeps failing, it closes and reopens the device, and as a last resort it resets the Kinect over USB.
  - libfreenect's messages go to an in-app log instead of the terminal.
- `kinect_audio.py`: the 4-microphone stream. It uploads the audio firmware, and if the audio starts silent, it reopens the audio device.
- `sound.py`: sound directions. SRP-PHAT (combining all 6 microphone pairs) finds the main direction. A direction is also estimated separately for each frequency, and those votes are collected into a histogram, which separates several simultaneous sources. A delay-and-sum beam handles "Mic: me".
- `usb_reset.py`: libusb helpers that clear stale command replies, reset the Kinect over USB, and wait for it to reconnect.
- `kinectcam.py`: the app. It handles tracking (face detector, with a fallback to the depth map), smooth framing and motor follow, background effects, and the button UI, and sends the output to the OBS Virtual Camera.

## Troubleshooting

- **Startup** normally takes 4–10 s. The app shows each step: connecting, starting streams, streaming. If the Kinect is stuck, it recovers on its own. If it still hasn't started after 60 s, the last libfreenect messages are printed. Run `./run.sh --reset` once, and as a last resort unplug the Kinect's power for 5 s.
- **No frames at all**: unplug the Kinect's **power adapter** for 5 seconds and plug it back in. If you can, plug its USB straight into the Mac instead of the Dell dock. The Kinect does not work well behind hubs.
- **Virtual camera not available**: open OBS, click *Start Virtual Camera* once, and approve the extension in System Settings › General › Login Items & Extensions. Then quit OBS and press **C**.
- **A video app doesn't list the camera**: fully quit and reopen that app after KinectCam starts.
- The Kinect's original output is 640×480. Output is scaled to 1280×720, so it will look softer than a modern webcam.
