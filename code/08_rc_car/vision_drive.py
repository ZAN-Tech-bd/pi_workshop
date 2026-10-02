"""Module 8 — Example: 6 colors -> 6 driving directions (RC car).

AI vocabulary this project teaches (put it on the slide):
  sense-think-act agent · pixel-level color segmentation (a rule-based
  classifier) · object detection & localization (biggest blob + centroid)
  · policy (color -> command mapping) · temporal smoothing (hold N frames)

The policy table — one colored card in front of the car camera:

    RED     -> F  forward          GREEN   -> L  left
    BLUE    -> B  backward         YELLOW  -> R  right
    ORANGE  -> G  front-left       PURPLE  -> I  front-right
    (nothing in view for N frames) -> S  stop

Those single letters are the SAME commands the RC-101 phone app sends, so
this brain instantly works with the classic car firmware too.

Run on the Pi:
    python3 vision_drive.py --selftest      # classifier + serial, no camera
    python3 vision_drive.py --dry-run       # camera in, commands printed
    python3 vision_drive.py                 # live: cards drive the car
"""

import argparse
import os
import sys
import time

import cv2
import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "04_opencv"))
from camera import Camera                    # noqa: E402
from color_track import detect, mask_for     # noqa: E402

# the policy: perception result -> action
DIRECTIONS = {
    "red":    ("F", "forward"),
    "blue":   ("B", "backward"),
    "green":  ("L", "left"),
    "yellow": ("R", "right"),
    "orange": ("G", "front-left"),
    "purple": ("I", "front-right"),
}
STABLE_FRAMES = 8          # a color must hold this many frames (anti-flicker)
MIN_AREA = 600             # ignore blobs smaller than this


def classify(frame):
    """Return (color, center, area) of the strongest of the 6 colors."""
    best = (None, None, 0)
    for color in DIRECTIONS:
        center, area = detect(mask_for(frame, color))
        if center and area > best[2]:
            best = (color, center, area)
    return best if best[2] >= MIN_AREA else (None, None, 0)


def annotate(frame, color, center):
    """Copy of the frame labeled with what the policy sees."""
    out = frame.copy()
    if color:
        bgr = {"red": (60, 60, 255), "blue": (255, 60, 60),
               "green": (60, 255, 60), "yellow": (60, 255, 255),
               "orange": (60, 140, 255), "purple": (255, 60, 255)}[color]
        cmd, name = DIRECTIONS[color]
        cv2.circle(out, center, 8, bgr, -1)
        cv2.putText(out, f"{color} -> {cmd} ({name})", (10, 28),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.75, bgr, 2)
    return out


class SerialLink:
    """Sends single-char commands (RC-101 style); PING proves the link."""

    def __init__(self, dry_run=False):
        self.dry = dry_run
        self.ser = None
        if not dry_run:
            import serial
            for port in ("/dev/ttyACM0", "/dev/ttyUSB0"):
                if os.path.exists(port):
                    self.ser = serial.Serial(port, 115200, timeout=2)
                    time.sleep(2)
                    break
            if self.ser is None:
                raise SystemExit("no Arduino found — use --dry-run")

    def ping(self):
        if not self.ser:
            return True
        self.ser.write(b"PING\n")
        return self.ser.readline().decode().strip() == "OK"

    def cmd(self, key):
        if not self.ser:
            print(f"TX {key} (dry-run)")
            return
        self.ser.write(key.encode())


def selftest(link):
    ok = True
    for color, (cmd, name) in DIRECTIONS.items():
        bgr = {"red": (0, 0, 255), "blue": (255, 0, 0), "green": (0, 255, 0),
               "yellow": (0, 255, 255), "orange": (0, 140, 255),
               "purple": (255, 0, 255)}[color]
        frame = np.zeros((480, 640, 3), np.uint8)
        cv2.rectangle(frame, (250, 160), (390, 320), bgr, -1)
        seen, center, area = classify(frame)
        good = seen == color
        ok &= good
        print(f"classifier: {color:7s} -> {seen} ({cmd} {name})",
              "OK" if good else "WRONG")
    print("link PING:", "OK" if link.ping() else "NO REPLY")
    ok &= link.ping()
    for color, (cmd, name) in DIRECTIONS.items():
        link.cmd(cmd)
        time.sleep(0.15)
    link.cmd("S")
    print("selftest:", "PASS" if ok else "FAIL")
    return ok


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--selftest", action="store_true")
    parser.add_argument("--seconds", type=int, default=120)
    args = parser.parse_args()

    link = SerialLink(dry_run=args.dry_run and not args.selftest)

    if args.selftest:
        raise SystemExit(0 if selftest(link) else 1)

    cam = Camera()
    print(f"camera: {cam.name} | show a colored card: red/blue/green/"
          f"yellow/orange/purple | Ctrl+C stops")
    streak_color, streak, last_sent = None, 0, None
    start = time.time()
    try:
        while time.time() - start < args.seconds:
            frame = cam.read()
            if frame is None:
                continue
            color, center, area = classify(frame)

            streak = streak + 1 if color == streak_color else 0
            streak_color = color

            if streak >= STABLE_FRAMES:
                cmd = DIRECTIONS[color][0] if color else "S"
                if cmd != last_sent:
                    link.cmd(cmd)
                    print(f"{color or 'nothing':8s} -> {cmd}")
                    last_sent = cmd
            cv2.imshow("rc", annotate(frame, color, center)) \
                if os.environ.get("DISPLAY") else None
            time.sleep(0.15)
    except KeyboardInterrupt:
        pass
    link.cmd("S")
    cam.close()


if __name__ == "__main__":
    main()
