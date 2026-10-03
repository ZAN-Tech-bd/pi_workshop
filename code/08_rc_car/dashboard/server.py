#!/usr/bin/env python3
"""Module 8 — RC Color Pilot dashboard (port 8081): sense, think, act.

The sense–think–act loop with pixel-level color segmentation, live in a browser:

    camera frame -> HSV -> one mask per color class -> clean-up -> biggest blob
      -> policy (class -> action) -> hold N frames -> command to the Arduino

Everything the classifier and the policy use is editable from the page while the
car runs: the color classes (hue / saturation / value ranges), what each class
makes the car do, the smallest blob that counts, how many frames a color must
hold, and the clean-up passes. Settings live in data/vision.json next to this file.

  http://raspberrypi.local:8081/

    GET  /                          the dashboard
    GET  /stream?view=camera|mask   MJPEG: annotated camera / segmentation map
                                    (mask also takes &context=0|1 and &only=<class>)
    GET  /snapshot.jpg?view=...     one frame of either view
    GET  /api/status                live state: what each class sees, the verdict,
                                    what goes to the car, link, events
    GET  /api/config                classes + policy   POST: replace (validated)
    POST /api/config/reset          back to the six course colors
    GET  /api/sample?x=0.5&y=0.5    HSV of the picture at x, y (0..1)
    POST /api/output   {"on": true}         act for real (off = dry run)
    POST /api/mode     {"mode": "auto"}     auto = vision drives, manual = you do
    POST /api/drive    {"key": "F"}         hold a key in manual mode; renew every
                                            ~250 ms, {"key": null} releases
    POST /api/speed    {"n": 5}             cruise speed 1-9
    POST /api/source   {"source": "camera"|"testcard"}
    POST /api/serial   {"port": "auto"|MAC|"/dev/ttyUSB1"|null}  car via BT / release
    POST /api/car      {"take": true}      take the car (the Gesture Pilot :8083 lets go) / false = release
    POST /api/wake                          this page was opened: the other pilots sleep, this one
                                            takes the camera and the car (starts asleep)
    POST /api/sleep    {"by": "..."}        another pilot was opened: camera off, output off,
                                            car released -> {"had_car": bool}
    GET  /api/arm                           Arm Twin poses (for "move the arm" actions)
    GET  /api/cmd?k=F · /api/mode?m=auto · /api/speed?n=5     (kept from v1)

Run:  python3 server.py [--port 8081] [--source testcard]
"""

import argparse
import copy
import fcntl
import gzip
import json
import math
import os
import re
import socket
import subprocess
import sys
import termios
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

import cv2
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
# import paths: the repo layout AND the flat deploy (~/Desktop/rc-dashboard)
sys.path.insert(0, os.path.join(HERE, "..", "..", "04_opencv"))
sys.path.insert(0, os.path.join(HERE, ".."))
sys.path.insert(0, HERE)
from camera import Camera, camera_label, list_cameras          # noqa: E402
from color_track import RANGES                                 # noqa: E402
from vision_drive import DIRECTIONS, MIN_AREA, STABLE_FRAMES   # noqa: E402

try:
    import serial
except ImportError:
    serial = None

STATIC = os.path.realpath(os.path.join(HERE, "static"))
DATA = os.path.join(HERE, "data")
CONFIG_PATH = os.path.join(DATA, "vision.json")
CAMERA_PATH = os.path.join(DATA, "camera.json")   # the picked camera, kept across restarts
ARM_URL = "http://127.0.0.1:8080"          # the Arm Twin dashboard on this Pi
GESTURE_URL = "http://127.0.0.1:8083"      # the Gesture Pilot: it shares the one car
# one pilot at a time: opening this page puts these to sleep (and they do the same to us)
ME = "Zan Color-Car (:8081)"
SLEEP_PEERS = [("Zan Gesture-Car (:8083)", GESTURE_URL), ("ZAN Pilot (:8082)", "http://127.0.0.1:8082")]
IDLE_SLEEP_S = 120                         # nobody on the page this long, output off -> sleep
CAR_BT_NAME = "ZAN_RC_Car"                 # the ZAN TriBot (ESP32) on Bluetooth
CAR_BT_CHANNEL = 1                         # its SerialBT SPP listens here
CAR_MAC_PATH = os.path.join(DATA, "car_bt.json")     # its MAC, once discovered
MAC_RE = re.compile(r"[0-9A-Fa-f]{2}(?::[0-9A-Fa-f]{2}){5}")

W, H = 640, 480                            # the picture the dashboard works with
PW, PH = 320, 240                          # segmentation runs at half size: 4x fewer pixels
AREA_SCALE = (W / PW) * (H / PH)           # blob areas are reported in full-size pixels

KEYS = {"F": "forward", "B": "backward", "L": "left", "R": "right", "G": "front-left",
        "I": "front-right", "H": "back-left", "J": "back-right", "S": "stop"}
SWATCH = {"red": "#e23b4e", "blue": "#2f6df0", "green": "#2fae4e",
          "yellow": "#f2c418", "orange": "#ff8a2a", "purple": "#9b4dff"}


def hhmmss():
    return time.strftime("%H:%M:%S")


# --------------------------------------------------------------------------- config

def default_config():
    """The six course colors from color_track.RANGES + the vision_drive policy."""
    classes = []
    for name, (key, _word) in DIRECTIONS.items():
        ranges = RANGES[name]
        lo, hi = ranges[0]
        # red is stored as two ranges (0-10 and 170-179): one wrapped range 170 -> 10
        h = [ranges[-1][0][0], ranges[0][1][0]] if len(ranges) == 2 else [lo[0], hi[0]]
        classes.append({"id": name, "name": name.capitalize(), "h": h, "s": [lo[1], hi[1]],
                        "v": [lo[2], hi[2]], "color": SWATCH.get(name, "#888888"), "on": True,
                        "action": {"type": "key", "key": key}})
    return {"classes": classes, "min_area": MIN_AREA, "hold": STABLE_FRAMES, "cleanup": 2,
            "nothing": {"type": "key", "key": "S"}}


def _int(v, lo, hi, default):
    try:
        v = int(round(float(v)))
    except (TypeError, ValueError):
        return default
    return max(lo, min(hi, v))


def _pair(v, lo, hi, default, ordered=True):
    if not isinstance(v, (list, tuple)) or len(v) != 2:
        return list(default)
    a, b = _int(v[0], lo, hi, default[0]), _int(v[1], lo, hi, default[1])
    return [min(a, b), max(a, b)] if ordered else [a, b]


def clean_action(a):
    if not isinstance(a, dict):
        return {"type": "none"}
    t = a.get("type")
    if t == "key" and a.get("key") in KEYS:
        return {"type": "key", "key": a["key"]}
    if t == "line":
        text = str(a.get("text", "")).strip()[:40]
        if text and all(32 <= ord(ch) < 127 for ch in text):
            return {"type": "line", "text": text}
    if t == "arm" and isinstance(a.get("pose"), str) and re.fullmatch(r"[\w-]{1,40}", a["pose"]):
        return {"type": "arm", "pose": a["pose"], "name": str(a.get("name") or a["pose"])[:40]}
    return {"type": "none"}


