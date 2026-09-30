# Module 7 — PickBot: vision-guided pick-and-place finale

Slides 35–41 · Result: the arm finds a green cube on its own, picks it up, and drops it
in the bin. The whole day in one loop:

```
camera ──▶ green mask ──▶ (cx,cy) pixels ──▶ homography ──▶ (x,y) mm
        ──▶ solve_ik ──▶ J,b,s,e,g ──UART──▶ OK ──▶ grip/lift/bin/release
```

> **Status on our bench:** brain fully built and unit-verified (homography + IK
> selftests PASS, command sequences verified against the real Nano in modules 5–6).
> The physical run needs the arm rig assembled and calibrated — the three calibration
> steps below are exactly what remains.

## 1. Rig setup (slide 37)

- Camera **fixed above the workspace, looking straight down** — mounted on the arm
  frame or a stand. If it ever moves, recalibrate (step 2).
- Green cubes within arm reach; the bin inside the workspace, taped down.

## 2. Calibrate pixels → mm (once)

```bash
cd ~/workshop/07_pickbot
python3 calibrate_homography.py --selftest    # must PASS before you start
python3 calibrate_homography.py --capture     # saves calib_frame.jpg
# mark 4 table points (tape), measure them in mm from the base center,
# read the same points in pixels off the frame, then:
python3 calibrate_homography.py --px 102,88 540,92 548,410 96,402 \
                                --mm 80,-100 80,100 230,100 230,-100
# -> homography.npy ; the sanity line should name a plausible workspace point
```

The numbers above are examples — every team measures its own four points. A
homography is exact for a flat table + fixed camera; that's the whole trick.

## 3. Calibrate the arm (once)

- Edit `L1, L2, Z_BASE` at the top of [`ik.py`](../code/07_pickbot/ik.py) from a
  ruler: shoulder→elbow, elbow→gripper, pivot height over the table.
- `python3 ik.py` → the ik→fk round-trip must print **PASS** for every point.
- Tune `GRIP_OPEN/GRIP_CLOSED/HOME/BIN/Z_PICK` with module 3's `calibrate.py`.

## 4. Run it

```bash
python3 pickbot.py --simulate      # full brain, moves printed not sent
python3 pickbot.py                 # live — hand on the servo supply switch
```

The loop only acts after the cube is **stable for 10 frames** (slide 39), solves IK,
runs approach → grip → lift → bin → release → home with every step **waiting for OK**,
then counts the cube (slide 38's `move()` pattern exactly).

## 5. Robustness checklist before any demo (slide 39)

| Risk | Guard already in the code |
|---|---|
| flickering detection | 10-frame stability counter |
| angle out of range | clamped on the Pi (IK bounds) AND on the Nano (module 3) |
| Arduino stops answering | serial timeout in `Link`, `!! arm rejected` aborts the sequence |
| arm hits the table | `Z_PICK`/`Z_LIFT` from calibration; first runs with empty gripper |
| anything unexpected | your hand on the servo supply = the real e-stop |

Rehearse the full loop **three times** before showing anyone — most demo failures are
timing or power, not vision (slide 39 notes).

## 6. Grand finale: the 60-second relay (slide 40)

1. Line up five green cubes on the table.
2. Press start — nobody touches the arm.
3. Most cubes in the bin after 60 seconds wins.
4. Dropped cube or collision doesn't count.
5. Bonus: name your robot before the run — winners' name sticks.

## What you learned (the whole day, slide 42)

Linux brain + microcontroller reflexes + a plain-text protocol + classical vision +
two calibration transforms = a robot. Same skeleton scales to ArUco markers and YOLO
(next steps, slide 43) without changing the shape of the system.
