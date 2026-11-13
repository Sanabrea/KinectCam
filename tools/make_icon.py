"""Draw the KinectCam app icon (1024x1024 PNG): a Kinect bar on a dark rounded tile."""
import sys

import cv2
import numpy as np

S = 1024
SS = 4  # supersampling for smooth edges
W = S * SS


def rr(img, x0, y0, x1, y1, r, color):
    x0, y0, x1, y1, r = [int(v * SS) for v in (x0, y0, x1, y1, r)]
    cv2.rectangle(img, (x0 + r, y0), (x1 - r, y1), color, -1)
    cv2.rectangle(img, (x0, y0 + r), (x1, y1 - r), color, -1)
    for cx, cy in ((x0 + r, y0 + r), (x1 - r, y0 + r), (x0 + r, y1 - r), (x1 - r, y1 - r)):
        cv2.circle(img, (cx, cy), r, color, -1)


def circle(img, x, y, r, color):
    cv2.circle(img, (int(x * SS), int(y * SS)), int(r * SS), color, -1, cv2.LINE_AA)


img = np.zeros((W, W, 4), np.uint8)
# background tile with a vertical gradient
tile = np.zeros((W, W, 4), np.uint8)
rr(tile, 100, 100, 924, 924, 185, (255, 255, 255, 255))
grad = np.linspace(0, 1, W)[:, None]
top, bottom = np.array([70, 48, 30]), np.array([30, 18, 12])          # BGR: deep blue
col = (top * (1 - grad) + bottom * grad)
tile_rgb = np.repeat(col[:, None, :], W, axis=1).reshape(W, W, 3)
img[..., :3] = tile_rgb.astype(np.uint8)
img[..., 3] = tile[..., 3]

# stand
rr(img, 455, 600, 569, 700, 20, (25, 25, 25, 255))
rr(img, 360, 680, 664, 735, 27, (25, 25, 25, 255))
# Kinect bar
rr(img, 170, 390, 854, 620, 110, (18, 18, 18, 255))
rr(img, 185, 405, 839, 605, 98, (40, 40, 40, 255))
# three lenses: IR emitter, RGB camera, IR camera
for x, r, ring, glass in ((330, 52, (70, 70, 70, 255), (20, 20, 20, 255)),
                          (512, 60, (80, 80, 80, 255), (120, 60, 20, 255)),
                          (694, 52, (70, 70, 70, 255), (20, 20, 20, 255))):
    circle(img, x, 505, r, ring)
    circle(img, x, 505, r * 0.68, glass)
circle(img, 494, 487, 15, (255, 220, 190, 255))   # glint on the RGB lens
# green status LED
circle(img, 512, 432, 11, (110, 240, 110, 255))
# sound waves (the microphone array) on the right
for i, rad in enumerate((120, 175, 230)):
    cv2.ellipse(img, (int(854 * SS - 60 * SS), int(505 * SS)), (int(rad * SS), int(rad * SS)), 0, -35, 35,
                (110, 240, 110, 255 - i * 60), int(18 * SS), cv2.LINE_AA)
img[..., 3] = np.minimum(img[..., 3], tile[..., 3])

out = cv2.resize(img, (S, S), interpolation=cv2.INTER_AREA)
cv2.imwrite(sys.argv[1] if len(sys.argv) > 1 else "icon_1024.png", out)
