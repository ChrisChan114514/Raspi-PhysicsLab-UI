#!/usr/bin/env python3
"""Raspberry Pi driver for the STM32F103 ADS1256 parallel bridge.

The STM32 owns the ADS1256 and continuously caches the latest AIN0-AINCOM
sample.  Raspberry Pi queries that cache through a 2-bit single-direction
handshake bus:

* Pi -> STM32: REQ + PI_TX0 + PI_TX1
* STM32 -> Pi: READY + STM_TX0 + STM_TX1

The protocol is intentionally slow-and-safe: every 2-bit symbol is acknowledged
by a toggle on the opposite handshake line, so Linux scheduling jitter does not
corrupt timing.
"""

from __future__ import annotations

import struct
import time
from dataclasses import dataclass
from typing import Iterable, List, Optional

import lgpio

from ads1256_bitbang import ADS1256Pins


CMD_GET_SAMPLE = 0x01
REQUEST_LEN = 8
RESPONSE_LEN = 17
STATUS_VALID_SAMPLE = 0x01
STATUS_UNSUPPORTED_CMD = 0x40
STATUS_BAD_REQUEST = 0x80


class STM32ParallelProtocolError(RuntimeError):
    """Raised when the STM32 parallel response is invalid or times out."""


@dataclass(frozen=True)
class STM32ParallelPins:
    req: int
    ready: int
    pi_tx0: int
    pi_tx1: int
    stm_tx0: int
    stm_tx1: int

    @classmethod
    def from_ads1256_defaults(cls) -> "STM32ParallelPins":
        ads = ADS1256Pins.from_wiringpi_defaults()
        return cls(
            req=ads.sclk,
            ready=ads.drdy,
            pi_tx0=ads.din,
            pi_tx1=ads.dout,
            stm_tx0=ads.cs,
            stm_tx1=ads.rst,
        )

    @property
    def pi_tx_pins(self) -> List[int]:
        return [self.pi_tx0, self.pi_tx1]

    @property
    def stm_tx_pins(self) -> List[int]:
        return [self.stm_tx0, self.stm_tx1]

    @property
    def named_pins(self) -> dict[str, int]:
        return {
            "REQ": self.req,
            "READY": self.ready,
            "PI_TX0": self.pi_tx0,
            "PI_TX1": self.pi_tx1,
            "STM_TX0": self.stm_tx0,
            "STM_TX1": self.stm_tx1,
        }


@dataclass(frozen=True)
class STM32ADS1256Sample:
    status: int
    seq: int
    raw: int
    uv: int
    age_ms: int

    @property
    def voltage_mv(self) -> float:
        return self.uv / 1000.0

    @property
    def has_valid_sample(self) -> bool:
        return bool(self.status & STATUS_VALID_SAMPLE)

    @property
    def request_had_error(self) -> bool:
        return bool(self.status & (STATUS_BAD_REQUEST | STATUS_UNSUPPORTED_CMD))


def crc16_ccitt(data: bytes) -> int:
    crc = 0xFFFF
    for byte in data:
        crc ^= byte << 8
        for _ in range(8):
            if crc & 0x8000:
                crc = ((crc << 1) ^ 0x1021) & 0xFFFF
            else:
                crc = (crc << 1) & 0xFFFF
    return crc


def iter_2bit_symbols(data: bytes) -> Iterable[int]:
    for byte in data:
        yield (byte >> 6) & 0x03
        yield (byte >> 4) & 0x03
        yield (byte >> 2) & 0x03
        yield byte & 0x03


