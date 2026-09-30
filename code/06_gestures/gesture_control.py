"""Module 6 — Example B: hand gestures -> arm commands.

    fist       -> close gripper and go home   ("grab it")
    open palm  -> open gripper                ("drop it")
    pinch      -> run the pick sequence       (thumb+index together)
    point      -> release over the bin        (one finger up)

TWO engines, same four gestures, same commands:

  glove    (default on Pi 4) — wear ONE colored glove (yellow by default).
           OpenCV counts fingertip blobs: 0/none = fist, 1 small = point,
           1 merged = pinch, 4-5 = palm. Pure module-4 skills, no extra
           dependencies. Pi 4 note: mediapipe 1.x wheels need CPU
           instructions the Cortex-A72 lacks (SIGILL), so this engine is
           the workshop default.
  mediapipe (stronger boards, e.g. Pi 5) — MediaPipe Hands finds 21
           landmarks; plain geometry turns them into the same gestures.
           Needs the venv + hand_landmarker.task (see docs/06-gestures.md).

Both feed the SAME brain as module 5: hold 8 frames -> send J-commands ->
wait for OK -> cooldown. The Nano firmware never changes.

Run on the Pi:
    python3 gesture_control.py --selftest            # no camera needed
    python3 gesture_control.py --engine glove        # live, glove
    python3 gesture_control.py --engine glove --glove-color red
    ~/workshop/venvs/gestures/bin/python gesture_control.py --engine mediapipe
"""

import argparse
import math
import os
import sys
import time

import cv2
import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "04_opencv"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "05_color_action"))
from camera import Camera            # noqa: E402
from color_track import mask_for, RANGES  # noqa: E402
from color_action import Link        # noqa: E402  (same serial link as module 5)

# ---------------------------------------------------------------- commands --
GRIP_OPEN, GRIP_CLOSED = 30, 100
HOME = (90, 90, 90)

COMMANDS = {
    "fist":  [f"J,{HOME[0]},{HOME[1]},{HOME[2]},{GRIP_CLOSED}", "H"],
    "palm":  [f"J,{HOME[0]},{HOME[1]},{HOME[2]},{GRIP_OPEN}"],
    "point": [f"J,30,80,100,{GRIP_CLOSED}",          # over the bin, holding
              f"J,30,80,100,{GRIP_OPEN}",            # release
              "H"],
    "pinch": [f"J,90,45,120,{GRIP_OPEN}",            # reach down
              f"J,90,45,120,{GRIP_CLOSED}",          # grab
              f"J,{HOME[0]},{HOME[1]},{HOME[2]},{GRIP_CLOSED}",  # lift
              f"J,30,80,100,{GRIP_CLOSED}",          # bin
              f"J,30,80,100,{GRIP_OPEN}",            # drop
              "H"],
}

STABLE_FRAMES = 8
COOLDOWN_S = 3.0

# ---------------------------------------------------------- glove engine --
# Blob areas in pixels at 640x480 — print your own with the debug line
# ("tips: ...") and tune these three once for your glove + distance.
TIP_MIN = 350        # smaller than this = noise, not a fingertip
PINCH_MIN = 1500     # one blob this big = two fingertips touching (pinch)
FIST_MIN = 3500      # one blob this big = the whole fist (no fingertips out)
PALM_TIPS = 4        # this many separate fingertip blobs = open palm


