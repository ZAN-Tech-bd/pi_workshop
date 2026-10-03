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
| 7 | RC Color Pilot | [`code/07_rc_car/`](code/07_rc_car/) · [`docs/07-rc-car.md`](docs/07-rc-car.md) | new | Vision-driven RC car: 6 colors → 6 directions + dashboard (:8081) | Color Rally |
| 8 | Gesture Pilot | [`code/08_gesture_car/`](code/08_gesture_car/) · [`docs/08-gesture-pilot.md`](docs/08-gesture-pilot.md) | new | MediaPipe hand gestures drive the car; teach your own gestures + dashboard (:8083) | Gesture Slalom |
| 9 | ZAN Pilot (LLM) | [`docs/09-zan-pilot-llm.md`](docs/09-zan-pilot-llm.md) | new | English → on-Pi qwen2.5:1.5b → intent JSON → car key (:8082) | Prompt Golf |
| A | Arm Twin dashboard | [`docs/appendix-arm-dashboard.md`](docs/appendix-arm-dashboard.md) | new | 3D digital twin + controller for the arm (:8080) — appendix, not a module | — |

## Kit list

- Raspberry Pi (4B / 5 / Zero 2 W) + microSD + 5 V PSU
- Pi Camera Module (any libcamera-supported unit; tested: IMX219 / Camera v2)
- Arduino Nano (CH340 clones appear as `/dev/ttyUSB0`, FTDI as `/dev/ttyACM0`)
- 4-DOF arm kit: 4× servo (base, shoulder, elbow, gripper), separate 5–6 V ≥3 A supply
- LED + 330 Ω resistor, jumper wires, breadboard
- One colored glove for the gesture module (yellow by default)
- Props: one red and one blue object, green cubes for the finale

## The protocol (used from module 2 onward)

```
Pi → Nano : J,<base>,<shoulder>,<elbow>,<gripper>\n   angles in degrees
Pi → Nano : H\n                                      go to home pose
Nano → Pi : OK\n                                     move finished
Nano → Pi : ERR\n                                    bad or out-of-range command
115200 baud, 8N1, one message per line
```

Design rule of the whole course: **the brain lives on the Pi, the Nano stays thin.**
Modules 5–7 are pure Python — the firmware never changes while you tune behaviors.

## Verified on real hardware

Raspberry Pi 4B · Raspberry Pi OS trixie · Python 3.13 · OpenCV 4.10 · Arduino Nano
(CH340, old bootloader — upload FQBN `arduino:avr:nano:cpu=atmega328old`) · IMX219 via
libcamera/Picamera2. Every module's run transcript: [`verify/`](verify/). Re-verified
end-to-end on 2026-10-01 with a **screenshot for every micro-step**:
[`docs/images/`](docs/images/) — embedded at the matching steps of each module guide,
raw transcripts in [`verify/session-2026-10-01/`](verify/session-2026-10-01/)
Two bench findings worth knowing:

- **mediapipe 1.x SIGILLs on the Pi 4's Cortex-A72** — the gesture module therefore
  ships a dependency-free OpenCV **glove engine** (default) plus the MediaPipe Tasks
  engine for Pi 5.
- **Only one program opens the camera sensor** — if a camera app (e.g. a dashboard) is
  running, `camera.py` falls back to its MJPEG stream automatically (`CAMERA_URL`).

## The Pi dashboard family (boot services on the bench Pi)

| Port | Dashboard | Guide |
|---|---|---|
| :8000 | Camera MJPEG | its own README (`~/Desktop/camera-dashboard`) |
| :8080 | **Arm Twin** — 3D digital twin + controller for the module-3 arm | [`docs/09-arm-dashboard.md`](docs/09-arm-dashboard.md) |
| :8081 | **RC Color Pilot** — module 8's vision policy + teleop | [`docs/08-rc-car.md`](docs/08-rc-car.md) |
| :8083 | **Gesture Pilot** — module 9: hand gestures (built-in + taught) drive the car | [`docs/09-gesture-pilot.md`](docs/09-gesture-pilot.md) |
| :8082 | **ZAN Pilot** — module 10: English → on-Pi LLM → car key (user service) | [`docs/10-zan-pilot-llm.md`](docs/10-zan-pilot-llm.md) |

One serial port, one camera sensor — the dashboards share both by design: they
consume the camera as an MJPEG stream, and only one of them holds `/dev/ttyUSB0`
(the RC dashboard drops to dry-mode automatically; press **Disconnect** in the
Arm Twin before uploads or workshop scripts).
