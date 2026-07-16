from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from statistics import median
from typing import Sequence

import numpy as np


@dataclass(frozen=True)
class FilterResult:
    voltage_mv: float | None
    rejected: bool


class SpikeRejectingVoltageFilter:
    """Physical guard, five-tap FIR smoothing, then first-order IIR smoothing."""

    def __init__(
        self,
        fir_taps: int = 5,
        iir_alpha: float = 0.35,
        minimum_mv: float = -3300.0,
        maximum_mv: float = 5000.0,
        deviation_floor_mv: float = 25.0,
        mad_multiplier: float = 8.0,
    ) -> None:
        if fir_taps <= 0:
            raise ValueError("fir_taps must be positive")
        if not 0.0 < iir_alpha <= 1.0:
            raise ValueError("iir_alpha must be in (0, 1]")
        self._valid_values: deque[float] = deque(maxlen=fir_taps)
        self._pending_step: deque[float] = deque(maxlen=3)
        self._iir_alpha = iir_alpha
        self._minimum_mv = minimum_mv
        self._maximum_mv = maximum_mv
        self._deviation_floor_mv = deviation_floor_mv
        self._mad_multiplier = mad_multiplier
        self._iir_value: float | None = None

    def reset(self) -> None:
        self._valid_values.clear()
        self._pending_step.clear()
        self._iir_value = None

    def update(self, voltage_mv: float) -> FilterResult:
        if not self._minimum_mv <= voltage_mv <= self._maximum_mv:
            self._pending_step.clear()
            return FilterResult(voltage_mv=self._iir_value, rejected=True)

        rejected = False
        if len(self._valid_values) >= 3:
            baseline = median(self._valid_values)
            mad = median(abs(value - baseline) for value in self._valid_values)
            threshold = max(
                self._deviation_floor_mv,
                self._mad_multiplier * 1.4826 * mad,
            )
            rejected = abs(voltage_mv - baseline) > threshold

        if rejected:
            self._pending_step.append(voltage_mv)
            pending_span = max(self._pending_step) - min(self._pending_step)
            if len(self._pending_step) < self._pending_step.maxlen or pending_span > self._deviation_floor_mv:
                return FilterResult(voltage_mv=self._iir_value, rejected=True)
            voltage_mv = median(self._pending_step)
            self._valid_values.clear()
            self._pending_step.clear()
        else:
            self._pending_step.clear()

        self._valid_values.append(voltage_mv)
        fir_value = sum(self._valid_values) / len(self._valid_values)
        if self._iir_value is None:
            self._iir_value = fir_value
        else:
            self._iir_value += self._iir_alpha * (fir_value - self._iir_value)
        return FilterResult(voltage_mv=self._iir_value, rejected=False)


@dataclass(frozen=True)
class FFTResult:
    frequencies_hz: np.ndarray
    amplitudes_mv: np.ndarray
    center_frequency_hz: float
    range_min_hz: float
    range_max_hz: float
    sample_rate_hz: float
    duration_s: float
    sample_count: int


def analyze_fft(
    timestamps_s: Sequence[float],
    voltages_mv: Sequence[float],
    minimum_points: int = 16,
    maximum_points: int = 256,
) -> FFTResult | None:
    count = min(len(timestamps_s), len(voltages_mv), maximum_points)
    if count < minimum_points:
        return None
    fft_count = 1 << (count.bit_length() - 1)
    timestamps = np.asarray(timestamps_s[-fft_count:], dtype=float)
    values = np.asarray(voltages_mv[-fft_count:], dtype=float)
    duration_s = float(timestamps[-1] - timestamps[0])
    if duration_s <= 0.0 or not np.all(np.isfinite(values)):
        return None

    sample_rate_hz = (fft_count - 1) / duration_s
    uniform_time = np.linspace(timestamps[0], timestamps[-1], fft_count)
    uniform_values = np.interp(uniform_time, timestamps, values)
    detrended = uniform_values - np.mean(uniform_values)
    window = np.hanning(fft_count)
    coherent_gain = max(float(np.sum(window)), 1.0)
    amplitudes = np.abs(np.fft.rfft(detrended * window)) * 2.0 / coherent_gain
    frequencies = np.fft.rfftfreq(fft_count, d=1.0 / sample_rate_hz)

    if len(frequencies) <= 1:
        return None
    peak_index = int(np.argmax(amplitudes[1:]) + 1)
    center_hz = float(frequencies[peak_index])
    resolution_hz = float(frequencies[1] - frequencies[0])
    nyquist_hz = sample_rate_hz / 2.0
    half_span_hz = max(4.0 * resolution_hz, center_hz * 0.75, nyquist_hz * 0.10)
    range_min_hz = max(0.0, center_hz - half_span_hz)
    range_max_hz = min(nyquist_hz, center_hz + half_span_hz)
    if range_max_hz - range_min_hz < 4.0 * resolution_hz:
        range_min_hz = max(0.0, center_hz - 2.0 * resolution_hz)
        range_max_hz = min(nyquist_hz, center_hz + 2.0 * resolution_hz)

    selection = (frequencies >= range_min_hz) & (frequencies <= range_max_hz)
    return FFTResult(
        frequencies_hz=frequencies[selection],
        amplitudes_mv=amplitudes[selection],
        center_frequency_hz=center_hz,
        range_min_hz=range_min_hz,
        range_max_hz=range_max_hz,
        sample_rate_hz=sample_rate_hz,
        duration_s=duration_s,
        sample_count=fft_count,
    )
