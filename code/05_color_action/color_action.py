"""Module 5 — Example A: color -> arm action.

    camera sees RED  -> arm plays action 1 (pick from the left)
    camera sees BLUE -> arm plays action 2 (pick from the right)

Everything you already built, glued together:

    camera.py (module 4)  ->  see
    this file             ->  decide (10 stable frames, then a pose sequence)
    J,b,s,e,g + OK (2,3)  ->  talk and move

The Arduino firmware does NOT change — every action is just a list of
J-commands sent from the Pi. Keep the brain on the Pi, keep the Nano thin.

Run on the Pi:
    python3 color_action.py              # live camera + real arm link
    python3 color_action.py --dry-run    # vision runs, commands only printed
    python3 color_action.py --selftest   # synthetic frames through the SAME
                                         # brain — verifies red->action1 and
                                         # blue->action2 without props/light
"""

import argparse
import os
import sys
import time

import cv2
import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "04_opencv"))
from camera import Camera                     # noqa: E402
from color_track import detect, mask_for      # noqa: E402

import serial  # noqa: E402

# --------------------------------------------------------------------------
# Action scripts — EXAMPLE poses. Find yours with calibrate.py (module 3),
# then edit here. Each line is one J,b,s,e,g the arm will visit in order.
# --------------------------------------------------------------------------
ACTIONS = {
    "red": [                                     # action 1: pick-left wave
        (90, 90, 90, 30),      # home, gripper open
        (150, 70, 110, 30),    # reach left
        (150, 70, 110, 100),   # close gripper
        (90, 90, 90, 100),     # lift home
        (30, 80, 100, 100),    # over the bin
        (30, 80, 100, 30),     # release
        (90, 90, 90, 30),      # home
    ],
    "blue": [                                    # action 2: pick-right salute
        (90, 90, 90, 30),
        (30, 70, 110, 30),     # reach right
        (30, 70, 110, 100),
        (90, 90, 90, 100),
        (150, 80, 100, 100),   # over the other side
        (150, 80, 100, 30),
        (90, 90, 90, 30),
    ],
}

STABLE_FRAMES = 10     # object must be seen this many frames in a row
COOLDOWN_S = 3.0       # after an action, ignore colors this long


# --------------------------------------------------------------------------
# The link to the arm — real serial, or a printer in --dry-run
# --------------------------------------------------------------------------
class Link:
    def __init__(self, dry_run=False):
        self.dry = dry_run
        self.ser = None
        if not dry_run:
            for port in ("/dev/ttyACM0", "/dev/ttyUSB0"):
                if os.path.exists(port):
                    self.ser = serial.Serial(port, 115200, timeout=5)
                    time.sleep(2)               # port-open reset
                    break
            if self.ser is None:
                raise SystemExit("No Arduino found — rerun with --dry-run")

    def cmd(self, msg):
        """Send one message, return True when the arm answered OK."""
        if self.dry or self.ser is None:
            print(f"TX {msg:<18} (dry-run)")
            return True
        self.ser.write(msg.encode() + b"\n")
        reply = self.ser.readline().decode().strip()
        print(f"TX {msg:<18} RX {reply}")
        return reply == "OK"


# --------------------------------------------------------------------------
# The brain — one frame in, maybe an action out
# --------------------------------------------------------------------------
class Brain:
    def __init__(self, link):
        self.link = link
        self.streak = {}          # color -> consecutive frames seen
        self.busy_until = 0.0

    def step(self, seen):
        """seen: dict color -> center for everything detected this frame."""
        now = time.time()
        for color in ACTIONS:
            self.streak[color] = self.streak.get(color, 0) + 1 if color in seen else 0

        if now < self.busy_until:
            return None
        for color, n in self.streak.items():
            if n >= STABLE_FRAMES:
                self.play(color)
                return color
        return None

    def play(self, color):
        print(f"*** {color.upper()} stable for {STABLE_FRAMES} frames -> action {list(ACTIONS).index(color) + 1}")
        self.link.cmd("H")
        for b, s, e, g in ACTIONS[color]:
            if not self.link.cmd(f"J,{b},{s},{e},{g}"):
                print("!! arm reported an error — action aborted")
                break
        self.link.cmd("H")
        self.busy_until = time.time() + COOLDOWN_S
        self.streak = {}


def see(frame):
    """Return {color: center} for red and blue in this frame."""
    found = {}
    for color in ("red", "blue"):
        center, area = detect(mask_for(frame, color))
        if center:
            found[color] = center
    return found


# --------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--selftest", action="store_true",
                        help="synthetic frames through the real brain")
    parser.add_argument("--seconds", type=int, default=60)
    args = parser.parse_args()

    brain = Brain(Link(dry_run=args.dry_run and not args.selftest))

    if args.selftest:
        # 14 frames of red at (160,120), then 14 of blue at (480,360)
        def make(color_bgr, cx, cy):
            f = np.zeros((480, 640, 3), np.uint8)
            cv2.circle(f, (cx, cy), 50, color_bgr, -1)
            return f
        fired = []

        def run_phase(frames):
            for f in frames:
                hit = brain.step(see(f))
                if hit:
                    fired.append(hit)

        run_phase([make((0, 0, 255), 160, 120)] * 14)   # red phase
        # the LIVE loop spends the cooldown in real time; the selftest runs
        # in milliseconds, so it fast-forwards the cooldown itself:
        brain.busy_until = 0.0
        brain.streak = {}
        run_phase([make((255, 0, 0), 480, 360)] * 14)   # blue phase
        print("selftest:", "PASS" if fired == ["red", "blue"] else f"FAIL {fired}")
        raise SystemExit(0 if fired == ["red", "blue"] else 1)

    cam = Camera()
    print(f"camera: {cam.name} | watching RED and BLUE | Ctrl+C to stop")
    start = time.time()
    try:
        while time.time() - start < args.seconds:
            frame = cam.read()
            if frame is None:
                continue
            seen = see(frame)
            hint = " ".join(f"{c}@{p}" for c, p in seen.items()) or "-"
            print(f"watching: {hint}")
            brain.step(seen)
            time.sleep(0.2)                     # ~5 fps is plenty for this
    except KeyboardInterrupt:
        pass
    cam.close()


if __name__ == "__main__":
    main()
