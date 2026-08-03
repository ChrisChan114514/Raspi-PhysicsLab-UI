from __future__ import annotations

from dataclasses import dataclass, field
from time import monotonic


CONTROL_ITEMS = ("lamp", "intensity", "camera")
CAMERA_VIEW_MODES = ("small", "full")
TOUCH_INPUT_NONE = ""
TOUCH_INPUT_ANGLE = "angle"
TOUCH_INPUT_INTENSITY = "intensity"
ANGLE_INPUT_MIN_DEG = 0.0
ANGLE_INPUT_MAX_DEG = 369.99
PWM_INPUT_MIN_PERCENT = 0.0
PWM_INPUT_MAX_PERCENT = 100.0
ANGLE_FINE_STEPS_DEG = (0.1, 0.5, 5.0)
PWM_STEP_OPTIONS_PERCENT = (0.1, 1.0, 5.0)
LAMP_NAMES = (
    "400nm紫外光",
    "450nm蓝光",
    "520nm绿光",
    "红光",
    "红外光",
    "灯位6",
)
LAMP_SHORT_NAMES = ("400nm", "450nm", "520nm", "红光", "红外", "灯位6")
UV_LAMP_INDEX = 0
BLUE_LAMP_INDEX = 1
GREEN_LAMP_INDEX = 2
LED4_LAMP_INDEX = 3
LED5_LAMP_INDEX = 4
LED6_LAMP_INDEX = 5
PWM_LAMP_INDICES = frozenset(
    (
        UV_LAMP_INDEX,
        BLUE_LAMP_INDEX,
        GREEN_LAMP_INDEX,
        LED4_LAMP_INDEX,
        LED5_LAMP_INDEX,
        LED6_LAMP_INDEX,
    )
)
DEFAULT_LAMP_ANGLES_DEG = (0.0, 60.0, 120.0, 180.0, 240.0, 300.0)
CALIBRATION_LAMP_INDEX = UV_LAMP_INDEX  # 400 nm


@dataclass
class SamplePoint:
    timestamp_s: float
    voltage_mv: float
    raw: int = 0
    source_voltage_mv: float = 0.0


def _compute_lamp_angles(
    calibration_offset_deg: float,
    fine_tune_deg: tuple[float, ...],
) -> tuple[float, ...]:
    return tuple(
        calibration_offset_deg + base + fine
        for base, fine in zip(DEFAULT_LAMP_ANGLES_DEG, fine_tune_deg)
    )


@dataclass
class DeviceState:
    lamp_angles_deg: tuple[float, ...] = DEFAULT_LAMP_ANGLES_DEG
    calibration_offset_deg: float = 0.0
    lamp_fine_tune_deg: tuple[float, ...] = (0.0, 0.0, 0.0, 0.0, 0.0, 0.0)
    calibration_mode: bool = False
    calibration_lamp_index: int = CALIBRATION_LAMP_INDEX
    selected_control: int = 0
    lamp_arrow_focus: int = 0
    lamp_index: int = 0
    active_lamp_index: int = 0
    intensity_percent: float = 100.0
    pwm_step_index: int = 1
    measuring: bool = True
    light_on: bool = False
    camera_enabled: bool = True
    camera_view_mode: str = "small"
    camera_ready: bool = False
    camera_frame_rgb: bytes | None = None
    camera_frame_size: tuple[int, int] = (0, 0)
    camera_frame_at_s: float = 0.0
    camera_error: str = ""
    last_button: str = "NONE"
    last_key: str = ""
    status: str = "设备就绪"
    fft_visible: bool = False
    rejected_spikes: int = 0
    motor_moving: bool = False
    motor_ready: bool = False
    motor_position_deg: float = 0.0
    motor_target_deg: float = 0.0
    motor_error: str = ""
    lamp_angle_offset_deg: float = field(init=False)
    motor_adjustment_active: bool = False
    motor_adjustment_input: str = ""
    motor_adjustment_replace_input: bool = True
    motor_adjustment_error: str = ""
    touch_input_kind: str = TOUCH_INPUT_NONE
    touch_input_value: str = ""
    touch_input_replace_input: bool = True
    touch_input_error: str = ""
    plot_time_zoom: float = 1.0
    plot_voltage_zoom: float = 1.0
    samples: list[SamplePoint] = field(default_factory=list)
    started_at_s: float = field(default_factory=monotonic)

    def __post_init__(self) -> None:
        # Recompute lamp_angles_deg from calibration + fine‑tune if
        # the caller only supplied the raw parameters.
        if (
            self.calibration_offset_deg != 0.0
            or any(v != 0.0 for v in self.lamp_fine_tune_deg)
        ):
            self.lamp_angles_deg = _compute_lamp_angles(
                self.calibration_offset_deg,
                self.lamp_fine_tune_deg,
            )
        self.lamp_angle_offset_deg = (
            self.lamp_angles_deg[0] - DEFAULT_LAMP_ANGLES_DEG[0]
        )

    @property
    def selected_name(self) -> str:
        return CONTROL_ITEMS[self.selected_control]

    @property
    def lamp_name(self) -> str:
        return LAMP_NAMES[self.lamp_index]

    @property
    def lamp_angle_deg(self) -> float:
        return self.lamp_angles_deg[self.lamp_index]

    @property
    def camera_view_name(self) -> str:
        return "小窗" if self.camera_view_mode == "small" else "全屏"

    @property
    def camera_auto_visible(self) -> bool:
        return self.motor_moving or self.motor_adjustment_active

    @property
    def camera_visible(self) -> bool:
        return self.camera_enabled or self.camera_auto_visible

    @property
    def touch_input_active(self) -> bool:
        return self.touch_input_kind != TOUCH_INPUT_NONE

    @property
    def pwm_step_percent(self) -> float:
        return PWM_STEP_OPTIONS_PERCENT[
            self.pwm_step_index % len(PWM_STEP_OPTIONS_PERCENT)
        ]

    def clear_samples(self) -> None:
        self.samples.clear()
        self.started_at_s = monotonic()
