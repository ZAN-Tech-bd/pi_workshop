#!/bin/bash
# Installs the Gesture Pilot dashboard the same way the other Pi dashboards
# live: a folder on the Desktop + a systemd service on port 8083.
#
#   bash install.sh              -> copies to ~/Desktop/gesture-dashboard (+ its venv)
#   sudo bash install.sh --service
#                                -> also installs+enables gesture-dashboard.service
#
# Co-exists with the other dashboards:
#   :8000 camera-dashboard · :8080 Arm Twin · :8081 RC Color Pilot · :8083 Gesture Pilot
# It reads the camera from the :8000 relay (never opens the sensor) and shares
# the ONE car with the Color Pilot: press "Take the car" on the page.
#
# Why a venv with Python 3.12 + mediapipe 0.10.18: the Pi 4's Cortex-A72 has
# no ARMv8 crypto extensions and mediapipe 1.x is built with them ("compiled
# with aes enabled" -> SIGILL). 0.10.18 is the newest aarch64 wheel that runs
# on a Pi 4, and it has no wheel for the system's Python 3.13 — uv fetches 3.12.

set -e
SRC="$(cd "$(dirname "$0")" && pwd)"            # code/08_gesture_car/dashboard
USER_HOME="$(getent passwd "${SUDO_USER:-$USER}" | cut -d: -f6)"
RUN_AS="${SUDO_USER:-$USER}"
DEST="$USER_HOME/Desktop/gesture-dashboard"
as_user() { if [ "$(id -un)" = "$RUN_AS" ]; then "$@"; else sudo -u "$RUN_AS" -H "$@"; fi; }

as_user mkdir -p "$DEST"
as_user cp "$SRC/server.py" "$SRC/gestures.py" "$SRC/carlink.py" "$SRC/index.html" "$DEST/"
rm -rf "$DEST/static" "$DEST/fixtures"
as_user cp -r "$SRC/static" "$SRC/fixtures" "$DEST/"
# $DEST/data/gestures.json (the gestures and examples edited on the page) is never touched

if [ ! -x "$DEST/.venv/bin/python" ]; then
  UV="$USER_HOME/.local/bin/uv"
  if [ ! -x "$UV" ]; then
    echo "== installing uv (Python manager) into ~/.local/bin"
    as_user sh -c 'curl -LsSf https://astral.sh/uv/install.sh | UV_NO_MODIFY_PATH=1 sh'
  fi
  echo "== creating the venv (Python 3.12 + mediapipe 0.10.18) — a few minutes on a Pi 4"
  as_user "$UV" venv --python 3.12 "$DEST/.venv"
  as_user "$UV" pip install --python "$DEST/.venv/bin/python" "mediapipe==0.10.18" pyserial
fi
as_user "$DEST/.venv/bin/python" "$DEST/gestures.py" --selftest | tail -1

as_user tee "$DEST/start.sh" >/dev/null <<'EOF'
#!/bin/bash
cd "$(dirname "$0")"
exec .venv/bin/python server.py --port 8083 "$@"
EOF
chmod +x "$DEST/start.sh"

as_user tee "$DEST/gesture-dashboard.service" >/dev/null <<EOF
[Unit]
Description=Gesture Pilot - MediaPipe hand gestures drive the RC car
After=network.target camera-dashboard.service

[Service]
Type=simple
WorkingDirectory=$DEST
ExecStart=$DEST/.venv/bin/python $DEST/server.py --port 8083
Restart=on-failure
RestartSec=3
User=$RUN_AS
Nice=5

[Install]
WantedBy=multi-user.target
EOF

as_user tee "$DEST/README.md" >/dev/null <<'EOF'
# Gesture Pilot (:8083)

MediaPipe hand gestures drive the ZAN TriBot — Module 8 of pi_workshop.
Deployed copy of code/08_gesture_car/dashboard from ZAN-Tech-bd/pi_workshop.
Source of truth: the repo; re-run its install.sh to refresh this copy.

Manual start : ./start.sh            (./start.sh --source demo  = no camera needed)
Service      : sudo systemctl restart gesture-dashboard
Status       : http://raspberrypi.local:8083/  (also /api/status, /snapshot.jpg)
Self-test    : .venv/bin/python gestures.py --selftest

Gestures (built-in rules and the ones you teach, with their examples), actions
and policy rules are edited on the page and saved in data/gestures.json
(Export/Import on the page; delete the file to get the starter set back).

Output starts OFF after every restart (dry run), and the car link starts
RELEASED: the car takes one Bluetooth driver at a time, and the Color Pilot
(:8081) normally holds it. "Take the car" asks :8081 to let go and connects
here; "Release the car" hands it back.

Camera: read from the camera-dashboard relay (http://127.0.0.1:8000/stream,
no parameters, so it never restarts the camera under the Color Pilot). The page
gets those frames passed straight through (full camera rate) and draws the
skeleton itself from /api/live; two MediaPipe workers analyse frames in parallel.

Safety: drive keys are re-sent every 250 ms while a gesture is held; no hand,
no matching gesture, or no fresh frame for 1 s -> S. Speed gestures fire once
and the car waits (S) while they are shown. Space/Esc on the page = output off.
EOF

echo "copied to $DEST"
if [ "$1" = "--service" ]; then
  cp "$DEST/gesture-dashboard.service" /etc/systemd/system/
  systemctl daemon-reload
  systemctl enable --now gesture-dashboard
  systemctl --no-pager --lines=3 status gesture-dashboard || true
else
  echo "to install the auto-start service:"
  echo "  sudo bash install.sh --service"
fi
