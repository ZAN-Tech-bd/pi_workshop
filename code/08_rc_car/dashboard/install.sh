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
# The car lamp shows "Car · not found" (dry run) while the only Nano is the
# arm's — the car gets its OWN Nano (a Nano is one brain at a time).

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
rm -rf "$DEST/static"
cp -r "$SRC/static" "$DEST/static"              # page script, styles, fonts
# $DEST/data/vision.json (the color classes edited on the page) is never touched

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

Color classes, actions and policy rules are edited on the page and saved in
data/vision.json (delete it to get the six course colors back).

Output starts OFF after every restart (dry run): switch it on in the page.

Serial: the car needs its OWN Arduino Nano running car_firmware.ino. The page
asks every free USB serial port "PING" and uses the one that answers "OK";
ports another program holds (the Arm Twin keeps the arm's Nano) are skipped.
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
