"""Module 3 — joint calibration helper.

Usage on the Pi:
    python3 calibrate.py <base> <shoulder> <elbow> <gripper>

Sends that pose to the arm and prints the reply. Move one joint at a time,
watch the real arm, and write down the numbers where it looks right — those
become your HOME pose and the MIN/MAX constants in arm_firmware.ino.

Typical things to find:
    - gripper fully open / fully closed angles
    - shoulder/elbow angles where the arm is level over the table
    - base angle facing your bin
"""

import os
import serial
import sys
import time


def find_port():
    for port in ("/dev/ttyACM0", "/dev/ttyUSB0"):
        if os.path.exists(port):
            return port
    raise SystemExit("No Arduino found on /dev/ttyACM0 or /dev/ttyUSB0")


if len(sys.argv) != 5:
    sys.exit("usage: python3 calibrate.py <base> <shoulder> <elbow> <gripper>")

angles = [int(a) for a in sys.argv[1:]]
if any(a < 0 or a > 180 for a in angles):
    sys.exit("angles must be 0..180")

ser = serial.Serial(find_port(), 115200, timeout=5)
time.sleep(2)

msg = "J," + ",".join(str(a) for a in angles)
ser.write(msg.encode() + b"\n")
print(f"{msg} -> {ser.readline().decode().strip()}")
ser.close()
