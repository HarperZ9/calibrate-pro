"""Reads the loop makes before it writes anything: warm-up, noise, primaries.

Every function here only shows patches and reads the instrument. None writes a
panel control. The pairing of a patch with a reading happens here, outside the
instrument port, as `calibrate_pro.application.instruments` requires.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from calibrate_pro.application.instruments import InstrumentPort
from calibrate_pro.calibration.closed_loop.controls import RGB, Clock, PatchPresenter
from calibrate_pro.calibration.closed_loop.intent import AchievableTarget
from calibrate_pro.calibration.closed_loop.metrics import delta_e_relative
from calibrate_pro.calibration.closed_loop.plan import StopRules

WHITE: RGB = (1.0, 1.0, 1.0)
BLACK: RGB = (0.0, 0.0, 0.0)
PRIMARIES: tuple[RGB, RGB, RGB] = ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0))


@dataclass(frozen=True)
class Probe:
    presenter: PatchPresenter
    port: InstrumentPort
    clock: Clock


def read_patch(probe: Probe, rgb: RGB, repeats: int) -> np.ndarray:
    """Show one patch and return the mean of `repeats` readings."""
    probe.presenter.show(rgb)
    readings = [np.array(probe.port.read().xyz) for _ in range(max(1, repeats))]
    return np.asarray(np.mean(readings, axis=0), dtype=np.float64)


@dataclass(frozen=True)
class NoiseEstimate:
    """Instrument noise as the loop sees it after averaging."""

    floor_de: float
    luminance_sigma_rel: float


def noise_floor(probe: Probe, target: AchievableTarget, stop: StopRules) -> NoiseEstimate:
    """Estimate the smallest white error the loop can tell from noise.

    Single readings of white are compared with their mean. The floor is
    k times their RMS difference, divided by the square root of the reads the
    loop averages per patch.
    """
    probe.presenter.show(WHITE)
    readings = [np.array(probe.port.read().xyz) for _ in range(max(2, stop.noise_probe_reads))]
    mean = np.mean(readings, axis=0)
    errors = [delta_e_relative(target, reading, mean) for reading in readings]
    root_n = float(np.sqrt(max(1, stop.repeat_reads)))
    rms = float(np.sqrt(np.mean(np.square(errors))))
    sigma_y = float(np.std([r[1] for r in readings], ddof=1)) / max(float(mean[1]), 1e-9)
    return NoiseEstimate(stop.noise_floor_k * rms / root_n, sigma_y / root_n)


@dataclass(frozen=True)
class WarmupResult:
    stable: bool
    elapsed_s: float
    last_rate_pct_per_min: float
    readings: int


def _window_rate(history: list[tuple[float, float]], noise_rel: float) -> tuple[float, bool]:
    """Drift rate over the last three intervals, and whether noise explains it."""
    (t0, y0), (t1, y1) = history[-4] if len(history) >= 4 else history[0], history[-1]
    change = abs(y1 - y0) / max(y0, 1e-9)
    rate = change * 100.0 / max((t1 - t0) / 60.0, 1e-9)
    return rate, change <= 3.0 * noise_rel


def warmup_gate(probe: Probe, stop: StopRules, noise_rel: float) -> WarmupResult:
    """Wait until white luminance drift falls below the threshold.

    The criterion follows `calibrate_pro.hardware.warmup_monitor`: drift in
    percent per minute over the last three intervals, under a threshold for a
    run of consecutive readings. A change that instrument noise explains also
    counts as stable. The clock is injected, so a simulated panel warms up in
    simulated time.
    """
    start = probe.clock.now()
    history = [(start, float(read_patch(probe, WHITE, stop.repeat_reads)[1]))]
    streak, rate = 0, float("inf")
    while probe.clock.now() - start < stop.warmup_max_s:
        probe.clock.sleep(stop.warmup_interval_s)
        history.append((probe.clock.now(), float(read_patch(probe, WHITE, stop.repeat_reads)[1])))
        if len(history) < 4:
            continue
        rate, within_noise = _window_rate(history, noise_rel)
        streak = streak + 1 if rate < stop.warmup_threshold_pct_per_min or within_noise else 0
        if streak >= stop.warmup_stable_count:
            return WarmupResult(True, probe.clock.now() - start, rate, len(history))
    return WarmupResult(False, probe.clock.now() - start, rate, len(history))


@dataclass(frozen=True)
class Characterization:
    """Primaries, white and black at one control state, as XYZ columns."""

    primaries_xyz: np.ndarray
    white_xyz: np.ndarray
    black_xyz: np.ndarray

    def primaries_xy(self) -> tuple[tuple[float, float], ...]:
        columns = []
        for index in range(3):
            column = self.primaries_xyz[:, index]
            total = float(np.sum(column))
            columns.append((float(column[0]) / total, float(column[1]) / total))
        return tuple(columns)


def characterize(probe: Probe, repeats: int) -> Characterization:
    """Read the three primaries, white and black at the current state."""
    black = read_patch(probe, BLACK, repeats)
    columns = [read_patch(probe, rgb, repeats) - black for rgb in PRIMARIES]
    white = read_patch(probe, WHITE, repeats)
    return Characterization(np.column_stack(columns), white, black)


__all__ = [
    "BLACK",
    "PRIMARIES",
    "WHITE",
    "Characterization",
    "NoiseEstimate",
    "Probe",
    "WarmupResult",
    "characterize",
    "noise_floor",
    "read_patch",
    "warmup_gate",
]
