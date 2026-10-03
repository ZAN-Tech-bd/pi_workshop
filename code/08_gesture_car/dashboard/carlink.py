"""The car link — the ZAN TriBot (ESP32 "ZAN_RC_Car") over Bluetooth.

Same link as the RC Color Pilot (code/07_rc_car/dashboard/server.py), kept in
its own file here: F/B/L/R/G/I/H/J/S drive keys, 1-9 speed, q turbo, single
characters over RFCOMM channel 1, NO handshake (never send PING: its I and G
are drive keys). A /dev/ttyUSBn port still works when asked for explicitly.

One car, one Bluetooth client: the ESP32 accepts a single connection, so this
dashboard and the Color Pilot (:8081) take turns — see Handover in server.py.
"""

import fcntl
import json
import os
import re
import socket
import subprocess
import termios
import threading
import time

try:
    import serial
except ImportError:
    serial = None

CAR_BT_NAME = "ZAN_RC_Car"
CAR_BT_CHANNEL = 1
MAC_RE = re.compile(r"[0-9A-Fa-f]{2}(?::[0-9A-Fa-f]{2}){5}")


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
        out = subprocess.run(["bluetoothctl", "devices"], capture_output=True, text=True, timeout=6).stdout
    except (OSError, subprocess.SubprocessError):
        return []
    return [(m.group(1), m.group(2).strip()) for m in re.finditer(r"Device ([0-9A-F:]{17}) (.+)", out)]


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
        subprocess.run(["bluetoothctl", "--timeout", "20"], input=script, capture_output=True, text=True, timeout=26)
    except (OSError, subprocess.SubprocessError):
        pass


class BTSocket:
    """The slice of pyserial's API CarLink uses, over an RFCOMM socket."""

    def __init__(self, mac, channel=CAR_BT_CHANNEL):
        self.sock = socket.socket(socket.AF_BLUETOOTH, socket.SOCK_STREAM, socket.BTPROTO_RFCOMM)
        self.sock.settimeout(10)
        self.sock.connect((mac, channel))          # OSError when off / out of range / taken
        self.sock.settimeout(0)
        self.buf = b""

    def write(self, data):
        self.sock.send(data)

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
            self.sock.close()
        except OSError:
            pass


class CarLink(threading.Thread):
    """Keeps the link to the car: want = None (released), "auto", a MAC or a /dev/tty*.

    mac_files: where a remembered car MAC may live (ours first, then the Color
    Pilot's, so a car paired there is found here too).
    """

    BAUD = 115200

    def __init__(self, want=None, log=None, mac_files=()):
        super().__init__(daemon=True, name="carlink")
        self.log = log or (lambda text, tag="info": None)
        self.want = want
        self.mac_files = list(mac_files)
        self.ser, self.port, self.is_tty = None, None, False
        self.state = "searching" if want else "off"
        self.detail = "Looking for ZAN_RC_Car over Bluetooth…" if want else "Released: the car is free for the Color Pilot"
        self.wlock = threading.Lock()
        self.next_scan, self.next_inquiry = 0.0, 0.0
        self.line = b""

    def ready(self):
        return self.ser is not None

    def release(self, detail="Released: the car is free for the Color Pilot"):
        with self.wlock:
            if self.ser:
                try:
                    self.ser.write(b"S")
                    self.ser.close()
                except Exception:  # noqa: BLE001
                    pass
            self.ser, self.port, self.is_tty = None, None, False
        self.state, self.detail = "off", detail

    def request(self, want):
        self.release(detail="Reconnecting…" if want else "Released: the car is free for the Color Pilot")
        self.want = want
        self.next_scan, self.next_inquiry = 0.0, 0.0
        if want:
            self.state, self.detail = "searching", "Looking for ZAN_RC_Car over Bluetooth…"

    def _drop(self, why):
        port = self.port
        try:
            self.ser.close()
        except Exception:  # noqa: BLE001
            pass
        self.ser, self.port, self.is_tty = None, None, False
        self.state, self.detail = "searching", f"Lost {port} ({why}) — looking again…"
        self.next_scan = time.time() + 2

    def write(self, data):
        with self.wlock:
            if not self.ser:
                return False
            try:
                self.ser.write(data)
                return True
            except Exception as e:  # noqa: BLE001
                self._drop(e.__class__.__name__)
                return False

    def remembered_mac(self):
        for path in self.mac_files:
            try:
                with open(path) as f:
                    mac = json.load(f).get("mac")
                if mac and MAC_RE.fullmatch(mac):
                    return mac
            except (OSError, ValueError, AttributeError):
                pass
        return None

    def connect_bt(self, mac, notes):
        try:
            ser = BTSocket(mac)
        except OSError as e:
            if (mac, CAR_BT_NAME) not in bt_known_devices():
                bt_pair(mac)
                notes.append(f"{mac}: pairing ({e.__class__.__name__})")
            else:
                notes.append(f"{mac}: {e.__class__.__name__} — car off, out of range, or still held by the Color Pilot?")
            return False
        with self.wlock:
            self.ser, self.port, self.is_tty = ser, f"ZAN_RC_Car ({mac})", False
        self.state, self.detail = "ready", f"ZAN TriBot on Bluetooth {mac}"
        if self.mac_files:
            try:
                os.makedirs(os.path.dirname(self.mac_files[0]), exist_ok=True)
                with open(self.mac_files[0], "w") as f:
                    json.dump({"mac": mac}, f)
            except OSError:
                pass
        return True

    def connect_tty(self, dev, notes):
        if not serial:
            notes.append("pyserial is not installed in this venv")
            return False
        if not os.path.exists(dev):
            notes.append(f"{dev} is not plugged in")
            return False
        holders = port_holders(dev)
        if holders:
            notes.append(f"{dev} is in use by {holders[0][:60]}")
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
        else:
            mac = next((m for m, n in bt_known_devices() if n == CAR_BT_NAME), None) or self.remembered_mac()
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
        if self.want:                           # not released meanwhile
            self.state = "searching"
            self.detail = "No car: " + "; ".join(notes) + ". Dry run until it appears."

    def car_talk(self, data):
        """The car's own lines (mode switches, OTA progress) go to the event log."""
        self.line += data
        while b"\n" in self.line:
            raw, self.line = self.line.split(b"\n", 1)
            text = raw.decode(errors="replace").strip()
            if text and ("Mode:" in text or text.startswith(("Ready", "OTA"))):
                self.log(f"Car: {text}")

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
                        self._drop(e.__class__.__name__)
                if self.is_tty and self.port and not os.path.exists(self.port):
                    port = self.port
                    self.release(detail="")
                    self.state, self.detail = "searching", f"{port} was unplugged — looking again…"
                    self.next_scan = time.time() + 2
            time.sleep(0.1)
