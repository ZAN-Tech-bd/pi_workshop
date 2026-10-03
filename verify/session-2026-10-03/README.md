# Session 2026-10-03 — all four dashboards verified (RC, Gesture, LLM; Arm Twin unchanged)

Bench: Pi 4B · trixie · the three-pilot rig (Color :8081 · Gesture :8083 ·
ZAN/LLM :8082) sharing one camera relay (:8000) and one Bluetooth car
(`ZAN_RC_Car 00:70:07:A3:1B:AE`). The Arm Twin (:8080) was checked unchanged
since the 2026-10-02 session (no files newer than that session's screenshots).

| Transcript | What it proves |
|---|---|
| `m8-api-v2.txt` | updated Color Pilot (:8081): live status incl. the car link + peer pilots, and the wake/sleep handover events in its log |
| `m9-api.txt` | Gesture Pilot (:8083) status: asleep/wake handshake, dry output, camera via the :8000 relay |
| `m9-selftest.txt` | `gestures.py --selftest`: all labelled MediaPipe hands OK, **taught 174/174**, non-hand + mirror-flip rejected — `selftest: PASS` |
| `m10-status-cold.txt` | ZAN Pilot (:8082) cold: qwen2.5:1.5b asleep, peers up, dry output |
| `m10-warm.txt` | `/api/warm` → `{"ok": true}`, model loading |
| `m10-chat.txt` | **the money shot**: `POST /api/chat {"text":"back up slowly"}` → SSE tokens assemble `{"action":"backward","speed":2}`; `done` event: dry-run flag, 69.9 s first (cold) turn, 2.3 tok/s |
| `m10-status-warm.txt` | after the turn: model `ready · warm (kept 24 h)`, event `"back up slowly" -> backward (dry run …)` |

Browser screenshots (Firefox on Xvfb, Selenium): `m9-dash-demo.png` (Demo
source driving Sense/Think/Act with the skeleton), `m9-library.png` (gesture
cards with live scores), `m10-idle.png` (page awake, car found over BT, model
warm), `m10-reply.png` (typed sentence → streamed reply → intent → ACTING
panel) — embedded in `docs/09-gesture-pilot.md` and `docs/10-zan-pilot-llm.md`.

Also this session: the deployed RC dashboard (Desktop copy, which runs on
:8081) was **ahead of the repo** — its server/index/static (car take/release,
wake/sleep, camera picking) were synced back into
`code/08_rc_car/dashboard/` so the repo is the source of truth again, matching
the already-updated `docs/08-rc-car.md`.

Note on the sleep protocol during capture: opening one pilot's page puts the
others asleep — an early LLM screenshot caught the "ASLEEP" card until the
capture was redone with :8082 as the only open page.
