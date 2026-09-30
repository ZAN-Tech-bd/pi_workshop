# Module 4 — Computer vision with OpenCV

Slides 30–34 · Result: a live view where a colored object gets a red dot on its center,
printed as `(cx, cy)` pixel coordinates — the number module 5 feeds to the arm.

## 1. Every classical vision pipeline is four moves (slide 31)

1. **Capture** — read frames from the camera
2. **Preprocess** — blur if noisy, convert BGR → HSV
3. **Detect** — threshold a color range, clean the mask, find contours
4. **Locate** — take the biggest blob, compute its center in pixels

( Later you can swap move 3 for YOLO and the rest stays identical — deck slide 43. )

## 2. Camera first

```bash
rpicam-hello --list-cameras   # must list your camera, e.g. "0 : imx219"
```

Nothing listed → reseat the ribbon (power off first; blue tab toward the USB/Ethernet
side), and enable the camera in `sudo raspi-config` → Interfaces (module 1, step 6).

Our kit code ([`camera.py`](../code/04_opencv/camera.py)) uses the **Pi camera module via
Picamera2**, and falls back to a USB webcam (`cv2.VideoCapture(0)`) automatically — so the
same scripts work either way. Picamera2 hands out **RGB** frames, so `camera.py` converts
them to **BGR**: from there on, every script is standard OpenCV.

## 3. Live view ([`live_view.py`](../code/04_opencv/live_view.py))

```bash
python3 live_view.py
```

- Desktop/VNC: a `camera` window opens, **q** quits.
- SSH without a display: it saves `live_view_0..4.jpg` — the headless substitute for a
  window. Copy them to your laptop (`scp pi@raspberrypi.local:workshop/04_opencv/*.jpg .`)
  to see what the camera sees.

Two facts that surprise everyone once (slide 32 notes): OpenCV uses **BGR**, not RGB; and
a frame is just a NumPy array `(height, width, 3)`.

## 4. Why HSV beats BGR for finding color (slide 33)

In BGR, color and brightness are mixed — a shadow breaks your threshold. HSV separates
them: **H**ue is the color, **S**aturation the vividness, **V**alue the brightness.

OpenCV ranges: **H 0–179** (not 360!), S and V 0–255.

| Color | Hue |
|---|---|
| Red | 0–10 **and** 170–179 (red wraps around the circle — needs two ranges) |
| Orange | 11–25 |
| Yellow | 26–34 |
| Green | 35–85 |
| Blue | 100–130 |

Starting points only — your room light moves them.

## 5. The detection pipeline ([`color_track.py`](../code/04_opencv/color_track.py))

```python
hsv  = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
mask = cv2.inRange(hsv, (35, 80, 80), (85, 255, 255))   # green band
mask = cv2.erode(mask, None, iterations=2)              # remove speckle noise
mask = cv2.dilate(mask, None, iterations=2)             # grow the object back
cnts, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
if cnts:
    c = max(cnts, key=cv2.contourArea)                  # biggest blob wins
    if cv2.contourArea(c) > 500:                        # ignore tiny noise
        x, y, w, h = cv2.boundingRect(c)
        cx, cy = x + w // 2, y + h // 2                 # <- what module 5 needs
```

Run it:

```bash
python3 color_track.py --color green            # hold something green in view
python3 color_track.py --color red --seconds 10
```

Each second it prints `green center=(312, 240) area=8412` (or `not detected`), and
headless saves annotated snapshots `color_track_00.jpg …`.

## 6. Tuning under real light ([`hsv_tune.py`](../code/04_opencv/hsv_tune.py))

```bash
python3 hsv_tune.py               # desktop/VNC: trackbars + live mask window
python3 hsv_tune.py --headless    # SSH: prints mask pixels + center per frame
```

Move H/S/V min/max trackbars until **only your object is white in the mask** — then copy
those numbers into the `RANGES` table at the top of `color_track.py`. Ten minutes of
tuning saves an hour of "why is it detecting my red chair".

**Troubleshooting**

| Symptom | Fix |
|---|---|
| `not detected` constantly | Lighting or range — retune; check S/V mins aren't too high for a dark room |
| Detects the floor/wall too | Raise `MIN_AREA`, tighten S/V max, or lower camera exposure |
| Center jumps around | Object too small/glare — diffuse the light, get closer |
| `imshow` error over SSH | Expected headless — that's what the snapshot mode is for, or use VNC |

## 7. Challenge: Color Hunter (3 pts)

Track a green object under **classroom lights** for 10 straight seconds without one
`not detected` line. Hard mode: swap to red (remember: two ranges).

## What you learned

- Capture → preprocess → detect → locate: the skeleton of ALL classical vision.
- HSV separates color from brightness — that's why it wins over BGR.
- `(cx, cy)` in pixels is the bridge to robotics — next we make it *act* on it.

Next: [Module 5 — Example A: color → arm action](05-color-action.md)
