#!/usr/bin/env python3
"""Command-line test for the STM32F103 ADS1256 parallel bridge."""

from __future__ import annotations

import argparse
import sys
import time

from stm32_parallel_bridge import STM32ADS1256Bridge, STM32ParallelPins


def main() -> int:
    parser = argparse.ArgumentParser(description="Query STM32 ADS1256 bridge over 2-bit GPIO handshake bus.")
    parser.add_argument("--gpiochip", type=int, default=0)
    parser.add_argument("--interval", type=float, default=0.5, help="Query interval in seconds.")
    parser.add_argument("--count", type=int, default=0, help="Number of queries. 0 means forever.")
    parser.add_argument("--timeout", type=float, default=1.0, help="READY toggle timeout per 2-bit symbol.")
    args = parser.parse_args()

    pins = STM32ParallelPins.from_ads1256_defaults()
    print("STM32 2-bit parallel bridge pin map, BCM numbering:")
    for name, pin in pins.named_pins.items():
        print(f"  {name:7s} -> GPIO{pin}")

    done = 0
    try:
        with STM32ADS1256Bridge(pins=pins, gpiochip=args.gpiochip, timeout_s=args.timeout) as bridge:
            while args.count <= 0 or done < args.count:
                sample = bridge.query_sample()
                print(
                    f"seq={sample.seq:05d} status=0x{sample.status:02X} "
                    f"raw={sample.raw:9d} uV={sample.uv:9d} "
                    f"mV={sample.voltage_mv:+.3f} age={sample.age_ms}ms",
                    flush=True,
                )
                done += 1
                time.sleep(args.interval)
    except PermissionError:
        print("GPIO permission denied. Try running with sudo or add the user to the gpio group.", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        return 130

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
