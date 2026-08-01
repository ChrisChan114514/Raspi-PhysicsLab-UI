from __future__ import annotations

import os
import time
import pygame

from .config import AppConfig
from .controller import ExperimentController
from .hardware import create_hardware
from .input import Button
from .self_test import (
    SELF_TEST_FAILED,
    SELF_TEST_PASSED,
    SelfTestProgress,
    startup_self_test_items,
)
from .state import UV_LAMP_INDEX, DeviceState
from .view import MainView
from .workers import (
    ButtonPollerThread,
    CameraPollerThread,
    MotorWorkerThread,
    VoltagePollerThread,
)


KEY_TO_BUTTON = {
    pygame.K_1: (Button.TEXT_INPUT, "1"),
    pygame.K_2: (Button.SELECT_PREVIOUS, "2"),
    pygame.K_8: (Button.SELECT_NEXT, "8"),
    pygame.K_4: (Button.DECREASE, "4"),
    pygame.K_6: (Button.INCREASE, "6"),
    pygame.K_a: (Button.CONFIRM, "A"),
    pygame.K_b: (Button.INTENSITY_UP, "B"),
    pygame.K_c: (Button.INTENSITY_DOWN, "C"),
    pygame.K_d: (Button.CLEAR_CURVE, "D"),
    pygame.K_5: (Button.TOGGLE_CAMERA, "5"),
    pygame.K_HASH: (Button.TOGGLE_MEASUREMENT, "#"),
    pygame.K_0: (Button.TEXT_INPUT, "0"),
    pygame.K_3: (Button.TEXT_INPUT, "3"),
    pygame.K_7: (Button.TEXT_INPUT, "7"),
    pygame.K_9: (Button.TEXT_INPUT, "9"),
    ord("*"): (Button.TEXT_INPUT, "*"),
    pygame.K_PERIOD: (Button.TEXT_INPUT, "*"),
    pygame.K_BACKSPACE: (Button.TEXT_INPUT, "C"),
    pygame.K_DELETE: (Button.TEXT_INPUT, "D"),
    pygame.K_RETURN: (Button.CONFIRM, "A"),
    pygame.K_KP_ENTER: (Button.CONFIRM, "A"),
    pygame.K_KP0: (Button.TEXT_INPUT, "0"),
    pygame.K_KP1: (Button.TEXT_INPUT, "1"),
    pygame.K_KP2: (Button.TEXT_INPUT, "2"),
    pygame.K_KP3: (Button.TEXT_INPUT, "3"),
    pygame.K_KP4: (Button.TEXT_INPUT, "4"),
    pygame.K_KP5: (Button.TEXT_INPUT, "5"),
    pygame.K_KP6: (Button.TEXT_INPUT, "6"),
    pygame.K_KP7: (Button.TEXT_INPUT, "7"),
    pygame.K_KP8: (Button.TEXT_INPUT, "8"),
    pygame.K_KP9: (Button.TEXT_INPUT, "9"),
    pygame.K_KP_PERIOD: (Button.TEXT_INPUT, "*"),
}


def _hold_self_test_screen(
    view: MainView,
    progress: SelfTestProgress,
    clock: pygame.time.Clock,
    duration_s: float,
    summary: str,
) -> None:
    deadline = time.monotonic() + max(0.0, duration_s)
    while time.monotonic() < deadline:
        pygame.event.pump()
        view.draw_self_test(progress.items, summary)
        clock.tick(30)


def _touch_position_from_event(
    event: pygame.event.Event,
    screen: pygame.Surface,
) -> tuple[int, int] | None:
    if event.type == pygame.MOUSEBUTTONUP and getattr(event, "button", 0) == 1:
        return int(event.pos[0]), int(event.pos[1])
    if event.type == pygame.FINGERUP:
        width, height = screen.get_size()
        return int(event.x * width), int(event.y * height)
    return None


def _is_duplicate_touch(
    position: tuple[int, int],
    last_position: tuple[int, int],
    last_at_s: float,
) -> bool:
    if time.monotonic() - last_at_s > 0.16:
        return False
    dx = position[0] - last_position[0]
    dy = position[1] - last_position[1]
    return dx * dx + dy * dy <= 24 * 24


