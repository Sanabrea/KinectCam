# Kinect audio firmware

The Kinect v1's 4-microphone array only works after Microsoft's audio firmware
is uploaded to it at every power-up. KinectCam looks for it here as
`firmware/audios.bin`. It belongs to Microsoft, so it is not in this repository.

Get it with libfreenect's `fwfetcher.py`, which downloads Microsoft's official
Xbox 360 system update and extracts the file (about 116 MB download):

```bash
# macOS (Homebrew libfreenect installs the script)
python3 /opt/homebrew/opt/libfreenect/share/fwfetcher.py
mv audios.bin firmware/

# any OS: the script is also in the libfreenect sources
#   https://github.com/OpenKinect/libfreenect/blob/master/src/fwfetcher.py
python fwfetcher.py
```

Without the file KinectCam still works; only the microphone features (sound
dots, mic focus, voice steer, calibration) are turned off.
