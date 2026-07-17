from __future__ import annotations

import time
from collections.abc import Callable

from .analysis import FilterResult, SpikeRejectingVoltageFilter
from .hardware import HardwareBundle, VoltageReading
from .input import Button, ButtonEvent
from .state import (
    CONTROL_ITEMS,
    LAMP_NAMES,
    UV_LAMP_INDEX,
    DeviceState,
    SamplePoint,
)


class ExperimentController:
    def __init__(
        self,
        hardware: HardwareBundle,
        state: DeviceState,
        lamp_selector: Callable[[int], None] | None = None,
    ) -> None:
        self.hardware = hardware
        self.state = state
        self._lamp_selector = lamp_selector or hardware.stepper.select_lamp
        self.voltage_filter = SpikeRejectingVoltageFilter()

    def handle_button(self, event: ButtonEvent) -> None:
        self.state.last_button = event.button.value
        self.state.last_key = event.key

        if event.button == Button.SELECT_PREVIOUS:
            self.state.selected_control = (self.state.selected_control - 1) % len(CONTROL_ITEMS)
        elif event.button == Button.SELECT_NEXT:
            self.state.selected_control = (self.state.selected_control + 1) % len(CONTROL_ITEMS)
        elif event.button == Button.DECREASE:
            self._adjust_selected(-1)
        elif event.button == Button.INCREASE:
            self._adjust_selected(1)
        elif event.button == Button.CONFIRM:
            self.confirm_selected()
        elif event.button == Button.INTENSITY_UP:
            self.set_intensity(self.state.intensity_percent + 5)
        elif event.button == Button.INTENSITY_DOWN:
            self.set_intensity(self.state.intensity_percent - 5)
        elif event.button == Button.CLEAR_CURVE:
            self.clear_curve()
        elif event.button == Button.TOGGLE_MEASUREMENT:
            self.toggle_measurement()
        elif event.button == Button.TOGGLE_FFT:
            self.state.fft_visible = not self.state.fft_visible
            self.state.status = "FFT分析已开启" if self.state.fft_visible else "FFT分析已关闭"

    def _adjust_selected(self, direction: int) -> None:
        selected = self.state.selected_name
        if selected == "lamp":
            self.set_lamp_arrow_focus(direction)
        elif selected == "intensity":
            self.set_intensity(self.state.intensity_percent + direction * 5)
        elif selected == "measurement":
            self.state.status = "测量开始或暂停请按 #"

    def set_lamp_arrow_focus(self, direction: int) -> None:
        self.state.lamp_arrow_focus = -1 if direction < 0 else 1
        target_index = (self.state.lamp_index + self.state.lamp_arrow_focus) % len(
            LAMP_NAMES
        )
        side = "左侧" if self.state.lamp_arrow_focus < 0 else "右侧"
        self.state.status = f"已选{side}箭头：{LAMP_NAMES[target_index]}，按 A 确认"

    def confirm_selected(self) -> None:
        selected = self.state.selected_name
        if selected == "lamp":
            self.select_lamp(self.state.lamp_index + self.state.lamp_arrow_focus)
        elif selected == "measurement":
            self.state.status = "A 键不控制测量，请按 # 开始或暂停"
        else:
            self.state.status = "当前参数已选中，可用 4 / 6 调整"

    def select_lamp(self, index: int) -> None:
        target_index = index % len(LAMP_NAMES)
        if (
            target_index == self.state.active_lamp_index
            and self.state.motor_ready
            and not self.state.motor_moving
        ):
            self.state.lamp_index = target_index
            self.state.motor_target_deg = self.state.lamp_angle_deg
            self.state.status = f"{self.state.lamp_name} 已在当前位置"
            return
        self.state.lamp_index = index % len(LAMP_NAMES)
        self.state.motor_target_deg = self.state.lamp_angle_deg
        self.state.motor_moving = True
        self.state.motor_ready = False
        self.state.motor_error = ""
        self.sync_light_output()
        self._lamp_selector(self.state.lamp_index)
        self.state.status = (
            f"正在旋转至：{self.state.lamp_name} "
            f"({self.state.motor_target_deg:.2f}°)"
        )

    def set_intensity(self, percent: int) -> None:
        self.state.intensity_percent = max(0, min(100, percent))
        self.hardware.light.set_intensity(self.state.intensity_percent)
        self.sync_light_output()
        self.state.status = f"光强：{self.state.intensity_percent}%"

    def toggle_measurement(self) -> None:
        self.set_measurement(not self.state.measuring)

    def clear_curve(self) -> None:
        self.state.clear_samples()
        self.state.rejected_spikes = 0
        self.voltage_filter.reset()
        self.state.status = "曲线已清空"

    def set_measurement(self, measuring: bool) -> None:
        if measuring and (self.state.motor_moving or not self.state.motor_ready):
            self.state.measuring = False
            self.sync_light_output()
            self.state.status = "灯组转轮尚未到位，暂不能测量"
            return
        self.state.measuring = measuring
        self.sync_light_output()
        self.state.status = "正在测量" if self.state.measuring else "测量已暂停"
        if self.state.measuring:
            last_timestamp = self.state.samples[-1].timestamp_s if self.state.samples else 0.0
            self.state.started_at_s = time.monotonic() - last_timestamp

    def sync_light_output(self) -> None:
        should_enable = (
            self.state.measuring
            and self.state.motor_ready
            and not self.state.motor_moving
            and self.state.active_lamp_index == UV_LAMP_INDEX
            and self.state.intensity_percent > 0
        )
        self.hardware.light.set_enabled(should_enable)
        self.state.light_on = self.hardware.light.enabled

    def record_voltage(self, reading: VoltageReading) -> FilterResult | None:
        if not self.state.measuring:
            return None
        filtered = self.voltage_filter.update(reading.voltage_mv)
        if filtered.rejected:
            self.state.rejected_spikes += 1
        if filtered.voltage_mv is None:
            return filtered
        self.state.samples.append(
            SamplePoint(
                timestamp_s=time.monotonic() - self.state.started_at_s,
                voltage_mv=filtered.voltage_mv,
                raw=reading.raw,
                source_voltage_mv=reading.voltage_mv,
            )
        )
        if len(self.state.samples) > 600:
            del self.state.samples[: len(self.state.samples) - 600]
        return filtered