def _dispatch_touch_action(
    view: MainView,
    controller: ExperimentController,
    position: tuple[int, int],
) -> None:
    region = view.find_touch_region(position)
    if region is None:
        return
    state = controller.state
    state.last_button = "TOUCH"
    state.last_key = "触控"
    action = region.action

    if action == "modal_block":
        return
    if action == "numeric_token":
        state.last_key = str(region.value)
        controller.append_numeric_token(str(region.value))
    elif action == "numeric_backspace":
        state.last_key = "退格"
        controller.backspace_numeric_input()
    elif action == "numeric_clear":
        state.last_key = "清空"
        controller.clear_numeric_input()
    elif action == "numeric_submit":
        state.last_key = "确认"
        controller.submit_numeric_input()
    elif action == "numeric_cancel":
        state.last_key = "取消"
        controller.cancel_numeric_input()
    elif action == "lamp_previous":
        controller.select_previous_lamp()
    elif action == "lamp_next":
        controller.select_next_lamp()
    elif action == "open_angle_page":
        controller.enter_motor_adjustment()
    elif action == "open_angle_input":
        controller.begin_angle_input()
    elif action == "angle_delta":
        controller.adjust_motor_angle_delta(float(region.value))
    elif action == "save_angle_offset":
        controller.save_angle_adjustment()
    elif action == "close_angle_adjustment":
        controller.close_angle_adjustment()
    elif action == "pwm_down":
        controller.adjust_intensity_by_step(-1)
    elif action == "pwm_up":
        controller.adjust_intensity_by_step(1)
    elif action == "cycle_pwm_step":
        controller.cycle_pwm_step()
    elif action == "open_intensity_input":
        controller.begin_intensity_input()
    elif action == "intensity_slider":
        fraction = (position[0] - region.rect.x) / max(1, region.rect.width)
        controller.set_intensity_from_slider(fraction)
    elif action == "toggle_measurement":
        controller.toggle_measurement()
    elif action == "clear_curve":
        controller.clear_curve()
    elif action == "toggle_camera":
        controller.toggle_camera()
    elif action == "camera_previous_mode":
        controller.select_previous_camera_mode()
    elif action == "camera_next_mode":
        controller.select_next_camera_mode()
    elif action == "time_zoom_out":
        controller.adjust_time_zoom(-1)
    elif action == "time_zoom_in":
        controller.adjust_time_zoom(1)
    elif action == "voltage_zoom_out":
        controller.adjust_voltage_zoom(-1)
    elif action == "voltage_zoom_in":
        controller.adjust_voltage_zoom(1)


