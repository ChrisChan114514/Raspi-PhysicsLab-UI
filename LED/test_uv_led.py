#!/usr/bin/env python3
"""Brief hardware test for one wavelength-lamp PWM output."""

from __future__ import annotations

import argparse
import time

from led_pwm import (
    BLUE_LED_BCM_GPIO,
    BLUE_LED_WIRINGPI_PIN,
    GREEN_LED_BCM_GPIO,
    GREEN_LED_WIRINGPI_PIN,
    UV_LED_BCM_GPIO,
    UV_LED_WIRINGPI_PIN,
    LedPwmConfig,
    PwmLed,
)


LAMPS = {
    "uv": ("400 nm UV", UV_LED_WIRINGPI_PIN, UV_LED_BCM_GPIO),
    "blue": ("450 nm blue", BLUE_LED_WIRINGPI_PIN, BLUE_LED_BCM_GPIO),
    "green": ("520 nm green", GREEN_LED_WIRINGPI_PIN, GREEN_LED_BCM_GPIO),
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Drive one wavelength lamp for a short PWM test."
    )
    parser.add_argument("--lamp", choices=tuple(LAMPS), default="uv")
    parser.add_argument("--duty", type=float, default=30.0)
    parser.add_argument("--seconds", type=float, default=3.0)
    parser.add_argument("--frequency", type=float, default=1000.0)
    parser.add_argument("--active-low", action="store_true")
    parser.add_argument("--debug", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not 0.0 <= args.duty <= 100.0:
        raise SystemExit("--duty must be in the range 0..100")
    if args.seconds <= 0:
        raise SystemExit("--seconds must be positive")

    lamp_name, wiringpi_pin, bcm_gpio = LAMPS[args.lamp]
    config = LedPwmConfig(
        wiringpi_pin=wiringpi_pin,
        bcm_gpio=bcm_gpio,
        frequency_hz=args.frequency,
        active_high=not args.active_low,
        initial_duty_percent=args.duty,
        debug=args.debug,
    )
    print(
        f"{lamp_name} LED: WiringPi {wiringpi_pin} -> BCM GPIO{bcm_gpio}, "
        f"duty={args.duty:g}%, "
        f"frequency={args.frequency:g} Hz, duration={args.seconds:g}s",
        flush=True,
    )
    with PwmLed(config) as led:
        led.set_enabled(True)
        time.sleep(args.seconds)
    print(f"{lamp_name} LED output is off.", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
