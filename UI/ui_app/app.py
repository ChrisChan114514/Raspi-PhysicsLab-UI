from __future__ import annotations

import os
import time
import pygame

from .config import AppConfig
from .controller import ExperimentController
from .hardware import create_hardware
from .input import Button, ButtonEvent
from .state import LAMP_ANGLES_DEG, DeviceState
from .view import MainView
from .workers import ButtonPollerThread, MotorWorkerThread, VoltagePollerThread


KEY_TO_BUTTON = {
    pygame.K_1: (Button.TOGGLE_FFT, "1"),
    pygame.K_2: (Button.SELECT_PREVIOUS, "2"),
    pygame.K_8: (Button.SELECT_NEXT, "8"),
    pygame.K_4: (Button.DECREASE, "4"),
    pygame.K_6: (Button.INCREASE, "6"),
    pygame.K_a: (Button.TOGGLE_MEASUREMENT, "A"),
    pygame.K_b: (Button.INTENSITY_UP, "B"),
    pygame.K_c: (Button.INTENSITY_DOWN, "C"),
    pygame.K_d: (Button.CLEAR_CURVE, "D"),
    pygame.K_HASH: (Button.PAUSE_MEASUREMENT, "#"),
    ord("*"): (Button.EXIT, "*"),
}


def run_app(config: AppConfig) -> int:
    os.environ.setdefault("SDL_VIDEO_CENTERED", "1")
    os.environ.setdefault("SDL_VIDEO_MINIMIZE_ON_FOCUS_LOSS", "0")
    pygame.init()
    hardware = None
    button_worker = None
    motor_worker = None
    voltage_worker = None
    try:
        screen = pygame.display.set_mode(config.display_size, pygame.FULLSCREEN)
        pygame.display.set_caption("不同材料光电流测量")
        pygame.mouse.set_visible(False)
        clock = pygame.time.Clock()

        hardware = create_hardware(
            config.backend,
            config.keypad_dir,
            config.ads1256_dir,
            config.motor_dir,
            motor_port=config.motor_port,
            motor_speed_rpm=config.motor_speed_rpm,
            motor_acceleration=config.motor_acceleration,
            motor_pulses_per_revolution=config.motor_pulses_per_revolution,
            debug_motor=config.debug_motor,
        )
        state = DeviceState()
        state.motor_position_deg = hardware.stepper.position_deg
        initial_lamp = min(
            range(len(LAMP_ANGLES_DEG)),
            key=lambda index: abs(
                state.motor_position_deg - LAMP_ANGLES_DEG[index]
            ),
        )
        state.lamp_index = initial_lamp
        state.active_lamp_index = initial_lamp
        state.motor_target_deg = LAMP_ANGLES_DEG[initial_lamp]
        state.motor_ready = (
            abs(state.motor_position_deg - state.motor_target_deg) <= 0.5
        )
        state.status = (
            f"电机已连接：{state.motor_position_deg:.2f}°"
            if state.motor_ready
            else f"电机待定位：{state.motor_position_deg:.2f}°"
        )
        motor_worker = MotorWorkerThread(hardware.stepper)
        controller = ExperimentController(
            hardware,
            state,
            lamp_selector=motor_worker.select_lamp,
        )
        view = MainView(screen, config.font_dir)
        button_worker = ButtonPollerThread(hardware.buttons, poll_hz=config.button_poll_hz)
        voltage_worker = VoltagePollerThread(
            hardware.photocurrent,
            sample_hz=config.voltage_sample_hz,
        )
        button_worker.start()
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
        while running:
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    running = False
                elif event.type == pygame.KEYDOWN:
                    if event.key == pygame.K_ESCAPE:
                        running = False
                    elif event.key in KEY_TO_BUTTON:
                        button, key = KEY_TO_BUTTON[event.key]
                        if button == Button.EXIT:
                            running = False
                        else:
                            controller.handle_button(ButtonEvent(button, key))

            for message in button_worker.drain():
                if message.kind == "reading" and message.reading is not None:
                    state.last_button = message.reading.button.value
                    if message.reading.key:
                        state.last_key = message.reading.key
                    if config.debug_buttons:
                        print(
                            f"[BUTTON READ] t={time.monotonic():.3f} "
                            f"button={message.reading.button.value} "
                            f"key={message.reading.key or '-'}",
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
                    if message.event.button == Button.EXIT:
                        running = False
                    else:
                        controller.handle_button(message.event)
                elif message.kind == "error":
                    state.status = f"按键读取错误：{message.error}"
                    if config.debug_buttons:
                        print(f"[BUTTON ERROR] {message.error}", flush=True)

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
                            f"({state.motor_target_deg:.0f}°)"
                        )
                elif message.kind == "reached" and message.result is not None:
                    state.active_lamp_index = message.lamp_index
                    state.motor_position_deg = message.result.actual_angle_deg
                    state.motor_error = ""
                    state.motor_moving = message.lamp_index != state.lamp_index
                    if message.lamp_index == state.lamp_index:
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

            view.draw(state)
            clock.tick(config.target_fps)
    finally:
        if motor_worker is not None:
            motor_worker.stop()
        if voltage_worker is not None:
            voltage_worker.stop()
        if button_worker is not None:
            button_worker.stop()
        if hardware is not None:
            hardware.close()
        pygame.quit()

    return 0
