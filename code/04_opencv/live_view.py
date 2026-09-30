"""Task 4.2 — capture and show live video (deck slide 32).

With a desktop (or VNC) it opens a window, press q to quit.
Over plain SSH (no display) it saves 5 snapshots instead, so you can still
see what the camera sees: live_view_0.jpg ... live_view_4.jpg

Run on the Pi:  python3 live_view.py
"""

import os
import time

import cv2

from camera import Camera


def main():
    cam = Camera()
    print("camera:", cam.name)

    if os.environ.get("DISPLAY"):                     # desktop or VNC
        try:
            while True:
                frame = cam.read()
                if frame is None:
                    break
                cv2.imshow("camera", frame)           # BGR — OpenCV's order
                if cv2.waitKey(1) == ord("q"):
                    break
            cv2.destroyAllWindows()
        except KeyboardInterrupt:
            pass
    else:                                             # headless over SSH
        for i in range(5):
            frame = cam.read()
            if frame is None:
                raise SystemExit("no frame from camera")
            path = f"live_view_{i}.jpg"
            cv2.imwrite(path, frame)                  # headless substitute for imshow
            print("saved", path)
            time.sleep(0.5)

    cam.close()
    print("done")


if __name__ == "__main__":
    main()
