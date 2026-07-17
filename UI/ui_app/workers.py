from __future__ import annotations

import queue
import threading
import time
from dataclasses import dataclass

from .hardware import (
    ButtonReader,
    PhotocurrentSensor,
    StepperMotor,
    StepperMoveResult,
    VoltageReading,
)
from .input import Button, ButtonEvent, ButtonReading


IDLE_BUTTONS = {Button.NONE}


@dataclass(frozen=True)
class ButtonWorkerMessage:
    kind: str
    reading: ButtonReading | None = None
    event: ButtonEvent | None = None
    error: str = ""


class ButtonPollerThread:
    def __init__(self, reader: ButtonReader, poll_hz: float) -> None:
        self.reader = reader
        self.period_s = 1.0 / poll_hz
        self.messages: queue.Queue[ButtonWorkerMessage] = queue.Queue()
        self._stop_event = threading.Event()
        self._thread = threading.Thread(target=self._run, name="matrix-keypad-poller", daemon=True)

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread.is_alive():
            self._thread.join(timeout=2.0)

    def drain(self) -> list[ButtonWorkerMessage]:
        messages: list[ButtonWorkerMessage] = []
        while True:
            try:
                messages.append(self.messages.get_nowait())
            except queue.Empty:
                return messages

    def _run(self) -> None:
        last_button = Button.NONE
        last_key = ""
        last_conflict_keys: tuple[str, ...] = ()
        while not self._stop_event.is_set():
            started = time.monotonic()
            try:
                reading = self.reader.poll()
                self.messages.put(ButtonWorkerMessage(kind="reading", reading=reading))

                if reading.conflict:
                    if reading.keys != last_conflict_keys:
                        self.messages.put(
                            ButtonWorkerMessage(kind="conflict", reading=reading)
                        )
                    last_button = Button.NONE
                    last_key = ""
                    last_conflict_keys = reading.keys
                elif reading.button not in IDLE_BUTTONS:
                    if reading.button != last_button or reading.key != last_key:
                        self.messages.put(
                            ButtonWorkerMessage(
                                kind="event",
                                event=ButtonEvent(reading.button, reading.key),
                            )
                        )
                    last_button = reading.button
                    last_key = reading.key
                    last_conflict_keys = ()
                else:
                    if last_button not in IDLE_BUTTONS or last_key:
                        last_button = Button.NONE
                        last_key = ""
                    last_conflict_keys = ()
            except Exception as exc:  # pragma: no cover - hardware path
                self.messages.put(ButtonWorkerMessage(kind="error", error=str(exc)))
                time.sleep(0.5)

            elapsed = time.monotonic() - started
            remaining = self.period_s - elapsed
            if remaining > 0:
                self._stop_event.wait(remaining)


@dataclass(frozen=True)
class SensorWorkerMessage:
    kind: str
    reading: VoltageReading | None = None
    error: str = ""


class VoltagePollerThread:
    def __init__(self, sensor: PhotocurrentSensor, sample_hz: float) -> None:
        self.sensor = sensor
        self.period_s = 1.0 / sample_hz
        self.messages: queue.Queue[SensorWorkerMessage] = queue.Queue()
        self._enabled_event = threading.Event()
        self._stop_event = threading.Event()
        self._context_lock = threading.Lock()
        self._lamp_index = 0
        self._intensity_percent = 0
        self._thread = threading.Thread(target=self._run, name="ain0-voltage-poller", daemon=True)

    def start(self) -> None:
        self._thread.start()

    def set_enabled(self, enabled: bool) -> None:
        if enabled:
            self._enabled_event.set()
        else:
            self._enabled_event.clear()

    def set_context(self, lamp_index: int, intensity_percent: int) -> None:
        with self._context_lock:
            self._lamp_index = lamp_index
            self._intensity_percent = intensity_percent

    def stop(self) -> None:
        self._stop_event.set()
        self._enabled_event.set()
        if self._thread.is_alive():
            self._thread.join(timeout=3.0)

    def drain(self) -> list[SensorWorkerMessage]:
        messages: list[SensorWorkerMessage] = []
        while True:
            try:
                messages.append(self.messages.get_nowait())
            except queue.Empty:
                return messages

    def _run(self) -> None:
        while not self._stop_event.is_set():
            if not self._enabled_event.wait(timeout=0.1):
                continue
            if self._stop_event.is_set():
                break

            started = time.monotonic()
            try:
                with self._context_lock:
                    lamp_index = self._lamp_index
                    intensity_percent = self._intensity_percent
                reading = self.sensor.read(
                    lamp_index=lamp_index,
                    intensity_percent=intensity_percent,
                )
                self.messages.put(SensorWorkerMessage(kind="reading", reading=reading))
            except Exception as exc:  # pragma: no cover - hardware path
                self.messages.put(SensorWorkerMessage(kind="error", error=str(exc)))
                self._stop_event.wait(0.5)

            elapsed = time.monotonic() - started
            remaining = self.period_s - elapsed
            if remaining > 0:
                self._stop_event.wait(remaining)


@dataclass(frozen=True)
class MotorWorkerMessage:
    kind: str
    lamp_index: int
    result: StepperMoveResult | None = None
    error: str = ""


class MotorWorkerThread:
    def __init__(self, motor: StepperMotor) -> None:
        self.motor = motor
        self.messages: queue.Queue[MotorWorkerMessage] = queue.Queue()
        self._requests: queue.Queue[int] = queue.Queue()
        self._stop_event = threading.Event()
        self._thread = threading.Thread(
            target=self._run,
            name="emm-motor-worker",
            daemon=True,
        )

    def start(self) -> None:
        self._thread.start()

    def select_lamp(self, lamp_index: int) -> None:
        self._requests.put(lamp_index)

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread.is_alive():
            self._thread.join(timeout=3.0)
        if self._thread.is_alive():
            try:
                self.motor.stop()
            except Exception:
                pass
            finally:
                self._thread.join(timeout=2.0)

    def drain(self) -> list[MotorWorkerMessage]:
        messages: list[MotorWorkerMessage] = []
        while True:
            try:
                messages.append(self.messages.get_nowait())
            except queue.Empty:
                return messages

    def _run(self) -> None:
        while not self._stop_event.is_set():
            try:
                lamp_index = self._requests.get(timeout=0.1)
            except queue.Empty:
                continue

            # If several keys were pressed during a move, execute only the newest target.
            while True:
                try:
                    lamp_index = self._requests.get_nowait()
                except queue.Empty:
                    break

            self.messages.put(MotorWorkerMessage("moving", lamp_index))
            try:
                result = self.motor.select_lamp(
                    lamp_index,
                    cancel_event=self._stop_event,
                )
                self.messages.put(
                    MotorWorkerMessage("reached", lamp_index, result=result)
                )
            except Exception as exc:  # pragma: no cover - hardware path
                if not self._stop_event.is_set():
                    self.messages.put(
                        MotorWorkerMessage("error", lamp_index, error=str(exc))
                    )
