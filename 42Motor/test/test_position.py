#!/usr/bin/env python3
"""Interactive absolute-position test for an EMM V5.0 stepper driver."""

from __future__ import annotations

import argparse
import math
import sys
import time
from dataclasses import dataclass
from typing import Optional, Tuple

try:
    import serial
    from serial.tools import list_ports
except ModuleNotFoundError:
    serial = None
    list_ports = None


MOTOR_ADDRESS = 0x01
BAUD_RATE = 115200
FIXED_CHECKSUM = 0x6B

VERSION_FUNCTION = 0x1F
ENABLE_FUNCTION = 0xF3
POSITION_FUNCTION = 0xFD
STOP_FUNCTION = 0xFE
READ_POSITION_FUNCTION = 0x36
READ_STATUS_FUNCTION = 0x3A

COMMAND_OK = 0x02
COMMAND_REJECTED = 0xE2
POSITION_REACHED = 0x9F
ERROR_REPLY = bytes((MOTOR_ADDRESS, 0x00, 0xEE, FIXED_CHECKSUM))

VERSION_REQUEST = bytes((MOTOR_ADDRESS, VERSION_FUNCTION, FIXED_CHECKSUM))
READ_POSITION_REQUEST = bytes(
    (MOTOR_ADDRESS, READ_POSITION_FUNCTION, FIXED_CHECKSUM)
)
READ_STATUS_REQUEST = bytes((MOTOR_ADDRESS, READ_STATUS_FUNCTION, FIXED_CHECKSUM))
ENABLE_REQUEST = bytes(
    (MOTOR_ADDRESS, ENABLE_FUNCTION, 0xAB, 0x01, 0x00, FIXED_CHECKSUM)
)
STOP_REQUEST = bytes(
    (MOTOR_ADDRESS, STOP_FUNCTION, 0x98, 0x00, FIXED_CHECKSUM)
)


class ProtocolError(RuntimeError):
    pass


class MoveTimeout(RuntimeError):
    pass


@dataclass(frozen=True)
class MotorState:
    raw: int
    enabled: bool
    reached: bool
    stalled: bool
    stall_protection: bool


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Interactively move EMM V5.0 motor address 1 to absolute angles "
            "between 0 and 360 degrees."
        )
    )
    parser.add_argument(
        "--port",
        default=None,
        help="Serial port override. Default: automatically select CH340.",
    )
    parser.add_argument(
        "--speed",
        type=int,
        default=60,
        help="Positioning speed in RPM. Default: 60.",
    )
    parser.add_argument(
        "--acceleration",
        type=int,
        default=50,
        help="Acceleration level from 0 to 255. Default: 50.",
    )
    parser.add_argument(
        "--pulses-per-revolution",
        type=int,
        default=3200,
        help="Command pulses per motor revolution. Default: 3200 (16 microsteps).",
    )
    parser.add_argument(
        "--tolerance",
        type=float,
        default=0.5,
        help="Maximum position error in degrees for success. Default: 0.5.",
    )
    parser.add_argument(
        "--move-timeout",
        type=float,
        default=15.0,
        help="Maximum seconds allowed for each move. Default: 15.",
    )
    parser.add_argument(
        "--poll-interval",
        type=float,
        default=0.10,
        help="Seconds between position samples. Default: 0.10.",
    )
    parser.add_argument(
        "--response-timeout",
        type=float,
        default=0.20,
        help="Maximum seconds to collect each serial response. Default: 0.20.",
    )
    return parser.parse_args()


def validate_args(args: argparse.Namespace) -> Optional[str]:
    if not 1 <= args.speed <= 3000:
        return "--speed must be in the range 1..3000 RPM"
    if not 0 <= args.acceleration <= 255:
        return "--acceleration must be in the range 0..255"
    if args.pulses_per_revolution <= 0:
        return "--pulses-per-revolution must be greater than zero"
    if args.pulses_per_revolution > 0xFFFFFFFF:
        return "--pulses-per-revolution is too large for the EMM command"
    if args.tolerance <= 0:
        return "--tolerance must be greater than zero"
    if args.move_timeout <= 0:
        return "--move-timeout must be greater than zero"
    if args.poll_interval <= 0:
        return "--poll-interval must be greater than zero"
    if args.response_timeout <= 0:
        return "--response-timeout must be greater than zero"
    return None


def hex_bytes(data: bytes) -> str:
    return data.hex(" ").upper() if data else "<no data>"


def port_description(port_info) -> str:
    fields = (
        port_info.device,
        port_info.description,
        port_info.manufacturer,
        port_info.hwid,
    )
    return " | ".join(str(value) for value in fields if value)


def available_port_descriptions() -> Tuple[str, ...]:
    return tuple(port_description(port_info) for port_info in list_ports.comports())