def clean_config(cfg):
    if not isinstance(cfg, dict):
        return default_config()
    base = default_config()
    out = {"classes": [], "min_area": _int(cfg.get("min_area"), 20, 200000, base["min_area"]),
           "hold": _int(cfg.get("hold"), 1, 60, base["hold"]),
           "cleanup": _int(cfg.get("cleanup"), 0, 5, base["cleanup"]),
           "nothing": clean_action(cfg.get("nothing", base["nothing"]))}
    seen = set()
    for c in (cfg.get("classes") or [])[:10]:
        if not isinstance(c, dict):
            continue
        cid = c.get("id") if isinstance(c.get("id"), str) and re.fullmatch(r"[\w-]{1,24}", c["id"]) else None
        cid = cid or f"c{len(seen) + 1}"
        while cid in seen:
            cid += "_"
        seen.add(cid)
        color = c.get("color") if isinstance(c.get("color"), str) and re.fullmatch(r"#[0-9a-fA-F]{6}", c["color"]) else "#888888"
        out["classes"].append({
            "id": cid, "name": (str(c.get("name") or cid).strip() or cid)[:24],
            "h": _pair(c.get("h"), 0, 179, (0, 10), ordered=False),   # h0 > h1 wraps through red
            "s": _pair(c.get("s"), 0, 255, (80, 255)), "v": _pair(c.get("v"), 0, 255, (80, 255)),
            "color": color.lower(), "on": bool(c.get("on", True)), "action": clean_action(c.get("action")),
        })
    return out


def hex_bgr(h):
    return (int(h[5:7], 16), int(h[3:5], 16), int(h[1:3], 16))


def class_mask(hsv, c):
    (h0, h1), (s0, s1), (v0, v1) = c["h"], c["s"], c["v"]
    if h0 <= h1:
        return cv2.inRange(hsv, (h0, s0, v0), (h1, s1, v1))
    # the range runs through 179 -> 0 (red): two masks OR-ed, exactly like color_track.py
    return cv2.bitwise_or(cv2.inRange(hsv, (h0, s0, v0), (179, s1, v1)),
                          cv2.inRange(hsv, (0, s0, v0), (h1, s1, v1)))


# --------------------------------------------------------------------------- test card

CARD_BGR = {"red": (48, 40, 214), "blue": (214, 96, 36), "green": (72, 176, 58),
            "yellow": (40, 220, 230), "orange": (30, 130, 248), "purple": (196, 62, 150)}
_TC = {}


