"""Calibrate where sounds are drawn in the picture, using your mouth as the reference.

    .venv/bin/python calibrate_mic.py

You talk from three places (your right, centre, your left). The camera finds
your face, the mic array measures the sound angle, and the script fits
    camera angle = gain * sign * mic angle + offset
and saves mic_gain / mic_offset into settings.json. Close KinectCam first.
"""
import json
import math
import os
import sys
import time

import cv2
import numpy as np

import kinect_audio
import kinect_device as kd
import sound
from sound import FOCAL_PX, SoundLocator

HERE = os.path.dirname(os.path.abspath(__file__))
SETTINGS = os.path.join(HERE, "settings.json")
PHASES = [
    ("Move to YOUR RIGHT (the left side of the picture), face the Kinect", "right"),
    ("Move to the CENTRE, face the Kinect", "centre"),
    ("Move to YOUR LEFT (the right side of the picture), face the Kinect", "left"),
]
MOVE_S, TALK_S = 5.0, 10.0


def cam_angle(x):
    return math.degrees(math.atan((x - 320) / FOCAL_PX))


def main():
    settings = json.load(open(SETTINGS)) if os.path.exists(SETTINGS) else {}
    sign = settings.get("mic_sign", -1) or -1
    old_gain, old_off = settings.get("mic_gain", 1.0), settings.get("mic_offset", 0.0)

    face_det = cv2.CascadeClassifier(os.path.join(cv2.data.haarcascades, "haarcascade_frontalface_default.xml"))
    print("Starting the Kinect camera and microphones (10-15 s)...", flush=True)
    dev = kd.start("color", False)
    audio = kinect_audio.KinectAudio()
    audio.start()
    t0 = time.time()
    while time.time() - t0 < 40:
        v, _, _ = dev.latest()
        a = audio.recent(1024)
        if v is not None and a is not None and len(a) >= 1024 and np.abs(a).max() > 0:
            break
        time.sleep(0.2)
    else:
        print("Kinect did not start - try again."); return 1
    time.sleep(1.0)

    loc = SoundLocator()
    results = []
    for prompt, name in PHASES:
        print(f"\n>>> {prompt}", flush=True)
        end_move = time.time() + MOVE_S
        while time.time() < end_move:
            loc.update(audio.recent(loc.N), time.time())     # keep the noise floor tracking
            print(f"\r    get ready... {end_move - time.time():3.0f} s ", end="", flush=True)
            time.sleep(0.05)
        print(f"\r>>> TALK NOW: count out loud, '1, 2, 3...' for {TALK_S:.0f} s, keep facing the Kinect", flush=True)
        pairs = []
        end = time.time() + TALK_S
        while time.time() < end:
            now = time.time()
            loc.update(audio.recent(loc.N), now)
            v, _, _ = dev.latest()
            face_x = None
            if v is not None:
                gray = cv2.equalizeHist(cv2.cvtColor(v, cv2.COLOR_RGB2GRAY))   # raw frames are RGB
                faces = face_det.detectMultiScale(gray, 1.1, 3, minSize=(50, 50))
                if len(faces):
                    fx, fy, fw, fh = max(faces, key=lambda f: f[2] * f[3])
                    face_x = fx + fw / 2
            above = loc.level_db - (loc.floor_db if loc.floor_db is not None else loc.level_db)
            heard = above > 5.0 and loc.angle is not None
            if face_x is not None and heard:
                pairs.append((loc.angle, face_x))
            print(f"\r    face {'yes' if face_x is not None else 'NO '}   loudness {above:+5.1f} dB   voice "
                  f"{'%+4.0f deg' % loc.angle if heard else '   -    '}"
                  f"   samples {len(pairs):3d}   {end - now:3.0f} s ", end="", flush=True)
            time.sleep(0.03)
        print()
        if len(pairs) < 10:
            print(f"    only {len(pairs)} usable samples here - skipping this spot")
            continue
        p = np.array(pairs)
        mic = float(np.median(p[:, 0]))
        x = float(np.median(p[:, 1]))
        results.append((name, mic, x, len(pairs)))
        print(f"    mouth at x={x:.0f} (camera {cam_angle(x):+.1f} deg), sound {mic:+.1f} deg")

    audio.stop()
    kd.stop()

    print("\n=== Result ===")
    if len(results) < 2:
        print("Not enough spots measured - nothing saved. Run it again and talk a bit louder.")
        return 1
    m = np.array([sign * r[1] for r in results])
    t = np.array([cam_angle(r[2]) for r in results])
    if np.ptp(m) > 10:
        gain, off = np.polyfit(m, t, 1)
        if not 0.5 <= gain <= 2.0:
            print(f"(fitted scale {gain:.2f} looks wrong; keeping scale 1 and fitting only the offset)")
            gain, off = 1.0, float(np.mean(t - m))
    else:
        gain, off = 1.0, float(np.mean(t - m))
    for (name, mic, x, n) in results:
        sound.set_calibration(old_gain, old_off)
        before = sound.angle_to_image_x(mic, sign)
        sound.set_calibration(gain, off)
        after = sound.angle_to_image_x(mic, sign)
        print(f"  {name:6s}: mouth x={x:4.0f}   dot before x={before:5.0f} (off by {before - x:+4.0f} px)"
              f"   after x={after:5.0f} (off by {after - x:+4.0f} px)")
    settings["mic_gain"] = round(float(gain), 4)
    settings["mic_offset"] = round(float(off), 2)
    with open(SETTINGS, "w") as f:
        json.dump(settings, f, indent=2)
    print(f"\nSaved: scale {gain:.3f}, offset {off:+.1f} deg  ->  settings.json. Start KinectCam to see it.")
    return 0


if __name__ == "__main__":
    try:
        rc = main()
    except KeyboardInterrupt:
        rc = 1
    os._exit(rc)
