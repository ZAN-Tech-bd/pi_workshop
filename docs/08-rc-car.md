# Module 8 — RC Color Pilot: a vision-driven robot car

NEW project (RC Car 101 kit + everything from modules 1–7) · Result: show a colored
card to the car's camera and it drives — 6 colors, 6 directions, live dashboard.

## The AI you are actually teaching (say these words)

This car is an **autonomous agent** running the **sense–think–act loop** — the same
architecture as a self-driving car, at toy scale:

| Stage | What happens here | AI vocabulary |
|---|---|---|
| Sense | camera frame | **observation** |
| Think (perception) | HSV mask per pixel → biggest blob + centroid | **pixel-level color segmentation** (a *rule-based classifier*), then **object detection & localization** |
| Think (decision) | color → driving command table | **policy** — a **rule-based / reactive agent** |
| Act | `F`/`B`/`L`/`R`… over UART → motors | action |
| Stability | color must hold 8 frames | **temporal smoothing / debouncing** |

The honest one-liner: *the pipeline shape is identical to deep learning — input →
features → classification → decision → action — we tune the classifier by hand (HSV
thresholds) instead of by gradient descent.* Swap the threshold classifier for a
trained detector later and nothing else changes.

## Hardware — the RC Car 101 kit

Arduino Nano (or Uno) · L298N motor driver · 4× DC motors + wheels · chassis ·
battery pack · Raspberry Pi + camera mounted on the car (Pi powered by its own
pack/bank).

⚠️ A Nano is a one-role brain: the PickBot arm Nano runs arm firmware, the car Nano
runs car firmware. Two projects, two Nanos (or re-flash when you switch).

### Wiring (L298N → Arduino, from the RC-101 guide)

| L298N | Arduino | Job |
|---|---|---|
| ENA | D5 | left-side speed (PWM) |
| IN1 / IN2 | D6 / D7 | left-side direction |
| IN3 / IN4 | D8 / D9 | right-side direction |
| ENB | D10 | right-side speed (PWM) |
| GND | GND | common ground with the battery − |

Left two motors parallel on OUT1/2, right pair on OUT3/4. Motors run on their own
battery — never from the Arduino 5 V pin.

## Firmware — RC-101 evolved

[`code/08_rc_car/car_firmware/car_firmware.ino`](../code/08_rc_car/car_firmware/car_firmware.ino)
keeps everything from the RC-101 phone-app code (same `F B L R G I H J S 1-9 q` keys,
same pins) and adds what a robot with a brain needs:

1. a **line protocol** for the Pi: `D,<left>,<right>` (−255..255, replies `OK`/`ERR`),
   `PING` → `OK`
2. **clamping** of every value
3. a **fail-safe**: no command for 900 ms → motors stop. A moving robot must never
   keep driving when its brain goes quiet.

Upload (Pi USB; HC-05 unplugged if fitted — same warning as RC-101):

```bash
scp -r code/08_rc_car pi@raspberrypi.local:workshop/
ssh pi@raspberrypi.local
~/.local/bin/arduino-cli compile --fqbn arduino:avr:nano:cpu=atmega328old ~/workshop/08_rc_car/car_firmware
~/.local/bin/arduino-cli upload  -p /dev/ttyUSB0 --fqbn arduino:avr:nano:cpu=atmega328old ~/workshop/08_rc_car/car_firmware
```

Using the HC-05 phone app instead of the Pi? Set `BAUD 9600` in the sketch header.

## The policy — 6 colors → 6 directions

| Card | Key | Action | | Card | Key | Action |
|---|---|---|---|---|---|---|
| 🔴 red | `F` | forward | | 🟢 green | `L` | left |
| 🔵 blue | `B` | backward | | 🟡 yellow | `R` | right |
| 🟠 orange | `G` | front-left | | 🟣 purple | `I` | front-right |
| nothing in view | `S` | stop | | | | |

The letters are literally the RC-101 app's keys — one firmware, two brains (phone or
Pi). Tune shades with module 4's `hsv_tune.py`; print a card set in these six colors.

## Run it

```bash
cd ~/workshop/08_rc_car
python3 vision_drive.py --selftest     # 6/6 classifier + PING + all keys sent
python3 vision_drive.py --dry-run      # camera in, commands printed
python3 vision_drive.py                # live: cards drive the car
python3 dashboard/server.py            # the dashboard (below)
```

## The dashboard — http://raspberrypi.local:8081/

Third member of the Pi dashboard family (8000 camera · 8080 Arm Twin · 8081 this):

- live annotated video — the frame **with the policy's verdict drawn on it**
- big "seeing" chip: current color → key → direction, with the frame streak
- **AUTO / MANUAL** toggle
- **teleop D-pad** (G F I / L S R / H B J) — press-and-hold drives, release stops;
  cruise-speed slider (1–9). MANUAL sends the same RC-101 keys as the app
- the policy table and a live event log (what was sent, when)
- serial not connected? It still runs as a vision demo ("serial off (dry)")

REST API for experiments: `/api/status`, `/api/cmd?k=F`, `/api/mode?m=manual`,
`/api/speed?n=5`, `/snapshot.jpg`, `/stream` (MJPEG).

## Testing procedure (in this order)

| Step | Command / action | Pass when |
|---|---|---|
| 1 | `python3 vision_drive.py --selftest` | 6× `classifier: … OK`, `link PING: OK`, `PASS` |
| 2 | dashboard up, open 8081 | video shows, "camera ok" pill green |
| 3 | MANUAL + hold F (car wheels OFF the ground) | event log `TX F`, wheels forward |
| 4 | release button | wheels stop (fail-safe backs you up too) |
| 5 | AUTO + red card in view | chip turns red, `policy: red -> F` in the log |
| 6 | walk through all six cards | each direction fires once, holds while held |
| 7 | remove cards | `nothing -> S`, car stops |

## Safety

First tests **wheels-off-ground** (car on a stand/cup). Speed slider low. The
firmware fail-safe stops the car whenever commands stop — the browser D-pad relies on
it when a button press is missed. Batteries out before wiring changes.

## Challenge: Color Rally

Lay out a course; a "traffic controller" student guides each car **only with color
cards** — no touching, no phone. Fastest clean lap wins. Bonus round: two controllers,
two cards at once — what should the policy do? (Answer: biggest blob wins — discuss
why as a class.)

## What you learned

- The sense–think–act loop is one file of Python plus one thin firmware.
- A policy is a table; changing behavior is editing the table.
- Fail-safes are what make autonomy safe enough to demo.

Predecessors: [Module 7 — PickBot](07-pickbot.md) · [Module 4 — OpenCV](04-opencv.md)
