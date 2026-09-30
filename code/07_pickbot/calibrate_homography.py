"""Module 7 — calibrate camera pixels to arm millimeters (deck slide 37).

The camera sees pixels; the arm speaks millimeters from its base. A
homography (perspective transform) maps one to the other — exact for a
flat table and a FIXED camera. If the camera moves, recalibrate.

Procedure (once, with the rig assembled):
  1. Save one camera frame:
         python3 calibrate_homography.py --capture
  2. Mark 4 points on the table (tape helps). Measure each in mm from the
     base center: +x = one side, +y = 90 degrees left of it.
  3. Read the same 4 points in PIXELS off the saved calib_frame.jpg (any
     image viewer, or hover in Thonny/VS Code).
  4. Compute and save:
         python3 calibrate_homography.py \
             --px 102,88 540,92 548,410 96,402 \
             --mm 80,-100 80,100 230,100 230,-100
     -> writes homography.npy next to this script.

Selftest (no camera needed):  python3 calibrate_homography.py --selftest
"""

import argparse

import cv2
import numpy as np

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "04_opencv"))
from camera import Camera  # noqa: E402

H_FILE = os.path.join(os.path.dirname(__file__), "homography.npy")


def compute(px, mm):
    src = np.float32(px)
    dst = np.float32(mm)
    return cv2.getPerspectiveTransform(src, dst)


def to_world(cx, cy, H):
    p = np.float32([[[cx, cy]]])
    return cv2.perspectiveTransform(p, H)[0][0]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--capture", action="store_true",
                        help="save one frame as calib_frame.jpg")
    parser.add_argument("--px", nargs=4, type=str,
                        help="four x,y pixels, same order as --mm")
    parser.add_argument("--mm", nargs=4, type=str,
                        help="four x,y mm measured from the arm base")
    parser.add_argument("--selftest", action="store_true")
    args = parser.parse_args()

    if args.selftest:
        # synthetic rectangle: pixel corners must map to exact mm corners
        px = [(102, 88), (540, 92), (548, 410), (96, 402)]
        mm = [(80, -100), (80, 100), (230, 100), (230, -100)]
        H = compute(px, mm)
        ok = True
        for (x, y), (ex, ey) in zip(px, mm):
            wx, wy = to_world(x, y, H)
            good = abs(wx - ex) < 0.01 and abs(wy - ey) < 0.01
            ok &= good
            print(f"pixel ({x},{y}) -> ({wx:.1f},{wy:.1f}) mm  "
                  f"expected ({ex},{ey})  {'OK' if good else 'WRONG'}")
        mid = to_world((102 + 548) / 2, (88 + 410) / 2, H)
        print(f"center -> ({mid[0]:.1f},{mid[1]:.1f}) mm (should be ~(155,0))")
        print("homography selftest:", "PASS" if ok else "FAIL")
        raise SystemExit(0 if ok else 1)

    if args.capture:
        cam = Camera()
        frame = cam.read()
        cam.close()
        if frame is None:
            raise SystemExit("no frame from camera")
        out = os.path.join(os.path.dirname(__file__), "calib_frame.jpg")
        cv2.imwrite(out, frame)
        print("saved", out, "- now mark 4 points and note their pixel coords")
        return

    if args.px and args.mm:
        px = [tuple(map(float, p.split(","))) for p in args.px]
        mm = [tuple(map(float, m.split(","))) for m in args.mm]
        if len(px) != 4 or len(mm) != 4:
            raise SystemExit("need exactly four --px and four --mm points")
        H = compute(px, mm)
        np.save(H_FILE, H)
        print("saved", H_FILE)
        cx, cy = to_world((px[0][0] + px[2][0]) / 2, (px[0][1] + px[2][1]) / 2, H)
        print(f"sanity: frame center maps to ({cx:.1f},{cy:.1f}) mm — "
              f"plausible for your workspace?")
        return

    parser.print_help()


if __name__ == "__main__":
    main()
