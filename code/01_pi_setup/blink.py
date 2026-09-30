"""Task 1.4 — Hello, hardware: blink an LED.

Wiring (deck slide 19):
    GPIO17 (physical pin 11) -> 330 ohm resistor -> LED long leg (+)
    LED short leg (-)        -> GND (physical pin 6)

Run on the Pi:
    python3 blink.py
Stop with Ctrl+C.
"""

from gpiozero import LED
from time import sleep

led = LED(17)  # GPIO number, not physical pin number

try:
    while True:
        led.on()
        sleep(0.5)
        led.off()
        sleep(0.5)
except KeyboardInterrupt:
    led.off()
    print("blink stopped")
