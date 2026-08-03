#!/usr/bin/env python3
"""Load installation-specific parameters for the EMM lamp wheel.

Configuration format (motor_config.json)::

    {
      "calibration_offset_deg": 0.0,
      "lamp_fine_tune_deg": [0.0, 0.0, 0.0, 0.0, 0.0, 0.0]
    }

- ``calibration_offset_deg`` — absolute offset for the 400 nm calibration
  lamp (lamp index 0).  All other lamps are placed at 60° intervals from
  this reference.
- ``lamp_fine_tune_deg`` — per‑lamp relative fine‑tune adjustments (six
  values, one per lamp).  The final angle for lamp *i* is::

      calibration_offset_deg + BASE_LAMP_ANGLES_DEG[i] + lamp_fine_tune_deg[i]

Legacy files containing only ``lamp_angle_offset_deg`` are migrated
automatically on load.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path


BASE_LAMP_ANGLES_DEG = (0.0, 60.0, 120.0, 180.0, 240.0, 300.0)
NUM_LAMPS = len(BASE_LAMP_ANGLES_DEG)
DEFAULT_CONFIG_PATH = Path(__file__).with_name("motor_config.json")


class MotorConfigError(ValueError):
    """The motor parameter file is missing or contains invalid values."""


@dataclass(frozen=True)
class MotorParameters:
    calibration_offset_deg: float
    lamp_fine_tune_deg: tuple[float, ...]

    @property
    def lamp_angle_offset_deg(self) -> float:
        """Backward‑compatible alias: total offset of lamp 0."""
        return self.calibration_offset_deg + self.lamp_fine_tune_deg[0]

    @property
    def lamp_angles_deg(self) -> tuple[float, ...]:
        return tuple(
            self.calibration_offset_deg + base + fine
            for base, fine in zip(BASE_LAMP_ANGLES_DEG, self.lamp_fine_tune_deg)
        )


def _validate_offset(value: object, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise MotorConfigError(f"{label} must be a number")
    number = float(value)
    if not math.isfinite(number):
        raise MotorConfigError(f"{label} must be finite")
    return number


def _validate_fine_tune_list(data: object, path: Path) -> tuple[float, ...]:
    if not isinstance(data, list):
        raise MotorConfigError(
            f"lamp_fine_tune_deg must be a list in motor parameter file: {path}"
        )
    if len(data) != NUM_LAMPS:
        raise MotorConfigError(
            f"lamp_fine_tune_deg must contain exactly {NUM_LAMPS} values, "
            f"got {len(data)} in: {path}"
        )
    result: list[float] = []
    for index, item in enumerate(data):
        result.append(_validate_offset(item, f"lamp_fine_tune_deg[{index}]"))
    return tuple(result)


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
        raise MotorConfigError(
            f"motor parameter file must contain a JSON object: {path}"
        )

    # ── migrate legacy format ──────────────────────────────────────
    if "lamp_angle_offset_deg" in data and "calibration_offset_deg" not in data:
        legacy = _validate_offset(
            data["lamp_angle_offset_deg"],
            "lamp_angle_offset_deg",
        )
        return MotorParameters(
            calibration_offset_deg=legacy,
            lamp_fine_tune_deg=(0.0,) * NUM_LAMPS,
        )

    # ── new format ─────────────────────────────────────────────────
    if "calibration_offset_deg" not in data:
        raise MotorConfigError(
            f"missing 'calibration_offset_deg' in motor parameter file: {path}"
        )
    calibration = _validate_offset(
        data["calibration_offset_deg"],
        "calibration_offset_deg",
    )

    fine_tune = (0.0,) * NUM_LAMPS
    if "lamp_fine_tune_deg" in data:
        fine_tune = _validate_fine_tune_list(data["lamp_fine_tune_deg"], path)

    return MotorParameters(
        calibration_offset_deg=calibration,
        lamp_fine_tune_deg=fine_tune,
    )


def save_calibration(
    calibration_offset_deg: float,
    lamp_fine_tune_deg: tuple[float, ...] | None = None,
    config_path: str | Path | None = None,
) -> MotorParameters:
    """Persist the calibration offset and (optionally) per‑lamp fine‑tune values."""
    calibration = _validate_offset(
        calibration_offset_deg,
        "calibration_offset_deg",
    )

    if lamp_fine_tune_deg is None:
        lamp_fine_tune_deg = (0.0,) * NUM_LAMPS
    if len(lamp_fine_tune_deg) != NUM_LAMPS:
        raise MotorConfigError(
            f"lamp_fine_tune_deg must contain exactly {NUM_LAMPS} values"
        )
    validated_fine: list[float] = []
    for index, value in enumerate(lamp_fine_tune_deg):
        validated_fine.append(
            _validate_offset(value, f"lamp_fine_tune_deg[{index}]"),
        )

    path = Path(config_path) if config_path is not None else DEFAULT_CONFIG_PATH
    temporary_path = path.with_suffix(path.suffix + ".tmp")
    payload = {
        "calibration_offset_deg": round(calibration, 6),
        "lamp_fine_tune_deg": [round(v, 6) for v in validated_fine],
    }
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
        raise MotorConfigError(
            f"cannot write motor parameter file {path}: {exc}"
        ) from exc

    return MotorParameters(
        calibration_offset_deg=calibration,
        lamp_fine_tune_deg=tuple(validated_fine),
    )


def save_lamp_angle_offset(
    lamp_angle_offset_deg: float,
    config_path: str | Path | None = None,
) -> MotorParameters:
    """Legacy helper — saves *only* the calibration offset, zeroing
    all per‑lamp fine‑tune values.  Prefer :func:`save_calibration`
    for new code."""
    return save_calibration(
        calibration_offset_deg=float(lamp_angle_offset_deg),
        lamp_fine_tune_deg=(0.0,) * NUM_LAMPS,
        config_path=config_path,
    )
