# Verification — every task ran on real hardware

Bench: Raspberry Pi 4 Model B (Debian 13 trixie, Python 3.13) + Arduino Nano (CH340,
old bootloader, `/dev/ttyUSB0`) + Pi Camera v2 (IMX219). Date: 2026-09-30 (UTC).

| File | Module | What it proves |
|---|---|---|
| [`verify-echo.txt`](verify-echo.txt) | 2 — UART | Pi sent `J,90,45,120,30` / `H`, Nano answered `ACK:…` both times |
| [`verify-arm.txt`](verify-arm.txt) | 3 — arm firmware | `H` + 6 valid `J,…` → `OK`; 200° / missing angle / garbage → `ERR` |
| [`verify-pipeline.txt`](verify-pipeline.txt) | 4 — OpenCV | red (both hue ranges), blue, green found at exact expected centers — ALL PASS |
| [`verify-color-action.txt`](verify-color-action.txt) | 5 — Example A | red → action 1, blue → action 2; 18 commands, every one answered `OK` by the Nano |
| [`verify-gestures.txt`](verify-gestures.txt) | 6 — Example B | blob classifier 4/4 (fist/palm/pinch/point) + all four command sequences `OK` |
| [`verify-ik.txt`](verify-ik.txt) | 7 — PickBot | IK↔FK round-trip on 4 targets; out-of-reach and singularity rejected — PASS |
| [`verify-homography.txt`](verify-homography.txt) | 7 — PickBot | 4 pixel corners → exact mm; center sanity (155,0) — PASS |
| [`frames/`](frames/) | 4 | real camera frames through the MJPEG stream (night-time bench scene) |

## Verified live vs pending hardware

**Verified live (software + serial end-to-end):** OS setup, library installs, LED
script run, sketch upload, UART both directions, arm firmware protocol, camera
capture, color pipeline, both example brains, IK and homography math.

**Pending physical items** (need parts on the bench, not code):

- LED blink witnessed with eyes (script ran clean; no LED wired during the session)
- servo motion / smooth ramps / calibration offsets (arm frame + servos + supply)
- glove gestures live in daylight (selftest passed; bench was dark, no glove)
- PickBot full pick-run (needs the assembled rig + the 3 calibration steps in
  docs/07-pickbot.md — homography.npy on the bench Pi currently holds EXAMPLE values)
