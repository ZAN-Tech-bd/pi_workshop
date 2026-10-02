#!/usr/bin/env python3
"""Module 8 — RC Color Pilot dashboard (port 8081).

Zero-dependency (Python stdlib + OpenCV), same pattern as the Pi Camera
Dashboard (8000) and Arm Twin (8080): one HTTP server, an MJPEG stream,
and an interactive page.

  http://raspberrypi.local:8081/

    /                 dashboard (live video + teleop + policy)
    /stream           MJPEG video (annotated: what the policy sees)
    /snapshot.jpg     latest annotated frame
    /api/status       JSON: camera, serial, mode, color, direction, events
    /api/cmd?k=F      send one RC-101 key (F B L R G I H J S 1-9 q)
    /api/mode?m=auto  auto = vision drives, manual = dashboard buttons
    /api/speed?n=5    set cruise speed (digit key 1-9)
    /shutdown (POST)  stop the server

Run:  python3 server.py [--port 8081]
"""

import argparse
import json
import os
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import cv2

HERE = os.path.dirname(os.path.abspath(__file__))
# import paths: works in the repo layout AND in a flat deploy
# (~/Desktop/rc-dashboard, installed by install.sh with local copies)
sys.path.insert(0, os.path.join(HERE, "..", "..", "04_opencv"))
sys.path.insert(0, os.path.join(HERE, ".."))
sys.path.insert(0, HERE)
from camera import Camera                 # noqa: E402
from vision_drive import DIRECTIONS, STABLE_FRAMES, SerialLink, annotate, classify  # noqa: E402

STATE = {
    "mode": "auto", "color": None, "direction": None, "cmd": None,
    "streak": 0, "fps": 0.0, "serial_ok": False, "serial_port": None,
    "camera": "?", "events": [], "started": time.strftime("%H:%M:%S"),
}
LOCK = threading.RLock()   # reentrant: handlers may log_event while holding it
JPEG = {"bytes": None, "n": 0}

VALID_KEYS = set("FBLRGHIJSq123456789")


def log_event(msg):
    with LOCK:
        STATE["events"] = ([time.strftime("%H:%M:%S") + "  " + msg]
                           + STATE["events"])[:12]


def link_send(link, key):
    if link and link.ser:
        link.cmd(key)
        STATE["cmd"] = key
        log_event(f"TX {key}")


def vision_loop(link):
    try:
        cam = Camera()
    except SystemExit as e:
        log_event(f"camera: {e}")
        return
    with LOCK:
        STATE["camera"] = cam.name
    log_event("camera up: " + cam.name)

    streak_color, streak, last_sent, frames, t0 = None, 0, None, 0, time.time()
    while True:
        frame = cam.read()
        if frame is None:
            time.sleep(0.2)
            continue
        color, center, area = classify(frame)
        streak = streak + 1 if color == streak_color else 0
        streak_color = color

        with LOCK:
            STATE["color"] = color
            STATE["direction"] = DIRECTIONS[color][1] if color else None
            STATE["streak"] = streak

            if STATE["mode"] == "auto" and streak >= STABLE_FRAMES:
                cmd = DIRECTIONS[color][0] if color else "S"
                if cmd != last_sent:
                    link_send(link, cmd)
                    log_event(f"policy: {color or 'nothing'} -> {cmd}")
                    last_sent = cmd

        ok, buf = cv2.imencode(".jpg", annotate(frame, color, center),
                               [cv2.IMWRITE_JPEG_QUALITY, 70])
        if ok:
            with LOCK:
                JPEG["bytes"] = buf.tobytes()
                JPEG["n"] += 1

        frames += 1
        now = time.time()
        if now - t0 >= 2:
            with LOCK:
                STATE["fps"] = round(frames / (now - t0), 1)
            frames, t0 = 0, now
        time.sleep(0.05)


class Handler(BaseHTTPRequestHandler):
    def _json(self, obj, code=200):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = self.path.split("?")[0]
        qs = dict(p.split("=", 1) for p in self.path.split("?")[1].split("&")
                  if "=" in p) if "?" in self.path else {}

        if path == "/" or path == "/index.html":
            with open(os.path.join(HERE, "index.html"), "rb") as f:
                body = f.read()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        elif path == "/stream":
            self.send_response(200)
            self.send_header("Content-Type",
                             "multipart/x-mixed-replace; boundary=frame")
            self.end_headers()
            seen = 0
            try:
                while True:
                    with LOCK:
                        data, n = JPEG["bytes"], JPEG["n"]
                    if data and n != seen:
                        seen = n
                        self.wfile.write(
                            b"--frame\r\nContent-Type: image/jpeg\r\n\r\n"
                            + data + b"\r\n")
                    time.sleep(0.08)
            except (BrokenPipeError, ConnectionResetError):
                return

        elif path == "/snapshot.jpg":
            with LOCK:
                data = JPEG["bytes"]
            if data is None:
                self._json({"error": "no frame yet"}, 503)
                return
            self.send_response(200)
            self.send_header("Content-Type", "image/jpeg")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        elif path == "/api/status":
            with LOCK:
                self._json(dict(STATE, events=list(STATE["events"])))

        elif path == "/api/cmd":
            k = qs.get("k", "")
            if k not in VALID_KEYS:
                self._json({"ok": False, "error": "bad key"}, 400)
                return
            with LOCK:
                if STATE["mode"] == "manual":
                    link_send(LINK[0], k)
                    self._json({"ok": True, "sent": k})
                else:
                    self._json({"ok": False,
                                "error": "switch to manual mode first"}, 409)

        elif path == "/api/mode":
            m = qs.get("m", "")
            if m not in ("auto", "manual"):
                self._json({"ok": False, "error": "auto|manual"}, 400)
                return
            with LOCK:
                STATE["mode"] = m
            log_event("mode -> " + m)
            self._json({"ok": True, "mode": m})

        elif path == "/api/speed":
            n = qs.get("n", "")
            if n in VALID_KEYS:
                link_send(LINK[0], n)
                log_event("cruise key " + n)
                self._json({"ok": True})
            else:
                self._json({"ok": False, "error": "1-9 or q"}, 400)
        else:
            self._json({"error": "not found"}, 404)

    def do_POST(self):
        if self.path.split("?")[0] == "/shutdown":
            log_event("shutdown requested")
            self._json({"ok": True})
            threading.Thread(target=lambda: (time.sleep(0.5), os._exit(0)),
                             daemon=True).start()
        else:
            self._json({"error": "not found"}, 404)

    def log_message(self, *a):
        pass


LINK = [None]

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8081)
    args = parser.parse_args()

    try:
        link = SerialLink()
        ok = link.ping()
        LINK[0] = link
        with LOCK:
            STATE["serial_ok"] = ok
            STATE["serial_port"] = getattr(link.ser, "port", None)
        log_event("serial: " + ("link OK" if ok else "no reply to PING"))
    except SystemExit:
        log_event("serial: not found — dashboard runs vision-only (dry)")
        with LOCK:
            STATE["serial_ok"] = False

    threading.Thread(target=vision_loop, args=(LINK[0],), daemon=True).start()

    srv = ThreadingHTTPServer(("0.0.0.0", args.port), Handler)
    print(f"RC Color Pilot dashboard: http://0.0.0.0:{args.port}/")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
