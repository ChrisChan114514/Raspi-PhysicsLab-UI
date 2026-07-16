from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class Button(str, Enum):
    NONE = "NONE"
    SELECT_PREVIOUS = "SELECT_PREVIOUS"
    SELECT_NEXT = "SELECT_NEXT"
    DECREASE = "DECREASE"
    INCREASE = "INCREASE"
    TOGGLE_MEASUREMENT = "TOGGLE_MEASUREMENT"
    INTENSITY_UP = "INTENSITY_UP"
    INTENSITY_DOWN = "INTENSITY_DOWN"
    CLEAR_CURVE = "CLEAR_CURVE"
    PAUSE_MEASUREMENT = "PAUSE_MEASUREMENT"
    TOGGLE_FFT = "TOGGLE_FFT"
    EXIT = "EXIT"


@dataclass(frozen=True)
class ButtonReading:
    button: Button
    key: str = ""


@dataclass(frozen=True)
class ButtonEvent:
    button: Button
    key: str = ""
