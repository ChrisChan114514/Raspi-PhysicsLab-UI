from __future__ import annotations

import time
from collections.abc import Callable

from .analysis import FilterResult, SpikeRejectingVoltageFilter
from .hardware import HardwareBundle, VoltageReading
from .input import Button, ButtonEvent
from .state import CONTROL_ITEMS, LAMP_NAMES, DeviceState, SamplePoint


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
        elif event.button == Button.TOGGLE_MEASUREMENT:
            self.toggle_measurement()
        elif event.button == Button.INTENSITY_UP:
            self.set_intensity(self.state.intensity_percent + 5)
        elif event.button == Button.INTENSITY_DOWN:
            self.set_intensity(self.state.intensity_percent - 5)
        elif event.button == Button.CLEAR_CURVE:
            self.clear_curve()
        elif event.button == Button.PAUSE_MEASUREMENT:
            self.set_measurement(False)
        elif event.button == Button.TOGGLE_FFT:
            self.state.fft_visible = not self.state.fft_visible
            self.state.status = "FFT分析已开启" if self.state.fft_visible else "FFT分析已关闭"

    def _adjust_selected(self, direction: int) -> None:
        selected = self.state.selected_name
        if selected == "lamp":
            self.select_lamp(self.state.lamp_index + direction)
        elif selected == "intensity":
            self.set_intensity(self.state.intensity_percent + direction * 5)
        elif selected == "measurement":
            self.set_measurement(direction > 0)

    def select_lamp(self, index: int) -> None:
        self.state.lamp_index = index % len(LAMP_NAMES)
        self.state.motor_target_deg = self.state.lamp_angle_deg
        self.state.motor_moving = True
        self.state.motor_ready = False
        self.state.motor_error = ""
        if self.state.measuring:
            self.set_measurement(False)
        self._lamp_selector(self.state.lamp_index)
        self.state.status = (
            f"正在旋转至：{self.state.lamp_name} "
            f"({self.state.motor_target_deg:.0f}°)"
        )

    def set_intensity(self, percent: int) -> None:
        self.state.intensity_percent = max(0, min(100, percent))
        self.hardware.light.set_intensity(self.state.intensity_percent)
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
            self.state.status = "灯组转轮尚未到位，暂不能测量"
            return
        self.state.measuring = measuring
        self.state.status = "正在测量" if self.state.measuring else "测量已暂停"
        if self.state.measuring:
            last_timestamp = self.state.samples[-1].timestamp_s if self.state.samples else 0.0
            self.state.started_at_s = time.monotonic() - last_timestamp

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