class STM32ADS1256Bridge:
    def __init__(
        self,
        pins: Optional[STM32ParallelPins] = None,
        gpiochip: int = 0,
        timeout_s: float = 1.0,
        settle_s: float = 0.00002,
    ) -> None:
        self.pins = pins or STM32ParallelPins.from_ads1256_defaults()
        self.gpiochip = gpiochip
        self.timeout_s = timeout_s
        self.settle_s = settle_s
        self.handle: int | None = None
        self._req_level = 0
        self._ready_level = 0
        self._seq = 0

    def __enter__(self) -> "STM32ADS1256Bridge":
        self.open()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def open(self) -> None:
        if self.handle is not None:
            return
        self.handle = lgpio.gpiochip_open(self.gpiochip)
        try:
            lgpio.gpio_claim_output(self.handle, self.pins.req, 0)
            lgpio.gpio_claim_input(self.handle, self.pins.ready)
            for pin in self.pins.pi_tx_pins:
                lgpio.gpio_claim_output(self.handle, pin, 0)
            for pin in self.pins.stm_tx_pins:
                lgpio.gpio_claim_input(self.handle, pin)
            self._req_level = 0
            self._ready_level = int(lgpio.gpio_read(self.handle, self.pins.ready))
            time.sleep(0.02)
        except Exception:
            self.close()
            raise

    def close(self) -> None:
        if self.handle is None:
            return
        try:
            lgpio.gpio_write(self.handle, self.pins.req, 0)
            for pin in self.pins.pi_tx_pins:
                lgpio.gpio_write(self.handle, pin, 0)
        finally:
            lgpio.gpiochip_close(self.handle)
            self.handle = None

    def reopen(self) -> None:
        self.close()
        time.sleep(0.05)
        self.open()

    def _require_handle(self) -> int:
        if self.handle is None:
            raise RuntimeError("GPIO chip is not open")
        return self.handle

    def _write_down_symbol(self, value: int) -> None:
        handle = self._require_handle()
        for bit, pin in enumerate(self.pins.pi_tx_pins):
            lgpio.gpio_write(handle, pin, 1 if (value & (1 << bit)) else 0)

    def _read_up_symbol(self) -> int:
        handle = self._require_handle()
        value = 0
        for bit, pin in enumerate(self.pins.stm_tx_pins):
            if lgpio.gpio_read(handle, pin):
                value |= 1 << bit
        return value

    def _toggle_req(self) -> None:
        self._req_level ^= 1
        lgpio.gpio_write(self._require_handle(), self.pins.req, self._req_level)

    def _wait_ready_toggle(self) -> None:
        handle = self._require_handle()
        deadline = time.monotonic() + self.timeout_s
        while time.monotonic() < deadline:
            level = int(lgpio.gpio_read(handle, self.pins.ready))
            if level != self._ready_level:
                self._ready_level = level
                return
            time.sleep(0.0002)
        raise TimeoutError("READY did not toggle")

    def _send_request(self, request: bytes) -> None:
        for symbol in iter_2bit_symbols(request):
            self._write_down_symbol(symbol)
            time.sleep(self.settle_s)
            self._toggle_req()
            self._wait_ready_toggle()

    def _read_response(self, size: int) -> bytes:
        symbols: list[int] = []
        for _ in range(size * 4):
            self._wait_ready_toggle()
            time.sleep(self.settle_s)
            symbols.append(self._read_up_symbol())
            self._toggle_req()

        out = bytearray()
        for i in range(0, len(symbols), 4):
            out.append(
                ((symbols[i] & 0x03) << 6)
                | ((symbols[i + 1] & 0x03) << 4)
                | ((symbols[i + 2] & 0x03) << 2)
                | (symbols[i + 3] & 0x03)
            )
        return bytes(out)

    def build_get_sample_request(self, seq: int) -> bytes:
        packet = bytearray(REQUEST_LEN)
        packet[0] = 0xA5
        packet[1] = 0x5A
        packet[2] = CMD_GET_SAMPLE
        struct.pack_into("<H", packet, 3, seq & 0xFFFF)
        packet[5] = 0x00
        struct.pack_into("<H", packet, 6, crc16_ccitt(packet[:6]))
        return bytes(packet)

    def query_sample(self, seq: int | None = None) -> STM32ADS1256Sample:
        self.open()
        if seq is None:
            seq = self._seq
            self._seq = (self._seq + 1) & 0xFFFF

        request = self.build_get_sample_request(seq)
        self._send_request(request)
        response = self._read_response(RESPONSE_LEN)

        if response[0:2] != b"\xA5\x5A":
            raise STM32ParallelProtocolError(f"bad response header: {response.hex(' ')}")

        expected_crc = struct.unpack_from("<H", response, 15)[0]
        actual_crc = crc16_ccitt(response[:15])
        if expected_crc != actual_crc:
            raise STM32ParallelProtocolError(
                f"CRC mismatch: expected=0x{expected_crc:04X} actual=0x{actual_crc:04X}; "
                f"response={response.hex(' ')}"
            )

        return STM32ADS1256Sample(
            status=response[2],
            seq=struct.unpack_from("<H", response, 3)[0],
            raw=struct.unpack_from("<i", response, 5)[0],
            uv=struct.unpack_from("<i", response, 9)[0],
            age_ms=struct.unpack_from("<H", response, 13)[0],
        )
