#!/usr/bin/env python3
"""Brief hardware test for the ultraviolet LED PWM output."""

from __future__ import annotations

import argparse
import time

from led_pwm import LedPwmConfig, PwmLed


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Drive the UV lamp on WiringPi pin 8 for a short test."
    )
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

    config = LedPwmConfig(
        frequency_hz=args.frequency,
        active_high=not args.active_low,
        initial_duty_percent=args.duty,
        debug=args.debug,
    )
    print(
        f"UV LED: WiringPi 8 -> BCM GPIO2, duty={args.duty:g}%, "
        f"frequency={args.frequency:g} Hz, duration={args.seconds:g}s",
        flush=True,
    )
    with PwmLed(config) as led:
        led.set_enabled(True)
        time.sleep(args.seconds)
    print("UV LED output is off.", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