def find_ch340_port() -> Tuple[str, str, Tuple[str, ...]]:
    matches = []
    for port_info in list_ports.comports():
        description = port_description(port_info)
        if "CH340" in description.upper():
            matches.append(port_info)

    if not matches:
        raise LookupError("no active serial device containing CH340 was found")

    matches.sort(key=lambda port_info: port_info.device)
    selected = matches[0]
    other_matches = tuple(port_description(port_info) for port_info in matches[1:])
    return selected.device, port_description(selected), other_matches


def resolve_port(requested_port: Optional[str]) -> str:
    if requested_port:
        print(f"Using requested serial port: {requested_port}")
        return requested_port

    selected_port, selected_description, other_matches = find_ch340_port()
    print(f"Auto-selected CH340 serial port: {selected_description}")
    if other_matches:
        print("Other active CH340 ports were not selected:")
        for description in other_matches:
            print(f"  {description}")
    return selected_port


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


def find_frame(raw: bytes, function: int, frame_length: int) -> Optional[bytes]:
    for start in range(max(0, len(raw) - frame_length + 1)):
        frame = raw[start : start + frame_length]
        if frame[0] != MOTOR_ADDRESS:
            continue
        if frame[1] != function:
            continue
        if frame[-1] != FIXED_CHECKSUM:
            continue
        return frame
    return None


def require_no_protocol_error(raw: bytes, operation: str) -> None:
    if ERROR_REPLY in raw:
        raise ProtocolError(f"{operation}: driver returned 01 00 EE 6B")


def parse_command_status(raw: bytes, function: int) -> Optional[int]:
    frame = find_frame(raw, function, 4)
    return frame[2] if frame is not None else None


def parse_position(raw: bytes) -> Optional[float]:
    frame = find_frame(raw, READ_POSITION_FUNCTION, 8)
    if frame is None or frame[2] not in (0x00, 0x01):
        return None

    raw_position = int.from_bytes(frame[3:7], "big")
    angle = raw_position * 360.0 / 65536.0
    return -angle if frame[2] == 0x01 else angle


def parse_motor_state(raw: bytes) -> Optional[MotorState]:
    frame = find_frame(raw, READ_STATUS_FUNCTION, 4)
    if frame is None:
        return None

    flags = frame[2]
    return MotorState(
        raw=flags,
        enabled=bool(flags & 0x01),
        reached=bool(flags & 0x02),
        stalled=bool(flags & 0x04),
        stall_protection=bool(flags & 0x08),
    )


def make_position_request(
    target_angle: float,
    speed: int,
    acceleration: int,
    pulses_per_revolution: int,
) -> bytes:
    pulses = round(target_angle * pulses_per_revolution / 360.0)
    return (
        bytes((MOTOR_ADDRESS, POSITION_FUNCTION, 0x00))
        + speed.to_bytes(2, "big")
        + bytes((acceleration,))
        + pulses.to_bytes(4, "big")
        + bytes((0x01, 0x00, FIXED_CHECKSUM))
    )


def read_position(port: "serial.Serial", timeout_s: float) -> float:
    raw = exchange(port, READ_POSITION_REQUEST, timeout_s)
    require_no_protocol_error(raw, "read position")
    position = parse_position(raw)
    if position is None:
        raise ProtocolError(f"invalid position response: {hex_bytes(raw)}")
    return position


def read_motor_state(port: "serial.Serial", timeout_s: float) -> MotorState:
    raw = exchange(port, READ_STATUS_REQUEST, timeout_s)
    require_no_protocol_error(raw, "read motor status")
    state = parse_motor_state(raw)
    if state is None:
        raise ProtocolError(f"invalid motor status response: {hex_bytes(raw)}")
    return state


def verify_connection(port: "serial.Serial", timeout_s: float) -> bytes:
    last_raw = b""
    for _ in range(3):
        last_raw = exchange(port, VERSION_REQUEST, timeout_s)
        require_no_protocol_error(last_raw, "read version")
        frame = find_frame(last_raw, VERSION_FUNCTION, 5)
        if frame is not None:
            return frame
        time.sleep(0.050)
    raise ProtocolError(f"no valid version response: {hex_bytes(last_raw)}")


def ensure_enabled(port: "serial.Serial", timeout_s: float) -> MotorState:
    state = read_motor_state(port, timeout_s)
    if state.stall_protection:
        raise ProtocolError("stall protection is active; clear the fault first")
    if state.enabled:
        return state

    raw = exchange(port, ENABLE_REQUEST, timeout_s)
    require_no_protocol_error(raw, "enable motor")
    command_status = parse_command_status(raw, ENABLE_FUNCTION)
    if command_status not in (None, COMMAND_OK):
        raise ProtocolError(
            f"enable command rejected with status 0x{command_status:02X}"
        )

    time.sleep(0.100)
    state = read_motor_state(port, timeout_s)
    if not state.enabled:
        raise ProtocolError("motor is still disabled after the enable command")
    return state


def stop_motor(port: "serial.Serial", timeout_s: float) -> None:
    try:
        exchange(port, STOP_REQUEST, timeout_s)
    except (OSError, serial.SerialException):
        pass


