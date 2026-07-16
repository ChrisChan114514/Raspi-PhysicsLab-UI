#!/usr/bin/env python3
"""Scan ADS1256 AIN0..AIN7 single-ended voltages."""

from __future__ import annotations

import argparse
import time

from ads1256_bitbang import (
    ADS1256BitBang,
    DRATE_100SPS,
    PGA_1,
    raw_to_voltage,
)
from check_connection import make_pins


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Scan ADS1256 single-ended channels.")
    parser.add_argument(
        "--numbering",
        choices=("wiringpi", "bcm"),
        default="wiringpi",
        help="Interpret the fixed ADS1256 pin map as WiringPi or BCM numbers. Default: wiringpi",
    )
    parser.add_argument("--gpiochip", type=int, default=0, help="lgpio chip number")
    parser.add_argument("--vref", type=float, default=2.5, help="Reference voltage. Default: 2.5 V")
    parser.add_argument("--interval", type=float, default=0.5, help="Scan interval. Default: 0.5 s")
    parser.add_argument("--discard", type=int, default=2, help="Discard reads after channel switch. Default: 2")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    pins = make_pins(args.numbering)

    print("Scanning AIN0..AIN7 single-ended. Values are AINx - AINCOM.")
    print("Press Ctrl+C to stop.")

    try:
        with ADS1256BitBang(pins=pins, gpiochip=args.gpiochip) as adc:
            while True:
                values = []
                for channel in range(8):
                    adc.configure_single_ended(
                        channel=channel,
                        pga=PGA_1,
                        drate=DRATE_100SPS,
                        selfcal=(channel == 0),
                    )
                    for _ in range(args.discard):
                        adc.read_single_raw()
                    raw = adc.read_single_raw()
                    voltage = raw_to_voltage(raw, vref=args.vref, pga=PGA_1)
                    values.append(f"AIN{channel}={voltage:+.5f}V")

                print("  ".join(values), flush=True)
                time.sleep(args.interval)
    except KeyboardInterrupt:
        print("\nSTOP")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
