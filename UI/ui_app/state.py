from __future__ import annotations

from dataclasses import dataclass, field
from time import monotonic


CONTROL_ITEMS = ("lamp", "intensity", "measurement")
LAMP_NAMES = ("紫外光", "蓝光", "绿光", "红光", "红外光", "灯位6")
UV_LAMP_INDEX = 0
DEFAULT_LAMP_ANGLES_DEG = (0.0, 60.0, 120.0, 180.0, 240.0, 300.0)


@dataclass
class SamplePoint:
    timestamp_s: float
    voltage_mv: float
    raw: int = 0
    source_voltage_mv: float = 0.0


@dataclass
class DeviceState:
    lamp_angles_deg: tuple[float, ...] = DEFAULT_LAMP_ANGLES_DEG
    selected_control: int = 0
    lamp_arrow_focus: int = 1
    lamp_index: int = 0
    active_lamp_index: int = 0
    intensity_percent: int = 30
    measuring: bool = False
    light_on: bool = False
    camera_ready: bool = False
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
    samples: list[SamplePoint] = field(default_factory=list)
    started_at_s: float = field(default_factory=monotonic)

    @property
    def selected_name(self) -> str:
        return CONTROL_ITEMS[self.selected_control]

    @property
    def lamp_name(self) -> str:
        return LAMP_NAMES[self.lamp_index]

    @property
    def lamp_angle_deg(self) -> float:
        return self.lamp_angles_deg[self.lamp_index]

    def clear_samples(self) -> None:
        self.samples.clear()
        self.started_at_s = monotonic()
