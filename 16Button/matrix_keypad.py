#!/usr/bin/env python3
"""4x4 matrix keypad scanner using Raspberry Pi GPIO through lgpio."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Iterable, Sequence

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

DEFAULT_WIRINGPI_PINS = (13, 14, 30, 21, 22, 23, 24, 25)
STANDARD_KEYMAP = (
    ("1", "2", "3", "A"),
    ("4", "5", "6", "B"),
    ("7", "8", "9", "C"),
    ("*", "0", "#", "D"),
)

# Keymap corrected from the measured wiring result:
# press 1->D, 2->C, 3->B, A->A, 4->#, 5->9, 6->6, B->3,
# 7->0, 8->8, 9->5, C->2, *->*, 0->7, #->4, D->1.
DEFAULT_KEYMAP = (
    ("D", "C", "B", "A"),
    ("#", "9", "6", "3"),
    ("0", "8", "5", "2"),
    ("*", "7", "4", "1"),
)

KEYMAPS = {
    "measured": DEFAULT_KEYMAP,
    "standard": STANDARD_KEYMAP,
}


@dataclass(frozen=True)
class MatrixPins:
    rows: tuple[int, int, int, int]
    cols: tuple[int, int, int, int]

    @classmethod
    def from_wiringpi(
        cls,
        pins: Sequence[int] = DEFAULT_WIRINGPI_PINS,
        swap_rc: bool = False,
    ) -> "MatrixPins":
        if len(pins) != 8:
            raise ValueError("4x4 keypad needs exactly 8 pins")
        bcm = tuple(wiringpi_to_bcm(pin) for pin in pins)
        rows = bcm[:4]
        cols = bcm[4:]
        if swap_rc:
            rows, cols = cols, rows
        return cls(rows=rows, cols=cols)


@dataclass(frozen=True)
class KeyState:
    key: str
    row: int
    col: int


@dataclass(frozen=True)
class KeypadEvent:
    kind: str
    key: str
    keys: tuple[str, ...]


def wiringpi_to_bcm(pin: int) -> int:
    try:
        return WIRINGPI_TO_BCM[pin]
    except KeyError as exc:
        raise ValueError(f"unsupported WiringPi pin: {pin}") from exc


class MatrixKeypad:
    def __init__(
        self,
        pins: MatrixPins,
        keymap: Sequence[Sequence[str]] = DEFAULT_KEYMAP,
        gpiochip: int = 0,
        settle_s: float = 0.001,
    ) -> None:
        self.pins = pins
        self.keymap = keymap
        self.gpiochip = gpiochip
        self.settle_s = settle_s
        self.handle: int | None = None

    def __enter__(self) -> "MatrixKeypad":
        self.open()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:  # noqa: ANN001
        self.close()

    def open(self) -> None:
        self.handle = lgpio.gpiochip_open(self.gpiochip)
        for row_pin in self.pins.rows:
            lgpio.gpio_claim_output(self._handle, row_pin, 0)
        for col_pin in self.pins.cols:
            lgpio.gpio_claim_input(self._handle, col_pin, getattr(lgpio, "SET_PULL_DOWN", 0))

    def close(self) -> None:
        if self.handle is not None:
            self._drive_rows(0)
            lgpio.gpiochip_close(self.handle)
            self.handle = None

    @property
    def _handle(self) -> int:
        if self.handle is None:
            raise RuntimeError("GPIO chip is not open")
        return self.handle

    def scan(self) -> list[KeyState]:
        pressed: list[KeyState] = []
        for row_index, row_pin in enumerate(self.pins.rows):
            self._drive_rows(0)
            lgpio.gpio_write(self._handle, row_pin, 1)
            time.sleep(self.settle_s)

            for col_index, col_pin in enumerate(self.pins.cols):
                if lgpio.gpio_read(self._handle, col_pin):
                    pressed.append(
                        KeyState(
                            key=self.keymap[row_index][col_index],
                            row=row_index,
                            col=col_index,
                        )
                    )

        self._drive_rows(0)
        return pressed

    def scan_keys(self) -> tuple[str, ...]:
        return normalize_keys(item.key for item in self.scan())

    def _drive_rows(self, level: int) -> None:
        for row_pin in self.pins.rows:
            lgpio.gpio_write(self._handle, row_pin, level)


class DebouncedMatrixKeypad:
    """Reusable 4x4 keypad API with debounced stable state and edge events."""

    def __init__(
        self,
        keypad: MatrixKeypad,
        debounce_s: float = 0.035,
    ) -> None:
        self.keypad = keypad
        self.debounce_s = debounce_s
        self.last_raw: tuple[str, ...] = ()
        self.stable_keys: tuple[str, ...] = ()
        self.changed_at = time.monotonic()

    def __enter__(self) -> "DebouncedMatrixKeypad":
        self.open()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:  # noqa: ANN001
        self.close()

    def open(self) -> None:
        self.keypad.open()
        self.changed_at = time.monotonic()

    def close(self) -> None:
        self.keypad.close()

    def poll(self) -> list[KeypadEvent]:
        raw_keys = self.keypad.scan_keys()
        now = time.monotonic()

        if raw_keys != self.last_raw:
            self.last_raw = raw_keys
            self.changed_at = now

        if now - self.changed_at < self.debounce_s or raw_keys == self.stable_keys:
            return []

        previous = self.stable_keys
        self.stable_keys = raw_keys
        events: list[KeypadEvent] = []

        for key in self.stable_keys:
            if key not in previous:
                events.append(KeypadEvent("KEY_DOWN", key, self.stable_keys))
        for key in previous:
            if key not in self.stable_keys:
                events.append(KeypadEvent("KEY_UP", key, self.stable_keys))
        return events


def normalize_keys(keys: Iterable[str]) -> tuple[str, ...]:
    return tuple(sorted(keys))


def keymap_by_name(name: str) -> tuple[tuple[str, str, str, str], ...]:
    try:
        return KEYMAPS[name]
    except KeyError as exc:
        raise ValueError(f"unsupported keymap: {name}") from exc


def format_pin_map(wiringpi_pins: Iterable[int], pins: MatrixPins) -> str:
    source = tuple(wiringpi_pins)
    parts = ["Keypad pin map:"]
    for index, wiringpi_pin in enumerate(source, start=1):
        role = "ROW" if index <= 4 else "COL"
        role_index = index if index <= 4 else index - 4
        bcm = wiringpi_to_bcm(wiringpi_pin)
        parts.append(f"  P{index}: WiringPi {wiringpi_pin:2d} -> BCM GPIO{bcm:2d} -> {role}{role_index}")
    parts.append(f"Rows BCM: {pins.rows}")
    parts.append(f"Cols BCM: {pins.cols}")
    return "\n".join(parts)
