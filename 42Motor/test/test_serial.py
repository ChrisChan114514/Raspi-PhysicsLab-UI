#!/usr/bin/env python3
"""Handshake with an EMM V5.0 motor by reading its version information."""

from __future__ import annotations

import argparse
import sys
import time
from dataclasses import dataclass
from typing import List, Optional, Tuple

try:
    import serial
except ModuleNotFoundError:
    serial = None


RASPI_GPIO_SERIAL_PORT = "/dev/serial0"
MOTOR_ADDRESS = 0x01
BAUD_RATE = 115200
VERSION_FUNCTION = 0x1F
FIXED_CHECKSUM = 0x6B
VERSION_REQUEST = bytes((MOTOR_ADDRESS, VERSION_FUNCTION, FIXED_CHECKSUM))
ERROR_REPLY = bytes((MOTOR_ADDRESS, 0x00, 0xEE, FIXED_CHECKSUM))


@dataclass(frozen=True)
class VersionReply:
    frame: bytes
    firmware_version: int
    hardware_version: int


@dataclass(frozen=True)
class Observation:
    attempt: int
    response: bytes


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Test an EMM V5.0 serial connection by reading the firmware and "
            "hardware versions from motor address 1 at 115200 baud."
        )
    )
    parser.add_argument(
        "--port",
        default=None,
        help="Serial port override. Default: Raspberry Pi GPIO UART /dev/serial0.",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=0.20,
        help="Maximum seconds to collect each response. Default: 0.20.",
    )
    parser.add_argument(
        "--retries",
        type=int,
        default=3,
        help="Number of handshake attempts. Default: 3.",
    )
    return parser.parse_args()


def hex_bytes(data: bytes) -> str:
    return data.hex(" ").upper() if data else "<no data>"


def resolve_port(requested_port: Optional[str]) -> str:
    if requested_port:
        print(f"Using requested serial port: {requested_port}")
        return requested_port

    print(f"Using Raspberry Pi GPIO UART: {RASPI_GPIO_SERIAL_PORT}")
    return RASPI_GPIO_SERIAL_PORT


def read_until_idle(port: "serial.Serial", timeout_s: float) -> bytes:
    response = bytearray()
    deadline = time.monotonic() + timeout_s
    idle_deadline: Optional[float] = None

    while time.monotonic() < deadline:
        waiting = port.in_waiting
        chunk = port.read(waiting if waiting else 1)
        now = time.monotonic()
        if chunk:
            response.extend(chunk)
            idle_deadline = now + 0.030
        elif response and idle_deadline is not None and now >= idle_deadline:
            break

    return bytes(response)


def exchange(port: "serial.Serial", request: bytes, timeout_s: float) -> bytes:
    port.reset_input_buffer()
    port.write(request)
    port.flush()
    return read_until_idle(port, timeout_s)


def find_version_reply(raw: bytes) -> Optional[VersionReply]:
    frame_length = 5
    for start in range(max(0, len(raw) - frame_length + 1)):
        frame = raw[start : start + frame_length]
        if frame[0] != MOTOR_ADDRESS:
            continue
        if frame[1] != VERSION_FUNCTION:
            continue
        if frame[-1] != FIXED_CHECKSUM:
            continue

        return VersionReply(
            frame=frame,
            firmware_version=frame[2],
            hardware_version=frame[3],
        )
    return None


def probe(
    port: "serial.Serial", timeout_s: float, retries: int
) -> Tuple[Optional[Tuple[VersionReply, int]], List[Observation]]:
    observations: List[Observation] = []

    for attempt in range(1, retries + 1):
        print(f"Handshake attempt {attempt}/{retries}: TX {hex_bytes(VERSION_REQUEST)}")
        raw = exchange(port, VERSION_REQUEST, timeout_s)
        reply = find_version_reply(raw)
        if reply is not None:
            return (reply, attempt), observations
        if raw:
            observations.append(Observation(attempt=attempt, response=raw))
        time.sleep(0.050)

    return None, observations


def print_success(reply: VersionReply, attempt: int) -> None:
    print()
    print("[SUCCESS] Valid EMM V5.0 version response received")
    print(f"  UART             : {BAUD_RATE}, 8N1")
    print(f"  Motor address    : {MOTOR_ADDRESS}")
    print(f"  TX                : {hex_bytes(VERSION_REQUEST)}")
    print(f"  RX                : {hex_bytes(reply.frame)}")
    print(
        f"  Firmware version : 0x{reply.firmware_version:02X} "
        f"({reply.firmware_version})"
    )
    print(
        f"  Hardware version : 0x{reply.hardware_version:02X} "
        f"({reply.hardware_version})"
    )
    print(f"  Handshake attempt: {attempt}")


def print_failure(observations: List[Observation], attempts: int) -> None:
    print()
    print("[FAIL] No valid EMM V5.0 version response was received")
    print(f"  Attempts       : {attempts}")
    print(f"  UART           : {BAUD_RATE}, 8N1")
    print(f"  Motor address  : {MOTOR_ADDRESS}")
    print(f"  TX             : {hex_bytes(VERSION_REQUEST)}")
    print("  Expected RX    : 01 1F <firmware> <hardware> 6B")

    if observations:
        print("  Received bytes:")
        for observation in observations:
            if observation.response == VERSION_REQUEST:
                kind = "TX echo only"
            elif ERROR_REPLY in observation.response:
                kind = "EMM error reply"
            else:
                kind = "invalid/incomplete reply"
            print(
                f"    attempt={observation.attempt}: "
                f"{hex_bytes(observation.response)} ({kind})"
            )
    else:
        print("  RX             : no bytes received")

    print("  Verify TX -> motor RX, RX -> motor TX, and common GND.")


def validate_args(args: argparse.Namespace) -> Optional[str]:
    if args.timeout <= 0:
        return "--timeout must be greater than zero"
    if args.retries < 1:
        return "--retries must be at least 1"
    return None


def main() -> int:
    args = parse_args()
    error = validate_args(args)
    if error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 2
    if serial is None:
        print(
            "ERROR: pyserial is not installed. Run: python -m pip install pyserial",
            file=sys.stderr,
        )
        return 2

    args.port = resolve_port(args.port)

    print()
    print("EMM V5.0 serial version handshake")
    print(f"UART: {args.port}, {BAUD_RATE}, 8N1")
    print(f"Address: {MOTOR_ADDRESS}")
    print(f"Checksum byte: 0x{FIXED_CHECKSUM:02X}")
    print("Safety: read-version command only; the motor will not move.")

    try:
        with serial.Serial(
            port=args.port,
            baudrate=BAUD_RATE,
            bytesize=serial.EIGHTBITS,
            parity=serial.PARITY_NONE,
            stopbits=serial.STOPBITS_ONE,
            timeout=0.01,
            write_timeout=0.5,
        ) as port:
            found, observations = probe(port, args.timeout, args.retries)
            if found is not None:
                reply, attempt = found
                print_success(reply, attempt)
                return 0

    except PermissionError:
        print(f"ERROR: permission denied for {args.port}.", file=sys.stderr)
        return 2
    except serial.SerialException as exc:
        print(f"ERROR: cannot use {args.port}: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("\nInterrupted.")
        return 130

    print_failure(observations, args.retries)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