def testcard(t):
    """A synthetic scene: a hand-held card that changes color every few seconds,
    with tiny reference chips along the bottom that are too small to count."""
    if "bg" not in _TC:
        yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
        light = 205 - 40 * ((xx - W * 0.35) ** 2 + (yy - H * 0.3) ** 2) / (W * W)
        bg = np.dstack([light * 0.97, light, light * 1.02]).clip(0, 255).astype(np.uint8)
        rng = np.random.default_rng(7)
        _TC["bg"] = bg
        _TC["noise"] = [rng.normal(0, 3.5, (H, W, 3)).astype(np.int16) for _ in range(4)]
    img = _TC["bg"].copy()
    names = list(CARD_BGR)
    for i, n in enumerate(names):                     # 14x14 chips: area < any sensible minimum
        x = 22 + i * 26
        cv2.rectangle(img, (x, H - 36), (x + 14, H - 22), CARD_BGR[n], -1)
    period = 3.4
    k = int(t // period) % (len(names) + 1)           # the extra slot is an empty hand: "nothing"
    phase = (t % period) / period
    if k < len(names) and phase < 0.84:
        cx, cy = W * 0.5 + 150 * math.sin(t * 0.8), H * 0.47 + 60 * math.sin(t * 1.55)
        box = cv2.boxPoints(((cx, cy), (150, 190), 10 * math.sin(t * 0.7)))
        cv2.fillConvexPoly(img, (box + (6, 8)).astype(np.int32), (120, 120, 118))   # shadow
        cv2.fillConvexPoly(img, box.astype(np.int32), CARD_BGR[names[k]])
    noisy = img.astype(np.int16) + _TC["noise"][int(t * 15) % 4]
    return noisy.clip(0, 255).astype(np.uint8)


# --------------------------------------------------------------------------- frame source

class Source(threading.Thread):
    """Keeps only the newest frame, so the loop never works on stale video."""

    def __init__(self, kind, which=None):
        super().__init__(daemon=True, name="source")
        self.kind = kind
        self.which = which            # None = auto, "picam", "usb:/dev/videoN"
        self.reopen = threading.Event()
        self.lock = threading.Lock()
        self.frame, self.seq, self.name, self.error = None, 0, "starting…", None
        self.cam = None
        self.awake = threading.Event()  # cleared = asleep: the camera is closed

    def close_cam(self):
        if self.cam is not None:
            try:
                self.cam.close()
            except Exception:  # noqa: BLE001
                pass
            self.cam = None

    def request_camera(self, which):
        """Switch camera. Only flags it: the source loop itself closes and
        reopens its capture — releasing a cv2 cap while another thread reads
        it segfaults, so close_cam() must stay in the loop's own thread."""
        self.which = which
        self.kind = "camera"          # choosing a camera means using it
        self.reopen.set()

    def publish(self, frame, name):
        with self.lock:
            self.frame, self.name = frame, name
            self.seq += 1

    def run(self):
        misses = 0
        while True:
            if not self.awake.is_set():  # asleep: let go of the camera, decode nothing
                self.close_cam()
                with self.lock:
                    self.frame, self.name = None, "asleep"
                self.error = None
                self.awake.wait(1.0)
                continue
            if self.reopen.is_set():  # a new camera was picked: swap it over
                self.reopen.clear()
                self.close_cam()
                continue
            if self.kind == "testcard":
                self.close_cam()
                self.error = None
                self.publish(testcard(time.time()), "Test card")
                time.sleep(1 / 30)
                continue
            if self.cam is None:
                try:
                    self.cam = Camera(W, H, which=self.which)
                    self.error, misses = None, 0
                except BaseException as e:  # Camera() raises SystemExit when nothing works
                    self.error = str(e).splitlines()[0] if str(e) else "no camera"
                    with self.lock:
                        self.name = "no camera"
                    time.sleep(4)
                    continue
            cam, frame = self.cam, self.cam.read()
            if frame is None:
                misses += 1
                if misses > 60:                       # stream died: reopen it
                    self.close_cam()
                time.sleep(0.03)
                continue
            misses = 0
            if frame.shape[1] != W or frame.shape[0] != H:
                frame = cv2.resize(frame, (W, H))
            self.publish(frame, cam.name)


# --------------------------------------------------------------------------- car link

def port_holders(dev):
    real, me, found = os.path.realpath(dev), os.getpid(), []
    for pid in os.listdir("/proc"):
        if not pid.isdigit() or int(pid) == me:
            continue
        try:
            for fd in os.listdir(f"/proc/{pid}/fd"):
                if os.path.realpath(f"/proc/{pid}/fd/{fd}") == real:
                    with open(f"/proc/{pid}/cmdline", "rb") as f:
                        found.append(f.read().replace(b"\0", b" ").decode(errors="replace").strip())
                    break
        except OSError:
            pass
    return found


def bt_known_devices():
    """[(mac, name)] the Pi's Bluetooth stack already knows (paired or seen)."""
    try:
        out = subprocess.run(["bluetoothctl", "devices"], capture_output=True,
                             text=True, timeout=6).stdout
    except (OSError, subprocess.SubprocessError):
        return []
    return [(m.group(1), m.group(2).strip())
            for m in re.finditer(r"Device ([0-9A-F:]{17}) (.+)", out)]


def bt_inquiry(name, timeout=12):
    """Scan the air for `name`; returns its MAC or None. Slow — rate-limit it."""
    try:
        p = subprocess.run(["bluetoothctl", "--timeout", str(timeout), "scan", "on"],
                           capture_output=True, text=True, timeout=timeout + 8)
    except (OSError, subprocess.SubprocessError):
        return None
    for m in re.finditer(r"Device ([0-9A-F:]{17}) (.+)", p.stdout):
        if m.group(2).strip() == name:
            return m.group(1)
    return None


def bt_pair(mac):
    """Pair + trust, best effort — an already-paired device sails through."""
    script = f"agent on\ndefault-agent\npair {mac}\ntrust {mac}\n"
    try:
        subprocess.run(["bluetoothctl", "--timeout", "20"], input=script,
                       capture_output=True, text=True, timeout=26)
    except (OSError, subprocess.SubprocessError):
        pass


class BTSocket:
    """The slice of pyserial's API CarLink uses, over an RFCOMM socket.

    The ZAN TriBot is an ESP32: classic Bluetooth SPP on channel 1, no
    handshake — the link is "ready" the moment it connects.
    """

    def __init__(self, mac, channel=CAR_BT_CHANNEL):
        self.sock = socket.socket(socket.AF_BLUETOOTH, socket.SOCK_STREAM, socket.BTPROTO_RFCOMM)
        self.sock.settimeout(10)
        self.sock.connect((mac, channel))          # OSError when off / out of range
        self.sock.settimeout(0)                    # non-blocking from here on
        self.buf = b""

    def write(self, data):
        self.sock.send(data)                       # OSError = the car is gone

    @property
    def in_waiting(self):
        while True:
            try:
                chunk = self.sock.recv(4096)
            except (BlockingIOError, InterruptedError):
                return len(self.buf)
            if not chunk:
                raise OSError("Bluetooth link closed by the car")
            self.buf += chunk

    def read(self, n=1):
        out, self.buf = self.buf[:n], self.buf[n:]
        return out

    def close(self):
        try:
            self.sock.settimeout(2)               # let the RFCOMM DISC handshake
            self.sock.shutdown(socket.SHUT_RDWR)  # finish — an abrupt close leaves
        except OSError:                           # a half-open session and both
            pass                                  # the kernel and the car go
        try:                                      # "busy" for the next client
            self.sock.close()
        except OSError:
            pass


class CarLink(threading.Thread):
    """Drives the ZAN TriBot (ESP32 "ZAN_RC_Car") over Bluetooth.

    Same keys as always — F/B/L/R/G/I/H/J/S, 1-9 speed, q turbo — but this
    firmware has no handshake, so nothing is ever probed: the letters of
    "PING" are drive commands to it (I = front-right, G = front-left) and a
    probe would launch the car. "ready" simply means connected.

    "auto" looks for ZAN_RC_Car among known devices, then inquiries; the MAC
    is remembered in data/car_bt.json. A MAC or a /dev/tty* port can be
    forced via /api/serial (a tty is still skipped while another program —
    the Arm Twin — holds it).

    The car's push button swaps RC and line-follower mode; it announces the
    change on the link ("Mode: …") and those lines go to the event log. In
    line-follower mode the firmware ignores drive keys.

    The old 900 ms fail-safe is gone from the firmware: the Driver re-sends
    the current key every 250 ms and S goes out when output turns off or the
    link is released — but if the Pi or the link dies mid-drive, the car
    keeps its last command. Aim the car at open floor.
    """

    BAUD = 115200                              # only the USB fallback cares

    def __init__(self, want="auto", hub=None):
        super().__init__(daemon=True, name="carlink")
        self.hub = hub
        self.want = want
        self.ser, self.port, self.is_tty = None, None, False
        self.state = "searching" if want else "off"
        self.detail = ("Looking for ZAN_RC_Car over Bluetooth…" if want else
                       "Serial is off (--serial none): dry run")
        self.wlock = threading.Lock()
        self.next_scan, self.next_inquiry, self.next_pair = 0.0, 0.0, 0.0
        self.line = b""

    def ready(self):
        return self.ser is not None

    def release(self, detail="Released — the car link is free for other programs"):
        with self.wlock:
            if self.ser:
                try:
                    self.ser.write(b"S")
                    self.ser.close()
                except Exception:  # noqa: BLE001
                    pass
            self.ser, self.port, self.is_tty = None, None, False
        self.state, self.detail = "off", detail

    def request(self, want, wait=5.0, detail=None):
        """want: None (release), "auto", a MAC or a /dev/tty*. `wait` is the
        breather before connecting: the car re-opens its SPP server ~2 s after
        a client leaves, so a hand-off from the other dashboard needs it."""
        self.release(detail=detail or ("Reconnecting…" if want else "Released — the car is free for either dashboard"))
        self.want = want
        self.next_scan = time.time() + (wait if want else 0.0)
        self.next_inquiry = 0.0
        if want:
            self.state, self.detail = "searching", "Looking for ZAN_RC_Car over Bluetooth…"

    def write(self, data):
        with self.wlock:
            if not self.ser:
                return False
            try:
                self.ser.write(data)
                return True
            except Exception as e:  # noqa: BLE001
                port = self.port
                try:
                    self.ser.close()
                except Exception:  # noqa: BLE001
                    pass
                self.ser, self.port, self.is_tty = None, None, False
                self.state, self.detail = "searching", f"Lost {port} ({e.__class__.__name__}) — looking again…"
                self.next_scan = time.time() + 2
                return False

    def connect_bt(self, mac, notes):
        try:
            ser = BTSocket(mac)
        except OSError as e:
            if (mac, CAR_BT_NAME) not in bt_known_devices() and time.time() >= self.next_pair:
                # first contact: pair, retry next scan. Rate-limited: a pair
                # attempt holds the radio for up to 20 s, and hammering it
                # every scan starves the very connect it is meant to help
                self.next_pair = time.time() + 60
                bt_pair(mac)
                notes.append(f"{mac}: pairing ({e.__class__.__name__})")
            else:
                notes.append(f"{mac}: {e.__class__.__name__} — car off or out of range?")
            return False
        with self.wlock:
            self.ser, self.port, self.is_tty = ser, f"ZAN_RC_Car ({mac})", False
        self.state, self.detail = "ready", f"ZAN TriBot on Bluetooth {mac}"
        try:
            os.makedirs(DATA, exist_ok=True)
            with open(CAR_MAC_PATH, "w") as f:
                json.dump({"mac": mac}, f)
        except OSError:
            pass
        return True

    def connect_tty(self, dev, notes):
        if not serial:
            notes.append("pyserial is not installed (sudo apt install python3-serial)")
            return False
        if not os.path.exists(dev):
            notes.append(f"{dev} is not plugged in")
            return False
        holders = port_holders(dev)
        if holders:
            who = "the Arm Twin" if "arm-dashboard" in holders[0] else holders[0][:60]
            notes.append(f"{dev} is in use by {who}")
            return False
        try:
            ser = serial.Serial()
            ser.port, ser.baudrate, ser.timeout, ser.write_timeout = dev, self.BAUD, 0, 1
            ser.exclusive = True
            ser.open()
            try:
                fcntl.ioctl(ser.fileno(), termios.TIOCEXCL)
            except OSError:
                pass
        except Exception as e:  # noqa: BLE001
            notes.append(f"{dev}: {e}")
            return False
        with self.wlock:
            self.ser, self.port, self.is_tty = ser, dev, True
        self.state, self.detail = "ready", f"Car on serial port {dev}"
        return True

    def scan(self):
        notes = []
        want = str(self.want)
        if MAC_RE.fullmatch(want):
            self.connect_bt(want, notes)
        elif want.startswith("/dev/"):
            self.connect_tty(want, notes)
        else:                                       # auto: ZAN_RC_Car on Bluetooth
            mac = next((m for m, n in bt_known_devices() if n == CAR_BT_NAME), None)
            if not mac and os.path.exists(CAR_MAC_PATH):
                try:
                    with open(CAR_MAC_PATH) as f:
                        mac = json.load(f).get("mac")
                except (OSError, ValueError):
                    pass
            if not mac and time.time() >= self.next_inquiry:
                mac = bt_inquiry(CAR_BT_NAME)
                self.next_inquiry = time.time() + 30
                if mac:
                    bt_pair(mac)
            if mac:
                if self.connect_bt(mac, notes):
                    return
            else:
                notes.append("no ZAN_RC_Car paired or in range (is the car switched on?)")
        self.state = "searching"
        self.detail = "No car: " + "; ".join(notes) + ". Dry run until it appears."

    def car_talk(self, data):
        """The car's own lines (mode switches, OTA progress) go to the event log."""
        self.line += data
        while b"\n" in self.line:
            raw, self.line = self.line.split(b"\n", 1)
            text = raw.decode(errors="replace").strip()
            if text and ("Mode:" in text or text.startswith(("Ready", "OTA"))) and self.hub:
                self.hub.log(f"Car: {text}")

    def run(self):
        while True:
            if self.want and self.ser is None and time.time() >= self.next_scan:
                try:
                    self.scan()
                except Exception as e:  # noqa: BLE001
                    self.detail = f"Car scan failed: {e}"
                self.next_scan = time.time() + 4
            elif self.ser is not None:
                with self.wlock:
                    try:
                        if self.ser and self.ser.in_waiting:
                            self.car_talk(self.ser.read(self.ser.in_waiting))
                    except Exception as e:  # noqa: BLE001
                        port = self.port
                        try:
                            self.ser.close()
                        except Exception:  # noqa: BLE001
                            pass
                        self.ser, self.port, self.is_tty = None, None, False
                        self.state, self.detail = "searching", f"Lost {port} ({e.__class__.__name__}) — looking again…"
                        self.next_scan = time.time() + 2
                if self.is_tty and self.port and not os.path.exists(self.port):
                    port = self.port
                    self.release(detail="")
                    self.state, self.detail = "searching", f"{port} was unplugged — looking again…"
                    self.next_scan = time.time() + 2
            time.sleep(0.1)


# --------------------------------------------------------------------------- sharing the car with :8083

class Handover(threading.Thread):
    """Shares the one car with the Gesture Pilot (:8083). The ESP32 takes a
    single Bluetooth client, so the two dashboards take turns:

      take    -> ask :8083 to release, wait until it has, then connect here
      release -> let go; the car is free and either dashboard can take it
      stand down: while we are only *looking* and :8083 already holds the car,
                  we stop looking (it can't win, and every failed page costs
                  the Pi's radio air time) — pressing "Take the car" asks.
    The Gesture Pilot runs the same protocol against us.

    One pilot at a time: opening a pilot's page wakes it (wake) and puts the
    other pilots to sleep (sleep). Asleep = camera closed, vision idle, output
    off, car released, so a page nobody uses costs no CPU. Nobody on the page
    for IDLE_SLEEP_S with output off sends this one to sleep by itself."""

    PEER = "the Gesture Pilot (:8083)"

    def __init__(self, hub, link):
        super().__init__(daemon=True, name="handover")
        self.hub, self.link = hub, link
        self.busy = threading.Lock()                 # one take/release/wake at a time

    @staticmethod
    def call(base, path, body=None, timeout=2.0):
        req = urllib.request.Request(base + path, data=None if body is None else json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json"},
                                     method="GET" if body is None else "POST")
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.load(r)

    @classmethod
    def peer_api(cls, path, body=None, timeout=2.0):
        return cls.call(GESTURE_URL, path, body, timeout)

    def sleep(self, why):
        """Let go of the camera, the output and the car. Returns whether we had the car."""
        hub, had_car = self.hub, self.link.ready()
        with hub.lock:
            was_asleep = hub.asleep
            hub.asleep, hub.asleep_why = True, why
            hub.output, hub.held = False, None
            hub.stats, hub.winner, hub.active, hub.streak_id, hub.streak = [], None, None, None, 0
            hub.fps, hub.proc_ms = 0.0, 0.0
        hub.source.awake.clear()
        if self.link.want or self.link.ready():
            self.link.request(None, detail="Asleep: the car is free for the pilot you opened")
        if not was_asleep:
            hub.log(f"Asleep: {why}")
        return had_car

    def wake(self):
        """This page was opened: the other pilots sleep, this one takes the camera and the car."""
        hub = self.hub
        with self.busy:
            with hub.lock:
                was_asleep, hub.asleep, hub.asleep_why = hub.asleep, False, None
                hub.seen_t = time.time()
            hub.source.awake.set()
            had_car = False
            for _name, base in SLEEP_PEERS:
                try:
                    had_car |= bool(self.call(base, "/api/sleep", {"by": ME}, timeout=5).get("had_car"))
                except Exception:  # noqa: BLE001 - that pilot isn't running: nothing to stop
                    pass
            if was_asleep:
                hub.log("Awake: the other pilots are asleep, the camera is ours")
                if hub.want_car and not self.link.want and not self.link.ready():
                    # the car re-opens its Bluetooth server ~2 s after the last driver left
                    self.link.request(hub.want_car, wait=5.0 if had_car else 0.5)
                    hub.log("Looking for the car (ZAN_RC_Car)…")

    def poll(self):
        try:
            L = self.peer_api("/api/status", timeout=1.5).get("link", {})
            self.hub.peer = {"up": True, "state": L.get("state"), "want": L.get("want"), "port": L.get("port")}
        except Exception:  # noqa: BLE001
            self.hub.peer = {"up": False}
        return self.hub.peer

    def run(self):
        while True:
            if self.busy.acquire(blocking=False):      # never mid take/release
                try:
                    peer = self.poll()
                    if peer.get("up") and peer.get("state") == "ready" and self.link.want and not self.link.ready():
                        self.link.request(None, detail=f"The car is with {self.PEER} — press Take the car to drive it from here")
                        self.hub.log(f"The car is with {self.PEER}: stopped looking for it")
                    if self.hub.idle_for() > IDLE_SLEEP_S:
                        self.sleep(f"nobody had this page open for {IDLE_SLEEP_S // 60} minutes")
                finally:
                    self.busy.release()
            time.sleep(2)

    def take(self):
        with self.busy:
            if self.hub.asleep:                         # a stale page: wake it first
                return
            peer, wait = self.poll(), 0.5
            if peer.get("up") and (peer.get("want") or peer.get("state") != "off"):
                had_car = peer.get("state") == "ready"
                try:
                    self.peer_api("/api/serial", {"port": None})
                    self.hub.log(f"Asked {self.PEER} to release the car")
                except Exception as e:  # noqa: BLE001
                    self.hub.log(f"Could not reach {self.PEER}: {e.__class__.__name__}", "warn")
                for _ in range(20):                     # until it reports released
                    if self.poll().get("state") in ("off", None):
                        break
                    time.sleep(0.25)
                wait = 5.0 if had_car else 0.5          # the car re-opens SPP ~2 s after a client leaves
            if self.hub.asleep:                         # another pilot was opened meanwhile
                return
            self.link.request("auto", wait=wait)
            self.hub.log("Looking for the car (ZAN_RC_Car)…")

    def give(self):
        with self.busy:
            self.link.request(None)
            self.hub.log("Car released — free for either dashboard")


# --------------------------------------------------------------------------- hub

class Hub:
    def __init__(self, source):
        self.lock = threading.RLock()
        self.frames = threading.Condition(threading.Lock())
        self.source = source
        try:
            with open(CONFIG_PATH) as f:
                self.cfg = clean_config(json.load(f))
        except (OSError, ValueError):
            self.cfg = default_config()
        self.dirty = False
        self.mode, self.output, self.speed = "auto", False, 5
        self.stats, self.winner, self.active = [], None, None
        self.streak_id, self.streak = None, 0
        self.fps, self.proc_ms = 0.0, 0.0
        self.held, self.held_until = None, 0.0
        self.would, self.last_sent, self.last_sent_t = None, None, 0.0
        self.events = []
        self.peer = {"up": False}  # the Gesture Pilot's car link, polled by Handover
        self.views = {}          # (view, context, only) -> {"jpg", "n", "viewers", "want"}
        self.latest = None       # newest frame (for /api/sample)
        self.started = hhmmss()
        self.asleep, self.asleep_why = True, "Nobody has opened this page yet"
        self.seen_t = 0.0        # last status poll from a browser (not from the other pilots)
        self.want_car = "auto"   # what to connect to on waking (None: dry run, --serial none)

    def log(self, text, tag="info"):
        with self.lock:
            self.events = [{"t": hhmmss(), "text": text, "tag": tag}] + self.events[:39]

    def idle_for(self):
        """Seconds nobody has used this page (0 while asleep, live, or a stream is open)."""
        with self.frames:
            watched = any(v["viewers"] > 0 for v in self.views.values())
        if self.asleep or self.output or watched:
            return 0.0
        return time.time() - self.seen_t

    def set_config(self, cfg):
        with self.lock:
            self.cfg = clean_config(cfg)
            self.dirty = True
            return self.cfg

    def want_view(self, key):
        with self.frames:
            v = self.views.setdefault(key, {"jpg": None, "n": 0, "viewers": 0, "want": 0.0})
            v["want"] = time.time() + 3
            return v

    def class_by_id(self, cid):
        return next((c for c in self.cfg["classes"] if c["id"] == cid), None)


def describe(action):
    t = action.get("type")
    if t == "key":
        return f"{action['key']} · {KEYS[action['key']]}"
    if t == "line":
        return action["text"]
    if t == "arm":
        return f"arm → {action.get('name') or action['pose']}"
    return "nothing"


# --------------------------------------------------------------------------- think: vision

class Vision(threading.Thread):
    """Sense + think: newest frame in, per-class stats and the verdict out."""

    def __init__(self, hub, renderer):
        super().__init__(daemon=True, name="vision")
        self.hub = hub
        self.renderer = renderer

    def run(self):
        while True:
            try:
                self.loop()
            except Exception as e:  # noqa: BLE001 - keep the dashboard alive, say what broke
                self.hub.log(f"Vision error: {e}", "warn")
                time.sleep(1)

    def loop(self):
        hub, src, last_seq = self.hub, self.hub.source, -1
        while True:
            with src.lock:
                frame, seq = src.frame, src.seq
            if frame is None or seq == last_seq:
                time.sleep(0.008)
                continue
            last_seq = seq
            t_start = time.time()
            cfg = hub.cfg
            small = cv2.resize(frame, (PW, PH), interpolation=cv2.INTER_AREA)
            hsv = cv2.cvtColor(small, cv2.COLOR_BGR2HSV)       # once per frame, not once per color
            labels = np.zeros((PH, PW), np.uint8)
            kernel = np.ones((2 * cfg["cleanup"] + 1,) * 2, np.uint8) if cfg["cleanup"] else None
            min_count = cfg["min_area"] / AREA_SCALE      # a smaller mask cannot hold a winning blob
            stats = []
            for i, c in enumerate(cfg["classes"]):
                st = {"id": c["id"], "coverage": 0.0, "area": 0, "box": None, "center": None}
                if c["on"]:
                    m = class_mask(hsv, c)
                    if kernel is not None:
                        # one (2n+1)x(2n+1) pass == n passes of the 3x3 default: kill speckles, regrow
                        m = cv2.erode(m, kernel)
                        m = cv2.dilate(m, kernel)
                    labels[(m > 0) & (labels == 0)] = i + 1                    # first class in the list wins
                    count = cv2.countNonZero(m)
                    st["coverage"] = round(count / (PW * PH), 4)
                    if count and count >= min_count:
                        contours, _ = cv2.findContours(m, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
                        big = max(contours, key=cv2.contourArea)
                        x, y, w, h = cv2.boundingRect(big)
                        st["area"] = int(cv2.contourArea(big) * AREA_SCALE)
                        st["box"] = [x * 2, y * 2, w * 2, h * 2]
                        st["center"] = [x * 2 + w, y * 2 + h]
                stats.append(st)
            counted = [s for s in stats if s["area"] >= cfg["min_area"]]
            winner = max(counted, key=lambda s: s["area"])["id"] if counted else None

            with hub.lock:
                if winner == hub.streak_id:
                    hub.streak += 1
                else:
                    hub.streak_id, hub.streak = winner, 1
                if hub.streak >= cfg["hold"] and hub.active != winner:
                    hub.active = winner
                hub.stats, hub.winner, hub.latest = stats, winner, frame

            hub.proc_ms = round((time.time() - t_start) * 1000, 1)
            self.renderer.submit(frame, small, labels, cfg, stats, winner)


class Render(threading.Thread):
    """Draw and JPEG-encode the views off the vision loop's critical path.

    The vision thread hands over the newest analysed scene; this thread keeps
    only the latest one (stale scenes are skipped), exactly like the frame
    source. hub.fps counts the frames actually delivered to the streams.
    """

    def __init__(self, hub):
        super().__init__(daemon=True, name="render")
        self.hub = hub
        self.cond = threading.Condition()
        self.scene, self.n = None, 0

    def submit(self, frame, small, labels, cfg, stats, winner):
        with self.cond:
            self.n += 1
            self.scene = (self.n, frame, small, labels, cfg, stats, winner)
            self.cond.notify_all()

    def run(self):
        seen, n, t0 = 0, 0, time.time()
        while True:
            with self.cond:
                while self.scene is None or self.scene[0] == seen:
                    self.cond.wait()
                scene, seen = self.scene, self.scene[0]
            self.render(*scene[1:])
            n += 1
            if time.time() - t0 >= 1.5:
                self.hub.fps, n, t0 = round(n / (time.time() - t0), 1), 0, time.time()

    def render(self, frame, small, labels, cfg, stats, winner):
        hub, now = self.hub, time.time()
        with hub.frames:
            keys = [k for k, v in hub.views.items() if v["viewers"] > 0 or v["want"] > now]
        out = {}
        for key in keys:
            view, context, only = key
            img = self.camera_view(frame, cfg, stats, winner) if view == "camera" else \
                self.mask_view(small, labels, cfg, context, only)
            ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 74])
            if ok:
                out[key] = buf.tobytes()
        with hub.frames:
            for key, jpg in out.items():
                v = hub.views[key]
                v["jpg"], v["n"] = jpg, v["n"] + 1
            hub.frames.notify_all()

    @staticmethod
    def camera_view(frame, cfg, stats, winner):
        img = frame.copy()
        for c, st in zip(cfg["classes"], stats):
            if not st["box"] or st["area"] < cfg["min_area"]:
                continue
            x, y, w, h = st["box"]
            col = hex_bgr(c["color"])
            if st["id"] == winner:
                cv2.rectangle(img, (x - 3, y - 3), (x + w + 3, y + h + 3), (255, 255, 255), 5, cv2.LINE_AA)
                cv2.rectangle(img, (x - 3, y - 3), (x + w + 3, y + h + 3), col, 3, cv2.LINE_AA)
                cx, cy = st["center"]
                cv2.drawMarker(img, (cx, cy), (255, 255, 255), cv2.MARKER_CROSS, 26, 5, cv2.LINE_AA)
                cv2.drawMarker(img, (cx, cy), col, cv2.MARKER_CROSS, 24, 2, cv2.LINE_AA)
            else:
                cv2.rectangle(img, (x, y), (x + w, y + h), col, 1, cv2.LINE_AA)
        return img

    @staticmethod
    def mask_view(small, labels, cfg, context, only):
        lut = np.zeros((256, 3), np.uint8)
        visible = np.zeros(256, bool)
        for i, c in enumerate(cfg["classes"]):
            if only and c["id"] != only:
                continue
            lut[i + 1] = hex_bgr(c["color"])
            visible[i + 1] = True
        img = lut[labels]
        if context:          # the scene, dimmed and grey, so you can see what got painted
            grey = (cv2.cvtColor(small, cv2.COLOR_BGR2GRAY) * 0.32).astype(np.uint8)
            img = np.where(visible[labels][..., None], img, cv2.merge([grey, grey, grey]))
        return cv2.resize(img, (W, H), interpolation=cv2.INTER_NEAREST)


