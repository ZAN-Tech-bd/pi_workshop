# Module 2 — UART: Pi to Arduino

Slides 20–26 · Result: a line typed in Python on the Pi gets an answer from the Arduino.

## 1. The idea

UART is asynchronous serial: **no clock wire**, both sides just agree on a speed
(**baud rate**). Ten bits travel per byte — 1 start, 8 data, 1 stop — and the line idles
high. At **115200 baud** that's ~11,520 bytes/second. Mismatch the two speeds and you
get garbage characters — the classic symptom.

Three wiring rules:

1. **Cross the lines:** Pi TX → Arduino RX, Arduino TX → Pi RX.
2. **Join the grounds:** without a common GND the signal means nothing.
3. **5 V vs 3.3 V:** Arduino logic is 5 V, Pi pins are 3.3 V. Never wire a 5 V TX
   straight into a Pi pin.

## 2. Two ways to wire it

| | Option A: USB cable **(we use this)** | Option B: GPIO pins |
|---|---|---|
| Connection | Pi USB → Arduino USB port | Pi TX (pin 8) ↔ Arduino RX (pin 0); Arduino TX (pin 1) → **level shifter** → Pi RX (pin 10); GND ↔ GND |
| Shows up as | `/dev/ttyACM0` (FTDI) or `/dev/ttyUSB0` (CH340 clones — our Nano) | `/dev/serial0` |
| Power | Powers the Arduino too | Arduino needs its own power |
| Catch | — | Unplug pins 0/1 to upload sketches; needs raspi-config UART enable |

Option A removes every voltage-level risk — that's why the workshop uses it. Option B is
what the USB cable does underneath, minus the convenience.

**Option B setup** (only if you go that route):

```bash
sudo raspi-config   # Interface Options → Serial Port → login shell: No, hardware serial: Yes
sudo reboot         # afterwards the port is /dev/serial0
```

## 3. Permissions (fix this once)

`Permission denied` on the serial port is the #1 problem — your user must be in the
`dialout` group (Raspberry Pi OS puts `pi`-style users in it already):

```bash
groups                                   # must list dialout
sudo usermod -aG dialout $USER           # if missing — then log out and back in
```

## 4. The protocol (used by every later module)

Agree on the message format **before** writing code. Plain text, one message per line,
newline-terminated — readable in any serial monitor:

```
J,90,45,120,30\n   Pi → Nano   set angles: base, shoulder, elbow, gripper (degrees)
H\n                Pi → Nano   go to the home pose
OK\n               Nano → Pi   the move is finished
ERR\n              Nano → Pi   bad or out-of-range command
```

## 5. Arduino side: the echo sketch

[`code/02_uart/arduino_echo/arduino_echo.ino`](../code/02_uart/arduino_echo/arduino_echo.ino)
reads a line and answers `ACK:<line>` — the minimal "is anyone alive" test:

```cpp
void setup()  { Serial.begin(115200); }
void loop() {
  if (Serial.available()) {
    String line = Serial.readStringUntil('\n');
    Serial.print("ACK:");
    Serial.println(line);
  }
}
```

Upload it **without the Arduino IDE** — everything happens on the Pi:

```bash
# one-time tool install (already done on the workshop Pi)
curl -fsSL https://raw.githubusercontent.com/arduino/arduino-cli/master/install.sh | BINDIR=~/.local/bin sh
~/.local/bin/arduino-cli core install arduino:avr

# per sketch
scp -r code/02_uart/arduino_echo pi@raspberrypi.local:workshop/02_uart/
ssh pi@raspberrypi.local
~/.local/bin/arduino-cli compile --fqbn arduino:avr:nano ~/workshop/02_uart/arduino_echo
~/.local/bin/arduino-cli upload  -p /dev/ttyUSB0 --fqbn arduino:avr:nano ~/workshop/02_uart/arduino_echo
```

Nano notes:

- CH340 clones (our kit) appear as **`/dev/ttyUSB0`**; FTDI boards as `/dev/ttyACM0`.
- Upload says `not in sync`? Your clone has the **old bootloader** — add
  `:cpu=atmega328old` to the FQBN (`arduino:avr:nano:cpu=atmega328old`) for *both*
  compile and upload.
- Manual serial monitor: `~/.local/bin/arduino-cli monitor -c arduino:avr:nano -p /dev/ttyUSB0`
  (quit with Ctrl+C). Test there first, so you know which side is at fault later.

## 6. Pi side: send and receive

[`code/02_uart/pi_send.py`](../code/02_uart/pi_send.py) — the two lines that matter:

```python
import serial, time

ser = serial.Serial("/dev/ttyUSB0", 115200, timeout=1)  # CH340 Nano; ACM0 for FTDI/Uno
time.sleep(2)          # real: opening the port resets most boards
ser.write(b"J,90,45,120,30\n")
print(ser.readline().decode().strip())   # -> ACK:J,90,45,120,30
```

Run it on the Pi:

```bash
cd ~/workshop/02_uart && python3 pi_send.py
```

Expected output:

```
sent:     J,90,45,120,30
received: ACK:J,90,45,120,30
sent:     H
received: ACK:H
```

**Troubleshooting**

| Symptom | Fix |
|---|---|
| `Permission denied` | `dialout` group (section 3) |
| First command ignored | That's the port-open reset — keep the `sleep(2)` |
| Garbage reply | Baud mismatch — both sides must be 115200 |
| `Device or resource busy` | A monitor/IDE still holds the port — close it |

## 7. Challenge: Echo Duel (3 pts)

First team whose Arduino answers a Python-sent line correctly wins. Speed round: make
the Pi send `J,<random angles>` five times and check every reply matches.

## What you learned

- UART = two crossed wires, one agreed speed, a common ground.
- A protocol is just an agreement — plain text lines beat binary on a workshop day.
- Test each side alone before blaming the other.

Next: [Module 3 — the 4-DOF arm](03-arm.md)
