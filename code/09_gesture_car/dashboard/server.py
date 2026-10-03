#!/usr/bin/env python3
"""Module 9 — Gesture Pilot dashboard (port 8083): your hand drives the car.

The RC Color Pilot's sense–think–act loop, one step up: the camera finds a
HAND (MediaPipe, 21 landmarks), the brain names the gesture (readable rules,
or nearest neighbours over examples you recorded), the policy maps gesture ->
car function, and the ZAN TriBot drives.

    camera -> MediaPipe Hands -> 21 landmarks -> gesture (rules / taught examples)
      -> hold N frames -> policy (gesture -> action) -> Bluetooth -> car

Everything is editable on the page while the car runs: add a gesture (a
built-in rule, or teach your own by showing it), rename it, change what it
does, re-record or delete its examples, delete it. Saved in data/gestures.json.

  http://raspberrypi.local:8083/

    GET  /                              the dashboard
    GET  /stream · /snapshot.jpg        camera with the hand skeleton drawn in
    GET  /api/status                    hand, finger states, every gesture's score,
                                        the verdict, what goes to the car, link, events
    GET  /api/config                    gestures + rules (examples summarized)
    POST /api/config                    replace (validated; stored examples are kept)
    POST /api/config/reset              back to the starter gestures
    GET  /api/examples?id=…             one taught gesture's examples (for drawing)
    POST /api/record   {"id", "count"}  record examples from the next frames with a hand
    POST /api/examples/delete {"id", "index"|"all"}
    GET  /api/export · POST /api/import gesture library as JSON, examples included
    POST /api/output   {"on": true}     act for real (off = dry run)
    POST /api/mode     {"mode": "auto"} auto = gestures drive, manual = the D-pad
    POST /api/drive    {"key": "F"}     hold a key in manual mode (renew every ~250 ms)
    POST /api/speed    {"n": "5"}       1-9 or "q" (turbo)
    POST /api/source   {"source": "camera"|"demo"}
    POST /api/car      {"take": true}   take the car from the Color Pilot (:8081) / give it back
    POST /api/serial   {"port": "auto"|MAC|"/dev/ttyUSB1"|null}

Run:  .venv/bin/python server.py [--port 8083] [--source demo] [--serial auto]
"""

import argparse
import copy
import gzip
import json
import math
import os
import re
import sys
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

os.environ.setdefault("GLOG_minloglevel", "2")          # MediaPipe: keep the journal readable
os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "2")

import cv2                                               # noqa: E402
import numpy as np                                       # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import gestures as G                                     # noqa: E402
from carlink import MAC_RE, CarLink                      # noqa: E402

STATIC = os.path.realpath(os.path.join(HERE, "static"))
DATA = os.path.join(HERE, "data")
CONFIG_PATH = os.path.join(DATA, "gestures.json")
CAR_MAC_PATH = os.path.join(DATA, "car_bt.json")
RC_MAC_PATH = os.path.expanduser("~/Desktop/rc-dashboard/data/car_bt.json")
CAMERA_URL = os.environ.get("CAMERA_URL", "http://127.0.0.1:8000/stream")   # no params: never restarts the camera
RC_URL = "http://127.0.0.1:8081"                         # the Color Pilot: it shares the one car

W, H = 640, 480
STALE_S = 1.0           # no analysed frame for this long -> the car is told to stop
IDLE_FPS = 3            # nobody watching and output off: look less often (be kind to :8081)


def hhmmss():
    return time.strftime("%H:%M:%S")


# --------------------------------------------------------------------------- picture sources

class Relay(threading.Thread):
    """Reads the camera-dashboard's MJPEG stream and keeps only the newest JPEG.

    No decoding here: the engine decodes the one frame it actually uses, so a
    30 fps camera costs nothing extra when MediaPipe runs at 15.
    """

    def __init__(self, url):
        super().__init__(daemon=True, name="relay")
        self.url = url
        self.lock = threading.Lock()
        self.cond = threading.Condition(self.lock)       # wakes the workers and /stream on each frame
        self.jpg, self.seq, self.t = None, 0, 0.0
        self.error, self.name = None, "starting…"
        self.active = True

    def rate(self):
        """Frames per second arriving from the camera (= the video on the page)."""
        now = time.time()
        self.stamps = [t for t in getattr(self, "stamps", []) if now - t < 2]
        return len(self.stamps) / 2

    def run(self):
        while True:
            if not self.active:
                time.sleep(0.3)
                continue
            try:
                with urllib.request.urlopen(self.url, timeout=5) as r:
                    self.error, self.name = None, f"Pi camera via :8000 relay"
                    buf = b""
                    while self.active:
                        chunk = r.read1(65536) if hasattr(r, "read1") else r.read(16384)
                        if not chunk:
                            raise OSError("stream ended")
                        buf += chunk
                        while True:                  # pull out every complete JPEG
                            a = buf.find(b"\xff\xd8")
                            b = buf.find(b"\xff\xd9", a + 2) if a >= 0 else -1
                            if a < 0 or b < 0:
                                buf = buf[a:] if a >= 0 else buf[-1:]
                                break
                            with self.cond:
                                self.jpg, self.t = buf[a:b + 2], time.time()
                                self.seq += 1
                                self.stamps = getattr(self, "stamps", [])[-90:] + [self.t]
                                self.cond.notify_all()
                            buf = buf[b + 2:]
                        if len(buf) > 4_000_000:
                            buf = b""
            except Exception as e:  # noqa: BLE001
                self.error = f"camera relay {self.url}: {e.__class__.__name__}"
                self.name = "no camera"
                time.sleep(2)


