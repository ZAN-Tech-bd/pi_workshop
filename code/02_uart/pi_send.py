"""Task 2.5 — Raspberry Pi: send a line, wait for the reply (deck slide 26).

With arduino_echo.ino on the Nano, the reply must be the line you sent,
prefixed with ACK:.

Run on the Pi (close any serial monitor first — only one program can hold
the port):

    python3 pi_send.py
"""

import os
import serial
import time


def find_port():
    """Uno/Nano with FTDI shows up as ttyACM0; CH340 clones as ttyUSB0."""
    for port in ("/dev/ttyACM0", "/dev/ttyUSB0"):
        if os.path.exists(port):
            return port
    raise SystemExit("No Arduino found on /dev/ttyACM0 or /dev/ttyUSB0")


ser = serial.Serial(find_port(), 115200, timeout=1)
time.sleep(2)  # real: opening the port resets most boards

ser.write(b"J,90,45,120,30\n")
print("sent:     J,90,45,120,30")
print("received:", ser.readline().decode().strip())

ser.write(b"H\n")
print("sent:     H")
print("received:", ser.readline().decode().strip())

ser.close()
