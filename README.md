# Pi Workshop — from Raspberry Pi to Robot Vision

Hands-on course: build a vision-guided 4-DOF pick-and-place robot arm. A Raspberry Pi
**sees** (OpenCV) and **decides** (Python), an Arduino Nano **moves** (servos), and UART
is the wire between brain and muscle.

Companion slide deck: *Pi to Robot Vision Workshop* (ZAN Tech BD).

## Course map — do the folders in order

| # | Module | Repo folder | Slides | What you build | Challenge |
|---|--------|-------------|--------|----------------|-----------|
| 1 | Meet the Pi / setup | [`code/01_pi_setup/`](code/01_pi_setup/) · [`docs/01-pi-setup.md`](docs/01-pi-setup.md) | 16–19 | Flash OS, SSH in, blink an LED | Blink Race |
| 2 | UART: Pi ↔ Arduino | [`code/02_uart/`](code/02_uart/) · [`docs/02-uart.md`](docs/02-uart.md) | 20–26 | Text protocol + echo round-trip | Echo Duel |
| 3 | 4-DOF arm firmware | [`code/03_arm/`](code/03_arm/) · [`docs/03-arm.md`](docs/03-arm.md) | 29 | Servo controller that obeys `J,...` | Smooth Operator |
| 4 | OpenCV basics | [`code/04_opencv/`](code/04_opencv/) · [`docs/04-opencv.md`](docs/04-opencv.md) | 30–34 | Find a colored object's center | Color Hunter |
| 5 | Example A: color → action | [`code/05_color_action/`](code/05_color_action/) · [`docs/05-color-action.md`](docs/05-color-action.md) | new | Red → arm action 1, blue → action 2 | — |
| 6 | Example B: gesture → command | [`code/06_gestures/`](code/06_gestures/) · [`docs/06-gestures.md`](docs/06-gestures.md) | new | Fist/palm/pinch/point steer the arm | — |
| 7 | PickBot finale | [`code/07_pickbot/`](code/07_pickbot/) · [`docs/07-pickbot.md`](docs/07-pickbot.md) | 35–41 | Full see→pick→place loop | 60-second relay |

## Kit list

- Raspberry Pi (4B / 5 / Zero 2 W) + microSD + 5 V PSU
- Pi Camera Module (any libcamera-supported unit; tested: IMX219 / Camera v2)
- Arduino Nano (CH340 clones appear as `/dev/ttyUSB0`, FTDI as `/dev/ttyACM0`)
- 4-DOF arm kit: 4× servo (base, shoulder, elbow, gripper), separate 5–6 V ≥2 A supply
- LED + 330 Ω resistor, jumper wires, breadboard
- Props: one red and one blue object (cube/ball), green cubes for the finale

## The protocol (used from module 2 onward)

```
Pi → Nano : J,<base>,<shoulder>,<elbow>,<gripper>\n   angles in degrees
Pi → Nano : H\n                                      go to home pose
Nano → Pi : OK\n                                     move finished
Nano → Pi : ERR\n                                    bad or out-of-range command
115200 baud, 8N1, one message per line
```

## Tested on

- Raspberry Pi OS **Debian 13 (trixie)**, kernel 6.18, Python 3.13, OpenCV 4.10
- Arduino Nano (CH340, old bootloader) over `/dev/ttyUSB0`
- Camera: IMX219 via libcamera/Picamera2

Verified task-by-task — transcripts and saved frames in [`verify/`](verify/).
