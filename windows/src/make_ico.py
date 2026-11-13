"""Write a multi-size Windows .ico (PNG-compressed entries) from a 1024px PNG."""
import struct
import sys

import cv2

src = cv2.imread(sys.argv[1], cv2.IMREAD_UNCHANGED)
sizes = [256, 64, 48, 32, 24, 16]
pngs = []
for s in sizes:
    img = cv2.resize(src, (s, s), interpolation=cv2.INTER_AREA)
    ok, data = cv2.imencode(".png", img)
    pngs.append(data.tobytes())

header = struct.pack("<HHH", 0, 1, len(sizes))
offset = 6 + 16 * len(sizes)
entries = b""
for s, data in zip(sizes, pngs):
    entries += struct.pack("<BBBBHHII", s % 256, s % 256, 0, 0, 1, 32, len(data), offset)
    offset += len(data)
with open(sys.argv[2], "wb") as f:
    f.write(header + entries + b"".join(pngs))
