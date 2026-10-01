"""Synthetic rig: fake Camera serving frames with a green square, so the REAL
pickbot.py loop runs end-to-end in --simulate mode without physical hardware.

Proves: green detect -> homography px->mm -> IK -> full pick sequence printed.
"""

import os
import sys

import numpy as np

W = os.path.expanduser("~/workshop")
sys.path.insert(0, os.path.join(W, "07_pickbot"))
sys.path.insert(0, os.path.join(W, "04_opencv"))
sys.path.insert(0, os.path.join(W, "05_color_action"))

import pickbot  # noqa: E402


class FakeCam:
    name = "synthetic rig (80x80 green square at pixel 320,240)"

    def read(self):
        frame = np.full((480, 640, 3), (45, 45, 45), np.uint8)
        frame[200:280, 280:360] = (0, 200, 0)      # BGR green
        return frame

    def close(self):
        pass


pickbot.Camera = FakeCam                          # pickbot now "sees" the rig
sys.argv = ["pickbot.py", "--simulate", "--seconds", "6"]
pickbot.main()
