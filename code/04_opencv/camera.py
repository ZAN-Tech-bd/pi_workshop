"""One camera, one API: read() returns BGR frames for OpenCV.

Source priority (first that works wins):
  1. Pi camera module via Picamera2 — the default for the workshop
  2. MJPEG stream (set CAMERA_URL, e.g. the camera-dashboard on this Pi:
     http://localhost:8000/stream) — lets a browser and your code SHARE
     one camera; only one program can open the sensor directly
  3. First USB webcam via cv2.VideoCapture(0)

All later modules import this, so switching cameras changes nothing else.
"""

import os

import cv2


class Camera:
    def __init__(self, width=640, height=480):
        self.picam2 = None
        self.cap = None

        # --- 1. Pi camera module -------------------------------------------------
        try:
            from picamera2 import Picamera2
            self.picam2 = Picamera2()
            cfg = self.picam2.create_video_configuration(
                main={"size": (width, height), "format": "RGB888"})
            self.picam2.configure(cfg)
            self.picam2.start()
            self.name = "Pi camera (Picamera2)"
            return
        except Exception:
            pass  # no Pi camera, or it is busy — try the next source

        # --- 2. MJPEG stream (e.g. camera-dashboard) -----------------------------
        url = os.environ.get(
            "CAMERA_URL",
            f"http://localhost:8000/stream?w={width}&h={height}&fps=15")
        cap = cv2.VideoCapture(url)
        for _ in range(10):                 # streams need a moment to warm up
            ok, frame = cap.read()
            if ok and frame is not None:
                self.cap = cap
                self.name = f"MJPEG stream ({url})"
                self._last = frame
                return
        cap.release()

        # --- 3. USB webcam --------------------------------------------------------
        cap = cv2.VideoCapture(0)
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
        ok, frame = cap.read()
        if ok and frame is not None:
            self.cap = cap
            self.name = "USB webcam (VideoCapture 0)"
            self._last = frame
            return

        raise SystemExit(
            "No camera available.\n"
            "  - Pi camera busy? Only ONE program opens the sensor directly;\n"
            "    stop it, or point CAMERA_URL at its MJPEG stream.\n"
            "  - No USB webcam found either.")

    def read(self):
        """Return one frame in BGR order (what OpenCV expects), or None."""
        if self.picam2 is not None:
            # Picamera2 gives RGB888 — flip to BGR so every cv2 call is standard
            return cv2.cvtColor(self.picam2.capture_array(), cv2.COLOR_RGB2BGR)
        if self.cap is not None:
            ok, frame = self.cap.read()
            return frame if ok else None
        return None

    def close(self):
        if self.picam2 is not None:
            self.picam2.stop()
        if self.cap is not None:
            self.cap.release()
