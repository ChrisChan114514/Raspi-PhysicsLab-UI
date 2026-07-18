from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class AppConfig:
    project_root: Path
    backend: str = "sim"
    display_size: tuple[int, int] = (1024, 600)
    target_fps: int = 30
    button_poll_hz: float = 20.0
    voltage_sample_hz: float = 10.0
    debug_buttons: bool = False
    debug_sensor: bool = False
    debug_motor: bool = False
    debug_led: bool = False
    debug_camera: bool = False
    motor_port: str | None = None
    motor_speed_rpm: int = 60
    motor_acceleration: int = 50
    motor_pulses_per_revolution: int = 3200
    led_pwm_frequency_hz: float = 1000.0
    led_active_low: bool = False
    camera_device: str | None = None
    camera_width: int = 640
    camera_height: int = 480
    camera_fps: float = 15.0

    @property
    def keypad_dir(self) -> Path:
        return self.project_root / "16Button"

    @property
    def font_dir(self) -> Path:
        return self.project_root / "Font"

    @property
    def ads1256_dir(self) -> Path:
        return self.project_root / "ADS1256"

    @property
    def motor_dir(self) -> Path:
        return self.project_root / "42Motor"

    @property
    def led_dir(self) -> Path:
        return self.project_root / "LED"

    @property
    def camera_dir(self) -> Path:
        return self.project_root / "USBCamara"
