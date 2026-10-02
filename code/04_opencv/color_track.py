"""Task 4.4 — detect a colored object and locate it (deck slide 34).

The core pipeline every later module reuses:

    frame -> HSV -> inRange mask -> erode/dilate -> biggest contour -> (cx, cy)

Red wraps around the hue circle, so it needs TWO ranges.

Run on the Pi:
    python3 color_track.py --color green
    python3 color_track.py --color red --seconds 10

Prints the center each second; headless (no DISPLAY) also saves annotated
snapshots color_track_XX.jpg so you can check over SSH.
"""

import argparse
import time

import cv2
import numpy as np

from camera import Camera

# Starting points only — tune under your real lighting (hsv_tune.py).
# OpenCV HSV: H 0..179, S 0..255, V 0..255
RANGES = {
    "green": [((35, 80, 80), (85, 255, 255))],
    "blue":  [((100, 80, 80), (130, 255, 255))],
    "red":   [((0, 80, 80), (10, 255, 255)),        # red part 1 (low hues)
              ((170, 80, 80), (179, 255, 255))],    # red part 2 (wrap-around)
    "yellow": [((26, 80, 80), (34, 255, 255))],     # the gesture glove
    "orange": [((11, 80, 80), (25, 255, 255))],     # module 8: rc car cards
    "purple": [((131, 80, 80), (169, 255, 255))],   # module 8: rc car cards
}

MIN_AREA = 500  # ignore blobs smaller than this many pixels


def detect(mask):
    """Clean the mask and return (center, area) of the biggest blob, or (None, 0)."""
    mask = cv2.erode(mask, None, iterations=2)      # kill speckle noise
    mask = cv2.dilate(mask, None, iterations=2)     # regrow the real object
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return None, 0
    c = max(contours, key=cv2.contourArea)
    area = cv2.contourArea(c)
    if area < MIN_AREA:
        return None, area
    x, y, w, h = cv2.boundingRect(c)
    return (x + w // 2, y + h // 2), area


def mask_for(frame, color):
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    mask = None
    for lo, hi in RANGES[color]:                    # red adds two masks together
        m = cv2.inRange(hsv, np.array(lo), np.array(hi))
        mask = m if mask is None else cv2.bitwise_or(mask, m)
    return mask


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--color", choices=list(RANGES), default="green")
    parser.add_argument("--seconds", type=int, default=8)
    args = parser.parse_args()

    cam = Camera()
    print(f"camera: {cam.name} | tracking {args.color} for {args.seconds}s")

    headless = not __import__("os").environ.get("DISPLAY")
    start = time.time()
    shots = 0
    try:
        while time.time() - start < args.seconds:
            frame = cam.read()
            if frame is None:
                continue
            center, area = detect(mask_for(frame, args.color))

            if center:
                cv2.circle(frame, center, 6, (0, 0, 255), -1)
                cv2.putText(frame, f"{args.color} ({center[0]},{center[1]}) area={int(area)}",
                            (10, 24), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)
                print(f"{args.color:5s} center={center} area={int(area)}")
            else:
                print(f"{args.color:5s} not detected")

            if headless and shots < 4:
                cv2.imwrite(f"color_track_{shots:02d}.jpg", frame)
                shots += 1
            elif not headless:
                cv2.imshow("track", frame)
                if cv2.waitKey(1) == ord("q"):
                    break
            time.sleep(1.0)
    finally:
        cam.close()
    print("done")


if __name__ == "__main__":
    main()
