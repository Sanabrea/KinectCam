"""Measure where sounds come from, to check the mic-array orientation.

    .venv/bin/python mic_probe.py SECONDS [--say "text"]

Prints the dominant sound angle(s). Sign convention of sound.py: + = toward mic 4.
"""
import subprocess
import sys
import time

import numpy as np

import kinect_audio
from sound import SoundLocator

secs = float(sys.argv[1]) if len(sys.argv) > 1 else 6
say = sys.argv[sys.argv.index("--say") + 1] if "--say" in sys.argv else None

audio = kinect_audio.KinectAudio()
audio.start()
t0 = time.time()
while time.time() - t0 < 15:
    x = audio.recent(1024)
    if x is not None and len(x) >= 1024 and np.abs(x).max() > 0:
        break
    time.sleep(0.1)
else:
    print("no audio"); audio.stop(); sys.exit(1)
time.sleep(1.0)

loc = SoundLocator()
proc = subprocess.Popen(["say", "-r", "170", say]) if say else None
angles, srcs = [], []
end = time.time() + secs
while time.time() < end:
    loc.update(audio.recent(loc.N), time.time())
    if loc.speaking and loc.angle is not None:
        angles.append(loc.angle)
    for s in loc.sources:
        srcs.append(round(s["angle"] / 5) * 5)
    time.sleep(0.033)
if proc:
    proc.terminate()
audio.stop()

if not angles:
    print("RESULT: nothing loud enough heard")
else:
    a = np.array(angles)
    print(f"RESULT: main angle median {np.median(a):+.0f} deg  (n={len(a)}, IQR {np.percentile(a,25):+.0f}..{np.percentile(a,75):+.0f})")
    vals, counts = np.unique(srcs, return_counts=True)
    top = sorted(zip(counts, vals), reverse=True)[:4]
    print("RESULT: source angles (count):", ", ".join(f"{v:+.0f} ({c})" for c, v in top))
