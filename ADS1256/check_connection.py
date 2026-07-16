#!/usr/bin/env python3
"""ADS1256 wiring and register-level connection check for Raspberry Pi."""

from __future__ import annotations

import argparse
import sys
import time
from dataclasses import dataclass
from typing import Dict, List

from ads1256_bitbang import (
    ADS1256BitBang,
    ADS1256Pins,
    DRATE_REG,
    IO_REG,
    WIRINGPI_TO_BCM,
)


REGISTER_NAMES = ("STATUS", "MUX", "ADCON", "DRATE", "IO")
DEFAULT_PATTERNS = (0x0, 0xF, 0x5, 0xA)
ADS1256_WIRINGPI_PINS = {
    "D3": 0,
    "D2": 1,
    "D1": 2,
    "D0": 3,
    "SCLK": 4,
    "DIN": 5,
    "DOUT": 6,
    "DRDY": 27,
    "CS": 28,
    "RST": 29,
}


@dataclass
class CheckResult:
    name: str
    ok: bool
    detail: str


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Check ADS1256 SPI, DRDY, RESET, and D0-D3 wiring."
    )
    parser.add_argument("--gpiochip", type=int, default=0, help="lgpio chip number")
    parser.add_argument(
        "--numbering",
        choices=("wiringpi", "bcm"),
        default="wiringpi",
        help="Interpret the fixed ADS1256 pin map as WiringPi or BCM numbers. Default: wiringpi",
    )
    parser.add_argument(
        "--half-period-us",
        type=float,
        default=5.0,
        help="Software SPI half period. Default: 5 us",
    )
    parser.add_argument(
        "--skip-reset",
        action="store_true",
        help="Do not toggle RST before the check.",
    )
    parser.add_argument(
        "--skip-dpins",
        action="store_true",
        help="Only check SPI registers; do not drive ADS1256 D0-D3 or Pi GPIO0-3.",
    )
    parser.add_argument(
        "--drdy-timeout",
        type=float,
        default=2.0,
        help="Seconds to wait for DRDY low before failing.",
    )
    return parser.parse_args()


def make_pins(numbering: str) -> ADS1256Pins:
    if numbering == "bcm":
        return ADS1256Pins.from_bcm_defaults()
    return ADS1256Pins.from_wiringpi_defaults()


def level_table(adc: ADS1256BitBang) -> str:
    parts = []
    for name, pin in adc.pins.named_pins.items():
        try:
            parts.append(f"{name}=GPIO{pin}:{adc.read(pin)}")
        except Exception:
            parts.append(f"{name}=GPIO{pin}:?")
    return " ".join(parts)


def format_regs(registers: Dict[str, int]) -> str:
    return " ".join(f"{name}=0x{value:02X}" for name, value in registers.items())


def register_sanity(registers: Dict[str, int]) -> CheckResult:
    values = list(registers.values())
    if all(value == 0x00 for value in values):
        return CheckResult(
            "register_sanity",
            False,
            "all first registers are 0x00; DOUT may be stuck low or SPI is not active",
        )
    if all(value == 0xFF for value in values):
        return CheckResult(
            "register_sanity",
            False,
            "all first registers are 0xFF; DOUT may be floating/high or CS/DOUT is wrong",
        )
    return CheckResult("register_sanity", True, format_regs(registers))


def check_drate_roundtrip(adc: ADS1256BitBang, timeout_s: float) -> CheckResult:
    original = adc.read_register(DRATE_REG, timeout_s=timeout_s)
    test_value = 0x82 if original != 0x82 else 0x13
    try:
        adc.write_register(DRATE_REG, test_value, timeout_s=timeout_s)
        time.sleep(0.02)
        readback = adc.read_register(DRATE_REG, timeout_s=timeout_s)
        return CheckResult(
            "spi_write_read",
            readback == test_value,
            f"DRATE original=0x{original:02X} wrote=0x{test_value:02X} read=0x{readback:02X}",
        )
    finally:
        adc.write_register(DRATE_REG, original, timeout_s=timeout_s)


def check_ads_outputs_to_pi(adc: ADS1256BitBang, timeout_s: float) -> CheckResult:
    adc.claim_data_pins_input()
    mismatches: List[str] = []

    for pattern in DEFAULT_PATTERNS:
        adc.write_register(IO_REG, pattern, timeout_s=timeout_s)
        time.sleep(0.02)
        got = adc.read_data_pins()
        if got != pattern:
            mismatches.append(f"ADS->Pi wrote=0x{pattern:X} read_gpio=0x{got:X}")

    if mismatches:
        return CheckResult("d0_d3_ads_to_pi", False, "; ".join(mismatches))
    return CheckResult("d0_d3_ads_to_pi", True, "ADS1256 D0-D3 output patterns reached Pi GPIO0-3")


