#!/usr/bin/env python3
"""Load installation-specific parameters for the EMM lamp wheel."""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path


BASE_LAMP_ANGLES_DEG = (0.0, 60.0, 120.0, 180.0, 240.0, 300.0)
DEFAULT_CONFIG_PATH = Path(__file__).with_name("motor_config.json")


class MotorConfigError(ValueError):
    """The motor parameter file is missing or contains invalid values."""


@dataclass(frozen=True)
class MotorParameters:
    lamp_angle_offset_deg: float

    @property
    def lamp_angles_deg(self) -> tuple[float, ...]:
        return tuple(
            angle + self.lamp_angle_offset_deg
            for angle in BASE_LAMP_ANGLES_DEG
        )


def load_motor_parameters(
    config_path: str | Path | None = None,
) -> MotorParameters:
    path = Path(config_path) if config_path is not None else DEFAULT_CONFIG_PATH
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise MotorConfigError(f"motor parameter file not found: {path}") from exc
    except OSError as exc:
        raise MotorConfigError(f"cannot read motor parameter file {path}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise MotorConfigError(
            f"invalid JSON in motor parameter file {path}: {exc}"
        ) from exc

    if not isinstance(data, dict):
        raise MotorConfigError(f"motor parameter file must contain a JSON object: {path}")
    if "lamp_angle_offset_deg" not in data:
        raise MotorConfigError(
            f"missing 'lamp_angle_offset_deg' in motor parameter file: {path}"
        )

    offset = data["lamp_angle_offset_deg"]
    if isinstance(offset, bool) or not isinstance(offset, (int, float)):
        raise MotorConfigError("lamp_angle_offset_deg must be a number")
    offset = float(offset)
    if not math.isfinite(offset):
        raise MotorConfigError("lamp_angle_offset_deg must be finite")

    return MotorParameters(lamp_angle_offset_deg=offset)


def save_lamp_angle_offset(
    lamp_angle_offset_deg: float,
    config_path: str | Path | None = None,
) -> MotorParameters:
    if isinstance(lamp_angle_offset_deg, bool) or not isinstance(
        lamp_angle_offset_deg,
        (int, float),
    ):
        raise MotorConfigError("lamp_angle_offset_deg must be a number")
    offset = float(lamp_angle_offset_deg)
    if not math.isfinite(offset):
        raise MotorConfigError("lamp_angle_offset_deg must be finite")

    path = Path(config_path) if config_path is not None else DEFAULT_CONFIG_PATH
    temporary_path = path.with_suffix(path.suffix + ".tmp")
    payload = {"lamp_angle_offset_deg": round(offset, 6)}
    try:
        temporary_path.write_text(
            json.dumps(payload, ensure_ascii=True, indent=2) + "\n",
            encoding="utf-8",
        )
        temporary_path.replace(path)
    except OSError as exc:
        try:
            temporary_path.unlink(missing_ok=True)
        except OSError:
            pass
        raise MotorConfigError(f"cannot write motor parameter file {path}: {exc}") from exc
    return MotorParameters(lamp_angle_offset_deg=offset)
