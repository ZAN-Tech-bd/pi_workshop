"""Module 7 — PickBot: the full vision-guided pick-and-place loop.

One loop, everything from modules 2-7 in it (deck slides 36-41):

    detect green (module 4)  ->  stable 10 frames  ->  pixels to mm
    (homography)  ->  joint angles (IK)  ->  J,..,..,..,..  ->  wait OK
    ->  grip  ->  home  ->  bin  ->  release  ->  home  ->  repeat

Prerequisites (each has its own doc):
  - arm_firmware.ino on the Nano (module 3)
  - homography.npy from calibrate_homography.py
  - L1/L2/Z_BASE measured in ik.py
  - GRIP/BIN poses tuned for YOUR arm

Run on the Pi:
    python3 pickbot.py --simulate   # full brain, moves only printed
    python3 pickbot.py              # live: keep a hand on the servo supply!
"""

import argparse
import os
import sys
import time

import cv2
import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "04_opencv"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "05_color_action"))
from camera import Camera                 # noqa: E402
from color_track import detect, mask_for  # noqa: E402
from color_action import Link              # noqa: E402
from calibrate_homography import to_world, H_FILE  # noqa: E402
from ik import solve_ik                    # noqa: E402

# ---- tune these for YOUR arm (module 3 calibrate.py) -----------------------
GRIP_OPEN, GRIP_CLOSED = 30, 100
HOME = (90, 90, 90)
BIN = (20, 80, 100)
Z_PICK = 20          # mm above the table where the gripper grabs
Z_LIFT = 80          # mm to lift to while traveling
STABLE_FRAMES = 10
COLOR = "green"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--simulate", action="store_true",
                        help="print moves instead of sending them")
    parser.add_argument("--seconds", type=int, default=120)
    args = parser.parse_args()

    if not os.path.exists(H_FILE):
        raise SystemExit("homography.npy missing — run calibrate_homography.py "
                         "first (docs/07-pickbot.md, step 2)")

    H = np.load(H_FILE)
    link = Link(dry_run=args.simulate)
    cam = Camera()
    print(f"camera: {cam.name} | homography loaded | watching {COLOR} | "
          f"{'SIMULATION' if args.simulate else 'LIVE — hand on the power switch!'}")

    def move(b, s, e, g, why=""):
        msg = f"J,{b:.0f},{s:.0f},{e:.0f},{int(g)}"
        ok = link.cmd(msg)                    # waits for OK before returning
        if not ok:
            print(f"!! arm rejected {msg} ({why})")
        return ok

    cubes, streak, start = 0, 0, time.time()
    try:
        while time.time() - start < args.seconds:
            frame = cam.read()
            if frame is None:
                continue
            found, area = detect(mask_for(frame, COLOR))

            if found is None:                 # detect() -> (None, 0) when empty
                streak = 0
                continue
            cx, cy = found
            streak += 1
            if streak < STABLE_FRAMES:        # anti-flicker guard (slide 39)
                continue

            wx, wy = to_world(cx, cy, H)
            print(f"cube at pixel ({cx},{cy}) -> ({wx:.0f},{wy:.0f}) mm")

            ik = solve_ik(wx, wy, Z_PICK)
            if ik is None:
                print("   out of reach — ignored")
                streak = 0
                continue

            b, s, e = ik
            print(f"   pick sequence J,{b},{s},{e}")
            move(b, s, e, GRIP_OPEN, "approach")
            move(b, s, e, GRIP_CLOSED, "grip")
            lift = solve_ik(wx * 0.3, wy * 0.3, Z_LIFT) or HOME  # toward home, up
            move(lift[0], lift[1], lift[2], GRIP_CLOSED, "lift")
            move(BIN[0], BIN[1], BIN[2], GRIP_CLOSED, "over bin")
            move(BIN[0], BIN[1], BIN[2], GRIP_OPEN, "release")
            move(HOME[0], HOME[1], HOME[2], GRIP_OPEN, "home")
            link.cmd("H")
            cubes += 1
            print(f"   cube #{cubes} in the bin")
            streak = 0
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    cam.close()
    print(f"done — {cubes} cube(s) picked")


if __name__ == "__main__":
    main()