# --------------------------------------------------------------------------- act: policy -> outputs

class Driver(threading.Thread):
    """Four times a second: decide the action and, when output is on, send it.

    Keys are re-sent every tick so a held card keeps the car going. The ZAN
    TriBot firmware (Oct 2026) has NO fail-safe any more — a dead link cannot
    stop it — so S is also sent when output switches off or the link is
    released; if the Pi dies mid-drive the car keeps its last command.
    """

    TICK = 0.25

    def __init__(self, hub, link):
        super().__init__(daemon=True, name="driver")
        self.hub, self.link = hub, link
        self.prev = None
        self.was_on = False
        self.sent_speed = None

    def decide(self):
        hub = self.hub
        if hub.mode == "manual":
            if hub.held and time.time() < hub.held_until:
                return {"type": "key", "key": hub.held}, "you"
            return {"type": "key", "key": "S"}, "you"
        c = hub.class_by_id(hub.active) if hub.active else None
        if c:
            return c["action"], c["name"]
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
                output = hub.output
                hub.would = describe(action)
                ident = (json.dumps(action, sort_keys=True), why, output)
            link_ok = self.link.ready()

            if output and link_ok and self.sent_speed != hub.speed:
                self.link.write(str(hub.speed).encode())
                self.sent_speed = hub.speed
            if not link_ok:
                self.sent_speed = None

            sent = False
            if output and link_ok and action["type"] in ("key", "line"):
                data = action["key"].encode() if action["type"] == "key" else (action["text"] + "\n").encode()
                sent = self.link.write(data)
                if sent:
                    with hub.lock:
                        hub.last_sent, hub.last_sent_t = describe(action), time.time()
            if self.was_on and not output and link_ok:
                self.link.write(b"S")                        # output switched off: stop now
            self.was_on = output

            if ident != self.prev:
                self.prev = ident
                who = "Manual" if why == "you" else (why or "Nothing seen")
                if action["type"] == "arm":
                    if output:
                        threading.Thread(target=self.move_arm, args=(action,), daemon=True).start()
                    hub.log(f"{who} → {describe(action)}", "sent" if output else "dry")
                else:
                    tag = "sent" if sent else "dry"
                    note = "" if sent or not output else " (no car Arduino)"
                    hub.log(f"{who} → {describe(action)}{note}", tag)

    def move_arm(self, action):
        try:
            with urllib.request.urlopen(f"{ARM_URL}/api/state", timeout=1.5) as r:
                poses = json.load(r).get("poses", {}).get("poses", [])
            pose = next((p for p in poses if p["id"] == action["pose"]), None)
            if not pose:
                self.hub.log(f"Arm pose “{action.get('name')}” no longer exists in the Arm Twin", "warn")
                return
            req = urllib.request.Request(f"{ARM_URL}/api/goal", data=json.dumps({"servo": pose["servo"]}).encode(),
                                         headers={"Content-Type": "application/json"}, method="POST")
            urllib.request.urlopen(req, timeout=1.5).close()
        except Exception as e:  # noqa: BLE001
            self.hub.log(f"Could not reach the Arm Twin on :8080 ({e.__class__.__name__})", "warn")


