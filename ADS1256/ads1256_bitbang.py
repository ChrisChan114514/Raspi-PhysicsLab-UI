#!/usr/bin/env python3
"""Minimal ADS1256 bit-banged SPI driver for Raspberry Pi connection checks."""

from __future__ import annotations

import time
from dataclasses import dataclass
from statistics import median
from typing import Dict, Iterable, List, Optional, Sequence

import lgpio


WIRINGPI_TO_BCM = {
    0: 17,
    1: 18,
    2: 27,
    3: 22,
    4: 23,
    5: 24,
    6: 25,
    7: 4,
    8: 2,
    9: 3,
    10: 8,
    11: 7,
    12: 10,
    13: 9,
    14: 11,
    15: 14,
    16: 15,
    21: 5,
    22: 6,
    23: 13,
    24: 19,
    25: 26,
    26: 12,
    27: 16,
    28: 20,
    29: 21,
    30: 0,
    31: 1,
}

STATUS_REG = 0x00
MUX_REG = 0x01
ADCON_REG = 0x02
DRATE_REG = 0x03
IO_REG = 0x04

ADCON_CLKOUT_OFF = 0x00
ADCON_SDCS_OFF = 0x00

SING_0 = 0x0F
SING_1 = 0x1F
SING_2 = 0x2F
SING_3 = 0x3F
SING_4 = 0x4F
SING_5 = 0x5F
SING_6 = 0x6F
SING_7 = 0x7F

DIFF_0_1 = 0x01
DIFF_2_3 = 0x23
DIFF_4_5 = 0x45
DIFF_6_7 = 0x67

PGA_1 = 0x00
PGA_2 = 0x01
PGA_4 = 0x02
PGA_8 = 0x03
PGA_16 = 0x04
PGA_32 = 0x05
PGA_64 = 0x06

DRATE_30000SPS = 0xF0
DRATE_15000SPS = 0xE0
DRATE_7500SPS = 0xD0
DRATE_3750SPS = 0xC0
DRATE_2000SPS = 0xB0
DRATE_1000SPS = 0xA1
DRATE_500SPS = 0x92
DRATE_100SPS = 0x82
DRATE_60SPS = 0x72
DRATE_50SPS = 0x63
DRATE_30SPS = 0x53
DRATE_25SPS = 0x43
DRATE_15SPS = 0x33
DRATE_10SPS = 0x23
DRATE_5SPS = 0x13
DRATE_2SPS = 0x03

RDATA = 0x01
SDATAC = 0x0F
RREG = 0x10
WREG = 0x50
SELFCAL = 0xF0
SYNC = 0xFC
WAKEUP = 0x00
RESET = 0xFE

SINGLE_ENDED_MUX = (
    SING_0,
    SING_1,
    SING_2,
    SING_3,
    SING_4,
    SING_5,
    SING_6,
    SING_7,
)

DIFFERENTIAL_MUX = {
    (0, 1): DIFF_0_1,
    (2, 3): DIFF_2_3,
    (4, 5): DIFF_4_5,
    (6, 7): DIFF_6_7,
}

PGA_GAIN_BY_CODE = {
    PGA_1: 1,
    PGA_2: 2,
    PGA_4: 4,
    PGA_8: 8,
    PGA_16: 16,
    PGA_32: 32,
    PGA_64: 64,
}


class ADS1256ProtocolError(RuntimeError):
    """Raised when the serial interface does not complete an ADS1256 transaction."""


@dataclass(frozen=True)
class ADS1256Pins:
    d3: int
    d2: int
    d1: int
    d0: int
    sclk: int
    din: int
    dout: int
    drdy: int
    cs: int
    rst: int

    @classmethod
    def from_bcm_defaults(cls) -> "ADS1256Pins":
        return cls(
            d3=0,
            d2=1,
            d1=2,
            d0=3,
            sclk=4,
            din=5,
            dout=6,
            drdy=27,
            cs=28,
            rst=29,
        )

    @classmethod
    def from_wiringpi_defaults(cls) -> "ADS1256Pins":
        return cls(
            d3=wiringpi_to_bcm(0),
            d2=wiringpi_to_bcm(1),
            d1=wiringpi_to_bcm(2),
            d0=wiringpi_to_bcm(3),
            sclk=wiringpi_to_bcm(4),
            din=wiringpi_to_bcm(5),
            dout=wiringpi_to_bcm(6),
            drdy=wiringpi_to_bcm(27),
            cs=wiringpi_to_bcm(28),
            rst=wiringpi_to_bcm(29),
        )

    @property
    def data_pins_by_bit(self) -> Dict[int, int]:
        return {
            0: self.d0,
            1: self.d1,
            2: self.d2,
            3: self.d3,
        }

    @property
    def named_pins(self) -> Dict[str, int]:
        return {
            "D3": self.d3,
            "D2": self.d2,
            "D1": self.d1,
            "D0": self.d0,
            "SCLK": self.sclk,
            "DIN": self.din,
            "DOUT": self.dout,
            "DRDY": self.drdy,
            "CS": self.cs,
            "RST": self.rst,
        }


