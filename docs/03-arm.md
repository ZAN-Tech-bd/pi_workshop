# Module 3 — the 4-DOF arm on the Arduino

Slide 29 · Result: the arm moves to any joint angles you send, smoothly, with safe
limits, and answers `OK`.

> The deck keeps this module to one slide — this guide is the full version.

## 1. Why the arm gets its own brain

Linux is **not real-time**: it cannot guarantee clean 20 ms servo pulses, so servos
driven straight from the Pi jitter. The Arduino can — that's the whole "Pi sees,
Arduino moves" split (deck slide 11: *brain vs reflexes*).

## 2. Assembly + wiring

Four servos — base (rotation), shoulder, elbow, gripper:

| Joint | Nano signal pin | Servo wire color |
|---|---|---|
| Base | **D3** | orange / yellow (signal) |
| Shoulder | **D5** | orange / yellow |
| Elbow | **D6** | orange / yellow |
| Gripper | **D9** | orange / yellow |
| All | — | red (5–6 V) and brown/black (GND) go to the **servo supply**, not the Nano |

### Power — read this twice

- 4 servos can spike **2–3 A**. The Nano's 5 V pin and the Pi's 5 V pins cannot supply
  that — a weak supply makes servos twitch and the Pi **reboot** (top troubleshooting
  entry in the deck, slide 41).
- Use a separate **5–6 V ≥ 3 A** supply (or a 2S battery + UBEC).
- **Join all grounds:** supply GND, Nano GND, (and Pi GND if wired direct) must connect.
  Without a common ground the signal means nothing.
- The real emergency stop is your hand on the servo supply switch — keep it close.

```
 servo supply (+5-6V) ──┬── all servo red wires
                       │
 servo supply GND ─────┼── all servo brown wires ── Nano GND
                       │
 Nano D3/D5/D6/D9 ─────┴── servo signal wires (one pin per joint)
```

## 3. The firmware

[`code/03_arm/arm_firmware/arm_firmware.ino`](../code/03_arm/arm_firmware/arm_firmware.ino)
is deliberately thin — it only:

1. **parses** `J,b,s,e,g` or `H`
2. **validates**: unreadable or outside 0–180 → `ERR`
3. **clamps** each angle into that joint's safe range (edit `MIN_x/MAX_x` for your arm)
4. **ramps** all four servos together, one degree per `STEP_MS` (15 ms) — smooth, no jumps
5. answers **`OK`** only after the move completes, so the Pi can wait for it

Because the Arduino stays dumb, every later module (color actions, gestures, PickBot)
is just Python on the Pi — **no re-flashing while you tune**.

### Upload (our kit: CH340 Nano, old bootloader)

```bash
scp -r code/03_arm pi@raspberrypi.local:workshop/
ssh pi@raspberrypi.local
~/.local/bin/arduino-cli compile --fqbn arduino:avr:nano:cpu=atmega328old ~/workshop/03_arm/arm_firmware
~/.local/bin/arduino-cli upload -p /dev/ttyUSB0 --fqbn arduino:avr:nano:cpu=atmega328old ~/workshop/03_arm/arm_firmware
```

("new" Nanos/Unos: drop the `:cpu=atmega328old`. `not in sync: resp=0x00` during upload
means you need it — that's this kit.)

## 4. Test it

```bash
cd ~/workshop/03_arm && python3 arm_test.py | tee verify-arm.txt
```

Expected:

```
H                 -> OK
J,90,45,120,30    -> OK
J,120,90,90,30    -> OK
J,90,120,90,30    -> OK
J,90,90,140,30    -> OK
J,90,90,90,80     -> OK
H                 -> OK
J,200,90,90,30    -> ERR
J,90,90,90        -> ERR
HELLO             -> ERR
done
```

With the arm powered you'll also **see** each ramp move. Without servos attached, the
replies alone prove the protocol side — that's how we verified it before assembly.

## 5. Calibrate YOUR arm

```bash
python3 calibrate.py 90 90 90 50     # try poses one joint at a time
```

Write down:

- gripper fully open / closed (→ `HOME_G`, `MIN_G/MAX_G`)
- the level-over-table shoulder/elbow angles (→ `HOME_S`, `HOME_E`)
- base angle pointing at your bin

Then edit those constants at the top of the `.ino` and re-upload — 30 seconds.

**Safety while calibrating:** first runs with an **empty gripper**, one joint at a time,
other hand on the supply switch, and set a safe minimum height before any automated move
(deck slide 39).

## 6. Challenge: Smooth Operator (3 pts)

All four joints move through a full sequence with **no jitter and no brownouts**. Judge's
eye: a coin standing on the shoulder bracket survives the run.

## What you learned

- Real-time reflexes belong on the microcontroller, decisions on the Pi.
- Servo power is a power problem, not a code problem — common ground or nothing works.
- Clamp twice (Pi **and** Nano): every layer protects the hardware below it.

Next: [Module 4 — OpenCV basics](04-opencv.md)