def arm_info(cache={"t": 0.0, "v": None}):
    if time.time() - cache["t"] < 3 and cache["v"] is not None:
        return cache["v"]
    try:
        with urllib.request.urlopen(f"{ARM_URL}/api/state", timeout=1.0) as r:
            d = json.load(r)
        link = d.get("state", {}).get("link", {})
        v = {"available": True, "connected": link.get("status") == "ready",
             "poses": [{"id": p["id"], "name": p["name"]} for p in d.get("poses", {}).get("poses", [])]}
    except Exception:  # noqa: BLE001
        v = {"available": False, "connected": False, "poses": []}
    cache.update(t=time.time(), v=v)
    return v


def saver(hub):
    while True:
        time.sleep(1.0)
        with hub.lock:
            if not hub.dirty:
                continue
            cfg, hub.dirty = copy.deepcopy(hub.cfg), False
        try:
            os.makedirs(DATA, exist_ok=True)
            tmp = CONFIG_PATH + ".tmp"
            with open(tmp, "w") as f:
                json.dump(cfg, f, indent=1)
            os.replace(tmp, CONFIG_PATH)
        except OSError as e:
            hub.log(f"Could not save settings: {e}", "warn")


# --------------------------------------------------------------------------- HTTP

MIME = {".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8",
        ".css": "text/css; charset=utf-8", ".svg": "image/svg+xml", ".woff2": "font/woff2",
        ".png": "image/png", ".json": "application/json", ".txt": "text/plain; charset=utf-8"}
