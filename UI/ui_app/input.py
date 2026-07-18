from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class Button(str, Enum):
    NONE = "NONE"
    SELECT_PREVIOUS = "SELECT_PREVIOUS"
    SELECT_NEXT = "SELECT_NEXT"
    DECREASE = "DECREASE"
    INCREASE = "INCREASE"
    CONFIRM = "CONFIRM"
    INTENSITY_UP = "INTENSITY_UP"
    INTENSITY_DOWN = "INTENSITY_DOWN"
    CLEAR_CURVE = "CLEAR_CURVE"
    TOGGLE_CAMERA = "TOGGLE_CAMERA"
    TOGGLE_MEASUREMENT = "TOGGLE_MEASUREMENT"
    TOGGLE_FFT = "TOGGLE_FFT"
    TEXT_INPUT = "TEXT_INPUT"


@dataclass(frozen=True)
class ButtonReading:
    button: Button
    key: str = ""
    keys: tuple[str, ...] = ()
    conflict: bool = False


@dataclass(frozen=True)
class ButtonEvent:
    button: Button
    key: str = ""