def check_pi_outputs_to_ads(adc: ADS1256BitBang, timeout_s: float) -> CheckResult:
    adc.write_register(IO_REG, 0xF0, timeout_s=timeout_s)
    time.sleep(0.02)
    adc.claim_data_pins_output(0)
    mismatches: List[str] = []

    for pattern in DEFAULT_PATTERNS:
        adc.write_data_pins(pattern)
        time.sleep(0.02)
        io_value = adc.read_register(IO_REG, timeout_s=timeout_s)
        got = io_value & 0x0F
        if got != pattern:
            mismatches.append(f"Pi->ADS wrote_gpio=0x{pattern:X} IO=0x{io_value:02X}")

    adc.claim_data_pins_input()
    if mismatches:
        return CheckResult("d0_d3_pi_to_ads", False, "; ".join(mismatches))
    return CheckResult("d0_d3_pi_to_ads", True, "Pi GPIO0-3 output patterns reached ADS1256 IO register")


def print_result(result: CheckResult) -> None:
    status = "PASS" if result.ok else "FAIL"
    print(f"[{status}] {result.name}: {result.detail}", flush=True)


def main() -> int:
    args = parse_args()
    pins = make_pins(args.numbering)
    failures = 0

    print("ADS1256 connection check")
    print(f"Pin numbering: {args.numbering}")
    print("Pin map used by lgpio:")
    for name, bcm_pin in pins.named_pins.items():
        if args.numbering == "wiringpi":
            wiringpi_pin = ADS1256_WIRINGPI_PINS[name]
            expected_bcm = WIRINGPI_TO_BCM[wiringpi_pin]
            print(f"  {name:4s} -> WiringPi {wiringpi_pin:2d} -> BCM GPIO{expected_bcm}")
        else:
            print(f"  {name:4s} -> BCM GPIO{bcm_pin}")
    print()
    print("Warnings:")
    print("  - ADS1256 digital I/O connected to Raspberry Pi must be 3.3V-level or level-shifted.")
    if args.numbering == "bcm":
        print("  - BCM GPIO28 and GPIO29 are not on the normal Raspberry Pi 4B 40-pin header.")
        print("  - BCM GPIO0/1 are normally HAT EEPROM pins; GPIO2/3 have I2C pull-ups.")
    print()

    try:
        with ADS1256BitBang(
            pins=pins,
            gpiochip=args.gpiochip,
            half_period_us=args.half_period_us,
        ) as adc:
            print(f"Initial levels: {level_table(adc)}")

            if not args.skip_reset:
                print("Toggling RST...")
                adc.hardware_reset()

            drdy_ok = adc.wait_drdy_low(args.drdy_timeout)
            drdy_result = CheckResult(
                "drdy_low",
                drdy_ok,
                "DRDY reached low" if drdy_ok else "DRDY did not go low; check power, clock crystal, DRDY wire",
            )
            print_result(drdy_result)
            failures += 0 if drdy_result.ok else 1
            if not drdy_ok:
                return 1

            registers = adc.read_named_registers()
            print_result(register_sanity(registers))
            if not register_sanity(registers).ok:
                failures += 1

            roundtrip = check_drate_roundtrip(adc, args.drdy_timeout)
            print_result(roundtrip)
            failures += 0 if roundtrip.ok else 1

            if not args.skip_dpins:
                saved_io = adc.read_register(IO_REG, timeout_s=args.drdy_timeout)
                try:
                    ads_to_pi = check_ads_outputs_to_pi(adc, args.drdy_timeout)
                    print_result(ads_to_pi)
                    failures += 0 if ads_to_pi.ok else 1

                    pi_to_ads = check_pi_outputs_to_ads(adc, args.drdy_timeout)
                    print_result(pi_to_ads)
                    failures += 0 if pi_to_ads.ok else 1
                finally:
                    adc.claim_data_pins_input()
                    adc.write_register(IO_REG, saved_io, timeout_s=args.drdy_timeout)

            final_registers = adc.read_named_registers()
            print(f"Final registers: {format_regs(final_registers)}")

    except PermissionError:
        print("ERROR: GPIO permission denied. Try running with sudo or add the user to the gpio group.", file=sys.stderr)
        return 2
    except ModuleNotFoundError as exc:
        print(
            f"ERROR: missing Python module {exc.name}. Install with: sudo apt install -y python3-lgpio",
            file=sys.stderr,
        )
        return 2
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    return 0 if failures == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
