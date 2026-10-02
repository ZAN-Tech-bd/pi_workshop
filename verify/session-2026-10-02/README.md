# Session 2026-10-02 — RC Color Pilot + Arm Twin dashboards verified with screenshots

Bench: Raspberry Pi 4B · trixie · Python 3.13 · IMX219 (via the camera
dashboard's MJPEG stream) · one CH340 Nano running the **workshop arm firmware**
(held by `arm-dashboard.service` on `/dev/ttyUSB0`).

Browser screenshots were taken of the **live services** (Firefox on Xvfb with
Mesa llvmpipe GL — the Pi has no desktop session; Selenium/geckodriver drove
real tab clicks). Terminal shots are rendered from these raw transcripts.

| Transcript / evidence | What it proves |
|---|---|
| `m8-service.txt` | `rc-dashboard.service` active on :8081 |
| `m8-api.txt` | `/api/status`: mode auto, ~8.5 fps, camera ok, serial dry, event log `policy: red -> F`, `orange -> G`, `nothing -> S` |
| `m8-snapshot.txt` | `/snapshot.jpg` serves `200 image/jpeg` (annotated frame) |
| `m8-selftest.txt` | classifier 6/6, all 6 keys TX'd; `link PING: NO REPLY` — the bench Nano runs ARM firmware and the port is held by the arm dashboard (the guide's two-Nano caveat, live) |
| `arm-service.txt` | `arm-dashboard.service` active on :8080, auto-connected: `Workshop arm firmware on /dev/ttyUSB0, channels B S E G` |

Screenshot set (in [`docs/images/`](../../docs/images/)):

- `m8-dash-auto.png` / `m8-dash-manual.png` / `m8-dash-phone.png` — the RC
  dashboard live in both modes plus the phone layout (mode switched over the
  documented REST API)
- `m8-snapshot.jpg` — one annotated frame from `/snapshot.jpg`
- `arm-dash-axes|tool|teach|setup.png` — the Arm Twin with the 3D model
  rendered (llvmpipe), live TCP readouts, all four tabs clicked for real

Notable interactions verified live:

- only one program can hold `/dev/ttyUSB0` — the arm dashboard keeps it, the RC
  dashboard degrades to dry-mode automatically (its status shows
  `serial off (dry)`), and workshop scripts would need the Disconnect button
- camera sharing works as designed: both dashboards consume the :8000 MJPEG
  stream instead of opening the sensor
