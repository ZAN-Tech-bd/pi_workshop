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
| [`verify-rc-selftest.txt`](verify-rc-selftest.txt) | 7 — RC Color Pilot | 6/6 color→direction classifier + `PING` link check — PASS |
| [`verify-rc-protocol.txt`](verify-rc-protocol.txt) | 7 — RC Color Pilot | `PING→OK`, `D,120,-120→OK`, `D,999,0→ERR` |
| [`verify-rc-dashboard.txt`](verify-rc-dashboard.txt) | 7 — RC Color Pilot | mode toggle, key dispatch, event log, snapshot served |
| [`frames/`](frames/) | 4+ | real camera frames through the MJPEG stream |

> The vision-guided pick-and-place finale originally drafted as a PickBot module was
> **cancelled and removed from the course** before the workshop.

## Re-verified 2026-10-01 — with per-step screenshots

Every module was re-run end-to-end on the same bench from a clean clone.
Terminal screenshots for each micro-step live in
[`docs/images/`](../docs/images/) (embedded at the matching steps of each
module guide); the raw transcripts behind them are in
[`session-2026-10-01/`](session-2026-10-01/). Outcome: every module behaved
exactly as documented (see the session table).

## Verified 2026-10-02 — both web dashboards live, with browser screenshots

Module 7's **RC Color Pilot** (:8081) and the **Arm Twin** (:8080) verified as
running boot-services with real browser screenshots of every view (Firefox on
Xvfb + llvmpipe GL, Selenium-driven tab clicks) — embedded in
[`docs/07-rc-car.md`](../docs/07-rc-car.md) and
[`docs/appendix-arm-dashboard.md`](../docs/appendix-arm-dashboard.md); raw
transcripts in [`session-2026-10-02/`](session-2026-10-02/). Highlights: vision
policy live at ~8.5 fps with `red -> F` / `orange -> G` events, REST switch to
MANUAL, `/snapshot.jpg` serving annotated frames, the Arm Twin connected to the
module-3 firmware with live mm readouts on all four tabs, and the port-sharing
rule demonstrated live (RC dashboard in its documented dry-mode while the Arm
Twin holds `/dev/ttyUSB0`).

## Verified 2026-10-03 — the four-port rig (8000 · 8080–8083)

The rig grew to **three pilots sharing one Bluetooth car** (Color :8081 ·
Gesture :8083 · ZAN LLM :8082) plus the unchanged Arm Twin (:8080). Verified
with transcripts and browser screenshots in
[`session-2026-10-03/`](session-2026-10-03/), embedded in
[`docs/08-gesture-pilot.md`](../docs/08-gesture-pilot.md) (module 8, new) and
[`docs/09-zan-pilot-llm.md`](../docs/09-zan-pilot-llm.md) (module 9, new).
Highlights: gesture selftest PASS (174/174 taught, non-hand + mirror
rejected); the LLM pilot parsed `"back up slowly"` → `{"action":"backward",
"speed":2}` live over SSE on the Pi's own qwen2.5:1.5b; the wake/sleep + car
handover between the three pilots observed in every status log; and the
deployed-but-newer RC dashboard code synced back into the repo.

## Verified live vs pending hardware

**Verified live (software + serial end-to-end):** OS setup, library installs, LED
script run, sketch upload, UART both directions, arm firmware protocol, camera
capture, color pipeline, both example brains, the RC car's classifier and
protocol, and all three dashboards.

**Pending physical items** (need parts on the bench, not code):

- LED blink witnessed with eyes (script ran clean; no LED wired during the session)
- servo motion / smooth ramps / calibration offsets (arm frame + servos + supply)
- glove gestures live in daylight (selftest passed; bench was dark, no glove)
- RC car driving on its own wheels (kit chassis; wheels-off-ground test first)