def glove_blobs(frame, color):
    """All glove-colored blobs: list of (center, area), biggest first."""
    mask = mask_for(frame, color)
    mask = cv2.erode(mask, None, iterations=2)
    mask = cv2.dilate(mask, None, iterations=2)
    cnts, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    blobs = []
    for c in cnts:
        area = cv2.contourArea(c)
        if area >= TIP_MIN:
            x, y, w, h = cv2.boundingRect(c)
            blobs.append(((x + w // 2, y + h // 2), area))
    return sorted(blobs, key=lambda b: -b[1])


def classify_blobs(blobs):
    """(center, area) blob list -> gesture name or None."""
    if not blobs:
        return None                       # no glove in view
    biggest = blobs[0][1]
    if len(blobs) >= PALM_TIPS:
        return "palm"                     # 4-5 separate fingertips
    if len(blobs) == 1:
        if biggest >= FIST_MIN:
            return "fist"                 # whole glove, fingers tucked
        if biggest >= PINCH_MIN:
            return "pinch"                # two tips merged into one blob
        return "point"                    # a single fingertip
    return None                           # 2-3 blobs = hand mid-transition


# ------------------------------------------------------ mediapipe engine --
def dist(a, b):
    return math.hypot(a[0] - b[0], a[1] - b[1])


def classify(pts):
    """21 normalized (x, y) landmarks -> gesture name or None.

    Finger "extended" = its tip clearly farther from the wrist than its
    middle knuckle — works however the hand is rotated.
    """
    wrist = pts[0]
    scale = dist(pts[0], pts[9]) or 1e-6

    def extended(tip, pip):
        return dist(pts[tip], wrist) > dist(pts[pip], wrist) * 1.15

    index, middle, ring, pinky = (extended(8, 6), extended(12, 10),
                                  extended(16, 14), extended(20, 18))
    thumb = dist(pts[4], wrist) > dist(pts[2], wrist) * 1.10
    fingers_up = sum((index, middle, ring, pinky, thumb))

    if dist(pts[4], pts[8]) < 0.35 * scale:          # thumb+index tips touch
        return "pinch"
    if fingers_up == 0:
        return "fist"
    if index and not (middle or ring or pinky):
        return "point"
    if fingers_up >= 4:
        return "palm"
    return None


HAND_CONNECTIONS = [(0, 1), (1, 2), (2, 3), (3, 4), (0, 5), (5, 6), (6, 7),
                    (7, 8), (5, 9), (9, 10), (10, 11), (11, 12), (9, 13),
                    (13, 14), (14, 15), (15, 16), (13, 17), (17, 18),
                    (18, 19), (19, 20), (0, 17)]


def make_landmarker():
    """mediapipe 1.x Tasks API (the old mp.solutions is gone in 1.x)."""
    import mediapipe as mp
    from mediapipe.tasks.python import BaseOptions
    from mediapipe.tasks.python import vision as mp_vision
    model = os.path.join(os.path.dirname(__file__), "hand_landmarker.task")
    if not os.path.exists(model):
        raise SystemExit("hand_landmarker.task missing next to this script — "
                         "download it once, see docs/06-gestures.md")
    return (mp, mp_vision.HandLandmarker.create_from_options(
        mp_vision.HandLandmarkerOptions(
            base_options=BaseOptions(model_asset_path=model),
            num_hands=1, min_hand_detection_confidence=0.5)))


# ------------------------------------------------------------------ brain --
class Brain:
    def __init__(self, link):
        self.link = link
        self.streak_name, self.streak = None, 0
        self.busy_until = 0.0

    def step(self, gesture):
        now = time.time()
        if gesture == self.streak_name:
            self.streak += 1
        else:
            self.streak_name, self.streak = gesture, 1

        if now < self.busy_until or not gesture:
            return None
        if self.streak >= STABLE_FRAMES:
            self.play(gesture)
            return gesture
        return None

    def play(self, gesture):
        print(f"*** {gesture.upper()} held {STABLE_FRAMES} frames -> command")
        for msg in COMMANDS[gesture]:
            if not self.link.cmd(msg):
                print("!! arm reported an error — command aborted")
                break
        self.busy_until = time.time() + COOLDOWN_S
        self.streak = 0


# --------------------------------------------------------------- selftest --
def synthetic_glove_frame(gesture):
    """Black frame with a yellow glove making `gesture`, blob-style."""
    img = np.zeros((480, 640, 3), np.uint8)
    yellow = (0, 255, 255)
    if gesture == "palm":                     # five separate fingertips
        for x in (200, 280, 360, 440, 520):
            cv2.circle(img, (x, 160), 16, yellow, -1)
    elif gesture == "point":                  # one fingertip
        cv2.circle(img, (320, 200), 16, yellow, -1)
    elif gesture == "pinch":                  # two fingertips touching = 1 big blob
        cv2.circle(img, (312, 200), 24, yellow, -1)
        cv2.circle(img, (334, 200), 24, yellow, -1)
    elif gesture == "fist":                   # the whole glove, no fingertips
        cv2.circle(img, (320, 220), 48, yellow, -1)
    return img


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--selftest", action="store_true")
    parser.add_argument("--engine", choices=("auto", "glove", "mediapipe"),
                        default="auto")
    parser.add_argument("--glove-color", default="yellow",
                        choices=list(RANGES))
    parser.add_argument("--seconds", type=int, default=60)
    args = parser.parse_args()

    brain = Brain(Link(dry_run=args.dry_run and not args.selftest))

    if args.selftest:
        print("== blob classifier (the Pi-4 default engine)")
        ok = True
        for name in ("fist", "palm", "pinch", "point"):
            got = classify_blobs(glove_blobs(synthetic_glove_frame(name), "yellow"))
            good = got == name
            ok &= good
            print(f"classifier: {name:6s} -> {got}", "OK" if good else "WRONG")
        fired = []
        for name in ("fist", "palm", "pinch", "point"):
            brain.busy_until = 0.0           # selftest owns the clock
            for _ in range(STABLE_FRAMES):
                hit = brain.step(name)
                if hit:
                    fired.append(hit)
        passed = ok and fired == ["fist", "palm", "pinch", "point"]
        print("selftest:", "PASS" if passed else f"FAIL blobs={ok} fired={fired}")
        raise SystemExit(0 if passed else 1)

    # ---- pick the engine -------------------------------------------------
    engine = args.engine
    if engine == "auto":
        # Default to the engine that runs EVERYWHERE, including Pi 4: the
        # mediapipe 1.x wheel needs CPU instructions the Cortex-A72 lacks
        # and dies with SIGILL — only force --engine mediapipe on a Pi 5.
        engine = "glove"
        print("engine: auto -> glove (mediapipe: force with --engine mediapipe on a Pi 5)")
    landmarker = None
    if engine == "mediapipe":
        landmarker = make_landmarker()       # (mediapipe module, detector)

    cam = Camera()
    print(f"camera: {cam.name} | engine: {engine} | "
          f"gestures: fist / palm / pinch / point | Ctrl+C stops")
    if engine == "glove":
        print(f"wearing the {args.glove_color} glove? hold one gesture steady "
              f"~{STABLE_FRAMES} frames")

    start, shots = time.time(), 0
    try:
        while time.time() - start < args.seconds:
            frame = cam.read()
            if frame is None:
                continue

            gesture = None
            if engine == "glove":
                blobs = glove_blobs(frame, args.glove_color)
                gesture = classify_blobs(blobs)
                tips = " ".join(f"{int(a)}" for _, a in blobs[:5])
                print(f"tips: [{tips}]  gesture: {gesture or '-'}")
                if shots < 4 and blobs:
                    for (cx, cy), _ in blobs:
                        cv2.circle(frame, (cx, cy), 8, (0, 0, 255), 2)
                    cv2.putText(frame, str(gesture), (10, 24),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)
                    cv2.imwrite(f"gesture_{shots:02d}.jpg", frame)
                    shots += 1
            else:
                mp, detector = landmarker
                rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                result = detector.detect(
                    mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb))
                if result.hand_landmarks:
                    lms = result.hand_landmarks[0]
                    gesture = classify([(p.x, p.y) for p in lms])
                print(f"hand: {gesture or '-'}")
                if shots < 4 and result.hand_landmarks:
                    pts_px = [(int(p.x * frame.shape[1]), int(p.y * frame.shape[0]))
                              for p in result.hand_landmarks[0]]
                    for a, b in HAND_CONNECTIONS:
                        cv2.line(frame, pts_px[a], pts_px[b], (0, 255, 0), 1)
                    for p in pts_px:
                        cv2.circle(frame, p, 3, (0, 0, 255), -1)
                    cv2.putText(frame, str(gesture), (10, 24),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)
                    cv2.imwrite(f"gesture_{shots:02d}.jpg", frame)
                    shots += 1

            brain.step(gesture)
    except KeyboardInterrupt:
        pass
    cam.close()


if __name__ == "__main__":
    main()
