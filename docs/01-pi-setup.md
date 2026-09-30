# Module 1 — Getting started with Raspberry Pi

Slides 16–19 · Result: a Pi you can log into from your laptop, with an LED you control from Python.

This guide starts from **zero** (fresh Pi, nothing installed). Our workshop Pi was already
set up this way — these are the exact steps, so nothing is missing.

## 1. What you need

- Raspberry Pi (4B, 5, or Zero 2 W) + official 5 V power supply
- microSD card (16 GB+, class 10)
- A laptop with an SD card reader (or a USB adapter)
- LED, 330 Ω resistor, 2 jumper wires (female–female or via breadboard)

## 2. Flash the SD card (on your laptop)

1. Install **Raspberry Pi Imager**: <https://www.raspberrypi.com/software/>
2. Choose:
   - **Device**: your Pi model
   - **OS**: Raspberry Pi OS (64-bit)
   - **Storage**: your microSD card
3. Click **Next → Edit Settings** and fill in the **OS Customisation** (this replaces all
   the old manual tricks):
   - **General**: set hostname (e.g. `workshop-pi`), username + password (write them down!)
   - **General**: tick *Configure wireless LAN* → your Wi-Fi name (SSID) + password, and
     your country code (e.g. `BD`)
   - **Services**: tick *Enable SSH* → *Use password authentication*
4. Save, confirm the warning that the card will be erased, and wait for the write.

## 3. First boot

1. Put the SD card in the Pi, connect power (and Ethernet if you use it instead of Wi-Fi).
2. Wait **about a minute** — first boot is slower (it resizes the card and generates keys).
3. No monitor needed: everything below happens from your laptop.

## 4. Connect over SSH

Find the Pi at `raspberrypi.local` (or the hostname you set, e.g. `workshop-pi.local`):

```bash
ssh pi@raspberrypi.local     # Linux / macOS terminal, Windows PowerShell — same command
```

- Answer `yes` to the fingerprint question (first time only).
- Type the password you set in Imager. You're in when the prompt reads `pi@raspberrypi:~ $`.

**Troubleshooting**
- `Could not resolve hostname` → Pi and laptop must be on the same network; try
  `ping raspberrypi.local`; as a fallback find the Pi's IP in your router's device list
  and `ssh pi@<IP>`.
- `Permission denied` → wrong username/password; re-flash is faster than guessing.
- Wi-Fi country must be set or Wi-Fi stays off — that's why Imager asks for it.

## 5. Update and install what the course needs

```bash
sudo apt update
sudo apt full-upgrade -y          # can take several minutes — start it early
sudo apt install -y python3-opencv python3-serial python3-gpiozero
```

`gpiozero` ships with Raspberry Pi OS already; installing it again is harmless. Check:

```bash
python3 -c 'import cv2, serial, gpiozero; print("cv2", cv2.__version__, "| pyserial", serial.__version__, "| gpiozero OK")'
```

Expected on Raspberry Pi OS (trixie): `cv2 4.10.0 | pyserial 3.5 | gpiozero OK`.

## 6. Enable the camera (needed from module 4)

```bash
sudo raspi-config            # Interfaces → Camera → enable, then reboot
rpicam-hello --list-cameras  # after reboot: must list your camera (e.g. imx219)
```

If your camera doesn't appear: power off, reseat the ribbon (blue tab toward the
Ethernet/USB side, contacts toward the HDMI side), and check it clicked in on both ends.

## 7. Hello, hardware: blink an LED

**Wiring** (pay attention: GPIO pins are 3.3 V only — never wire 5 V to a GPIO pin):

```
GPIO17  (physical pin 11) ──[330 Ω]──▶|── GND (physical pin 6)
                                LED long leg (+) is the one after the resistor
```

Copy the course code to the Pi (from your laptop, in the folder where you cloned this repo):

```bash
scp -r code/01_pi_setup pi@raspberrypi.local:workshop/
```

Then on the Pi:

```bash
cd ~/workshop/01_pi_setup
python3 blink.py
```

The LED blinks twice per second. Stop with **Ctrl+C** (the script turns the LED off and
exits cleanly). The whole program:

```python
from gpiozero import LED
from time import sleep

led = LED(17)          # GPIO number, not the physical pin number!

try:
    while True:
        led.on();  sleep(0.5)
        led.off(); sleep(0.5)
except KeyboardInterrupt:
    led.off()
    print("blink stopped")
```

**Troubleshooting**
- LED never lights → it's backwards (long leg must be on the resistor/GPIO17 side), or
  you used physical pin 17 instead of GPIO17 — use pin **11** (which *is* GPIO17).
- `PermissionError` on GPIO → you're not on Raspberry Pi OS or not in the `gpio` group.

## 8. Challenge: Blink Race (3 pts)

First team with a blinking LED **and** a working SSH login wins. Speed-round: change the
delay to 0.1 s, then make a heartbeat pattern (short-short-long).

## What you learned

- A Pi is a real Linux computer you can drive headlessly over SSH.
- Imager settings (user/Wi-Fi/SSH) replace all manual config files.
- GPIO pins are how Linux touches the physical world — safely at 3.3 V.

Next: [Module 2 — UART: Pi to Arduino](02-uart.md)
