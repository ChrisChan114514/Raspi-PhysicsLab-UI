#!/usr/bin/env python3
"""PWM driver for the wavelength lamps connected to Raspberry Pi GPIO."""

from __future__ import annotations

import math
from dataclasses import dataclass

try:
    import lgpio
except ModuleNotFoundError:
    lgpio = None


UV_LED_WIRINGPI_PIN = 8
UV_LED_BCM_GPIO = 2
BLUE_LED_WIRINGPI_PIN = 9
BLUE_LED_BCM_GPIO = 3
GREEN_LED_WIRINGPI_PIN = 7
GREEN_LED_BCM_GPIO = 4

LED_BCM_GPIO_BY_WIRINGPI_PIN = {
    UV_LED_WIRINGPI_PIN: UV_LED_BCM_GPIO,
    GREEN_LED_WIRINGPI_PIN: GREEN_LED_BCM_GPIO,
    BLUE_LED_WIRINGPI_PIN: BLUE_LED_BCM_GPIO,
}


class LedPwmError(RuntimeError):
    """The PWM GPIO could not be configured or driven."""


@dataclass(frozen=True)
class LedPwmConfig:
    wiringpi_pin: int = UV_LED_WIRINGPI_PIN
    bcm_gpio: int = UV_LED_BCM_GPIO
    gpiochip: int = 0
    frequency_hz: float = 1000.0
    active_high: bool = True
    initial_duty_percent: float = 30.0
    debug: bool = False

    def validate(self) -> None:
        expected_bcm_gpio = LED_BCM_GPIO_BY_WIRINGPI_PIN.get(self.wiringpi_pin)
        if expected_bcm_gpio is None:
            raise ValueError(
                "WiringPi pin must be one of "
                f"{sorted(LED_BCM_GPIO_BY_WIRINGPI_PIN)}"
            )
        if self.bcm_gpio != expected_bcm_gpio:
            raise ValueError(
                f"WiringPi pin {self.wiringpi_pin} must map to "
                f"BCM GPIO{expected_bcm_gpio}"
            )
        if self.gpiochip < 0:
            raise ValueError("gpiochip must not be negative")
        if not math.isfinite(self.frequency_hz) or self.frequency_hz <= 0:
            raise ValueError("frequency_hz must be a positive finite number")
        if not math.isfinite(self.initial_duty_percent):
            raise ValueError("initial_duty_percent must be finite")
        if not 0.0 <= self.initial_duty_percent <= 100.0:
            raise ValueError("initial_duty_percent must be in the range 0..100")


class PwmLed:
    """Safe on/off and duty-cycle control for one externally driven LED lamp."""

    def __init__(self, config: LedPwmConfig | None = None) -> None:
        self.config = config or LedPwmConfig()
        self.config.validate()
        self._chip_handle: int | None = None
        self._enabled = False
        self._duty_percent = float(self.config.initial_duty_percent)
        self._pwm_active = False

    @property
    def is_open(self) -> bool:
        return self._chip_handle is not None

    @property
    def enabled(self) -> bool:
        return self._enabled and self._duty_percent > 0.0

    @property
    def duty_percent(self) -> float:
        return self._duty_percent

    @property
    def output_percent(self) -> float:
        return self._duty_percent if self._enabled else 0.0

    def open(self) -> None:
        if self.is_open:
            return
        if lgpio is None:
            raise LedPwmError(
                "python3-lgpio is not installed; run: "
                "sudo apt install -y python3-lgpio"
            )

        handle: int | None = None
        try:
            handle = lgpio.gpiochip_open(self.config.gpiochip)
            off_level = 0 if self.config.active_high else 1
            lgpio.gpio_claim_output(handle, self.config.bcm_gpio, off_level)
            self._chip_handle = handle
            self._enabled = False
            self._pwm_active = False
            self._apply_output()
        except Exception as exc:
            if handle is not None:
                try:
                    lgpio.gpiochip_close(handle)
                except Exception:
                    pass
            self._chip_handle = None
            raise LedPwmError(
                f"cannot open WiringPi {self.config.wiringpi_pin} "
                f"(BCM GPIO{self.config.bcm_gpio}): {exc}"
            ) from exc

        self._debug(
            f"opened WiringPi {self.config.wiringpi_pin} -> "
            f"BCM GPIO{self.config.bcm_gpio}, "
            f"frequency={self.config.frequency_hz:g} Hz"
        )

    def set_enabled(self, enabled: bool) -> None:
        enabled = bool(enabled)
        if enabled == self._enabled:
            return
        self._enabled = enabled
        if self.is_open:
            self._apply_output()

    def set_duty_cycle(self, percent: float) -> None:
        if not math.isfinite(percent):
            raise ValueError("PWM duty cycle must be finite")
        percent = max(0.0, min(100.0, float(percent)))
        if math.isclose(percent, self._duty_percent, abs_tol=1e-9):
            return
        self._duty_percent = percent
        if self.is_open and self._enabled:
            self._apply_output()

    def close(self) -> None:
        if not self.is_open:
            self._chip_handle = None
            self._enabled = False
            return

        assert lgpio is not None
        assert self._chip_handle is not None
        handle = self._chip_handle
        self._enabled = False
        try:
            self._apply_output()
        finally:
            try:
                lgpio.gpio_free(handle, self.config.bcm_gpio)
            finally:
                try:
                    lgpio.gpiochip_close(handle)
                finally:
                    self._chip_handle = None
        self._debug("closed with output disabled")

    def __enter__(self) -> "PwmLed":
        self.open()
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:  # noqa: ANN001
        self.close()

    def _apply_output(self) -> None:
        if not self.is_open:
            raise LedPwmError("PWM LED GPIO is not open")
        assert lgpio is not None
        assert self._chip_handle is not None

        requested_duty = self._duty_percent if self._enabled else 0.0
        if requested_duty <= 0.0:
            self._set_steady_level(0 if self.config.active_high else 1)
        elif requested_duty >= 100.0:
            self._set_steady_level(1 if self.config.active_high else 0)
        else:
            gpio_high_duty = (
                requested_duty
                if self.config.active_high
                else 100.0 - requested_duty
            )
            lgpio.tx_pwm(
                self._chip_handle,
                self.config.bcm_gpio,
                self.config.frequency_hz,
                gpio_high_duty,
            )
            self._pwm_active = True
        self._debug(
            f"enabled={self._enabled} duty={self._duty_percent:.1f}% "
            f"output={requested_duty:.1f}%"
        )

    def _set_steady_level(self, level: int) -> None:
        assert lgpio is not None
        assert self._chip_handle is not None
        if self._pwm_active:
            steady_duty = 100.0 if level else 0.0
            lgpio.tx_pwm(
                self._chip_handle,
                self.config.bcm_gpio,
                self.config.frequency_hz,
                steady_duty,
            )
            self._pwm_active = False
        lgpio.gpio_write(self._chip_handle, self.config.bcm_gpio, level)

    def _debug(self, message: str) -> None:
        if self.config.debug:
            print(f"[LED] {message}", flush=True)
