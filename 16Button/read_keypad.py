#!/usr/bin/env python3
"""Print 4x4 membrane keypad events from the command line."""

from __future__ import annotations

import argparse
import time

from matrix_keypad import (
    DebouncedMatrixKeypad,
    DEFAULT_WIRINGPI_PINS,
    MatrixKeypad,
    MatrixPins,
    format_pin_map,
    keymap_by_name,
)


def parse_pin_list(value: str) -> tuple[int, ...]:
    pins = tuple(int(part.strip()) for part in value.split(",") if part.strip())
    if len(pins) != 8:
        raise argparse.ArgumentTypeError("expected exactly 8 comma-separated WiringPi pins")
    return pins


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Scan a 4x4 matrix keypad.")
    parser.add_argument(
        "--pins",
        type=parse_pin_list,
        default=DEFAULT_WIRINGPI_PINS,
        help="8 WiringPi pins in keypad P1..P8 order. Default: 13,14,30,21,22,23,24,25",
    )
    parser.add_argument(
        "--swap-rc",
        action="store_true",
        help="Treat P1..P4 as columns and P5..P8 as rows.",
    )
    parser.add_argument(
        "--keymap",
        choices=("measured", "standard"),
        default="measured",
        help="Key label mapping. Default: measured, corrected from this keypad wiring.",
    )
    parser.add_argument("--gpiochip", type=int, default=0, help="lgpio chip number. Default: 0")
    parser.add_argument("--poll-ms", type=float, default=10.0, help="Scan period. Default: 10 ms")
    parser.add_argument("--debounce-ms", type=float, default=35.0, help="Debounce time. Default: 35 ms")
    parser.add_argument(
        "--print-idle",
        action="store_true",
        help="Also print IDLE lines when no key is pressed.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    pins = MatrixPins.from_wiringpi(args.pins, swap_rc=args.swap_rc)
    keymap = keymap_by_name(args.keymap)
    poll_s = args.poll_ms / 1000.0
    debounce_s = args.debounce_ms / 1000.0

    print(format_pin_map(args.pins, pins), flush=True)
    print("READY press keys; Ctrl+C to stop", flush=True)

    try:
        keypad = MatrixKeypad(pins=pins, keymap=keymap, gpiochip=args.gpiochip)
        with DebouncedMatrixKeypad(keypad, debounce_s=debounce_s) as scanner:
            while True:
                for event in scanner.poll():
                    print(
                        f"{event.kind} key={event.key} keys={','.join(event.keys) or 'NONE'}",
                        flush=True,
                    )

                if args.print_idle and not scanner.last_raw:
                    print("IDLE", flush=True)

                time.sleep(poll_s)
    except KeyboardInterrupt:
        print("\nSTOP", flush=True)
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
