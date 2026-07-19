from __future__ import annotations

import math
import time
from collections.abc import Callable

from .analysis import FilterResult, SpikeRejectingVoltageFilter
from .hardware import HardwareBundle, VoltageReading
from .input import Button, ButtonEvent
from .state import (
    CAMERA_VIEW_MODES,
    CONTROL_ITEMS,
    DEFAULT_LAMP_ANGLES_DEG,
    LAMP_NAMES,
    PWM_LAMP_INDICES,
    DeviceState,
    SamplePoint,
)


class ExperimentController:
    def __init__(
        self,
        hardware: HardwareBundle,
        state: DeviceState,
        lamp_selector: Callable[[int], None] | None = None,
        angle_selector: Callable[[int, float], None] | None = None,
        offset_saver: Callable[[float], None] | None = None,
    ) -> None:
        self.hardware = hardware
        self.state = state
        self._lamp_selector = lamp_selector or hardware.stepper.select_lamp
        self._angle_selector = angle_selector
        self._offset_saver = offset_saver or hardware.stepper.save_lamp_angle_offset
        self.voltage_filter = SpikeRejectingVoltageFilter()

    def handle_button(self, event: ButtonEvent) -> None:
        self.state.last_button = event.button.value
        self.state.last_key = event.key

        if self.state.motor_adjustment_active:
            self._handle_motor_adjustment_key(event.key)
            return

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
        elif event.button == Button.TOGGLE_CAMERA:
            self.toggle_camera()
        elif event.button == Button.TOGGLE_MEASUREMENT:
            self.toggle_measurement()
        elif event.button == Button.TOGGLE_FFT:
            self.state.fft_visible = not self.state.fft_visible
            self.state.status = "FFT分析已开启" if self.state.fft_visible else "FFT分析已关闭"

    def _adjust_selected(self, direction: int) -> None:
        selected = self.state.selected_name
        if selected == "lamp":
            self.set_lamp_focus(direction)
        elif selected == "intensity":
            self.set_intensity(self.state.intensity_percent + direction * 5)
        elif selected == "camera":
            self.set_camera_view_mode("small" if direction < 0 else "full")

    def set_lamp_focus(self, direction: int) -> None:
        step = -1 if direction < 0 else 1
        self.state.lamp_arrow_focus = max(
            -1,
            min(1, self.state.lamp_arrow_focus + step),
        )
        if self.state.lamp_arrow_focus == 0:
            self.state.status = f"已选{self.state.lamp_name}，按 A 手动调节角度"
            return
        target_index = (self.state.lamp_index + self.state.lamp_arrow_focus) % len(
            LAMP_NAMES
        )
        side = "左侧" if self.state.lamp_arrow_focus < 0 else "右侧"
        self.state.status = f"已选{side}箭头：{LAMP_NAMES[target_index]}，按 A 确认"

    def confirm_selected(self) -> None:
        selected = self.state.selected_name
        if selected == "lamp":
            if self.state.lamp_arrow_focus == 0:
                self.enter_motor_adjustment()
            else:
                self.select_lamp(self.state.lamp_index + self.state.lamp_arrow_focus)
                self.state.lamp_arrow_focus = 0
        elif selected == "camera":
            self.toggle_camera()
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
        self._prepare_auto_camera()
        self.sync_light_output()
        if self._angle_selector is None:
            self._lamp_selector(self.state.lamp_index)
        else:
            self._angle_selector(
                self.state.lamp_index,
                self.state.motor_target_deg,
            )
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

    def toggle_camera(self) -> None:
        self.set_camera_enabled(not self.state.camera_enabled)

    def set_camera_enabled(self, enabled: bool) -> None:
        self.state.camera_enabled = bool(enabled)
        self.state.camera_ready = False
        self.state.camera_frame_rgb = None
        self.state.camera_frame_size = (0, 0)
        self.state.camera_frame_at_s = 0.0
        self.state.camera_error = ""
        if self.state.camera_enabled:
            self.state.status = f"USB摄像已开启：{self.state.camera_view_name}"
        elif self.state.camera_auto_visible:
            self.state.status = "常驻摄像已关闭，电机调节期间自动显示"
        else:
            self.state.status = "USB摄像已关闭"

    def set_camera_view_mode(self, mode: str) -> None:
        if mode not in CAMERA_VIEW_MODES:
            raise ValueError(f"unsupported camera view mode: {mode}")
        self.state.camera_view_mode = mode
        self.state.status = f"摄像画面：{self.state.camera_view_name}"

    def enter_motor_adjustment(self) -> None:
        if self.state.motor_moving:
            self.state.status = "电机正在转动，请到位后再手动调节"
            return
        self.state.motor_adjustment_active = True
        self._prepare_auto_camera()
        if 0.0 <= self.state.motor_target_deg <= 360.0:
            self.state.motor_adjustment_input = self._format_angle(
                self.state.motor_target_deg
            )
            self.state.motor_adjustment_error = ""
        else:
            self.state.motor_adjustment_input = ""
            self.state.motor_adjustment_error = "请输入 0~360° 的目标角度"
        self.state.motor_adjustment_replace_input = True
        self.state.status = f"手动调节：{self.state.lamp_name}"

    def _handle_motor_adjustment_key(self, key: str) -> None:
        if key == "#":
            self._save_motor_adjustment()
            return
        if key == "A":
            self._submit_manual_input()
            return
        if key == "D":
            self.state.motor_adjustment_input = ""
            self.state.motor_adjustment_replace_input = True
            self.state.motor_adjustment_error = ""
            return
        if key in {"B", "C"}:
            return
        if key == "*":
            if self.state.motor_adjustment_replace_input:
                value_text = "0."
            elif "." not in self.state.motor_adjustment_input:
                value_text = self.state.motor_adjustment_input + "."
            else:
                return
            if self._set_manual_input(value_text):
                self.state.motor_adjustment_replace_input = False
            return
        if len(key) != 1 or not key.isdigit():
            return

        if self.state.motor_adjustment_replace_input:
            value_text = key
        else:
            value_text = self.state.motor_adjustment_input + key
        if len(value_text) > 10:
            self.state.motor_adjustment_error = "输入值过长"
            return
        if self._set_manual_input(value_text):
            self.state.motor_adjustment_replace_input = False

    def _set_manual_input(self, value_text: str) -> bool:
        try:
            angle_deg = float(value_text)
        except ValueError:
            return False
        if not math.isfinite(angle_deg) or not 0.0 <= angle_deg <= 360.0:
            self.state.motor_adjustment_error = "角度范围必须为 0~360°"
            return False
        self.state.motor_adjustment_input = value_text
        self.state.motor_adjustment_error = ""
        return True

    def _submit_manual_input(self) -> None:
        if self.state.motor_moving:
            self.state.motor_adjustment_error = "电机正在转动，请到位后再确认"
            return
        if self.state.motor_adjustment_error in {
            "输入值过长",
            "角度范围必须为 0~360°",
        }:
            return
        if not self.state.motor_adjustment_input:
            self.state.motor_adjustment_error = "请输入 0~360° 的目标角度"
            return
        try:
            angle_deg = float(self.state.motor_adjustment_input)
        except ValueError:
            self.state.motor_adjustment_error = "请输入有效的目标角度"
            return
        if not math.isfinite(angle_deg) or not 0.0 <= angle_deg <= 360.0:
            self.state.motor_adjustment_error = "角度范围必须为 0~360°"
            return
        self._apply_manual_angle(angle_deg)
        self.state.motor_adjustment_replace_input = True

    def _apply_manual_angle(self, target_angle_deg: float) -> None:
        if not math.isfinite(target_angle_deg):
            self.state.motor_adjustment_error = "角度必须是有限数值"
            return
        if not 0.0 <= target_angle_deg <= 360.0:
            self.state.motor_adjustment_error = "角度范围必须为 0~360°"
            return
        offset_deg = (
            target_angle_deg
            - DEFAULT_LAMP_ANGLES_DEG[self.state.lamp_index]
        )
        self.state.lamp_angle_offset_deg = offset_deg
        self.state.lamp_angles_deg = tuple(
            base_angle + offset_deg
            for base_angle in DEFAULT_LAMP_ANGLES_DEG
        )
        self.state.motor_target_deg = target_angle_deg
        self.state.motor_moving = True
        self.state.motor_ready = False
        self.state.motor_error = ""
        self.state.motor_adjustment_error = ""
        self.sync_light_output()
        if self._angle_selector is None:
            self.hardware.stepper.move_to_angle(target_angle_deg)
        else:
            self._angle_selector(self.state.lamp_index, target_angle_deg)
        self.state.status = (
            f"正在转动：{self.state.lamp_name} {target_angle_deg:.3f}°"
        )

    def _save_motor_adjustment(self) -> None:
        try:
            self._offset_saver(self.state.lamp_angle_offset_deg)
        except Exception as exc:
            self.state.motor_adjustment_error = f"保存失败：{exc}"
            self.state.status = self.state.motor_adjustment_error
            return
        self.state.motor_adjustment_active = False
        self.state.motor_adjustment_replace_input = True
        self.state.motor_adjustment_error = ""
        self.state.lamp_arrow_focus = 0
        self.state.status = (
            f"已保存装配偏移：{self.state.lamp_angle_offset_deg:+.3f}°"
        )

    def _prepare_auto_camera(self) -> None:
        if self.state.camera_enabled:
            return
        self.state.camera_ready = False
        self.state.camera_frame_rgb = None
        self.state.camera_frame_size = (0, 0)
        self.state.camera_frame_at_s = 0.0
        self.state.camera_error = ""

    @staticmethod
    def _format_angle(angle_deg: float) -> str:
        return f"{angle_deg:.3f}".rstrip("0").rstrip(".")

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
        self.hardware.light.select_lamp(self.state.active_lamp_index)
        should_enable = (
            self.state.measuring
            and self.state.motor_ready
            and not self.state.motor_moving
            and self.state.active_lamp_index in PWM_LAMP_INDICES
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
