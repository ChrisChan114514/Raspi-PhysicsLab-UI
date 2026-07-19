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
from .state import BLUE_LAMP_INDEX, GREEN_LAMP_INDEX, UV_LAMP_INDEX


MATRIX_KEY_TO_BUTTON = {
    "2": Button.SELECT_PREVIOUS,
    "8": Button.SELECT_NEXT,
    "4": Button.DECREASE,
    "6": Button.INCREASE,
    "A": Button.CONFIRM,
    "B": Button.INTENSITY_UP,
    "C": Button.INTENSITY_DOWN,
    "D": Button.CLEAR_CURVE,
    "5": Button.TOGGLE_CAMERA,
    "#": Button.TOGGLE_MEASUREMENT,
    "1": Button.TOGGLE_FFT,
    "*": Button.TEXT_INPUT,
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
        keys = self._scanner.stable_keys
        if len(keys) > 1:
            return ButtonReading(
                button=Button.NONE,
                key="+".join(keys),
                keys=keys,
                conflict=True,
            )
        for key in keys:
            button = MATRIX_KEY_TO_BUTTON.get(key, Button.TEXT_INPUT)
            return ButtonReading(button=button, key=key, keys=(key,))
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
    def lamp_angles_deg(self) -> tuple[float, ...]:
        return (0.0, 60.0, 120.0, 180.0, 240.0, 300.0)

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

    @abstractmethod
    def move_to_angle(
        self,
        target_angle_deg: float,
        cancel_event: threading.Event | None = None,
    ) -> StepperMoveResult:
        raise NotImplementedError

    def save_lamp_angle_offset(self, offset_deg: float) -> None:
        raise NotImplementedError

    def stop(self) -> None:
        return None

    def close(self) -> None:
        return None


class SimulatedStepperMotor(StepperMotor):
    def __init__(
        self,
        lamp_angles_deg: tuple[float, ...],
        motor_config_path: Path,
    ) -> None:
        self._lamp_angles_deg = lamp_angles_deg
        self._position_deg = lamp_angles_deg[0]
        self._motor_config_path = motor_config_path

    @property
    def lamp_angles_deg(self) -> tuple[float, ...]:
        return self._lamp_angles_deg

    @property
    def position_deg(self) -> float:
        return self._position_deg

    def select_lamp(
        self,
        lamp_index: int,
        cancel_event: threading.Event | None = None,
    ) -> StepperMoveResult:
        del cancel_event
        started = time.monotonic()
        angle = self._lamp_angles_deg[lamp_index]
        self._position_deg = angle
        return StepperMoveResult(
            lamp_index=lamp_index,
            target_angle_deg=angle,
            actual_angle_deg=angle,
            error_deg=0.0,
            elapsed_s=time.monotonic() - started,
        )

    def move_to_angle(
        self,
        target_angle_deg: float,
        cancel_event: threading.Event | None = None,
    ) -> StepperMoveResult:
        del cancel_event
        started = time.monotonic()
        self._position_deg = float(target_angle_deg)
        return StepperMoveResult(
            lamp_index=-1,
            target_angle_deg=self._position_deg,
            actual_angle_deg=self._position_deg,
            error_deg=0.0,
            elapsed_s=time.monotonic() - started,
        )

    def save_lamp_angle_offset(self, offset_deg: float) -> None:
        from motor_config import save_lamp_angle_offset  # noqa: PLC0415

        parameters = save_lamp_angle_offset(offset_deg, self._motor_config_path)
        self._lamp_angles_deg = parameters.lamp_angles_deg


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
        from motor_config import save_lamp_angle_offset  # noqa: PLC0415

        config = EmmConfig(
            port=port,
            speed_rpm=speed_rpm,
            acceleration=acceleration,
            pulses_per_revolution=pulses_per_revolution,
            debug=debug,
        )
        self._motor = EmmV5Motor(config)
        self._motor_config_path = motor_dir / "motor_config.json"
        self._save_lamp_angle_offset = save_lamp_angle_offset
        self._lamp_angles_deg = self._motor.lamp_angles_deg
        version = self._motor.open()
        print(
            f"[MOTOR] port={self._motor.port_name} "
            f"version={version.firmware:02X}/{version.hardware:02X} "
            f"lamp_offset={self._motor.parameters.lamp_angle_offset_deg:+.3f} deg "
            f"position={self._motor.last_position_deg:.3f} deg",
            flush=True,
        )

    @property
    def lamp_angles_deg(self) -> tuple[float, ...]:
        return self._lamp_angles_deg

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

    def move_to_angle(
        self,
        target_angle_deg: float,
        cancel_event: threading.Event | None = None,
    ) -> StepperMoveResult:
        result = self._motor.move_to_angle(
            target_angle_deg,
            cancel_event=cancel_event,
        )
        return StepperMoveResult(
            lamp_index=-1,
            target_angle_deg=result.target_angle_deg,
            actual_angle_deg=result.actual_angle_deg,
            error_deg=result.error_deg,
            elapsed_s=result.elapsed_s,
        )

    def save_lamp_angle_offset(self, offset_deg: float) -> None:
        parameters = self._save_lamp_angle_offset(
            offset_deg,
            self._motor_config_path,
        )
        self._motor.set_lamp_angle_offset(parameters.lamp_angle_offset_deg)
        self._lamp_angles_deg = parameters.lamp_angles_deg

    def stop(self) -> None:
        self._motor.stop()

    def close(self) -> None:
        self._motor.close()


class LightController:
    @property
    def enabled(self) -> bool:
        return False

    def select_lamp(self, lamp_index: int) -> None:
        raise NotImplementedError

    def set_enabled(self, enabled: bool) -> None:
        raise NotImplementedError

    def set_intensity(self, percent: int) -> None:
        raise NotImplementedError

    def close(self) -> None:
        return None


class SimulatedLightController(LightController):
    def __init__(self) -> None:
        self.intensity_percent = 100
        self._enabled = False
        self._active_lamp_index = UV_LAMP_INDEX

    @property
    def enabled(self) -> bool:
        return self._enabled and self.intensity_percent > 0

    def select_lamp(self, lamp_index: int) -> None:
        lamp_index = int(lamp_index)
        if lamp_index != self._active_lamp_index:
            self._enabled = False
            self._active_lamp_index = lamp_index

    def set_enabled(self, enabled: bool) -> None:
        self._enabled = bool(enabled)

    def set_intensity(self, percent: int) -> None:
        self.intensity_percent = max(0, min(100, percent))

    def close(self) -> None:
        self._enabled = False


class RaspberryPiPwmLightController(LightController):
    def __init__(
        self,
        led_dir: Path,
        frequency_hz: float = 1000.0,
        active_high: bool = True,
        initial_intensity_percent: int = 100,
        debug: bool = False,
    ) -> None:
        driver_path = led_dir / "led_pwm.py"
        if not driver_path.is_file():
            raise FileNotFoundError(f"未找到灯组 PWM 驱动：{driver_path}")
        sys.path.insert(0, str(led_dir))
        from led_pwm import (  # noqa: PLC0415
            BLUE_LED_BCM_GPIO,
            BLUE_LED_WIRINGPI_PIN,
            GREEN_LED_BCM_GPIO,
            GREEN_LED_WIRINGPI_PIN,
            UV_LED_BCM_GPIO,
            UV_LED_WIRINGPI_PIN,
            LedPwmConfig,
            PwmLed,
        )

        self.intensity_percent = max(0, min(100, initial_intensity_percent))
        self._active_lamp_index = UV_LAMP_INDEX
        pins_by_lamp_index = {
            UV_LAMP_INDEX: (UV_LED_WIRINGPI_PIN, UV_LED_BCM_GPIO),
            BLUE_LAMP_INDEX: (BLUE_LED_WIRINGPI_PIN, BLUE_LED_BCM_GPIO),
            GREEN_LAMP_INDEX: (GREEN_LED_WIRINGPI_PIN, GREEN_LED_BCM_GPIO),
        }
        self._leds: dict[int, PwmLed] = {}
        try:
            for lamp_index, (wiringpi_pin, bcm_gpio) in pins_by_lamp_index.items():
                led = PwmLed(
                    LedPwmConfig(
                        wiringpi_pin=wiringpi_pin,
                        bcm_gpio=bcm_gpio,
                        frequency_hz=frequency_hz,
                        active_high=active_high,
                        initial_duty_percent=self.intensity_percent,
                        debug=debug,
                    )
                )
                led.open()
                self._leds[lamp_index] = led
        except Exception:
            for led in self._leds.values():
                led.close()
            raise

    @property
    def enabled(self) -> bool:
        led = self._leds.get(self._active_lamp_index)
        return led.enabled if led is not None else False

    def select_lamp(self, lamp_index: int) -> None:
        lamp_index = int(lamp_index)
        if lamp_index == self._active_lamp_index:
            return
        for led in self._leds.values():
            led.set_enabled(False)
        self._active_lamp_index = lamp_index

    def set_enabled(self, enabled: bool) -> None:
        for lamp_index, led in self._leds.items():
            led.set_enabled(bool(enabled) and lamp_index == self._active_lamp_index)

    def set_intensity(self, percent: int) -> None:
        self.intensity_percent = max(0, min(100, percent))
        for led in self._leds.values():
            led.set_duty_cycle(self.intensity_percent)

    def close(self) -> None:
        first_error: Exception | None = None
        for led in self._leds.values():
            try:
                led.close()
            except Exception as exc:
                if first_error is None:
                    first_error = exc
        if first_error is not None:
            raise first_error


@dataclass(frozen=True)
class CameraReading:
    width: int
    height: int
    rgb_bytes: bytes
    captured_at_s: float


class CameraSource(ABC):
    @abstractmethod
    def read(self) -> CameraReading:
        raise NotImplementedError

    def close(self) -> None:
        return None


class SimulatedCameraSource(CameraSource):
    def __init__(self, width: int = 320, height: int = 180) -> None:
        self.width = width
        self.height = height
        pixels = bytearray(width * height * 3)
        for y in range(height):
            for x in range(width):
                offset = (y * width + x) * 3
                band = (x // 40 + y // 30) % 2
                pixels[offset] = 34 if band else 18
                pixels[offset + 1] = 116 if band else 62
                pixels[offset + 2] = 102 if band else 72
        self._rgb_bytes = bytes(pixels)

    def read(self) -> CameraReading:
        return CameraReading(
            width=self.width,
            height=self.height,
            rgb_bytes=self._rgb_bytes,
            captured_at_s=time.monotonic(),
        )


class OpenCVUSBCameraSource(CameraSource):
    def __init__(
        self,
        camera_dir: Path,
        device: str | None = None,
        width: int = 640,
        height: int = 480,
        fps: float = 15.0,
        debug: bool = False,
    ) -> None:
        driver_path = camera_dir / "usb_camera.py"
        if not driver_path.is_file():
            raise FileNotFoundError(f"未找到 USB 摄像头驱动：{driver_path}")
        sys.path.insert(0, str(camera_dir))
        from usb_camera import (  # noqa: PLC0415
            USBCamera,
            USBCameraConfig,
            USBCameraError,
        )

        self._camera = USBCamera(
            USBCameraConfig(
                device=device,
                width=width,
                height=height,
                fps=fps,
                debug=debug,
            )
        )
        self._camera_error = USBCameraError

    def read(self) -> CameraReading:
        try:
            if self._camera.is_open:
                frame = self._camera.read()
            else:
                # Open and capture in the poller thread. Some V4L2/OpenCV
                # builds do not behave reliably when opened in one thread and
                # read continuously from another.
                frame = self._camera.open()
        except self._camera_error:
            self._camera.close()
            raise
        return CameraReading(
            width=frame.width,
            height=frame.height,
            rgb_bytes=frame.rgb_bytes,
            captured_at_s=frame.captured_at_s,
        )

    def close(self) -> None:
        self._camera.close()


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
        light_controller: LightController,
        camera_source: CameraSource,
    ) -> None:
        self.buttons = button_reader
        self.photocurrent = photocurrent_sensor
        self.stepper = stepper_motor
        self.light = light_controller
        self.camera = camera_source

    def close(self) -> None:
        try:
            self.light.close()
        finally:
            try:
                self.camera.close()
            finally:
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
    led_dir: Path,
    camera_dir: Path,
    motor_port: str | None = None,
    motor_speed_rpm: int = 60,
    motor_acceleration: int = 50,
    motor_pulses_per_revolution: int = 3200,
    led_pwm_frequency_hz: float = 1000.0,
    led_active_low: bool = False,
    camera_device: str | None = None,
    camera_width: int = 640,
    camera_height: int = 480,
    camera_fps: float = 15.0,
    debug_motor: bool = False,
    debug_led: bool = False,
    debug_camera: bool = False,
) -> HardwareBundle:
    if backend == "hardware":
        buttons = MatrixKeypadButtonReader(keypad_dir=keypad_dir)
        light = None
        camera = None
        sensor = None
        stepper = None
        try:
            light = RaspberryPiPwmLightController(
                led_dir=led_dir,
                frequency_hz=led_pwm_frequency_hz,
                active_high=not led_active_low,
                debug=debug_led,
            )
            camera = OpenCVUSBCameraSource(
                camera_dir=camera_dir,
                device=camera_device,
                width=camera_width,
                height=camera_height,
                fps=camera_fps,
                debug=debug_camera,
            )
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
            for device in (light, camera, stepper, sensor, buttons):
                if device is None:
                    continue
                try:
                    device.close()
                except Exception as cleanup_error:
                    print(f"[HARDWARE CLEANUP ERROR] {cleanup_error}", flush=True)
            raise
        return HardwareBundle(buttons, sensor, stepper, light, camera)
    sys.path.insert(0, str(motor_dir))
    from motor_config import load_motor_parameters  # noqa: PLC0415

    motor_parameters = load_motor_parameters(motor_dir / "motor_config.json")
    return HardwareBundle(
        SimulatedButtonReader(),
        SimulatedPhotocurrentSensor(),
        SimulatedStepperMotor(
            motor_parameters.lamp_angles_deg,
            motor_dir / "motor_config.json",
        ),
        SimulatedLightController(),
        SimulatedCameraSource(),
    )
