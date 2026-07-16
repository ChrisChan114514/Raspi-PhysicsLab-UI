from __future__ import annotations

import math
import random
import sys
import threading
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path

from .input import Button, ButtonReading


MATRIX_KEY_TO_BUTTON = {
    "2": Button.SELECT_PREVIOUS,
    "8": Button.SELECT_NEXT,
    "4": Button.DECREASE,
    "6": Button.INCREASE,
    "A": Button.TOGGLE_MEASUREMENT,
    "B": Button.INTENSITY_UP,
    "C": Button.INTENSITY_DOWN,
    "D": Button.CLEAR_CURVE,
    "#": Button.PAUSE_MEASUREMENT,
    "1": Button.TOGGLE_FFT,
    "*": Button.EXIT,
}


class ButtonReader(ABC):
    @abstractmethod
    def poll(self) -> ButtonReading:
        raise NotImplementedError

    def close(self) -> None:
        return None


class SimulatedButtonReader(ButtonReader):
    def poll(self) -> ButtonReading:
        return ButtonReading(Button.NONE)


class MatrixKeypadButtonReader(ButtonReader):
    def __init__(
        self,
        keypad_dir: Path,
        poll_debounce_s: float = 0.035,
    ) -> None:
        module_path = keypad_dir / "matrix_keypad.py"
        if not module_path.is_file():
            raise FileNotFoundError(
                f"未找到矩阵键盘驱动：{module_path}。"
                "请确认已将 16Button 目录完整传到 /home/cc/Desktop/UICode/16Button。"
            )
        sys.path.insert(0, str(keypad_dir))
        from matrix_keypad import (  # noqa: PLC0415
            DEFAULT_WIRINGPI_PINS,
            DebouncedMatrixKeypad,
            MatrixKeypad,
            MatrixPins,
            keymap_by_name,
        )

        pins = MatrixPins.from_wiringpi(DEFAULT_WIRINGPI_PINS)
        keypad = MatrixKeypad(pins=pins, keymap=keymap_by_name("measured"))
        self._scanner = DebouncedMatrixKeypad(keypad, debounce_s=poll_debounce_s)
        self._scanner.open()

    def poll(self) -> ButtonReading:
        self._scanner.poll()
        for key in self._scanner.stable_keys:
            button = MATRIX_KEY_TO_BUTTON.get(key, Button.NONE)
            return ButtonReading(button=button, key=key)
        return ButtonReading(Button.NONE)

    def close(self) -> None:
        self._scanner.close()


@dataclass(frozen=True)
class StepperMoveResult:
    lamp_index: int
    target_angle_deg: float
    actual_angle_deg: float
    error_deg: float
    elapsed_s: float


class StepperMotor(ABC):
    @property
    def position_deg(self) -> float:
        return 0.0

    @abstractmethod
    def select_lamp(
        self,
        lamp_index: int,
        cancel_event: threading.Event | None = None,
    ) -> StepperMoveResult:
        raise NotImplementedError

    def stop(self) -> None:
        return None

    def close(self) -> None:
        return None


class SimulatedStepperMotor(StepperMotor):
    def __init__(self) -> None:
        self.position = 0

    @property
    def position_deg(self) -> float:
        return float(self.position * 60)

    def select_lamp(
        self,
        lamp_index: int,
        cancel_event: threading.Event | None = None,
    ) -> StepperMoveResult:
        del cancel_event
        started = time.monotonic()
        self.position = lamp_index
        angle = float(lamp_index * 60)
        return StepperMoveResult(
            lamp_index=lamp_index,
            target_angle_deg=angle,
            actual_angle_deg=angle,
            error_deg=0.0,
            elapsed_s=time.monotonic() - started,
        )


class EMMV5StepperMotor(StepperMotor):
    def __init__(
        self,
        motor_dir: Path,
        port: str | None = None,
        speed_rpm: int = 60,
        acceleration: int = 50,
        pulses_per_revolution: int = 3200,
        debug: bool = False,
    ) -> None:
        driver_path = motor_dir / "emm_v5.py"
        if not driver_path.is_file():
            raise FileNotFoundError(f"未找到 EMM 电机驱动：{driver_path}")
        sys.path.insert(0, str(motor_dir))
        from emm_v5 import EmmConfig, EmmV5Motor  # noqa: PLC0415

        config = EmmConfig(
            port=port,
            speed_rpm=speed_rpm,
            acceleration=acceleration,
            pulses_per_revolution=pulses_per_revolution,
            debug=debug,
        )
        self._motor = EmmV5Motor(config)
        version = self._motor.open()
        print(
            f"[MOTOR] port={self._motor.port_name} "
            f"version={version.firmware:02X}/{version.hardware:02X} "
            f"position={self._motor.last_position_deg:.3f} deg",
            flush=True,
        )

    @property
    def position_deg(self) -> float:
        return self._motor.last_position_deg

    def select_lamp(
        self,
        lamp_index: int,
        cancel_event: threading.Event | None = None,
    ) -> StepperMoveResult:
        result = self._motor.select_lamp(lamp_index, cancel_event=cancel_event)
        return StepperMoveResult(
            lamp_index=lamp_index,
            target_angle_deg=result.target_angle_deg,
            actual_angle_deg=result.actual_angle_deg,
            error_deg=result.error_deg,
            elapsed_s=result.elapsed_s,
        )

    def stop(self) -> None:
        self._motor.stop()

    def close(self) -> None:
        self._motor.close()


