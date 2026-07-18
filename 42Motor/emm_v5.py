#!/usr/bin/env python3
"""Reusable serial driver for an EMM V5.0 LED-wheel stepper motor."""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Optional

from motor_config import MotorParameters, load_motor_parameters

try:
    import serial
except ModuleNotFoundError:
    serial = None


RASPI_GPIO_SERIAL_PORT = "/dev/serial0"

VERSION_FUNCTION = 0x1F
ENABLE_FUNCTION = 0xF3
POSITION_FUNCTION = 0xFD
STOP_FUNCTION = 0xFE
READ_POSITION_FUNCTION = 0x36
READ_STATUS_FUNCTION = 0x3A

COMMAND_OK = 0x02
COMMAND_REJECTED = 0xE2
POSITION_REACHED = 0x9F


class EmmError(RuntimeError):
    """Base exception raised by the EMM driver."""


class EmmConnectionError(EmmError):
    """The serial device is missing, unavailable, or returned no handshake."""


class EmmProtocolError(EmmError):
    """The driver returned an invalid frame or rejected a command."""


class EmmMoveTimeout(EmmError):
    """The requested position was not reached before the deadline."""


class EmmMoveCancelled(EmmError):
    """The current motion was stopped by the caller."""


@dataclass(frozen=True)
class EmmConfig:
    port: Optional[str] = None
    address: int = 0x01
    baud_rate: int = 115200
    checksum: int = 0x6B
    speed_rpm: int = 60
    acceleration: int = 50
    pulses_per_revolution: int = 3200
    position_tolerance_deg: float = 0.5
    move_timeout_s: float = 15.0
    response_timeout_s: float = 0.20
    poll_interval_s: float = 0.10
    stable_samples: int = 2
    debug: bool = False

    def validate(self) -> None:
        if not 1 <= self.address <= 255:
            raise ValueError("address must be in the range 1..255")
        if self.baud_rate <= 0:
            raise ValueError("baud_rate must be positive")
        if not 0 <= self.checksum <= 255:
            raise ValueError("checksum must be in the range 0..255")
        if not 1 <= self.speed_rpm <= 3000:
            raise ValueError("speed_rpm must be in the range 1..3000")
        if not 0 <= self.acceleration <= 255:
            raise ValueError("acceleration must be in the range 0..255")
        if not 1 <= self.pulses_per_revolution <= 0xFFFFFFFF:
            raise ValueError("pulses_per_revolution must fit in uint32")
        if self.position_tolerance_deg <= 0:
            raise ValueError("position_tolerance_deg must be positive")
        if self.move_timeout_s <= 0:
            raise ValueError("move_timeout_s must be positive")
        if self.response_timeout_s <= 0:
            raise ValueError("response_timeout_s must be positive")
        if self.poll_interval_s <= 0:
            raise ValueError("poll_interval_s must be positive")
        if self.stable_samples < 1:
            raise ValueError("stable_samples must be at least 1")


@dataclass(frozen=True)
class VersionInfo:
    firmware: int
    hardware: int
    frame: bytes


@dataclass(frozen=True)
class MotorState:
    raw: int
    enabled: bool
    reached: bool
    stalled: bool
    stall_protection: bool


@dataclass(frozen=True)
class MoveResult:
    target_angle_deg: float
    actual_angle_deg: float
    error_deg: float
    elapsed_s: float
    lamp_index: Optional[int] = None


def hex_bytes(data: bytes) -> str:
    return data.hex(" ").upper() if data else "<no data>"


