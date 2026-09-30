"""Task 4 check — verify the detection pipeline against known ground truth.

Draws pure red / blue / green shapes at KNOWN pixel positions on synthetic
frames, runs the exact same mask_for() + detect() used live, and checks the
reported centers. Works in any lighting — no camera, no props needed.

Run on the Pi:  python3 test_pipeline.py
"""

import cv2
import numpy as np

from color_track import detect, mask_for


def frame_with(color_bgr, shape, cx, cy, size):
    """Black canvas with one colored, filled shape centered at (cx, cy)."""
    img = np.zeros((480, 640, 3), dtype=np.uint8)
    if shape == "circle":
        cv2.circle(img, (cx, cy), size, color_bgr, -1)
    else:
        cv2.rectangle(img, (cx - size, cy - size), (cx + size, cy + size),
                      color_bgr, -1)
    return img


# (name, BGR color, shape, true center, radius/size)
CASES = [
    ("red   low-hue circle", (0, 0, 255), "circle", 120, 100, 45),
    ("red   wrap-hue square", (60, 0, 255), "rect",   500, 120, 45),  # darker red wraps H past 170
    ("blue  square",         (255, 0, 0),  "rect",   320, 300, 50),
    ("green circle",         (0, 255, 0),  "circle", 160, 380, 45),
]

TRACK = {"red   low-hue circle": "red",
         "red   wrap-hue square": "red",
         "blue  square": "blue",
         "green circle": "green"}

TOLERANCE = 12  # pixels
failures = 0

for name, bgr, shape, cx, cy, size in CASES:
    frame = frame_with(bgr, shape, cx, cy, size)
    center, area = detect(mask_for(frame, TRACK[name]))
    ok = center is not None and abs(center[0] - cx) <= TOLERANCE and abs(center[1] - cy) <= TOLERANCE
    status = "PASS" if ok else "FAIL"
    failures += 0 if ok else 1
    got = f"({center[0]},{center[1]}) area={int(area)}" if center else "None"
    print(f"{status}  {name}: expected ({cx},{cy}) -> got {got}")

print("ALL PASS" if failures == 0 else f"{failures} FAILURES")
raise SystemExit(1 if failures else 0)