class LightController:
    def __init__(self) -> None:
        self.intensity_percent = 30

    def set_intensity(self, percent: int) -> None:
        self.intensity_percent = max(0, min(100, percent))


@dataclass(frozen=True)
class VoltageReading:
    voltage_mv: float
    raw: int


class PhotocurrentSensor(ABC):
    @abstractmethod
    def read(self, lamp_index: int, intensity_percent: int) -> VoltageReading:
        raise NotImplementedError

    def close(self) -> None:
        return None


class SimulatedPhotocurrentSensor(PhotocurrentSensor):
    def read(self, lamp_index: int, intensity_percent: int) -> VoltageReading:
        base = (lamp_index + 1) * 4.0 + intensity_percent * 0.22
        wave = math.sin(time.monotonic() * 1.4) * 1.5
        noise = random.uniform(-0.35, 0.35)
        voltage_mv = max(0.0, base + wave + noise)
        raw = round((voltage_mv / 1000.0) * 8_388_608 / 5.0)
        return VoltageReading(voltage_mv=voltage_mv, raw=raw)


class ADS1256PhotocurrentSensor(PhotocurrentSensor):
    def __init__(
        self,
        ads1256_dir: Path,
        vref_v: float = 2.5,
        average: int = 3,
    ) -> None:
        driver_path = ads1256_dir / "ads1256_bitbang.py"
        if not driver_path.is_file():
            raise FileNotFoundError(
                f"未找到 ADS1256 驱动：{driver_path}。"
                "请确认已将 ADS1256 目录完整传到 /home/cc/Desktop/UICode/ADS1256。"
            )
        sys.path.insert(0, str(ads1256_dir))
        from ads1256_bitbang import (  # noqa: PLC0415
            ADS1256BitBang,
            ADS1256Pins,
            ADS1256ProtocolError,
            DRATE_30SPS,
            PGA_1,
        )

        self._vref_v = vref_v
        self._average = average
        self._pga = PGA_1
        self._drate = DRATE_30SPS
        self._protocol_error = ADS1256ProtocolError
        adc = ADS1256BitBang(pins=ADS1256Pins.from_wiringpi_defaults(), gpiochip=0)
        self._adc = adc
        try:
            self._adc.open()
            self._configure()
        except Exception:
            self._adc.close()
            raise

    def _configure(self) -> None:
        self._adc.hardware_reset()
        if not self._adc.wait_drdy_low(2.0):
            raise TimeoutError("ADS1256 DRDY 未拉低，请检查供电、时钟和 DRDY 接线")
        self._adc.configure_single_ended(
            channel=0,
            pga=self._pga,
            drate=self._drate,
            buffer_enabled=False,
            autocal_enabled=True,
            selfcal=True,
        )
        for _ in range(3):
            self._adc.read_single_raw()

    def read(self, lamp_index: int, intensity_percent: int) -> VoltageReading:
        try:
            stats = self._read_stats()
        except (self._protocol_error, TimeoutError) as exc:
            print(f"[ADS1256 RECOVERY] {exc}", flush=True)
            self._configure()
            stats = self._read_stats()
        return VoltageReading(voltage_mv=stats.voltage * 1000.0, raw=stats.raw)

    def _read_stats(self):  # noqa: ANN202
        return self._adc.read_voltage_stats(
            vref=self._vref_v,
            pga=self._pga,
            samples=self._average,
            discard=0,
            method="median",
        )

    def close(self) -> None:
        self._adc.close()


class HardwareBundle:
    def __init__(
        self,
        button_reader: ButtonReader,
        photocurrent_sensor: PhotocurrentSensor,
        stepper_motor: StepperMotor,
    ) -> None:
        self.buttons = button_reader
        self.photocurrent = photocurrent_sensor
        self.stepper = stepper_motor
        self.light = LightController()

    def close(self) -> None:
        try:
            self.stepper.close()
        finally:
            try:
                self.photocurrent.close()
            finally:
                self.buttons.close()


def create_hardware(
    backend: str,
    keypad_dir: Path,
    ads1256_dir: Path,
    motor_dir: Path,
    motor_port: str | None = None,
    motor_speed_rpm: int = 60,
    motor_acceleration: int = 50,
    motor_pulses_per_revolution: int = 3200,
    debug_motor: bool = False,
) -> HardwareBundle:
    if backend == "hardware":
        buttons = MatrixKeypadButtonReader(keypad_dir=keypad_dir)
        sensor = None
        stepper = None
        try:
            sensor = ADS1256PhotocurrentSensor(ads1256_dir=ads1256_dir)
            stepper = EMMV5StepperMotor(
                motor_dir=motor_dir,
                port=motor_port,
                speed_rpm=motor_speed_rpm,
                acceleration=motor_acceleration,
                pulses_per_revolution=motor_pulses_per_revolution,
                debug=debug_motor,
            )
        except Exception:
            if stepper is not None:
                stepper.close()
            if sensor is not None:
                sensor.close()
            buttons.close()
            raise
        return HardwareBundle(buttons, sensor, stepper)
    return HardwareBundle(
        SimulatedButtonReader(),
        SimulatedPhotocurrentSensor(),
        SimulatedStepperMotor(),
    )