def run_app(config: AppConfig) -> int:
    os.environ.setdefault("SDL_VIDEO_CENTERED", "1")
    os.environ.setdefault("SDL_VIDEO_MINIMIZE_ON_FOCUS_LOSS", "0")
    pygame.init()
    hardware = None
    button_worker = None
    camera_worker = None
    motor_worker = None
    voltage_worker = None
    try:
        screen = pygame.display.set_mode(config.display_size, pygame.FULLSCREEN)
        pygame.display.set_caption("不同材料光电流测量")
        pygame.mouse.set_visible(False)
        clock = pygame.time.Clock()
        view = MainView(screen, config.font_dir)
        self_test = SelfTestProgress(startup_self_test_items())

        def report_self_test(key: str, status: str, detail: str) -> None:
            self_test.update(key, status, detail)
            view.draw_self_test(self_test.items)
            print(
                f"[SELF-TEST] {key} {status}: {detail}",
                flush=True,
            )
            if status in (SELF_TEST_PASSED, SELF_TEST_FAILED):
                _hold_self_test_screen(
                    view,
                    self_test,
                    clock,
                    config.self_test_step_delay_s,
                    "正在检查硬件连接",
                )

        view.draw_self_test(self_test.items)
        report_self_test("display", "running", "确认 SDL 显示表面与输出分辨率")
        display_failure_detail = ""
        try:
            if not pygame.display.get_init() or pygame.display.get_surface() is None:
                raise RuntimeError("SDL 显示输出尚未初始化")
            display_width, display_height = screen.get_size()
            if display_width <= 0 or display_height <= 0:
                raise RuntimeError("SDL 返回了无效显示尺寸")
            if (display_width, display_height) != config.display_size:
                raise RuntimeError(
                    f"分辨率为 {display_width}x{display_height}，"
                    f"期望 {config.display_size[0]}x{config.display_size[1]}"
                )
            display_driver = pygame.display.get_driver()
            if display_driver in {"dummy", "offscreen"}:
                raise RuntimeError(
                    f"SDL 使用不可见显示驱动 {display_driver}；"
                    "请检查 DISPLAY、XAUTHORITY 或 SDL_VIDEODRIVER"
                )
            display_detail = (
                f"{display_width}x{display_height} / "
                f"{display_driver}"
            )
            report_self_test("display", SELF_TEST_PASSED, display_detail)
        except Exception as exc:
            display_failure_detail = str(exc)
            report_self_test("display", SELF_TEST_FAILED, display_failure_detail)

        hardware = create_hardware(
            config.backend,
            config.keypad_dir,
            config.ads1256_dir,
            config.motor_dir,
            config.led_dir,
            config.camera_dir,
            motor_port=config.motor_port,
            motor_speed_rpm=config.motor_speed_rpm,
            motor_acceleration=config.motor_acceleration,
            motor_pulses_per_revolution=config.motor_pulses_per_revolution,
            led_pwm_frequency_hz=config.led_pwm_frequency_hz,
            led_active_low=config.led_active_low,
            camera_device=config.camera_device,
            camera_width=config.camera_width,
            camera_height=config.camera_height,
            camera_fps=config.camera_fps,
            debug_motor=config.debug_motor,
            debug_led=config.debug_led,
            debug_camera=config.debug_camera,
            progress_callback=report_self_test,
        )
        if display_failure_detail:
            hardware.self_test_failures = {
                "display": display_failure_detail,
                **hardware.self_test_failures,
            }
        if self_test.failed_items:
            failed_labels = "、".join(item.label for item in self_test.failed_items)
            self_test_summary = (
                f"自检完成：{len(self_test.failed_items)} 项异常（{failed_labels}），"
                "相关功能将停用或受限"
            )
            self_test_delay_s = config.self_test_failure_delay_s
        else:
            self_test_summary = "自检完成：全部设备正常，正在进入实验界面"
            self_test_delay_s = config.self_test_result_delay_s
        _hold_self_test_screen(
            view,
            self_test,
            clock,
            self_test_delay_s,
            self_test_summary,
        )

        state = DeviceState(lamp_angles_deg=hardware.stepper.lamp_angles_deg)
        state.motor_position_deg = hardware.stepper.position_deg
        nearest_lamp = min(
            range(len(state.lamp_angles_deg)),
            key=lambda index: abs(
                state.motor_position_deg - state.lamp_angles_deg[index]
            ),
        )
        state.active_lamp_index = nearest_lamp
        state.lamp_index = UV_LAMP_INDEX
        state.motor_target_deg = state.lamp_angles_deg[UV_LAMP_INDEX]
        state.motor_ready = (
            hardware.device_available("emm")
            and abs(state.motor_position_deg - state.motor_target_deg) <= 0.5
        )
        state.measuring = (
            hardware.device_available("ads1256")
            and hardware.device_available("emm")
        )
        state.camera_enabled = hardware.device_available("camera")
        if not state.camera_enabled:
            state.camera_error = hardware.self_test_failures.get("camera", "设备不可用")
        state.started_at_s = time.monotonic()
        hardware.light.set_intensity(state.intensity_percent)
        motor_worker = MotorWorkerThread(hardware.stepper)
        controller = ExperimentController(
            hardware,
            state,
            lamp_selector=motor_worker.select_lamp,
            angle_selector=motor_worker.move_to_angle,
            offset_saver=hardware.stepper.save_lamp_angle_offset,
        )
        if not hardware.device_available("emm"):
            state.status = "自检异常：EMM 电机不可用，转轮功能已停用"
            controller.sync_light_output()
        elif state.motor_ready:
            controller.sync_light_output()
            state.status = f"正在测量：{state.lamp_name}已到位"
        else:
            controller.select_lamp(UV_LAMP_INDEX)
        if hardware.self_test_failures:
            failure_names = {
                "ads1256": "ADS1256",
                "display": "HDMI 显示",
                "emm": "EMM 电机",
                "keypad": "矩阵键盘",
                "leds": "LED PWM",
                "camera": "USB 摄像头",
            }
            unavailable = "、".join(
                failure_names.get(key, key)
                for key in hardware.self_test_failures
            )
            state.status = f"自检异常：{unavailable}"
        button_worker = ButtonPollerThread(hardware.buttons, poll_hz=config.button_poll_hz)
        camera_worker = CameraPollerThread(
            hardware.camera,
            capture_hz=config.camera_fps,
        )
        camera_worker.set_enabled(state.camera_visible)
        voltage_worker = VoltagePollerThread(
            hardware.photocurrent,
            sample_hz=config.voltage_sample_hz,
        )
        button_worker.start()
        camera_worker.start()
        motor_worker.start()
        voltage_worker.start()
        if config.debug_buttons:
            print(
                f"[BUTTON] debug enabled backend={config.backend} "
                f"poll_hz={config.button_poll_hz:g} keypad_dir={config.keypad_dir}",
                flush=True,
            )
        if config.debug_sensor:
            print(
                f"[SENSOR] backend={config.backend} source={type(hardware.photocurrent).__name__} "
                f"sample_hz={config.voltage_sample_hz:g}",
                flush=True,
            )

        running = True
        last_touch_at_s = 0.0
        last_touch_position = (-10000, -10000)
        while running:
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    running = False
                elif (
                    touch_position := _touch_position_from_event(event, screen)
                ) is not None:
                    if not _is_duplicate_touch(
                        touch_position,
                        last_touch_position,
                        last_touch_at_s,
                    ):
                        _dispatch_touch_action(view, controller, touch_position)
                        last_touch_position = touch_position
                        last_touch_at_s = time.monotonic()
                elif event.type == pygame.KEYDOWN:
                    if event.key in KEY_TO_BUTTON:
                        button, key = KEY_TO_BUTTON[event.key]
                        state.last_button = button.value
                        state.last_key = key
                        if state.touch_input_active:
                            controller.handle_numeric_key(key)

            for message in button_worker.drain():
                if message.kind == "reading" and message.reading is not None:
                    state.last_button = message.reading.button.value
                    if message.reading.key:
                        state.last_key = "多键" if message.reading.conflict else message.reading.key
                    if config.debug_buttons:
                        keys = ",".join(message.reading.keys) or "-"
                        print(
                            f"[BUTTON READ] t={time.monotonic():.3f} "
                            f"button={message.reading.button.value} "
                            f"key={message.reading.key or '-'} "
                            f"keys={keys} "
                            f"conflict={message.reading.conflict}",
                            flush=True,
                        )
                elif message.kind == "event" and message.event is not None:
                    if config.debug_buttons:
                        print(
                            f"[BUTTON EVENT] t={time.monotonic():.3f} "
                            f"button={message.event.button.value} "
                            f"key={message.event.key or '-'}",
                            flush=True,
                        )
                    if state.touch_input_active:
                        controller.handle_numeric_key(message.event.key)
                    else:
                        state.last_button = "KEYPAD_IDLE"
                        state.last_key = message.event.key
                        state.status = "当前界面不接收矩阵键盘控制"
                elif message.kind == "conflict" and message.reading is not None:
                    state.last_button = "CONFLICT"
                    state.last_key = "多键"
                    if state.touch_input_active:
                        state.status = "数字输入按键冲突：请一次只按一个键"
                    if config.debug_buttons:
                        print(
                            f"[BUTTON CONFLICT] t={time.monotonic():.3f} "
                            f"keys={','.join(message.reading.keys)}",
                            flush=True,
                        )
                elif message.kind == "error":
                    state.status = f"按键读取错误：{message.error}"
                    if config.debug_buttons:
                        print(f"[BUTTON ERROR] {message.error}", flush=True)

            for message in camera_worker.drain():
                if not state.camera_visible:
                    state.camera_ready = False
                    state.camera_frame_rgb = None
                    state.camera_frame_size = (0, 0)
                    state.camera_frame_at_s = 0.0
                    state.camera_error = ""
                elif message.kind == "frame" and message.frame is not None:
                    first_frame = state.camera_frame_rgb is None
                    state.camera_ready = True
                    state.camera_frame_rgb = message.frame.rgb_bytes
                    state.camera_frame_size = (
                        message.frame.width,
                        message.frame.height,
                    )
                    state.camera_frame_at_s = message.frame.captured_at_s
                    state.camera_error = ""
                    if config.debug_camera and first_frame:
                        print(
                            f"[CAMERA FRAME] size={message.frame.width}x"
                            f"{message.frame.height}",
                            flush=True,
                        )
                elif message.kind == "error":
                    state.camera_ready = False
                    state.camera_frame_rgb = None
                    state.camera_frame_size = (0, 0)
                    state.camera_frame_at_s = 0.0
                    state.camera_error = message.error
                    if config.debug_camera:
                        print(f"[CAMERA ERROR] {message.error}", flush=True)

            camera_worker.set_enabled(state.camera_visible)

            voltage_worker.set_context(state.active_lamp_index, state.intensity_percent)
            voltage_worker.set_enabled(state.measuring)
            for message in voltage_worker.drain():
                if message.kind == "reading" and message.reading is not None:
                    if config.debug_sensor:
                        print(
                            f"[SENSOR READ] mV={message.reading.voltage_mv:+.6f} "
                            f"RAW={message.reading.raw}",
                            flush=True,
                        )
                    filter_result = controller.record_voltage(message.reading)
                    if (
                        config.debug_sensor
                        and filter_result is not None
                        and filter_result.rejected
                    ):
                        print(
                            f"[FILTER REJECT] mV={message.reading.voltage_mv:+.6f} "
                            f"count={state.rejected_spikes}",
                            flush=True,
                        )
                    if state.status.startswith("采样错误："):
                        state.status = "正在测量"
                elif message.kind == "error":
                    state.status = f"采样错误：{message.error}"
                    print(f"[SENSOR ERROR] {message.error}", flush=True)

            for message in motor_worker.drain():
                if message.kind == "moving":
                    state.motor_moving = True
                    if message.lamp_index == state.lamp_index:
                        state.status = (
                            f"正在旋转至：{state.lamp_name} "
                            f"({state.motor_target_deg:.2f}°)"
                        )
                elif message.kind == "reached" and message.result is not None:
                    state.active_lamp_index = message.lamp_index
                    state.motor_position_deg = message.result.actual_angle_deg
                    state.motor_error = ""
                    current_target = (
                        message.lamp_index == state.lamp_index
                        and abs(
                            message.result.target_angle_deg
                            - state.motor_target_deg
                        ) <= 0.05
                    )
                    state.motor_moving = not current_target
                    if current_target:
                        state.motor_ready = True
                        state.status = (
                            f"OK：{state.lamp_name} 已到位 "
                            f"({message.result.actual_angle_deg:.2f}°)"
                        )
                elif message.kind == "error":
                    state.motor_error = message.error
                    if message.lamp_index == state.lamp_index:
                        state.motor_moving = False
                        state.motor_ready = False
                        state.status = f"电机错误：{message.error}"
                    print(f"[MOTOR ERROR] {message.error}", flush=True)

            controller.sync_light_output()
            view.draw(state)
            clock.tick(config.target_fps)
    finally:
        if hardware is not None:
            try:
                hardware.light.set_enabled(False)
            except Exception as exc:
                print(f"[LED CLOSE ERROR] {exc}", flush=True)
        if motor_worker is not None:
            motor_worker.stop()
        if camera_worker is not None:
            camera_worker.stop()
        if voltage_worker is not None:
            voltage_worker.stop()
        if button_worker is not None:
            button_worker.stop()
        if hardware is not None:
            hardware.close()
        pygame.quit()

    return 0
