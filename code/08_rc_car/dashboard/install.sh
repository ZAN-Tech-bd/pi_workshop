#!/bin/bash
# Installs the RC Color Pilot dashboard the same way the other Pi dashboards
# live: a folder on the Desktop + a systemd service on port 8081.
#
#   bash install.sh              -> copies to ~/Desktop/rc-dashboard
#   sudo bash install.sh --service
#                                -> also installs+enables rc-dashboard.service
#
# Co-exists with the other dashboards:
#   :8000 camera-dashboard · :8080 Arm Twin · :8081 RC Color Pilot
# The serial pill shows "serial off (dry)" while the Arm Twin holds the
# USB port — the car gets its OWN Nano (a Nano is one brain at a time).

set -e
SRC="$(cd "$(dirname "$0")" && pwd)"            # code/08_rc_car/dashboard
MOD="$SRC/.."
OPEC="$SRC/../../04_opencv"
DEST="$HOME/Desktop/rc-dashboard"

mkdir -p "$DEST"
cp "$SRC/server.py" "$SRC/index.html" \
   "$MOD/vision_drive.py" \
   "$OPEC/camera.py" "$OPEC/color_track.py" \
   "$DEST/"

cat > "$DEST/start.sh" <<'EOF'
#!/bin/bash
cd "$(dirname "$0")"
exec python3 server.py --port 8081
EOF
chmod +x "$DEST/start.sh"

cat > "$DEST/rc-dashboard.service" <<'EOF'
[Unit]
Description=RC Color Pilot - 6-color vision policy dashboard
After=network.target

[Service]
Type=simple
WorkingDirectory=/home/pi/Desktop/rc-dashboard
ExecStart=/usr/bin/python3 /home/pi/Desktop/rc-dashboard/server.py --port 8081
Restart=on-failure
RestartSec=3
User=pi

[Install]
WantedBy=multi-user.target
EOF

cat > "$DEST/README.md" <<'EOF'
# RC Color Pilot (:8081)

6-color vision policy dashboard — Pi sees, Nano drives.
Deployed copy of code/08_rc_car/dashboard from ZAN-Tech-bd/pi_workshop.
Source of truth: the repo; re-run its install.sh to refresh this copy.

Manual start : ./start.sh
Service      : sudo systemctl restart rc-dashboard
Status       : http://raspberrypi.local:8081/  (also /api/status, /snapshot.jpg)

Serial: the car needs its OWN Arduino Nano. While the Arm Twin service holds
/dev/ttyUSB0, this dashboard runs vision-only ("serial off (dry)") — stop the
arm service or plug in the car's Nano to drive for real.
EOF

echo "copied to $DEST"

if [ "$1" = "--service" ]; then
  cp "$DEST/rc-dashboard.service" /etc/systemd/system/
  systemctl daemon-reload
  systemctl enable --now rc-dashboard
  systemctl --no-pager --lines=3 status rc-dashboard || true
else
  echo "to install the auto-start service:"
  echo "  sudo bash install.sh --service"
fi