@dataclass(frozen=True)
class ADS1256SampleStats:
    raw: int
    voltage: float
    samples: int
    method: str
    min_raw: int
    max_raw: int
    span_raw: int
    mean_raw: float
    min_voltage: float
    max_voltage: float
    span_voltage: float


def wiringpi_to_bcm(pin: int) -> int:
    try:
        return WIRINGPI_TO_BCM[pin]
    except KeyError as exc:
        raise ValueError(f"unsupported WiringPi pin: {pin}") from exc


class ADS1256BitBang:
    """Small ADS1256 helper using lgpio and software SPI mode 1."""

    def __init__(
        self,
        pins: Optional[ADS1256Pins] = None,
        gpiochip: int = 0,
        half_period_us: float = 5.0,
    ) -> None:
        self.pins = pins or ADS1256Pins.from_wiringpi_defaults()
        self.gpiochip = gpiochip
        self.half_period_us = half_period_us
        self.handle: Optional[int] = None

    def __enter__(self) -> "ADS1256BitBang":
        self.open()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:  # noqa: ANN001
        self.close()

    def open(self) -> None:
        self.handle = lgpio.gpiochip_open(self.gpiochip)
        self._claim_outputs(
            {
                self.pins.sclk: 0,
                self.pins.din: 0,
                self.pins.cs: 1,
                self.pins.rst: 1,
            }
        )
        self.claim_data_pins_input()
        self._claim_inputs([self.pins.dout, self.pins.drdy])

    def close(self) -> None:
        if self.handle is not None:
            lgpio.gpiochip_close(self.handle)
            self.handle = None

    def _require_handle(self) -> int:
        if self.handle is None:
            raise RuntimeError("GPIO chip is not open")
        return self.handle

    def _claim_outputs(self, pin_levels: Dict[int, int]) -> None:
        handle = self._require_handle()
        for pin, level in pin_levels.items():
            lgpio.gpio_claim_output(handle, pin, int(bool(level)))

    def _claim_inputs(self, pins: Iterable[int]) -> None:
        handle = self._require_handle()
        for pin in pins:
            lgpio.gpio_claim_input(handle, pin)

    def claim_data_pins_input(self) -> None:
        self._claim_inputs(self.pins.data_pins_by_bit.values())

    def claim_data_pins_output(self, nibble: int = 0) -> None:
        self._claim_outputs(
            {
                pin: (nibble >> bit) & 0x01
                for bit, pin in self.pins.data_pins_by_bit.items()
            }
        )

    def write_data_pins(self, nibble: int) -> None:
        for bit, pin in self.pins.data_pins_by_bit.items():
            self.write(pin, (nibble >> bit) & 0x01)

    def read_data_pins(self) -> int:
        value = 0
        for bit, pin in self.pins.data_pins_by_bit.items():
            value |= self.read(pin) << bit
        return value

    def read(self, pin: int) -> int:
        return int(lgpio.gpio_read(self._require_handle(), pin))

    def write(self, pin: int, level: int) -> None:
        lgpio.gpio_write(self._require_handle(), pin, int(bool(level)))

    def cs_low(self) -> None:
        self.write(self.pins.cs, 0)
        self.delay_us(5)

    def cs_high(self) -> None:
        self.delay_us(5)
        self.write(self.pins.cs, 1)

    def delay_us(self, microseconds: float) -> None:
        if microseconds <= 0:
            return
        deadline_ns = time.perf_counter_ns() + round(microseconds * 1000.0)
        while time.perf_counter_ns() < deadline_ns:
            pass

    def hardware_reset(self, low_ms: float = 200.0, high_ms: float = 1000.0) -> None:
        self.write(self.pins.cs, 1)
        self.write(self.pins.sclk, 0)
        self.write(self.pins.din, 0)
        self.write(self.pins.rst, 0)
        time.sleep(low_ms / 1000.0)
        self.write(self.pins.rst, 1)
        time.sleep(high_ms / 1000.0)

    def wait_drdy_low(self, timeout_s: float = 2.0) -> bool:
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            if self.read(self.pins.drdy) == 0:
                return True
            time.sleep(0.001)
        return False

    def transfer_byte(self, value: int) -> int:
        """Transfer one byte with SPI mode 1: idle low, sample after falling edge."""
        result = 0
        for bit_index in range(7, -1, -1):
            self.write(self.pins.din, (value >> bit_index) & 0x01)
            self.delay_us(self.half_period_us)
            self.write(self.pins.sclk, 1)
            self.delay_us(self.half_period_us)
            self.write(self.pins.sclk, 0)
            result = (result << 1) | self.read(self.pins.dout)
            self.delay_us(self.half_period_us)
        return result

    def command(self, value: int, wait_drdy: bool = True) -> None:
        if wait_drdy:
            self.wait_drdy_low()
        self.cs_low()
        self.transfer_byte(value)
        self.cs_high()

    def direct_command(self, value: int, timeout_s: float = 2.0) -> None:
        if not self.wait_drdy_low(timeout_s):
            raise TimeoutError("DRDY did not go low before direct command")
        self.cs_low()
        self.transfer_byte(value)
        self.cs_high()

    def read_registers(
        self,
        start_register: int,
        count: int = 1,
        timeout_s: float = 2.0,
    ) -> List[int]:
        if not self.wait_drdy_low(timeout_s):
            raise TimeoutError("DRDY did not go low before RREG")

        self.cs_low()
        self.transfer_byte(RREG | (start_register & 0x0F))
        self.transfer_byte((count - 1) & 0xFF)
        self.delay_us(10)
        values = [self.transfer_byte(0xFF) for _ in range(count)]
        self.cs_high()
        return values

    def read_register(self, register: int, timeout_s: float = 2.0) -> int:
        return self.read_registers(register, 1, timeout_s=timeout_s)[0]

    def write_registers(
        self,
        start_register: int,
        values: Iterable[int],
        timeout_s: float = 2.0,
    ) -> None:
        values = list(values)
        if not values:
            return
        if not self.wait_drdy_low(timeout_s):
            raise TimeoutError("DRDY did not go low before WREG")

        self.cs_low()
        self.transfer_byte(WREG | (start_register & 0x0F))
        self.transfer_byte((len(values) - 1) & 0xFF)
        for value in values:
            self.transfer_byte(value & 0xFF)
        self.cs_high()

    def write_register(self, register: int, value: int, timeout_s: float = 2.0) -> None:
        self.write_registers(register, [value], timeout_s=timeout_s)

    def read_named_registers(self) -> Dict[str, int]:
        values = self.read_registers(STATUS_REG, 5)
        return {
            "STATUS": values[0],
            "MUX": values[1],
            "ADCON": values[2],
            "DRATE": values[3],
            "IO": values[4],
        }

    def verify_single_ended_configuration(
        self,
        channel: int,
        pga: int,
        drate: int,
        buffer_enabled: bool,
        autocal_enabled: bool,
    ) -> Dict[str, int]:
        registers = self.read_named_registers()
        expected_status_options = (0x02 if buffer_enabled else 0x00) | (
            0x04 if autocal_enabled else 0x00
        )
        expected = {
            "STATUS options": expected_status_options,
            "MUX": SINGLE_ENDED_MUX[channel],
            "ADCON": ADCON_CLKOUT_OFF | ADCON_SDCS_OFF | (pga & 0x07),
            "DRATE": drate,
        }
        actual = {
            "STATUS options": registers["STATUS"] & 0x0E,
            "MUX": registers["MUX"],
            "ADCON": registers["ADCON"] & 0x7F,
            "DRATE": registers["DRATE"],
        }
        mismatches = [
            f"{name}=0x{actual[name]:02X}, expected=0x{value:02X}"
            for name, value in expected.items()
            if actual[name] != value
        ]
        if mismatches:
            raise ADS1256ProtocolError("ADS1256 configuration mismatch: " + "; ".join(mismatches))
        return registers

    def configure_single_ended(
        self,
        channel: int,
        pga: int = PGA_1,
        drate: int = DRATE_100SPS,
        buffer_enabled: bool = False,
        autocal_enabled: bool = True,
        selfcal: bool = True,
        timeout_s: float = 2.0,
    ) -> None:
        if channel < 0 or channel >= len(SINGLE_ENDED_MUX):
            raise ValueError("single-ended channel must be 0..7")
        if pga not in PGA_GAIN_BY_CODE:
            raise ValueError("PGA code must be one of 0..6")

        self.direct_command(SDATAC, timeout_s=timeout_s)
        self.set_status_options(
            buffer_enabled=buffer_enabled,
            autocal_enabled=autocal_enabled,
            timeout_s=timeout_s,
        )
        self.write_register(MUX_REG, SINGLE_ENDED_MUX[channel], timeout_s=timeout_s)

        self.set_adcon_options(pga=pga, timeout_s=timeout_s)
        self.write_register(DRATE_REG, drate, timeout_s=timeout_s)

        if selfcal:
            self.direct_command(SELFCAL, timeout_s=timeout_s)
            if not self.wait_drdy_low(timeout_s):
                raise TimeoutError("DRDY did not go low after SELFCAL")

        self.sync_wakeup(timeout_s=timeout_s)
        self.verify_single_ended_configuration(
            channel=channel,
            pga=pga,
            drate=drate,
            buffer_enabled=buffer_enabled,
            autocal_enabled=autocal_enabled,
        )

    def configure_differential(
        self,
        positive_channel: int,
        negative_channel: int,
        pga: int = PGA_1,
        drate: int = DRATE_100SPS,
        buffer_enabled: bool = False,
        autocal_enabled: bool = True,
        selfcal: bool = True,
        timeout_s: float = 2.0,
    ) -> None:
        mux = DIFFERENTIAL_MUX.get((positive_channel, negative_channel))
        if mux is None:
            raise ValueError("supported differential pairs are (0,1), (2,3), (4,5), (6,7)")
        self.configure_mux(
            mux=mux,
            pga=pga,
            drate=drate,
            buffer_enabled=buffer_enabled,
            autocal_enabled=autocal_enabled,
            selfcal=selfcal,
            timeout_s=timeout_s,
        )

    def configure_mux(
        self,
        mux: int,
        pga: int = PGA_1,
        drate: int = DRATE_100SPS,
        buffer_enabled: bool = False,
        autocal_enabled: bool = True,
        selfcal: bool = True,
        timeout_s: float = 2.0,
    ) -> None:
        if pga not in PGA_GAIN_BY_CODE:
            raise ValueError("PGA code must be one of 0..6")

        self.direct_command(SDATAC, timeout_s=timeout_s)
        self.set_status_options(
            buffer_enabled=buffer_enabled,
            autocal_enabled=autocal_enabled,
            timeout_s=timeout_s,
        )
        self.write_register(MUX_REG, mux & 0xFF, timeout_s=timeout_s)
        self.set_adcon_options(pga=pga, timeout_s=timeout_s)
        self.write_register(DRATE_REG, drate, timeout_s=timeout_s)

        if selfcal:
            self.direct_command(SELFCAL, timeout_s=timeout_s)
            if not self.wait_drdy_low(timeout_s):
                raise TimeoutError("DRDY did not go low after SELFCAL")

        self.sync_wakeup(timeout_s=timeout_s)

    def set_adcon_options(
        self,
        pga: int = PGA_1,
        timeout_s: float = 2.0,
    ) -> int:
        if pga not in PGA_GAIN_BY_CODE:
            raise ValueError("PGA code must be one of 0..6")

        adcon = ADCON_CLKOUT_OFF | ADCON_SDCS_OFF | (pga & 0x07)
        self.write_register(ADCON_REG, adcon, timeout_s=timeout_s)
        return self.read_register(ADCON_REG, timeout_s=timeout_s)

    def set_status_options(
        self,
        buffer_enabled: bool = True,
        autocal_enabled: bool = True,
        timeout_s: float = 2.0,
    ) -> int:
        status = self.read_register(STATUS_REG, timeout_s=timeout_s)
        # Preserve the device ID and read-only DRDY bit; force MSB-first output.
        status &= 0xF1
        if buffer_enabled:
            status |= 0x02
        if autocal_enabled:
            status |= 0x04
        self.write_register(STATUS_REG, status, timeout_s=timeout_s)
        return self.read_register(STATUS_REG, timeout_s=timeout_s)

    def wakeup(self) -> None:
        self.cs_low()
        self.transfer_byte(WAKEUP)
        self.cs_high()

    def sync_wakeup(self, timeout_s: float = 2.0) -> None:
        if not self.wait_drdy_low(timeout_s):
            raise TimeoutError("DRDY did not go low before SYNC/WAKEUP")
        self.cs_low()
        self.transfer_byte(SYNC)
        self.delay_us(5)
        self.transfer_byte(WAKEUP)
        self.cs_high()

    def read_single_raw(self, timeout_s: float = 2.0) -> int:
        if not self.wait_drdy_low(timeout_s):
            raise TimeoutError("DRDY did not go low before RDATA")

        self.cs_low()
        self.transfer_byte(RDATA)
        self.delay_us(10)
        raw = (
            (self.transfer_byte(0xFF) << 16)
            | (self.transfer_byte(0xFF) << 8)
            | self.transfer_byte(0xFF)
        )
        self.cs_high()
        if self.read(self.pins.drdy) == 0:
            raise ADS1256ProtocolError(
                "DRDY remained low after 24-bit RDATA; the software-SPI transaction lost alignment"
            )
        return signed24_to_int(raw)

    def read_voltage(
        self,
        vref: float = 2.5,
        pga: int = PGA_1,
        timeout_s: float = 2.0,
    ) -> float:
        return raw_to_voltage(self.read_single_raw(timeout_s=timeout_s), vref=vref, pga=pga)

    def read_raw_samples(
        self,
        samples: int = 8,
        discard: int = 3,
        timeout_s: float = 2.0,
    ) -> List[int]:
        if samples <= 0:
            raise ValueError("samples must be positive")
        if discard < 0:
            raise ValueError("discard must not be negative")

        for _ in range(discard):
            self.read_single_raw(timeout_s=timeout_s)
        return [self.read_single_raw(timeout_s=timeout_s) for _ in range(samples)]

    def read_stable_raw(
        self,
        samples: int = 8,
        discard: int = 3,
        method: str = "median",
        timeout_s: float = 2.0,
    ) -> int:
        return combine_samples(
            self.read_raw_samples(samples=samples, discard=discard, timeout_s=timeout_s),
            method=method,
        )

    def read_stable_voltage(
        self,
        vref: float = 2.5,
        pga: int = PGA_1,
        samples: int = 8,
        discard: int = 3,
        method: str = "median",
        timeout_s: float = 2.0,
    ) -> float:
        raw = self.read_stable_raw(
            samples=samples,
            discard=discard,
            method=method,
            timeout_s=timeout_s,
        )
        return raw_to_voltage(raw, vref=vref, pga=pga)

    def read_voltage_stats(
        self,
        vref: float = 2.5,
        pga: int = PGA_1,
        samples: int = 8,
        discard: int = 3,
        method: str = "median",
        timeout_s: float = 2.0,
    ) -> ADS1256SampleStats:
        raws = self.read_raw_samples(samples=samples, discard=discard, timeout_s=timeout_s)
        raw = combine_samples(raws, method=method)
        min_raw = min(raws)
        max_raw = max(raws)
        min_voltage = raw_to_voltage(min_raw, vref=vref, pga=pga)
        max_voltage = raw_to_voltage(max_raw, vref=vref, pga=pga)
        return ADS1256SampleStats(
            raw=raw,
            voltage=raw_to_voltage(raw, vref=vref, pga=pga),
            samples=len(raws),
            method=method,
            min_raw=min_raw,
            max_raw=max_raw,
            span_raw=max_raw - min_raw,
            mean_raw=sum(raws) / len(raws),
            min_voltage=min_voltage,
            max_voltage=max_voltage,
            span_voltage=max_voltage - min_voltage,
        )


def signed24_to_int(value: int) -> int:
    value &= 0xFFFFFF
    if value & 0x800000:
        return value - 0x1000000
    return value


def raw_to_voltage(raw: int, vref: float = 2.5, pga: int = PGA_1) -> float:
    gain = PGA_GAIN_BY_CODE[pga]
    return raw * ((2.0 * vref) / 8_388_608.0) / gain


def combine_samples(raws: Sequence[int], method: str = "median") -> int:
    if not raws:
        raise ValueError("raws must not be empty")
    if method == "mean":
        return round(sum(raws) / len(raws))
    if method == "median":
        return round(median(raws))
    raise ValueError("method must be 'median' or 'mean'")