class EmmV5Motor:
    """Synchronous EMM motor API intended to run in a hardware worker thread."""

    def __init__(self, config: Optional[EmmConfig] = None) -> None:
        self.config = config or EmmConfig()
        self.config.validate()
        self.parameters: MotorParameters = load_motor_parameters()
        self._lamp_angles_deg = self.parameters.lamp_angles_deg
        self._port: Optional["serial.Serial"] = None
        self._port_name: Optional[str] = None
        self._lock = threading.RLock()
        self._last_position_deg = 0.0

    @property
    def is_open(self) -> bool:
        return self._port is not None and self._port.is_open

    @property
    def port_name(self) -> Optional[str]:
        return self._port_name

    @property
    def last_position_deg(self) -> float:
        return self._last_position_deg

    @property
    def lamp_angles_deg(self) -> tuple[float, ...]:
        return self._lamp_angles_deg

    def set_lamp_angle_offset(self, offset_deg: float) -> None:
        parameters = MotorParameters(lamp_angle_offset_deg=float(offset_deg))
        self.parameters = parameters
        self._lamp_angles_deg = parameters.lamp_angles_deg

    def open(self) -> VersionInfo:
        with self._lock:
            if self.is_open:
                return self.read_version()
            if serial is None:
                raise EmmConnectionError(
                    "pyserial is not installed; run: python -m pip install pyserial"
                )

            if self.config.port:
                port_name = self.config.port
                description = port_name
            else:
                port_name = RASPI_GPIO_SERIAL_PORT
                description = f"Raspberry Pi GPIO UART {RASPI_GPIO_SERIAL_PORT}"

            self._debug(f"opening {description}")

            try:
                self._port = serial.Serial(
                    port=port_name,
                    baudrate=self.config.baud_rate,
                    bytesize=serial.EIGHTBITS,
                    parity=serial.PARITY_NONE,
                    stopbits=serial.STOPBITS_ONE,
                    timeout=0.01,
                    write_timeout=0.5,
                )
                self._port_name = port_name
                version = self.read_version()
                self.ensure_enabled()
                self._last_position_deg = self.read_position()
                return version
            except Exception:
                self._close_port_only()
                raise

    def close(self) -> None:
        with self._lock:
            if not self.is_open:
                self._close_port_only()
                return
            try:
                self._stop_unlocked()
            except Exception:
                pass
            finally:
                self._close_port_only()

    def __enter__(self) -> "EmmV5Motor":
        self.open()
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:  # noqa: ANN001
        self.close()

    def read_version(self) -> VersionInfo:
        with self._lock:
            request = bytes(
                (self.config.address, VERSION_FUNCTION, self.config.checksum)
            )
            last_raw = b""
            for _ in range(3):
                last_raw = self._exchange(request)
                self._raise_on_error_frame(last_raw, "read version")
                frame = self._find_frame(last_raw, VERSION_FUNCTION, 5)
                if frame is not None:
                    return VersionInfo(frame[2], frame[3], frame)
                time.sleep(0.05)
            raise EmmConnectionError(
                f"no valid EMM version response on {self._port_name}: "
                f"{hex_bytes(last_raw)}"
            )

    def read_position(self) -> float:
        with self._lock:
            request = bytes(
                (self.config.address, READ_POSITION_FUNCTION, self.config.checksum)
            )
            raw = self._exchange(request)
            self._raise_on_error_frame(raw, "read position")
            frame = self._find_frame(raw, READ_POSITION_FUNCTION, 8)
            if frame is None or frame[2] not in (0x00, 0x01):
                raise EmmProtocolError(
                    f"invalid position response: {hex_bytes(raw)}"
                )

            magnitude = int.from_bytes(frame[3:7], "big")
            angle = magnitude * 360.0 / 65536.0
            self._last_position_deg = -angle if frame[2] else angle
            return self._last_position_deg

    def read_state(self) -> MotorState:
        with self._lock:
            request = bytes(
                (self.config.address, READ_STATUS_FUNCTION, self.config.checksum)
            )
            raw = self._exchange(request)
            self._raise_on_error_frame(raw, "read motor status")
            frame = self._find_frame(raw, READ_STATUS_FUNCTION, 4)
            if frame is None:
                raise EmmProtocolError(
                    f"invalid motor status response: {hex_bytes(raw)}"
                )

            flags = frame[2]
            return MotorState(
                raw=flags,
                enabled=bool(flags & 0x01),
                reached=bool(flags & 0x02),
                stalled=bool(flags & 0x04),
                stall_protection=bool(flags & 0x08),
            )

    def ensure_enabled(self) -> MotorState:
        with self._lock:
            state = self.read_state()
            if state.stall_protection:
                raise EmmProtocolError(
                    "stall protection is active; clear the motor fault first"
                )
            if state.enabled:
                return state

            request = bytes(
                (
                    self.config.address,
                    ENABLE_FUNCTION,
                    0xAB,
                    0x01,
                    0x00,
                    self.config.checksum,
                )
            )
            raw = self._exchange(request)
            self._check_command_reply(raw, ENABLE_FUNCTION, "enable motor")
            time.sleep(0.10)
            state = self.read_state()
            if not state.enabled:
                raise EmmProtocolError(
                    "motor is still disabled after the enable command"
                )
            return state

    def select_lamp(
        self,
        lamp_index: int,
        cancel_event: Optional[threading.Event] = None,
    ) -> MoveResult:
        if not 0 <= lamp_index < len(self._lamp_angles_deg):
            raise ValueError(
                "lamp_index must be in the range "
                f"0..{len(self._lamp_angles_deg) - 1}"
            )
        result = self.move_to_angle(
            self._lamp_angles_deg[lamp_index],
            cancel_event=cancel_event,
        )
        return MoveResult(
            target_angle_deg=result.target_angle_deg,
            actual_angle_deg=result.actual_angle_deg,
            error_deg=result.error_deg,
            elapsed_s=result.elapsed_s,
            lamp_index=lamp_index,
        )

    def move_to_angle(
        self,
        target_angle_deg: float,
        cancel_event: Optional[threading.Event] = None,
    ) -> MoveResult:
        with self._lock:
            self._require_open()
            self.ensure_enabled()
            request = self.make_position_request(target_angle_deg)
            raw = self._exchange(request)
            self._check_command_reply(raw, POSITION_FUNCTION, "position command")

            started = time.monotonic()
            deadline = started + self.config.move_timeout_s
            stable_count = 0
            last_position = self._last_position_deg
            last_state: Optional[MotorState] = None

            while time.monotonic() < deadline:
                if cancel_event is not None and cancel_event.is_set():
                    self._stop_unlocked()
                    raise EmmMoveCancelled("motor movement was cancelled")

                last_position = self.read_position()
                last_state = self.read_state()
                if last_state.stall_protection or last_state.stalled:
                    self._stop_unlocked()
                    raise EmmProtocolError(
                        f"motor stall detected (status=0x{last_state.raw:02X})"
                    )
                if not last_state.enabled:
                    self._stop_unlocked()
                    raise EmmProtocolError("motor became disabled while moving")

                error = abs(last_position - target_angle_deg)
                if last_state.reached and error <= self.config.position_tolerance_deg:
                    stable_count += 1
                    if stable_count >= self.config.stable_samples:
                        return MoveResult(
                            target_angle_deg=target_angle_deg,
                            actual_angle_deg=last_position,
                            error_deg=error,
                            elapsed_s=time.monotonic() - started,
                        )
                else:
                    stable_count = 0

                time.sleep(self.config.poll_interval_s)

            self._stop_unlocked()
            state_text = "unknown" if last_state is None else f"0x{last_state.raw:02X}"
            raise EmmMoveTimeout(
                f"target {target_angle_deg:.1f} deg was not reached in "
                f"{self.config.move_timeout_s:.1f}s "
                f"(position={last_position:.3f} deg, status={state_text})"
            )

    def make_position_request(self, target_angle_deg: float) -> bytes:
        direction = 0x01 if target_angle_deg < 0 else 0x00
        pulses = round(
            abs(target_angle_deg) * self.config.pulses_per_revolution / 360.0
        )
        if pulses > 0xFFFFFFFF:
            raise ValueError("target angle exceeds the EMM uint32 pulse range")
        return (
            bytes((self.config.address, POSITION_FUNCTION, direction))
            + self.config.speed_rpm.to_bytes(2, "big")
            + bytes((self.config.acceleration,))
            + pulses.to_bytes(4, "big")
            + bytes((0x01, 0x00, self.config.checksum))
        )

    def stop(self) -> None:
        with self._lock:
            if self.is_open:
                self._stop_unlocked()

    def _stop_unlocked(self) -> None:
        request = bytes(
            (
                self.config.address,
                STOP_FUNCTION,
                0x98,
                0x00,
                self.config.checksum,
            )
        )
        self._exchange(request)

    def _check_command_reply(self, raw: bytes, function: int, operation: str) -> None:
        self._raise_on_error_frame(raw, operation)
        frame = self._find_frame(raw, function, 4)
        if frame is None:
            # Response=None/Reached are valid driver settings; polling verifies motion.
            return
        status = frame[2]
        if status == COMMAND_REJECTED:
            raise EmmProtocolError(
                f"{operation} rejected: motor disabled or stall protection active"
            )
        if status not in (COMMAND_OK, POSITION_REACHED):
            raise EmmProtocolError(
                f"{operation} returned unexpected status 0x{status:02X}"
            )

    def _raise_on_error_frame(self, raw: bytes, operation: str) -> None:
        error_frame = bytes(
            (self.config.address, 0x00, 0xEE, self.config.checksum)
        )
        if error_frame in raw:
            raise EmmProtocolError(f"{operation}: driver returned {hex_bytes(error_frame)}")

    def _find_frame(
        self,
        raw: bytes,
        function: int,
        frame_length: int,
    ) -> Optional[bytes]:
        for start in range(max(0, len(raw) - frame_length + 1)):
            frame = raw[start : start + frame_length]
            if frame[0] != self.config.address:
                continue
            if frame[1] != function:
                continue
            if frame[-1] != self.config.checksum:
                continue
            return frame
        return None

    def _exchange(self, request: bytes) -> bytes:
        self._require_open()
        assert self._port is not None
        self._port.reset_input_buffer()
        self._port.write(request)
        self._port.flush()
        response = self._read_until_idle()
        self._debug(f"TX {hex_bytes(request)} | RX {hex_bytes(response)}")
        return response

    def _read_until_idle(self) -> bytes:
        assert self._port is not None
        response = bytearray()
        deadline = time.monotonic() + self.config.response_timeout_s
        idle_deadline: Optional[float] = None

        while time.monotonic() < deadline:
            waiting = self._port.in_waiting
            chunk = self._port.read(waiting if waiting else 1)
            now = time.monotonic()
            if chunk:
                response.extend(chunk)
                idle_deadline = now + 0.030
            elif response and idle_deadline is not None and now >= idle_deadline:
                break
        return bytes(response)

    def _require_open(self) -> None:
        if not self.is_open:
            raise EmmConnectionError("EMM serial port is not open")

    def _close_port_only(self) -> None:
        if self._port is not None:
            try:
                self._port.close()
            finally:
                self._port = None
                self._port_name = None

    def _debug(self, message: str) -> None:
        if self.config.debug:
            print(f"[EMM] {message}", flush=True)
