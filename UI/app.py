#!/usr/bin/env python3
"""Raspberry Pi UI entrypoint for the photoelectric-current experiment."""

from __future__ import annotations

import argparse
from pathlib import Path

from ui_app.app import run_app
from ui_app.config import AppConfig


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="光电流测量实验控制界面")
    parser.add_argument(
        "--backend",
        choices=("sim", "hardware"),
        default="sim",
        help="选择模拟设备或树莓派硬件，默认使用 sim",
    )
    parser.add_argument(
        "--debug-buttons",
        action="store_true",
        help="在终端打印矩阵键盘读数和按键事件",
    )
    parser.add_argument(
        "--debug-sensor",
        action="store_true",
        help="在终端打印 ADS1256 IN0 的 RAW 和 mV 采样值",
    )
    parser.add_argument(
        "--debug-motor",
        action="store_true",
        help="在终端打印 EMM 电机的串口收发帧",
    )
    parser.add_argument(
        "--debug-led",
        action="store_true",
        help="在终端打印三路灯组 PWM 输出状态",
    )
    parser.add_argument(
        "--debug-camera",
        action="store_true",
        help="在终端打印 USB 摄像头连接和帧错误",
    )
    parser.add_argument(
        "--motor-port",
        default=None,
        help="指定电机串口，例如 /dev/serial0；默认使用树莓派 GPIO UART /dev/serial0",
    )
    parser.add_argument(
        "--motor-speed",
        type=int,
        default=60,
        help="灯组转轮定位速度（RPM），默认 60",
    )
    parser.add_argument(
        "--motor-acceleration",
        type=int,
        default=50,
        help="EMM 加速度档位 0~255，默认 50",
    )
    parser.add_argument(
        "--motor-pulses-per-revolution",
        type=int,
        default=3200,
        help="电机每圈命令脉冲数，默认 3200（16 细分）",
    )
    parser.add_argument(
        "--led-pwm-frequency",
        type=float,
        default=1000.0,
        help="灯组 PWM 频率（Hz），默认 1000",
    )
    parser.add_argument(
        "--led-active-low",
        action="store_true",
        help="三路灯组驱动输入均为低电平有效",
    )
    parser.add_argument(
        "--camera-device",
        default=None,
        help="可选 MF500 节点；即使指定路径也会严格验证设备名称",
    )
    parser.add_argument(
        "--camera-width",
        type=int,
        default=640,
        help="USB 摄像头请求宽度，默认 640",
    )
    parser.add_argument(
        "--camera-height",
        type=int,
        default=480,
        help="USB 摄像头请求高度，默认 480",
    )
    parser.add_argument(
        "--camera-fps",
        type=float,
        default=15.0,
        help="USB 摄像头采集帧率，默认 15",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    config = AppConfig(
        project_root=Path(__file__).resolve().parents[1],
        backend=args.backend,
        debug_buttons=args.debug_buttons,
        debug_sensor=args.debug_sensor,
        debug_motor=args.debug_motor,
        debug_led=args.debug_led,
        debug_camera=args.debug_camera,
        motor_port=args.motor_port,
        motor_speed_rpm=args.motor_speed,
        motor_acceleration=args.motor_acceleration,
        motor_pulses_per_revolution=args.motor_pulses_per_revolution,
        led_pwm_frequency_hz=args.led_pwm_frequency,
        led_active_low=args.led_active_low,
        camera_device=args.camera_device,
        camera_width=args.camera_width,
        camera_height=args.camera_height,
        camera_fps=args.camera_fps,
    )
    return run_app(config)


if __name__ == "__main__":
    raise SystemExit(main())
