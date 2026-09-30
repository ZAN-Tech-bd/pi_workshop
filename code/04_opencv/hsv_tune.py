"""Task 4.5 — tune the HSV range under YOUR real lighting (deck slide 33).

The table in the docs is only a starting point: shadows and room lights move
the right values around. This tool shows you the effect live.

Desktop/VNC:  python3 hsv_tune.py            -> trackbars + live mask
SSH headless: python3 hsv_tune.py --headless -> prints mask stats + centers
"""

import argparse
import time

import cv2
import numpy as np

from camera import Camera
from color_track import detect

parser = argparse.ArgumentParser()
parser.add_argument("--headless", action="store_true", help="no window, print stats")
parser.add_argument("--h-min", type=int, nargs=3, default=[35, 80, 80])
parser.add_argument("--h-max", type=int, nargs=3, default=[85, 255, 255])
args = parser.parse_args()

cam = Camera()
print("camera:", cam.name)

if not args.headless:
    cv2.namedWindow("tune")
    for name, val in [("Hmin", args.h_min[0]), ("Smin", args.h_min[1]), ("Vmin", args.h_min[2]),
                      ("Hmax", args.h_max[0]), ("Smax", args.h_max[1]), ("Vmax", args.h_max[2])]:
        cv2.createTrackbar(name, "tune", val, 255 if name[0] != "H" else 179, lambda x: None)

try:
    while True:
        frame = cam.read()
        if frame is None:
            break

        if args.headless:
            lo = tuple(args.h_min)
            hi = tuple(args.h_max)
        else:
            lo = tuple(cv2.getTrackbarPos(n, "tune") for n in ("Hmin", "Smin", "Vmin"))
            hi = tuple(cv2.getTrackbarPos(n, "tune") for n in ("Hmax", "Smax", "Vmax"))

        hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
        mask = cv2.inRange(hsv, np.array(lo), np.array(hi))
        center, area = detect(mask)

        if args.headless:
            print(f"mask pixels={int(mask.sum()/255):6d}  center={center}  area={area}")
            time.sleep(0.5)
        else:
            if center:
                cv2.circle(frame, center, 6, (0, 0, 255), -1)
            cv2.putText(frame, f"{lo}-{hi}", (10, 20),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 1)
            cv2.imshow("tune", frame)
            cv2.imshow("mask", mask)
            if cv2.waitKey(1) == ord("q"):
                break
except KeyboardInterrupt:
    pass

cam.close()
