from __future__ import annotations

import math
import time
from collections.abc import Callable

from .analysis import FilterResult, SpikeRejectingVoltageFilter
from .hardware import HardwareBundle, VoltageReading
from .input import Button, ButtonEvent
from .state import (
    ANGLE_INPUT_MAX_DEG,
    ANGLE_INPUT_MIN_DEG,
    CAMERA_VIEW_MODES,
    CONTROL_ITEMS,
    DEFAULT_LAMP_ANGLES_DEG,
    LAMP_NAMES,
    PWM_INPUT_MAX_PERCENT,
    PWM_INPUT_MIN_PERCENT,
    PWM_STEP_OPTIONS_PERCENT,
    PWM_LAMP_INDICES,
    TOUCH_INPUT_ANGLE,
    TOUCH_INPUT_INTENSITY,
    TOUCH_INPUT_NONE,
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

        if self.state.touch_input_active:
            self.handle_numeric_key(event.key)
            return

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

    def begin_angle_input(self) -> None:
        if self.state.motor_moving:
            self.state.status = "电机正在转动，请到位后再输入角度"
            return
        self.enter_motor_adjustment()
        if not self.state.motor_adjustment_active:
            return
        self.state.touch_input_kind = TOUCH_INPUT_ANGLE
        self.state.touch_input_value = self.state.motor_adjustment_input
        self.state.touch_input_replace_input = True
        self.state.touch_input_error = self.state.motor_adjustment_error
        self.state.status = f"输入转盘角度：{self.state.lamp_name}"

    def begin_intensity_input(self) -> None:
        if not self.hardware.device_available("leds"):
            self.state.light_on = False
            self.state.status = "LED PWM 自检未通过，无法输入光强"
            return
        self.state.touch_input_kind = TOUCH_INPUT_INTENSITY
        self.state.touch_input_value = self._format_percent(
            self.state.intensity_percent
        )
        self.state.touch_input_replace_input = True
        self.state.touch_input_error = ""
        self.state.status = "输入 PWM 光强"

    def handle_numeric_key(self, key: str) -> bool:
        if not self.state.touch_input_active:
            return False
        if key == "A":
            return self.submit_numeric_input()
        if key == "#":
            self.cancel_numeric_input()
            return True
        if key == "D":
            self.clear_numeric_input()
            return True
        if key == "C":
            self.backspace_numeric_input()
            return True
        if key == "*":
            self.append_numeric_token(".")
            return True
        if len(key) == 1 and key.isdigit():
            self.append_numeric_token(key)
            return True
        return False

    def append_numeric_token(self, token: str) -> None:
        if not self.state.touch_input_active:
            return
        kind = self.state.touch_input_kind
        if token == "." and "." in self.state.touch_input_value and not self.state.touch_input_replace_input:
            return
        if self.state.touch_input_replace_input:
            value_text = "0." if token == "." else token
        else:
            value_text = self.state.touch_input_value + token
        if len(value_text) > (10 if kind == TOUCH_INPUT_ANGLE else 6):
            self._set_touch_input_error("输入值过长")
            return
        if kind == TOUCH_INPUT_INTENSITY and not self._percent_precision_ok(value_text):
            self._set_touch_input_error("PWM 光强最多保留两位小数")
            return
        if kind == TOUCH_INPUT_ANGLE and not self._angle_precision_ok(value_text):
            self._set_touch_input_error("角度最多保留两位小数")
            return
        self._set_touch_input_text(value_text)
        self.state.touch_input_replace_input = False

    def backspace_numeric_input(self) -> None:
        if not self.state.touch_input_active:
            return
        if self.state.touch_input_replace_input:
            self.clear_numeric_input()
            return
        value_text = self.state.touch_input_value[:-1]
        self._set_touch_input_text(value_text)
        self.state.touch_input_replace_input = False

    def clear_numeric_input(self) -> None:
        if not self.state.touch_input_active:
            return
        self._set_touch_input_text("")
        self.state.touch_input_replace_input = False

    def cancel_numeric_input(self) -> None:
        if not self.state.touch_input_active:
            return
        was_angle_input = self.state.touch_input_kind == TOUCH_INPUT_ANGLE
        self.state.touch_input_kind = TOUCH_INPUT_NONE
        self.state.touch_input_value = ""
        self.state.touch_input_replace_input = True
        self.state.touch_input_error = ""
        if was_angle_input and not self.state.motor_moving:
            self.state.motor_adjustment_active = False
            self.state.motor_adjustment_error = ""
        self.state.status = "数字输入已取消"

    def submit_numeric_input(self) -> bool:
        if not self.state.touch_input_active:
            return False
        kind = self.state.touch_input_kind
        value = self._parse_touch_input()
        if value is None:
            return False

        if kind == TOUCH_INPUT_ANGLE:
            if self.state.motor_moving:
                self._set_touch_input_error("电机正在转动，请到位后再确认")
                return False
            self.state.motor_adjustment_input = self._format_angle(value)
            self.state.motor_adjustment_error = ""
            self._submit_manual_input()
            if self.state.motor_adjustment_error:
                self._set_touch_input_error(self.state.motor_adjustment_error)
                return False
            self._close_touch_input()
            self.state.status = "已提交转盘角度；到位后可点“保存偏移”"
            return True

        if kind == TOUCH_INPUT_INTENSITY:
            self.set_intensity(value)
            if not self.hardware.device_available("leds"):
                return False
            self._close_touch_input()
            return True

        return False

    def save_angle_adjustment(self) -> None:
        if not self.state.motor_adjustment_active:
            self.state.status = "当前没有待保存的角度偏移"
            return
        if self.state.motor_moving:
            self.state.motor_adjustment_error = "电机正在转动，到位后再保存"
            self.state.status = self.state.motor_adjustment_error
            return
        self._save_motor_adjustment()

    def close_angle_adjustment(self) -> None:
        self._close_touch_input()
        if not self.state.motor_adjustment_active:
            return
        self.state.motor_adjustment_active = False
        self.state.motor_adjustment_replace_input = True
        self.state.motor_adjustment_error = ""
        self.state.lamp_arrow_focus = 0
        self.state.status = "角度调节已退出；未写入配置文件"

    def adjust_motor_angle_delta(self, delta_deg: float) -> None:
        if not self.state.motor_adjustment_active:
            self.enter_motor_adjustment()
        if not self.state.motor_adjustment_active:
            return
        if self.state.motor_moving:
            self.state.motor_adjustment_error = "电机正在转动，到位后再调节"
            self.state.status = self.state.motor_adjustment_error
            return
        target = self.state.motor_target_deg + delta_deg
        target = max(ANGLE_INPUT_MIN_DEG, min(ANGLE_INPUT_MAX_DEG, target))
        self.state.motor_adjustment_input = self._format_angle(target)
        self._apply_manual_angle(target)

    def cycle_pwm_step(self) -> None:
        self.state.pwm_step_index = (
            self.state.pwm_step_index + 1
        ) % len(PWM_STEP_OPTIONS_PERCENT)
        self.state.status = f"PWM 步进：{self._format_percent(self.state.pwm_step_percent)}%"

    def adjust_intensity_by_step(self, direction: int) -> None:
        step = self.state.pwm_step_percent
        self.set_intensity(self.state.intensity_percent + direction * step)

    def set_intensity_from_slider(self, fraction: float) -> None:
        percent = round(max(0.0, min(1.0, fraction)) * 100, 2)
        self.set_intensity(percent)

    def select_previous_lamp(self) -> None:
        self.select_lamp(self.state.lamp_index - 1)

    def select_next_lamp(self) -> None:
        self.select_lamp(self.state.lamp_index + 1)

    def select_previous_camera_mode(self) -> None:
        self._select_camera_mode(-1)

    def select_next_camera_mode(self) -> None:
        self._select_camera_mode(1)

    def _select_camera_mode(self, direction: int) -> None:
        modes = ("off", "small", "full")
        if not self.state.camera_enabled:
            current_index = 0
        else:
            current_index = 1 if self.state.camera_view_mode == "small" else 2
        target_mode = modes[(current_index + direction) % len(modes)]
        if target_mode == "off":
            self.set_camera_enabled(False)
            return
        self.set_camera_view_mode(target_mode)
        if not self.state.camera_enabled:
            self.set_camera_enabled(True)

    @staticmethod
    def _clamp_zoom(value: float) -> float:
        return max(0.35, min(6.0, value))

    def adjust_time_zoom(self, direction: int) -> None:
        factor = 1.25 if direction > 0 else 0.8
        self.state.plot_time_zoom = self._clamp_zoom(
            self.state.plot_time_zoom * factor
        )
        self.state.status = f"时间轴缩放 ×{self.state.plot_time_zoom:.2f}"

    def adjust_voltage_zoom(self, direction: int) -> None:
        factor = 1.25 if direction > 0 else 0.8
        self.state.plot_voltage_zoom = self._clamp_zoom(
            self.state.plot_voltage_zoom * factor
        )
        self.state.status = f"电压轴缩放 ×{self.state.plot_voltage_zoom:.2f}"

    def toggle_camera_view_mode(self) -> None:
        self.set_camera_view_mode(
            "full" if self.state.camera_view_mode == "small" else "small"
        )

    def _set_touch_input_text(self, value_text: str) -> None:
        self.state.touch_input_value = value_text
        error = self._touch_input_validation_error(value_text)
        self._set_touch_input_error(error)

    def _set_touch_input_error(self, error: str) -> None:
        self.state.touch_input_error = error
        if self.state.touch_input_kind == TOUCH_INPUT_ANGLE:
            self.state.motor_adjustment_error = error

    def _touch_input_validation_error(self, value_text: str) -> str:
        if not self.state.touch_input_active or not value_text:
            return ""
        if self.state.touch_input_kind == TOUCH_INPUT_ANGLE:
            try:
                angle_deg = float(value_text)
            except ValueError:
                return "请输入有效角度"
            if (
                not math.isfinite(angle_deg)
                or not ANGLE_INPUT_MIN_DEG <= angle_deg <= ANGLE_INPUT_MAX_DEG
            ):
                return "角度范围必须为 0~369.99°"
            if not self._angle_precision_ok(value_text):
                return "角度最多保留两位小数"
            return ""
        if self.state.touch_input_kind == TOUCH_INPUT_INTENSITY:
            try:
                percent = float(value_text)
            except ValueError:
                return "请输入有效 PWM 光强"
            if (
                not math.isfinite(percent)
                or not PWM_INPUT_MIN_PERCENT <= percent <= PWM_INPUT_MAX_PERCENT
            ):
                return "PWM 光强范围必须为 0~100%"
            if not self._percent_precision_ok(value_text):
                return "PWM 光强最多保留两位小数"
            return ""
        return ""

    def _parse_touch_input(self) -> float | None:
        value_text = self.state.touch_input_value
        if not value_text:
            self._set_touch_input_error(
                "请输入 0~369.99° 的目标角度"
                if self.state.touch_input_kind == TOUCH_INPUT_ANGLE
                else "请输入 0~100% 的 PWM 光强"
            )
            return None
        error = self._touch_input_validation_error(value_text)
        if error:
            self._set_touch_input_error(error)
            return None
        try:
            return float(value_text)
        except ValueError:
            self._set_touch_input_error("请输入有效数字")
            return None

    def _close_touch_input(self) -> None:
        self.state.touch_input_kind = TOUCH_INPUT_NONE
        self.state.touch_input_value = ""
        self.state.touch_input_replace_input = True
        self.state.touch_input_error = ""

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
        if not self.hardware.device_available("emm"):
            self.state.status = "EMM 电机自检未通过，无法切换灯位"
            return
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

    def set_intensity(self, percent: float) -> None:
        if not self.hardware.device_available("leds"):
            self.state.light_on = False
            self.state.status = "LED PWM 自检未通过，灯光功能不可用"
            return
        self.state.intensity_percent = round(
            max(PWM_INPUT_MIN_PERCENT, min(PWM_INPUT_MAX_PERCENT, float(percent))),
            2,
        )
        self.hardware.light.set_intensity(self.state.intensity_percent)
        self.sync_light_output()
        self.state.status = f"光强：{self._format_percent(self.state.intensity_percent)}%"

    def toggle_measurement(self) -> None:
        self.set_measurement(not self.state.measuring)

    def toggle_camera(self) -> None:
        self.set_camera_enabled(not self.state.camera_enabled)

    def set_camera_enabled(self, enabled: bool) -> None:
        if enabled and not self.hardware.device_available("camera"):
            self.state.camera_enabled = False
            self.state.camera_ready = False
            self.state.camera_error = self.hardware.self_test_failures.get(
                "camera",
                "设备不可用",
            )
            self.state.status = "USB 摄像头自检未通过，摄像功能不可用"
            return
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
        if not self.hardware.device_available("emm"):
            self.state.status = "EMM 电机自检未通过，无法调节角度"
            return
        if self.state.motor_moving:
            self.state.status = "电机正在转动，请到位后再手动调节"
            return
        self.state.motor_adjustment_active = True
        self._prepare_auto_camera()
        if ANGLE_INPUT_MIN_DEG <= self.state.motor_target_deg <= ANGLE_INPUT_MAX_DEG:
            self.state.motor_adjustment_input = self._format_angle(
                self.state.motor_target_deg
            )
            self.state.motor_adjustment_error = ""
        else:
            self.state.motor_adjustment_input = ""
            self.state.motor_adjustment_error = "请输入 0~369.99° 的目标角度"
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
        if (
            not math.isfinite(angle_deg)
            or not ANGLE_INPUT_MIN_DEG <= angle_deg <= ANGLE_INPUT_MAX_DEG
        ):
            self.state.motor_adjustment_error = "角度范围必须为 0~369.99°"
            return False
        if not self._angle_precision_ok(value_text):
            self.state.motor_adjustment_error = "角度最多保留两位小数"
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
            "角度范围必须为 0~369.99°",
            "角度最多保留两位小数",
        }:
            return
        if not self.state.motor_adjustment_input:
            self.state.motor_adjustment_error = "请输入 0~369.99° 的目标角度"
            return
        try:
            angle_deg = float(self.state.motor_adjustment_input)
        except ValueError:
            self.state.motor_adjustment_error = "请输入有效的目标角度"
            return
        if (
            not math.isfinite(angle_deg)
            or not ANGLE_INPUT_MIN_DEG <= angle_deg <= ANGLE_INPUT_MAX_DEG
        ):
            self.state.motor_adjustment_error = "角度范围必须为 0~369.99°"
            return
        self._apply_manual_angle(angle_deg)
        self.state.motor_adjustment_replace_input = True

    def _apply_manual_angle(self, target_angle_deg: float) -> None:
        if not math.isfinite(target_angle_deg):
            self.state.motor_adjustment_error = "角度必须是有限数值"
            return
        if not ANGLE_INPUT_MIN_DEG <= target_angle_deg <= ANGLE_INPUT_MAX_DEG:
            self.state.motor_adjustment_error = "角度范围必须为 0~369.99°"
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
        if not self.hardware.device_available("camera"):
            return
        if self.state.camera_enabled:
            return
        self.state.camera_ready = False
        self.state.camera_frame_rgb = None
        self.state.camera_frame_size = (0, 0)
        self.state.camera_frame_at_s = 0.0
        self.state.camera_error = ""

    @staticmethod
    def _format_angle(angle_deg: float) -> str:
        return f"{angle_deg:.2f}".rstrip("0").rstrip(".")

    @staticmethod
    def _format_percent(percent: float) -> str:
        return f"{percent:.2f}".rstrip("0").rstrip(".")

    @staticmethod
    def _percent_precision_ok(value_text: str) -> bool:
        if "." not in value_text:
            return True
        return len(value_text.split(".", 1)[1]) <= 2

    @staticmethod
    def _angle_precision_ok(value_text: str) -> bool:
        if "." not in value_text:
            return True
        return len(value_text.split(".", 1)[1]) <= 2

    def clear_curve(self) -> None:
        self.state.clear_samples()
        self.state.rejected_spikes = 0
        self.voltage_filter.reset()
        self.state.status = "曲线已清空"

    def set_measurement(self, measuring: bool) -> None:
        if measuring and not self.hardware.device_available("ads1256"):
            self.state.measuring = False
            self.sync_light_output()
            self.state.status = "ADS1256 自检未通过，无法开始测量"
            return
        if measuring and not self.hardware.device_available("emm"):
            self.state.measuring = False
            self.sync_light_output()
            self.state.status = "EMM 电机自检未通过，无法确认灯位"
            return
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
