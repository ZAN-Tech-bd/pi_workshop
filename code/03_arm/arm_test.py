"""Module 3 — protocol test for the arm firmware (no arm needed to test).

Checks, over the same USB serial link as module 2:
  1. H          -> OK        (home)
  2. J,...      -> OK        (valid move, angles inside 0..180)
  3. sweeps     -> OK        (small base/shoulder/elbow moves)
  4. J,200,...  -> ERR       (out of range)
  5. garbage    -> ERR       (not the protocol)

With servos attached you also SEE the smooth ramp; without them the
replies still prove parsing, clamping and the reply logic work.

Run on the Pi:  python3 arm_test.py | tee verify-arm.txt
"""

import os
import serial
import time


def find_port():
    for port in ("/dev/ttyACM0", "/dev/ttyUSB0"):
        if os.path.exists(port):
            return port
    raise SystemExit("No Arduino found on /dev/ttyACM0 or /dev/ttyUSB0")


ser = serial.Serial(find_port(), 115200, timeout=5)
time.sleep(2)  # the port-open reset


def cmd(msg):
    ser.write(msg.encode() + b"\n")
    reply = ser.readline().decode().strip()
    print(f"{msg:<18} -> {reply}")
    return reply


cmd("H")
cmd("J,90,45,120,30")      # the deck's example move
cmd("J,120,90,90,30")      # base sweep
cmd("J,90,120,90,30")      # shoulder sweep
cmd("J,90,90,140,30")      # elbow sweep
cmd("J,90,90,90,80")       # gripper close
cmd("H")                   # back home
cmd("J,200,90,90,30")      # 200 degrees -> must be ERR
cmd("J,90,90,90")          # missing angle -> must be ERR
cmd("HELLO")               # not the protocol -> must be ERR

ser.close()
print("done")
