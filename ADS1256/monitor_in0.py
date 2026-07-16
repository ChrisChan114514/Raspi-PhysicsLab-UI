#!/usr/bin/env python3
"""Print ADS1256 AIN0 millivolts and signed raw value every 0.5 seconds."""

from __future__ import annotations

import argparse
import time

from ads1256_bitbang import (
    ADS1256BitBang,
    ADS1256Pins,
    ADS1256ProtocolError,
    DRATE_10SPS,
    DRATE_100SPS,
    DRATE_1000SPS,
    DRATE_15SPS,
    DRATE_2SPS,
    DRATE_30SPS,
    DRATE_50SPS,
    DRATE_5SPS,
    DRATE_60SPS,
    DRATE_500SPS,
    PGA_1,
    PGA_16,
    PGA_2,
    PGA_32,
    PGA_4,
    PGA_64,
    PGA_8,
)
from check_connection import make_pins


DRATE_BY_NAME = {
    "1000": DRATE_1000SPS,
    "500": DRATE_500SPS,
    "100": DRATE_100SPS,
    "60": DRATE_60SPS,
    "50": DRATE_50SPS,
    "30": DRATE_30SPS,
    "15": DRATE_15SPS,
    "10": DRATE_10SPS,
    "5": DRATE_5SPS,
    "2": DRATE_2SPS,
}

PGA_BY_GAIN = {
    1: PGA_1,
    2: PGA_2,
    4: PGA_4,
    8: PGA_8,
    16: PGA_16,
    32: PGA_32,
    64: PGA_64,
}

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Monitor ADS1256 AIN0 and print only mV and RAW values."
    )
    parser.add_argument(
        "--numbering",
        choices=("wiringpi", "bcm"),
        default="wiringpi",
        help="Interpret the fixed ADS1256 pin map as WiringPi or BCM numbers. Default: wiringpi",
    )
    parser.add_argument("--gpiochip", type=int, default=0, help="lgpio chip number")
    parser.add_argument(
        "--interval",
        type=float,
        default=0.5,
        help="Print interval in seconds. Default: 0.5",
    )
    parser.add_argument(
        "--vref",
        type=float,
        default=2.5,
        help="ADS1256 reference voltage. Default: 2.5 V",
    )
    parser.add_argument(
        "--drate",
        choices=tuple(DRATE_BY_NAME),
        default="30",
        help="ADS1256 sample rate in SPS. Default: 30",
    )
    parser.add_argument(
        "--pga",
        type=int,
        choices=tuple(PGA_BY_GAIN),
        default=1,
        help="ADS1256 PGA gain. Default: 1",
    )
    parser.add_argument(
        "--buffer",
        action="store_true",
        help="Enable ADS1256 input buffer. Default: disabled for 0..3.3V single-ended input",
    )
    parser.add_argument(
        "--no-autocal",
        action="store_true",
        help="Disable ADS1256 ACAL bit. Default: enabled",
    )
    parser.add_argument(
        "--no-selfcal",
        action="store_true",
        help="Skip SELFCAL during startup. Default: run SELFCAL",
    )
    parser.add_argument(
        "--discard",
        type=int,
        default=3,
        help="Discard this many readings after configuration. Default: 3",
    )
    parser.add_argument(
        "--average",
        type=int,
        default=3,
        help="Read this many samples per printed value. Default: 3",
    )
    parser.add_argument(
        "--method",
        choices=("median", "mean"),
        default="median",
        help="How to combine samples for one printed value. Default: median",
    )
    return parser.parse_args()


def format_reading(voltage: float, raw: int) -> str:
    return f"mV={voltage * 1000:+.6f} RAW={raw}"


def configure_adc(adc: ADS1256BitBang, args: argparse.Namespace) -> None:
    adc.hardware_reset()
    if not adc.wait_drdy_low(2.0):
        raise TimeoutError("DRDY did not go low; check ADS1256 power/clock/DRDY wire")
    adc.configure_single_ended(
        channel=0,
        pga=PGA_BY_GAIN[args.pga],
        drate=DRATE_BY_NAME[args.drate],
        buffer_enabled=args.buffer,
        autocal_enabled=not args.no_autocal,
        selfcal=not args.no_selfcal,
    )
    for _ in range(args.discard):
        adc.read_single_raw()


def main() -> int:
    args = parse_args()
    pins: ADS1256Pins = make_pins(args.numbering)

    try:
        with ADS1256BitBang(pins=pins, gpiochip=args.gpiochip) as adc:
            configure_adc(adc, args)

            while True:
                try:
                    stats = adc.read_voltage_stats(
                        vref=args.vref,
                        pga=PGA_BY_GAIN[args.pga],
                        samples=args.average,
                        discard=0,
                        method=args.method,
                    )
                except (ADS1256ProtocolError, TimeoutError):
                    configure_adc(adc, args)
                    continue
                print(format_reading(stats.voltage, stats.raw), flush=True)
                time.sleep(args.interval)
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
