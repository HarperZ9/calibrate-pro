"""SMPTE ST 2084 perceptual quantizer in absolute luminance units."""

from __future__ import annotations

from typing import Any

import numpy as np

ST2084_M1 = 2610.0 / 16384.0
ST2084_M2 = 2523.0 / 4096.0 * 128.0
ST2084_C1 = 3424.0 / 4096.0
ST2084_C2 = 2413.0 / 4096.0 * 32.0
ST2084_C3 = 2392.0 / 4096.0 * 32.0
ST2084_PEAK_NITS = 10000.0


def _validated_float64_samples(samples: Any, peak_luminance: float) -> np.ndarray:
    if not np.isfinite(peak_luminance) or peak_luminance <= 0:
        raise ValueError("peak_luminance must be finite and positive")
    values = np.asarray(samples, dtype=np.float64)
    if not np.all(np.isfinite(values)):
        raise ValueError("ST 2084 samples must be finite")
    return values


def pq_eotf(signal: Any, peak_luminance: float = ST2084_PEAK_NITS) -> np.ndarray:
    """Decode a PQ signal to absolute luminance in cd/m2."""
    value = np.clip(_validated_float64_samples(signal, peak_luminance), 0.0, 1.0)
    power = np.power(value, 1.0 / ST2084_M2)
    numerator = np.maximum(power - ST2084_C1, 0.0)
    denominator = ST2084_C2 - ST2084_C3 * power
    denominator = np.where(np.abs(denominator) < 1e-30, 1e-30, denominator)
    normalized = np.power(np.maximum(numerator / denominator, 0.0), 1.0 / ST2084_M1)
    return np.asarray(normalized * peak_luminance, dtype=np.float64)


def pq_oetf(luminance: Any, peak_luminance: float = ST2084_PEAK_NITS) -> np.ndarray:
    """Encode absolute luminance in cd/m2 as a PQ signal."""
    value = np.clip(_validated_float64_samples(luminance, peak_luminance), 0.0, peak_luminance)
    power = np.power(value / peak_luminance, ST2084_M1)
    numerator = ST2084_C1 + ST2084_C2 * power
    denominator = 1.0 + ST2084_C3 * power
    return np.asarray(np.power(numerator / denominator, ST2084_M2), dtype=np.float64)