_gz = {}


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    hub = link = source = handover = None

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

    def json(self, obj, code=200):
        self.send_body(code, json.dumps(obj).encode(), "application/json", {"Cache-Control": "no-store"})

    def body(self):
        n = int(self.headers.get("Content-Length") or 0)
        if n > 256 * 1024:
            raise ValueError("too large")
        d = json.loads(self.rfile.read(n) or b"{}") if n else {}
        if not isinstance(d, dict):
            raise ValueError("expected a JSON object")
        return d

    def static(self, rel):
        full = os.path.realpath(os.path.join(STATIC, rel)) if rel != "index.html" else os.path.join(HERE, "index.html")
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

    def view_key(self, q):
        view = "mask" if q.get("view", ["camera"])[0] == "mask" else "camera"
        if view == "camera":
            return ("camera", False, None)
        only = q.get("only", [""])[0]
        return ("mask", q.get("context", ["1"])[0] != "0", only if re.fullmatch(r"[\w-]{1,24}", only or "") else None)

    def stream(self, key):
        hub = self.hub
        self.send_response(200)
        self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=frame")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "close")
        self.end_headers()
        self.close_connection = True
        v = hub.want_view(key)
        with hub.frames:
            v["viewers"] += 1
        seen = -1
        try:
            while True:
                with hub.frames:
                    hub.frames.wait_for(lambda: v["n"] != seen, timeout=2)
                    data, seen = v["jpg"], v["n"]
                if data:
                    self.wfile.write(b"--frame\r\nContent-Type: image/jpeg\r\nContent-Length: " +
                                     str(len(data)).encode() + b"\r\n\r\n" + data + b"\r\n")
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass
        finally:
            with hub.frames:
                v["viewers"] -= 1

    def from_page(self):
        """A browser — not the other pilots polling our status (they use urllib)."""
        return not (self.headers.get("User-Agent") or "").startswith("Python-urllib")

    def status(self):
        hub, link, src = self.hub, self.link, self.source
        if self.from_page():
            hub.seen_t = time.time()
        with hub.lock:
            cfg = hub.cfg
            active = hub.class_by_id(hub.active) if hub.active else None
            s = {
                "mode": hub.mode, "output": hub.output, "speed": hub.speed,
                "stats": hub.stats, "winner": hub.winner, "active": hub.active,
                "streak": hub.streak if hub.streak_id == hub.winner else 0, "hold": cfg["hold"],
                "would": hub.would, "last_sent": hub.last_sent, "last_sent_age": round(time.time() - hub.last_sent_t, 1) if hub.last_sent else None,
                "held": hub.held if time.time() < hub.held_until else None,
                "fps": hub.fps, "proc_ms": hub.proc_ms,
                "source": {"kind": src.kind, "name": src.name, "error": src.error,
                           "camera_id": src.which, "cameras": list_cameras()},
                "link": {"state": link.state, "detail": link.detail, "port": link.port, "want": link.want},
                "peer": hub.peer,
                "asleep": hub.asleep, "asleep_why": hub.asleep_why,
                "events": hub.events[:14],
                # v1 fields, kept for the course docs and verify scripts
                "color": active["id"] if active else None,
                "direction": KEYS.get(active["action"].get("key"), None) if active and active["action"]["type"] == "key" else None,
                "cmd": hub.last_sent.split(" ")[0] if hub.last_sent else None,
                "serial_ok": link.ready(), "serial_port": link.port, "camera": src.name, "started": hub.started,
            }
        return s

    def do_GET(self):
        url = urlparse(self.path)
        q, path = parse_qs(url.query), url.path
        hub = self.hub
        if path in ("/", "/index.html"):
            return self.static("index.html")
        if path.startswith("/static/"):
            return self.static(path[len("/static/"):])
        if path == "/stream":
            return self.stream(self.view_key(q))
        if path == "/snapshot.jpg":
            key = self.view_key(q)
            v = hub.want_view(key)
            with hub.frames:
                n0 = v["n"]
                hub.frames.wait_for(lambda: v["n"] != n0, timeout=2.5)   # a frame rendered after this request
                data = v["jpg"]
            if not data:
                return self.json({"error": "no frame yet"}, 503)
            return self.send_body(200, data, "image/jpeg", {"Cache-Control": "no-store"})
        if path == "/api/status":
            return self.json(self.status())
        if path == "/api/cameras":
            return self.json({"cameras": list_cameras(), "camera_id": self.source.which})
        if path == "/api/config":
            return self.json(hub.cfg)
        if path == "/api/arm":
            return self.json(arm_info())
        if path == "/api/sample":
            with hub.lock:
                frame = hub.latest
            if frame is None:
                return self.json({"error": "no frame yet"}, 503)
            try:
                x = min(max(float(q.get("x", ["0.5"])[0]), 0.0), 1.0)
                y = min(max(float(q.get("y", ["0.5"])[0]), 0.0), 1.0)
            except ValueError:
                return self.json({"error": "x and y are 0..1"}, 400)
            px, py = int(x * (W - 1)), int(y * (H - 1))
            patch = frame[max(0, py - 4):py + 5, max(0, px - 4):px + 5].reshape(-1, 3)
            bgr = np.median(patch, axis=0).astype(np.uint8)
            hsv = cv2.cvtColor(bgr.reshape(1, 1, 3), cv2.COLOR_BGR2HSV)[0, 0]
            hits = [c["id"] for c in hub.cfg["classes"]
                    if c["on"] and class_mask(hsv.reshape(1, 1, 3), c)[0, 0]]
            return self.json({"x": px, "y": py, "h": int(hsv[0]), "s": int(hsv[1]), "v": int(hsv[2]),
                              "rgb": "#%02x%02x%02x" % (bgr[2], bgr[1], bgr[0]), "classes": hits})
        # ---- v1 compatibility (query-string API) ----
        if path == "/api/cmd":
            k = q.get("k", [""])[0]
            if k not in KEYS and k not in set("123456789q"):
                return self.json({"ok": False, "error": "bad key"}, 400)
            if hub.mode != "manual":
                return self.json({"ok": False, "error": "switch to manual mode first"}, 409)
            with hub.lock:
                if k in KEYS:
                    hub.held, hub.held_until = k, time.time() + 0.6   # like one tap on the D-pad
                else:
                    hub.speed = 9 if k == "q" else int(k)
            return self.json({"ok": True, "sent": k, "output": hub.output})
        if path == "/api/mode":
            return self.set_mode(q.get("m", [""])[0])
        if path == "/api/speed":
            return self.set_speed(q.get("n", [""])[0])
        return self.json({"error": "not found"}, 404)

    def set_mode(self, m):
        if m not in ("auto", "manual"):
            return self.json({"ok": False, "error": "mode is auto or manual"}, 400)
        with self.hub.lock:
            self.hub.mode, self.hub.held = m, None
        self.hub.log("Vision drives (auto)" if m == "auto" else "You drive (manual)")
        return self.json({"ok": True, "mode": m})

    def set_speed(self, n):
        n = str(n)
        if n not in set("123456789"):
            return self.json({"ok": False, "error": "speed is 1-9"}, 400)
        with self.hub.lock:
            self.hub.speed = int(n)
        return self.json({"ok": True, "speed": int(n)})

    def do_POST(self):
        path = urlparse(self.path).path
        hub = self.hub
        try:
            b = self.body()
        except ValueError as e:
            return self.json({"ok": False, "error": f"bad request: {e}"}, 400)
        if path == "/api/config":
            return self.json({"ok": True, "config": hub.set_config(b.get("config", b))})
        if path == "/api/config/reset":
            hub.log("Classifier reset to the six course colors")
            return self.json({"ok": True, "config": hub.set_config(default_config())})
        if path == "/api/output":
            with hub.lock:
                if b.get("on") and hub.asleep:
                    return self.json({"ok": False, "error": "This pilot is asleep: wake it first"}, 409)
                hub.output = bool(b.get("on"))
            hub.log("Output on — actions go to the hardware" if hub.output else "Output off — dry run", "info")
            return self.json({"ok": True, "output": hub.output})
        if path == "/api/wake":
            self.handover.wake()
            return self.json({"ok": True})
        if path == "/api/sleep":
            had_car = self.handover.sleep(f"{str(b.get('by') or 'another pilot')[:60]} was opened")
            return self.json({"ok": True, "had_car": had_car})
        if path == "/api/mode":
            return self.set_mode(b.get("mode"))
        if path == "/api/speed":
            return self.set_speed(b.get("n"))
        if path == "/api/drive":
            k = b.get("key")
            if k is not None and k not in KEYS:
                return self.json({"ok": False, "error": "key is one of F B L R G I H J S"}, 400)
            with hub.lock:
                if hub.mode != "manual":
                    return self.json({"ok": False, "error": "switch to manual mode first"}, 409)
                hub.held, hub.held_until = k, time.time() + 0.6     # dead-man: renew while held
            return self.json({"ok": True})
        if path == "/api/source":
            kind = b.get("source")
            if kind not in ("camera", "testcard"):
                return self.json({"ok": False, "error": "source is camera or testcard"}, 400)
            self.source.kind = kind
            hub.log("Picture from the test card" if kind == "testcard" else "Picture from the camera")
            return self.json({"ok": True})
        if path == "/api/camera":
            cam_id = b.get("camera")
            if cam_id is not None and not re.fullmatch(r"(picam|usb:/dev/video\d+|usb)", str(cam_id)):
                return self.json({"ok": False, "error": "camera is null, picam or usb:/dev/videoN"}, 400)
            self.source.request_camera(cam_id)
            try:                              # keep the choice across restarts
                os.makedirs(DATA, exist_ok=True)
                with open(CAMERA_PATH, "w") as f:
                    json.dump({"camera": cam_id}, f)
            except OSError:
                pass
            hub.log(f"Camera: {camera_label(cam_id)}")
            return self.json({"ok": True, "camera": cam_id, "cameras": list_cameras()})
        if path == "/api/serial":
            want = b.get("port")
            if want is not None and want != "auto" and not (
                    re.fullmatch(r"/dev/tty(USB|ACM|rfcomm)\d+", str(want)) or MAC_RE.fullmatch(str(want))):
                return self.json({"ok": False, "error": "port is auto, a car MAC, /dev/ttyUSBn, /dev/ttyACMn or null"}, 400)
            self.link.request(want)
            hub.log("Car link released" if want is None else f"Looking for the car ({want})")
            return self.json({"ok": True})
        if path == "/api/car":
            threading.Thread(target=self.handover.take if b.get("take") else self.handover.give, daemon=True).start()
            return self.json({"ok": True})
        if path == "/shutdown":
            hub.log("shutdown requested")
            threading.Thread(target=lambda: (time.sleep(0.5), os._exit(0)), daemon=True).start()
            return self.json({"ok": True})
        return self.json({"error": "not found"}, 404)


