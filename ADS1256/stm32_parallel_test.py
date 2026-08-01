#!/usr/bin/env python3
"""Test Raspberry Pi <-> STM32 2-bit single-direction handshake bridge.

This uses the Raspberry Pi pins that were previously used by the direct
ADS1256 bit-banged SPI driver.  The bus is not half-duplex:

* Pi -> STM32: REQ + PI_TX0 + PI_TX1
* STM32 -> Pi: READY + STM_TX0 + STM_TX1

Every byte is transferred as four 2-bit symbols, MSB first: bits 7..6, 5..4,
3..2, 1..0.  REQ and READY are toggle handshakes, so Linux scheduling jitter is
fine; STM32 keeps output bits stable until Pi acknowledges them.
"""

from __future__ import annotations

import argparse
import struct
import sys
import time
from dataclasses import dataclass
from typing import Iterable, List

import lgpio

from ads1256_bitbang import ADS1256Pins


CMD_GET_SAMPLE = 0x01
REQUEST_LEN = 8
RESPONSE_LEN = 17


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


class STM32ParallelBridge:
    def __init__(
        self,
        pins: STM32ParallelPins | None = None,
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

    def __enter__(self) -> "STM32ParallelBridge":
        self.handle = lgpio.gpiochip_open(self.gpiochip)
        lgpio.gpio_claim_output(self.handle, self.pins.req, 0)
        lgpio.gpio_claim_input(self.handle, self.pins.ready)
        for pin in self.pins.pi_tx_pins:
            lgpio.gpio_claim_output(self.handle, pin, 0)
        for pin in self.pins.stm_tx_pins:
            lgpio.gpio_claim_input(self.handle, pin)
        self._req_level = 0
        self._ready_level = int(lgpio.gpio_read(self.handle, self.pins.ready))
        time.sleep(0.02)
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if self.handle is not None:
            lgpio.gpio_write(self.handle, self.pins.req, 0)
            for pin in self.pins.pi_tx_pins:
                lgpio.gpio_write(self.handle, pin, 0)
            lgpio.gpiochip_close(self.handle)
            self.handle = None

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

    def query_sample(self, seq: int) -> dict[str, int | float]:
        request = self.build_get_sample_request(seq)
        self._send_request(request)
        response = self._read_response(RESPONSE_LEN)

        if response[0:2] != b"\xA5\x5A":
            raise RuntimeError(f"bad response header: {response.hex(' ')}")

        expected_crc = struct.unpack_from("<H", response, 15)[0]
        actual_crc = crc16_ccitt(response[:15])
        if expected_crc != actual_crc:
            raise RuntimeError(
                f"CRC mismatch: expected=0x{expected_crc:04X} actual=0x{actual_crc:04X}; "
                f"response={response.hex(' ')}"
            )

        status = response[2]
        resp_seq = struct.unpack_from("<H", response, 3)[0]
        raw = struct.unpack_from("<i", response, 5)[0]
        uv = struct.unpack_from("<i", response, 9)[0]
        age_ms = struct.unpack_from("<H", response, 13)[0]

        return {
            "status": status,
            "seq": resp_seq,
            "raw": raw,
            "uv": uv,
            "mv": uv / 1000.0,
            "age_ms": age_ms,
        }


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

    seq = 0
    done = 0
    try:
        with STM32ParallelBridge(pins=pins, gpiochip=args.gpiochip, timeout_s=args.timeout) as bridge:
            while args.count <= 0 or done < args.count:
                sample = bridge.query_sample(seq)
                print(
                    "seq={seq:05d} status=0x{status:02X} raw={raw:9d} "
                    "uV={uv:9d} mV={mv:+.3f} age={age_ms}ms".format(**sample),
                    flush=True,
                )
                seq = (seq + 1) & 0xFFFF
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