def move_to_angle(
    port: "serial.Serial",
    target_angle: float,
    args: argparse.Namespace,
) -> None:
    request = make_position_request(
        target_angle,
        args.speed,
        args.acceleration,
        args.pulses_per_revolution,
    )
    print(f"TX: {hex_bytes(request)}")
    raw = exchange(port, request, args.response_timeout)
    require_no_protocol_error(raw, "position command")

    command_status = parse_command_status(raw, POSITION_FUNCTION)
    if command_status == COMMAND_REJECTED:
        raise ProtocolError(
            "position command rejected (motor disabled or stall protection active)"
        )
    if command_status not in (None, COMMAND_OK, POSITION_REACHED):
        raise ProtocolError(
            f"position command returned status 0x{command_status:02X}"
        )

    deadline = time.monotonic() + args.move_timeout
    stable_samples = 0
    last_position: Optional[float] = None
    last_state: Optional[MotorState] = None

    while time.monotonic() < deadline:
        last_position = read_position(port, args.response_timeout)
        last_state = read_motor_state(port, args.response_timeout)

        if last_state.stall_protection or last_state.stalled:
            raise ProtocolError(
                f"motor stall detected (status=0x{last_state.raw:02X})"
            )
        if not last_state.enabled:
            raise ProtocolError("motor became disabled while moving")

        error = abs(last_position - target_angle)
        print(
            f"\rPosition: {last_position:8.3f} deg | "
            f"Target: {target_angle:7.3f} deg | Error: {error:6.3f} deg | "
            f"Reached: {'yes' if last_state.reached else 'no '} ",
            end="",
            flush=True,
        )

        if last_state.reached and error <= args.tolerance:
            stable_samples += 1
            if stable_samples >= 2:
                print()
                print(
                    f"OK! Target reached: {last_position:.3f} deg "
                    f"(error {error:.3f} deg)"
                )
                return
        else:
            stable_samples = 0

        time.sleep(args.poll_interval)

    print()
    stop_motor(port, args.response_timeout)
    position_text = "unknown" if last_position is None else f"{last_position:.3f} deg"
    state_text = "unknown" if last_state is None else f"0x{last_state.raw:02X}"
    raise MoveTimeout(
        f"target {target_angle:.3f} deg was not reached within "
        f"{args.move_timeout:.1f}s (position={position_text}, status={state_text})"
    )


def parse_target_angle(text: str) -> Optional[float]:
    try:
        angle = float(text)
    except ValueError:
        return None
    if not math.isfinite(angle) or not 0.0 <= angle <= 360.0:
        return None
    return angle


def interactive_loop(port: "serial.Serial", args: argparse.Namespace) -> None:
    while True:
        text = input("\nTarget angle 0..360 deg (q to quit): ").strip()
        if text.lower() in {"q", "quit", "exit"}:
            print("Exited.")
            return

        target_angle = parse_target_angle(text)
        if target_angle is None:
            print("Invalid input. Enter a number from 0 to 360, or q to quit.")
            continue

        try:
            move_to_angle(port, target_angle, args)
        except (MoveTimeout, ProtocolError) as exc:
            stop_motor(port, args.response_timeout)
            print(f"[FAIL] {exc}")


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

    try:
        args.port = resolve_port(args.port)
    except LookupError as exc:
        print(f"ERROR: {exc}.", file=sys.stderr)
        detected_ports = available_port_descriptions()
        if detected_ports:
            print("Detected serial devices:", file=sys.stderr)
            for description in detected_ports:
                print(f"  {description}", file=sys.stderr)
        else:
            print("No serial devices are currently detected.", file=sys.stderr)
        return 2

    print()
    print("EMM V5.0 interactive absolute-position test")
    print(f"UART: {args.port}, {BAUD_RATE}, 8N1")
    print(f"Address: {MOTOR_ADDRESS}, checksum: 0x{FIXED_CHECKSUM:02X}")
    print(
        f"Motion: {args.speed} RPM, acceleration {args.acceleration}, "
        f"{args.pulses_per_revolution} pulses/revolution"
    )
    print(
        "Coordinate zero is the driver's existing power-on/cleared zero; "
        "this program does not reset it."
    )

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
            version = verify_connection(port, args.response_timeout)
            state = ensure_enabled(port, args.response_timeout)
            position = read_position(port, args.response_timeout)
            print(
                f"Connected: version RX={hex_bytes(version)}, "
                f"enabled={'yes' if state.enabled else 'no'}, "
                f"position={position:.3f} deg"
            )
            interactive_loop(port, args)
            return 0

    except PermissionError:
        print(f"ERROR: permission denied for {args.port}.", file=sys.stderr)
        return 2
    except serial.SerialException as exc:
        print(f"ERROR: cannot use {args.port}: {exc}", file=sys.stderr)
        return 2
    except ProtocolError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    except (KeyboardInterrupt, EOFError):
        try:
            stop_motor(port, args.response_timeout)
        except UnboundLocalError:
            pass
        print("\nStopped and exited.")
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