def main():
    ap = argparse.ArgumentParser(description="RC Color Pilot dashboard")
    ap.add_argument("--port", type=int, default=8081)
    ap.add_argument("--source", choices=("camera", "testcard"), default="camera")
    ap.add_argument("--camera", default=None, help="picam, usb:/dev/videoN, or omit for auto")
    ap.add_argument("--serial", default="auto",
                    help="auto, a MAC like 11:22:33:44:55:66, a port like /dev/ttyUSB1, or none")
    args = ap.parse_args()
    if args.camera is None:                   # fall back to the last picked camera
        try:
            with open(CAMERA_PATH) as f:
                args.camera = json.load(f).get("camera")
        except (OSError, ValueError, AttributeError):
            pass

    source = Source(args.source, which=args.camera)
    hub = Hub(source)
    hub.want_car = None if args.serial == "none" else args.serial
    link = CarLink(None, hub)                 # starts asleep: no camera, no car until the page opens
    link.detail = "Asleep: open this page to wake it"
    handover = Handover(hub, link)
    renderer = Render(hub)
    Handler.hub, Handler.link, Handler.source, Handler.handover = hub, link, source, handover
    for t in (source, link, renderer, Vision(hub, renderer), Driver(hub, link), handover):
        t.start()
    threading.Thread(target=saver, args=(hub,), daemon=True).start()
    hub.log("Dashboard started asleep — opening the page wakes it; output is off until you switch it on")
    srv = ThreadingHTTPServer(("0.0.0.0", args.port), Handler)
    srv.daemon_threads = True
    print(f"RC Color Pilot dashboard: http://0.0.0.0:{args.port}/", flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        link.release()


if __name__ == "__main__":
    main()