class Demo:
    """Plays the labelled fixture hands (MediaPipe test images) as if seen live —
    the whole loop works with no camera and no hand. Landmarks skip MediaPipe."""

    PERIOD = 2.6

    def __init__(self):
        hands = G.load_fixture()
        order = ["thumb_up", "point_left", "point_right", "thumb_down", "victory", "open_palm", "fist", None, "point_up"]
        self.seq = []
        for want in order:
            d = next((h for h in hands if h["truth"] == want and h["rot"] in (0, 90, -90, 180)), None)
            self.seq.append(d)

    def current(self, t):
        k = int(t // self.PERIOD) % len(self.seq)
        return self.seq[k], (t % self.PERIOD) / self.PERIOD

    def picture(self, d, phase):
        img = np.full((H, W, 3), (74, 49, 38), np.uint8)          # slate, like the page
        cv2.putText(img, "DEMO: recorded test hands, no camera", (16, H - 18),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (150, 150, 150), 1, cv2.LINE_AA)
        if d is None or phase > 0.88:
            return img, None
        lm = np.array(d["lm"], float)
        # fit the hand into the frame, slight sway so it looks alive
        p = lm[:, :2] * [d["w"], d["h"]]
        lo, hi = p.min(0), p.max(0)
        s = 300 / max(hi - lo)
        c = (lo + hi) / 2
        q = (p - c) * s + [W / 2 + 40 * math.sin(phase * 6.28), H / 2 - 10]
        out = np.column_stack([q[:, 0] / W, q[:, 1] / H, lm[:, 2] * s * d["w"] / W])
        return img, out


# --------------------------------------------------------------------------- hub (shared state)

class Hub:
    def __init__(self):
        self.lock = threading.RLock()
        self.frames = threading.Condition(threading.Lock())
        try:
            with open(CONFIG_PATH) as f:
                self.cfg = G.clean_config(json.load(f))
        except (OSError, ValueError):
            self.cfg = G.default_config()
        self.dirty = False
        self.mode, self.output, self.speed = "auto", False, "5"
        self.source = "camera"
        self.hand, self.result = None, None              # last Hand + classify() result
        self.winner, self.active, self.activation = None, None, 0
        self.streak_id, self.streak = None, 0
        self.frame_t = 0.0                               # when the last frame was analysed
        self.fps, self.proc_ms = 0.0, 0.0
        self.held, self.held_until = None, 0.0
        self.would, self.last_sent, self.last_sent_t = None, None, 0.0
        self.recording = None                            # {"id", "want", "got", "until"}
        self.events = []
        self.jpg, self.jpg_n = None, 0                   # demo pictures for /stream
        self.live = threading.Condition()                # /api/live: one push per analysed frame
        self.live_n = 0
        self.last_frame = None                           # newest analysed picture (display space)
        self.viewers, self.seen_t = 0, 0.0               # page polls + stream clients
        self.rc = {"up": False}
        self.started = hhmmss()

    def log(self, text, tag="info"):
        with self.lock:
            self.events = [{"t": hhmmss(), "text": text, "tag": tag}] + self.events[:39]

    def gesture(self, gid):
        return next((g for g in self.cfg["gestures"] if g["id"] == gid), None)

    def set_config(self, cfg):
        with self.lock:
            self.cfg = G.clean_config(cfg, old=self.cfg)
            if self.active and not self.gesture(self.active):
                self.active = None
            self.dirty = True
            return self.cfg

    def watched(self):
        return self.viewers > 0 or time.time() - self.seen_t < 5


# --------------------------------------------------------------------------- think: the engine

class Engine:
    """Newest frame -> MediaPipe -> Hand -> classify -> hold -> active gesture.

    MediaPipe takes ~60-120 ms a frame on a Pi 4 core, so `workers` threads
    (each with its own detector) take turns on the newest frames: two run at
    ~1.9x the rate of one. MediaPipe releases the GIL, so they really run in
    parallel. Results are applied in frame order; a frame that finishes after
    a newer one is dropped. The video the page shows does NOT wait for any of
    this: /stream passes the camera's own JPEGs straight through.
    """

    MAX_WORKERS = 2

    def __init__(self, hub, relay, demo):
        self.hub, self.relay, self.demo = hub, relay, demo
        self.lock = threading.Lock()
        self.claimed = 0                                 # newest relay frame a worker has taken
        self.last_src, self.last_done = None, -1
        self.ready = threading.Event()
        self.error = None
        self.n, self.t0 = 0, time.time()
        self.mp = None
        self.mp_lock = threading.Lock()

    def start(self):
        for i in range(self.MAX_WORKERS):
            Worker(self, i).start()

    def mediapipe(self):
        with self.mp_lock:                               # slow import, once, only when a camera is used
            if self.mp is None:
                import mediapipe as mp
                self.mp = mp
        return self.mp

    def submit(self, seq, src, frame, lm, handed, t_start):
        hub = self.hub
        with self.lock:                                  # one result at a time, in frame order
            if src == self.last_src and seq <= self.last_done:
                return                                   # a newer frame already finished
            self.last_src, self.last_done = src, seq
            cfg = hub.cfg
            hand = G.Hand(lm, W, H, handed) if lm is not None else None
            result = G.classify(cfg, hand) if hand else None
            winner = result["winner"] if result else None
            self.think(hand, result, winner, cfg)
            hub.proc_ms = round((time.time() - t_start) * 1000, 1)
            hub.last_frame = frame
            self.n += 1
            if time.time() - self.t0 >= 1.5:
                hub.fps, self.n, self.t0 = round(self.n / (time.time() - self.t0), 1), 0, time.time()
        self.ready.set()
        if src == "demo" and hub.watched():              # the demo picture is drawn here; the camera's isn't
            ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
            if ok:
                with hub.frames:
                    hub.jpg, hub.jpg_n = buf.tobytes(), hub.jpg_n + 1
                    hub.frames.notify_all()
        with hub.live:
            hub.live_n += 1
            hub.live.notify_all()

    def think(self, hand, result, winner, cfg):
        hub = self.hub
        with hub.lock:
            if winner == hub.streak_id:
                hub.streak += 1
            else:
                hub.streak_id, hub.streak = winner, 1
            # starting an action needs `hold` frames; letting go needs only 2 (stopping should be quick)
            need = cfg["hold"] if winner else min(2, cfg["hold"])
            if hub.streak >= need and hub.active != winner:
                hub.active = winner
                hub.activation += 1
            hub.hand, hub.result, hub.winner, hub.frame_t = hand, result, winner, time.time()
            rec = hub.recording
            if rec:
                g = hub.gesture(rec["id"])
                if g is None or g["kind"] != "taught":
                    hub.recording = None
                elif hand is not None:
                    g["samples"].append(G.make_sample(hand, cfg["mirror"]))
                    g["samples"] = g["samples"][-G.MAX_SAMPLES:]
                    rec["got"] += 1
                    hub.dirty = True
                    if rec["got"] >= rec["want"]:
                        hub.recording = None
                        hub.log(f"Recorded {rec['got']} examples of “{g['name']}”")
                elif time.time() > rec["until"]:
                    hub.recording = None
                    hub.log(f"Recording stopped: no hand seen ({rec['got']} of {rec['want']} examples)", "warn")


class Worker(threading.Thread):
    def __init__(self, engine, idx):
        super().__init__(daemon=True, name=f"worker{idx}")
        self.engine, self.idx = engine, idx
        self.hands, self.model = None, None

    def detector(self, model):
        if self.hands is None or self.model != model:
            mp = self.engine.mediapipe()
            if self.hands:
                self.hands.close()
            self.hands = mp.solutions.hands.Hands(
                static_image_mode=False, max_num_hands=1, model_complexity=model,
                min_detection_confidence=0.6, min_tracking_confidence=0.5)
            self.model = model
        return self.hands

    def run(self):
        while True:
            try:
                self.loop()
            except Exception as e:  # noqa: BLE001 - keep the dashboard alive, say what broke
                self.engine.error = f"{e.__class__.__name__}: {e}"
                self.engine.hub.log(f"Engine error: {self.engine.error}", "warn")
                time.sleep(1)

    def loop(self):
        eng, hub, relay = self.engine, self.engine.hub, self.engine.relay
        demo_seq = 0
        while True:
            cfg = hub.cfg
            idle = not hub.watched() and not hub.output and not hub.recording
            on_duty = 1 if idle or hub.source == "demo" else cfg["workers"]
            if self.idx >= on_duty:                      # this worker is not needed right now
                time.sleep(0.2)
                continue
            if hub.source == "demo":
                time.sleep(1 / 15)
                t_start = time.time()
                d, phase = eng.demo.current(t_start)
                frame, lm = eng.demo.picture(d, phase)
                demo_seq += 1
                eng.submit(demo_seq, "demo", frame, lm, d["hand"] if d else None, t_start)
                continue
            with relay.cond:                             # claim the newest frame nobody has taken
                relay.cond.wait_for(lambda: relay.seq > eng.claimed, timeout=1.0)
                if relay.seq <= eng.claimed or relay.jpg is None:
                    continue
                jpg, seq = relay.jpg, relay.seq
                eng.claimed = seq
            t_start = time.time()
            frame = cv2.imdecode(np.frombuffer(jpg, np.uint8), cv2.IMREAD_COLOR)
            if frame is None:
                continue
            if frame.shape[1] != W or frame.shape[0] != H:
                frame = cv2.resize(frame, (W, H))
            if cfg["mirror"]:
                frame = cv2.flip(frame, 1)               # selfie view: your left is the screen's left
            res = self.detector(cfg["model"]).process(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
            lm, handed = None, None
            if res.multi_hand_landmarks:
                lm = [[p.x, p.y, p.z] for p in res.multi_hand_landmarks[0].landmark]
                handed = res.multi_handedness[0].classification[0].label
                if not cfg["mirror"]:                    # MediaPipe assumes a mirrored picture
                    handed = {"Left": "Right", "Right": "Left"}[handed]
            eng.submit(seq, "camera", frame, lm, handed, t_start)
            if idle:
                time.sleep(max(0.0, 1 / IDLE_FPS - (time.time() - t_start)))


def annotate(frame, hand, color):
    """The frame with the hand skeleton drawn in (only /snapshot.jpg needs this now)."""
    img = frame.copy()
    if hand is not None:
        col = G_bgr(color) if color else (235, 235, 235)
        pts = [(int(x * W), int(y * H)) for x, y, _ in hand.lm]
        for a, b in G.CONNECTIONS:
            cv2.line(img, pts[a], pts[b], (20, 20, 20), 6, cv2.LINE_AA)
            cv2.line(img, pts[a], pts[b], col, 3, cv2.LINE_AA)
        for i, p in enumerate(pts):
            r = 6 if i in (4, 8, 12, 16, 20) else 4
            cv2.circle(img, p, r, (255, 255, 255), -1, cv2.LINE_AA)
            cv2.circle(img, p, r, (20, 20, 20), 1, cv2.LINE_AA)
    return img


def G_bgr(h):
    return (int(h[5:7], 16), int(h[3:5], 16), int(h[1:3], 16))


# --------------------------------------------------------------------------- act: the driver

class Driver(threading.Thread):
    """Four times a second: decide what the car is told and, when output is on, send it.

    Drive keys are re-sent every tick (the TriBot has no fail-safe of its own:
    it keeps its last key). Speed actions fire ONCE when their gesture becomes
    active; while they are held the car is told S. No fresh frame for 1 s
    (camera gone, engine stuck) counts as "no gesture" -> S.
    """

    TICK = 0.25

    def __init__(self, hub, link):
        super().__init__(daemon=True, name="driver")
        self.hub, self.link = hub, link
        self.prev, self.was_on, self.sent_speed, self.fired = None, False, None, 0
        self.stalled = False

    def decide(self):
        hub = self.hub
        if hub.mode == "manual":
            if hub.held and time.time() < hub.held_until:
                return {"type": "key", "key": hub.held}, "you"
            return {"type": "key", "key": "S"}, "you"
        stale = time.time() - hub.frame_t > STALE_S
        if stale != self.stalled:
            self.stalled = stale
            hub.log("No fresh picture: the car is told to stop" if stale else "Picture back", "warn" if stale else "info")
        g = hub.gesture(hub.active) if hub.active and not stale else None
        if g and g["on"]:
            return g["action"], g["name"]
        return hub.cfg["nothing"], None

    def run(self):
        while True:
            try:
                self.loop()
            except Exception as e:  # noqa: BLE001
                self.hub.log(f"Output error: {e}", "warn")
                time.sleep(1)

    def loop(self):
        hub = self.hub
        while True:
            time.sleep(self.TICK)
            with hub.lock:
                action, why = self.decide()
                if action["type"] in ("speed", "step") and hub.activation != self.fired and why not in (None, "you"):
                    self.fired = hub.activation
                    i = G.SPEEDS.index(hub.speed)
                    hub.speed = action["n"] if action["type"] == "speed" else \
                        G.SPEEDS[max(0, min(len(G.SPEEDS) - 1, i + action["d"]))]
                    hub.log(f"{why} → {G.describe(action)}: speed {hub.speed.replace('q', 'turbo')}",
                            "sent" if hub.output and self.link.ready() else "dry")
                key = action["key"] if action["type"] == "key" else "S"
                output = hub.output
                hub.would = G.describe({"type": "key", "key": key}) if action["type"] != "key" else G.describe(action)
                ident = (key, why, output)
                speed = hub.speed
            link_ok = self.link.ready()
            if output and link_ok and self.sent_speed != speed:
                if self.link.write(speed.encode()):
                    self.sent_speed = speed
            if not link_ok:
                self.sent_speed = None
            sent = False
            if output and link_ok:
                sent = self.link.write(key.encode())
                if sent:
                    with hub.lock:
                        hub.last_sent, hub.last_sent_t = G.describe({"type": "key", "key": key}), time.time()
            if self.was_on and not output and link_ok:
                self.link.write(b"S")                        # output switched off: stop now
            self.was_on = output
            if ident != self.prev:
                self.prev = ident
                who = "Manual" if why == "you" else (why or "No gesture")
                note = "" if sent or not output else " (no car connected)"
                hub.log(f"{who} → {G.describe({'type': 'key', 'key': key})}{note}", "sent" if sent else "dry")


# --------------------------------------------------------------------------- sharing the car with :8081

class Handover(threading.Thread):
    """Watches the Color Pilot (:8081). The ESP32 takes one Bluetooth client, so
    "take the car" = ask :8081 to release it, then connect; "give it back" =
    release ours, then ask :8081 to look for the car again."""

    def __init__(self, hub, link):
        super().__init__(daemon=True, name="handover")
        self.hub, self.link = hub, link

    @staticmethod
    def rc(path, body=None, timeout=2.0):
        req = urllib.request.Request(RC_URL + path, data=None if body is None else json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json"},
                                     method="GET" if body is None else "POST")
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.load(r)

    def run(self):
        while True:
            try:
                st = self.rc("/api/status", timeout=1.5)
                L = st.get("link", {})
                self.hub.rc = {"up": True, "state": L.get("state"), "want": L.get("want"), "port": L.get("port"),
                               "output": st.get("output")}
            except Exception:  # noqa: BLE001
                self.hub.rc = {"up": False}
            time.sleep(3)

    def take(self):
        if self.hub.rc.get("up") and self.hub.rc.get("want"):
            try:
                self.rc("/api/serial", {"port": None})
                self.hub.log("Asked the Color Pilot (:8081) to release the car")
                time.sleep(1.0)                          # let the ESP32 drop that connection
            except Exception as e:  # noqa: BLE001
                self.hub.log(f"Could not reach the Color Pilot: {e.__class__.__name__}", "warn")
        self.link.request("auto")
        self.hub.log("Looking for the car (ZAN_RC_Car)…")

    def give(self):
        self.link.request(None)
        self.hub.log("Car released")
        if self.hub.rc.get("up"):
            try:
                self.rc("/api/serial", {"port": "auto"})
                self.hub.log("Handed the car back to the Color Pilot (:8081)")
            except Exception as e:  # noqa: BLE001
                self.hub.log(f"Could not reach the Color Pilot: {e.__class__.__name__}", "warn")


def saver(hub):
    while True:
        time.sleep(1.0)
        with hub.lock:
            if not hub.dirty or hub.recording:
                continue
            cfg, hub.dirty = copy.deepcopy(hub.cfg), False
        try:
            os.makedirs(DATA, exist_ok=True)
            tmp = CONFIG_PATH + ".tmp"
            with open(tmp, "w") as f:
                json.dump(cfg, f, separators=(",", ":"))
            os.replace(tmp, CONFIG_PATH)
        except OSError as e:
            hub.log(f"Could not save the gestures: {e}", "warn")


# --------------------------------------------------------------------------- HTTP

MIME = {".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8",
        ".css": "text/css; charset=utf-8", ".svg": "image/svg+xml", ".woff2": "font/woff2",
        ".png": "image/png", ".json": "application/json"}
_gz = {}


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    hub = link = engine = relay = handover = None

    def log_message(self, *a):
        pass

    def send_body(self, code, body, ctype, extra=None):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def json(self, obj, code=200, extra=None):
        self.send_body(code, json.dumps(obj).encode(), "application/json", {"Cache-Control": "no-store", **(extra or {})})

    def body(self, limit=256 * 1024):
        n = int(self.headers.get("Content-Length") or 0)
        if n > limit:
            raise ValueError("too large")
        d = json.loads(self.rfile.read(n) or b"{}") if n else {}
        if not isinstance(d, dict):
            raise ValueError("expected a JSON object")
        return d

    def static(self, rel):
        full = os.path.join(HERE, "index.html") if rel == "index.html" else os.path.realpath(os.path.join(STATIC, rel))
        if rel != "index.html" and (not full.startswith(STATIC + os.sep) or not os.path.isfile(full)):
            return self.json({"error": "not found"}, 404)
        st = os.stat(full)
        etag = f'"{st.st_mtime_ns:x}-{st.st_size:x}"'
        if self.headers.get("If-None-Match") == etag:
            self.send_response(304)
            self.send_header("ETag", etag)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        with open(full, "rb") as f:
            data = f.read()
        ext = os.path.splitext(full)[1]
        extra = {"ETag": etag, "Cache-Control": "public, max-age=86400" if rel.startswith("fonts/") else "no-cache"}
        if ext in (".html", ".js", ".css", ".svg") and "gzip" in (self.headers.get("Accept-Encoding") or ""):
            if _gz.get(full, (None,))[0] != etag:
                _gz[full] = (etag, gzip.compress(data, 6))
            data = _gz[full][1]
            extra["Content-Encoding"] = "gzip"
        self.send_body(200, data, MIME.get(ext, "application/octet-stream"), extra)

    def stream(self):
        """MJPEG to the page. Camera: the relay's own JPEGs, untouched, at the
        camera's full rate (the page mirrors them and draws the skeleton on top).
        Demo: the pictures the engine draws."""
        hub, relay = self.hub, self.relay
        self.send_response(200)
        self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=frame")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "close")
        self.end_headers()
        self.close_connection = True
        with hub.frames:
            hub.viewers += 1
        seen_cam, seen_demo = -1, -1
        try:
            while True:
                if hub.source == "camera":
                    with relay.cond:
                        relay.cond.wait_for(lambda: relay.seq != seen_cam, timeout=2)
                        data, seen_cam = relay.jpg, relay.seq
                else:
                    with hub.frames:
                        hub.frames.wait_for(lambda: hub.jpg_n != seen_demo, timeout=2)
                        data, seen_demo = hub.jpg, hub.jpg_n
                if data:
                    self.wfile.write(b"--frame\r\nContent-Type: image/jpeg\r\nContent-Length: " +
                                     str(len(data)).encode() + b"\r\n\r\n" + data + b"\r\n")
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass
        finally:
            with hub.frames:
                hub.viewers -= 1

    def live_state(self):
        """The fast-changing part of the status: one push per analysed frame."""
        hub = self.hub
        with hub.lock:
            res = hub.result
            g = hub.gesture(hub.winner) if hub.winner else None
            return {"hand": hub.hand.summary() if hub.hand else None,
                    "scores": res["scores"] if res else {}, "why": res["why"] if res else None,
                    "nearest": res["nearest"] if res else None,
                    "winner": hub.winner, "active": hub.active, "hold": hub.cfg["hold"],
                    "streak": hub.streak if hub.streak_id == hub.winner else 0,
                    "stale": time.time() - hub.frame_t > STALE_S, "fps": hub.fps, "proc_ms": hub.proc_ms,
                    "recording": dict(hub.recording) if hub.recording else None,
                    "would": hub.would, "color": g["color"] if g else None}

    def live(self):
        """Server-Sent Events: the page redraws the skeleton and the scores the
        moment a frame is analysed, instead of polling for them."""
        hub = self.hub
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "close")
        self.end_headers()
        self.close_connection = True
        with hub.frames:
            hub.viewers += 1
        seen = -1
        try:
            while True:
                with hub.live:
                    hub.live.wait_for(lambda: hub.live_n != seen, timeout=2)
                    fresh, seen = hub.live_n != seen, hub.live_n
                self.wfile.write(b"data: " + json.dumps(self.live_state()).encode() + b"\n\n" if fresh
                                 else b": keep-alive\n\n")
                self.wfile.flush()
                time.sleep(0.02)                         # at most ~50 pushes a second
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass
        finally:
            with hub.frames:
                hub.viewers -= 1

    def status(self):
        hub, link, relay = self.hub, self.link, self.relay
        hub.seen_t = time.time()
        with hub.lock:
            res = hub.result
            st = {
                "mode": hub.mode, "output": hub.output, "speed": hub.speed,
                "hand": hub.hand.summary() if hub.hand else None,
                "scores": res["scores"] if res else {}, "why": res["why"] if res else None,
                "nearest": res["nearest"] if res else None,
                "winner": hub.winner, "active": hub.active, "hold": hub.cfg["hold"],
                "streak": hub.streak if hub.streak_id == hub.winner else 0,
                "would": hub.would, "last_sent": hub.last_sent,
                "held": hub.held if time.time() < hub.held_until else None,
                "fps": hub.fps, "proc_ms": hub.proc_ms, "stale": time.time() - hub.frame_t > STALE_S,
                "camera_fps": round(self.relay.rate(), 1) if hub.source == "camera" else None,
                "recording": dict(hub.recording) if hub.recording else None,
                "source": {"kind": hub.source, "name": "Demo hands" if hub.source == "demo" else relay.name,
                           "error": None if hub.source == "demo" else (relay.error or self.engine.error),
                           "loading": hub.source == "camera" and not self.engine.ready.is_set()},
                "link": {"state": link.state, "detail": link.detail, "port": link.port, "want": link.want},
                "rc": hub.rc, "events": hub.events[:14], "started": hub.started,
                "examples": {g["id"]: len(g["samples"]) for g in hub.cfg["gestures"] if g["kind"] == "taught"},
            }
        return st

    def do_GET(self):
        url = urlparse(self.path)
        q, path = parse_qs(url.query), url.path
        hub = self.hub
        if path in ("/", "/index.html"):
            return self.static("index.html")
        if path.startswith("/static/"):
            return self.static(path[len("/static/"):])
        if path == "/stream":
            return self.stream()
        if path == "/api/live":
            return self.live()
        if path == "/snapshot.jpg":
            hub.seen_t = time.time()
            with hub.live:
                n0 = hub.live_n
                hub.live.wait_for(lambda: hub.live_n != n0, timeout=2.5)   # a frame analysed after this request
            with hub.lock:
                frame, hand = hub.last_frame, hub.hand
                g = hub.gesture(hub.winner) if hub.winner else None
            if frame is None:
                return self.json({"error": "no frame yet"}, 503)
            ok, buf = cv2.imencode(".jpg", annotate(frame, hand, g["color"] if g else None), [cv2.IMWRITE_JPEG_QUALITY, 80])
            return self.send_body(200, buf.tobytes(), "image/jpeg", {"Cache-Control": "no-store"})
        if path == "/api/status":
            return self.json(self.status())
        if path == "/api/config":
            with hub.lock:
                return self.json(G.public_config(hub.cfg))
        if path == "/api/builtins":
            return self.json([{"rule": k, "name": n, "emoji": e} for k, (n, e, _r) in G.BUILTINS.items()])
        if path == "/api/examples":
            with hub.lock:
                g = hub.gesture(q.get("id", [""])[0])
                if not g or g["kind"] != "taught":
                    return self.json({"error": "no such taught gesture"}, 404)
                ex = []
                for s in g["samples"]:
                    f, hand = G.sample_feat(s, hub.cfg["mirror"])
                    ex.append({"hand": hand, "norm": [[round(float(x), 3), round(float(y), 3)] for x, y, _ in f]})
            return self.json({"id": g["id"], "examples": ex})
        if path == "/api/export":
            with hub.lock:
                body = json.dumps({"gesture_pilot": 1, "config": hub.cfg}, indent=1).encode()
            return self.send_body(200, body, "application/json",
                                  {"Content-Disposition": 'attachment; filename="gestures.json"', "Cache-Control": "no-store"})
        return self.json({"error": "not found"}, 404)

    def do_POST(self):
        path = urlparse(self.path).path
        hub = self.hub
        try:
            b = self.body(limit=4 * 1024 * 1024 if path == "/api/import" else 256 * 1024)
        except ValueError as e:
            return self.json({"ok": False, "error": f"bad request: {e}"}, 400)
        if path == "/api/config":
            cfg = hub.set_config(b.get("config", b))
            return self.json({"ok": True, "config": G.public_config(cfg)})
        if path == "/api/config/reset":
            with hub.lock:
                hub.recording = None
                hub.cfg, hub.active, hub.dirty = G.default_config(), None, True
            hub.log("Gestures reset to the starter set")
            return self.json({"ok": True, "config": G.public_config(hub.cfg)})
        if path == "/api/import":
            cfg = b.get("config")
            if not isinstance(cfg, dict) or not isinstance(cfg.get("gestures"), list):
                return self.json({"ok": False, "error": "not a Gesture Pilot export"}, 400)
            with hub.lock:
                hub.recording = None
                hub.cfg, hub.active, hub.dirty = G.clean_config(cfg), None, True
            hub.log(f"Imported {len(hub.cfg['gestures'])} gestures")
            return self.json({"ok": True, "config": G.public_config(hub.cfg)})
        if path == "/api/record":
            with hub.lock:
                g = hub.gesture(b.get("id"))
                if not g or g["kind"] != "taught":
                    return self.json({"ok": False, "error": "pick a taught gesture first"}, 400)
                want = int(G._num(b.get("count"), 1, 40, 20, int))
                if b.get("replace"):
                    g["samples"] = []
                hub.recording = {"id": g["id"], "want": want, "got": 0, "until": time.time() + 15}
            hub.log(f"Recording “{g['name']}”: hold the gesture in view")
            return self.json({"ok": True})
        if path == "/api/record/cancel":
            with hub.lock:
                hub.recording = None
                hub.dirty = True
            return self.json({"ok": True})
        if path == "/api/examples/delete":
            with hub.lock:
                g = hub.gesture(b.get("id"))
                if not g or g["kind"] != "taught":
                    return self.json({"ok": False, "error": "no such taught gesture"}, 404)
                if b.get("all"):
                    g["samples"] = []
                elif isinstance(b.get("index"), int) and 0 <= b["index"] < len(g["samples"]):
                    g["samples"].pop(b["index"])
                else:
                    return self.json({"ok": False, "error": "index out of range"}, 400)
                hub.dirty = True
                n = len(g["samples"])
            return self.json({"ok": True, "examples": n})
        if path == "/api/output":
            with hub.lock:
                hub.output = bool(b.get("on"))
            hub.log("Output on — actions go to the car" if hub.output else "Output off — dry run")
            return self.json({"ok": True, "output": hub.output})
        if path == "/api/mode":
            m = b.get("mode")
            if m not in ("auto", "manual"):
                return self.json({"ok": False, "error": "mode is auto or manual"}, 400)
            with hub.lock:
                hub.mode, hub.held = m, None
            hub.log("Gestures drive" if m == "auto" else "You drive (D-pad)")
            return self.json({"ok": True, "mode": m})
        if path == "/api/speed":
            n = str(b.get("n"))
            if n not in G.SPEEDS:
                return self.json({"ok": False, "error": "speed is 1-9 or q"}, 400)
            with hub.lock:
                hub.speed = n
            return self.json({"ok": True, "speed": n})
        if path == "/api/drive":
            k = b.get("key")
            if k is not None and k not in G.KEYS:
                return self.json({"ok": False, "error": "key is one of F B L R G I H J S"}, 400)
            with hub.lock:
                if hub.mode != "manual":
                    return self.json({"ok": False, "error": "switch to “You drive” first"}, 409)
                hub.held, hub.held_until = k, time.time() + 0.6       # dead-man: renew while held
            return self.json({"ok": True})
        if path == "/api/source":
            kind = b.get("source")
            if kind not in ("camera", "demo"):
                return self.json({"ok": False, "error": "source is camera or demo"}, 400)
            hub.source = kind
            self.relay.active = kind == "camera"
            hub.log("Picture from the camera" if kind == "camera" else "Demo hands (no camera)")
            return self.json({"ok": True})
        if path == "/api/car":
            threading.Thread(target=self.handover.take if b.get("take") else self.handover.give, daemon=True).start()
            return self.json({"ok": True})
        if path == "/api/serial":
            want = b.get("port")
            if want is not None and want != "auto" and not (
                    re.fullmatch(r"/dev/tty(USB|ACM|rfcomm)\d+", str(want)) or MAC_RE.fullmatch(str(want))):
                return self.json({"ok": False, "error": "port is auto, a car MAC, /dev/ttyUSBn, /dev/ttyACMn or null"}, 400)
            self.link.request(want)
            hub.log("Car link released" if want is None else f"Looking for the car ({want})")
            return self.json({"ok": True})
        return self.json({"error": "not found"}, 404)


def main():
    ap = argparse.ArgumentParser(description="Gesture Pilot dashboard")
    ap.add_argument("--port", type=int, default=8083)
    ap.add_argument("--source", choices=("camera", "demo"), default="camera")
    ap.add_argument("--serial", default="none",
                    help="none (default: press 'Take the car' on the page), auto, a MAC, or /dev/ttyUSBn")
    args = ap.parse_args()

    hub = Hub()
    hub.source = args.source
    relay = Relay(CAMERA_URL)
    relay.active = args.source == "camera"
    link = CarLink(None if args.serial == "none" else args.serial, hub.log, mac_files=[CAR_MAC_PATH, RC_MAC_PATH])
    engine = Engine(hub, relay, Demo())
    handover = Handover(hub, link)
    Handler.hub, Handler.link, Handler.engine, Handler.relay, Handler.handover = hub, link, engine, relay, handover
    cv2.setNumThreads(1)
    for t in (relay, link, engine, Driver(hub, link), handover):
        t.start()                                        # engine.start() launches its workers
    threading.Thread(target=saver, args=(hub,), daemon=True).start()
    hub.log("Dashboard started — output is off until you switch it on")
    srv = ThreadingHTTPServer(("0.0.0.0", args.port), Handler)
    srv.daemon_threads = True
    print(f"Gesture Pilot dashboard: http://0.0.0.0:{args.port}/", flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        link.release()


if __name__ == "__main__":
    main()
