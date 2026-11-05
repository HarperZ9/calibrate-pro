"""A simulated LCD panel with DDC/CI-style controls, for planted-truth tests.

Every number this panel emits is simulated. The model is deliberately not the
model the controller assumes, so convergence is earned:

- gains act on linear light through an exponent other than one, then quantize
  to 8-bit steps, as a panel's internal white-balance table would;
- brightness drives a backlight with a floor and a power-law response;
- black is backlight leakage at a fixed native contrast, raised by offsets;
- warm-up scales luminance, and the blue channel more, by a decaying
  exponential in simulated time.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

from calibrate_pro.calibration.closed_loop.controls import RGB, Clock, ControlSpec

_SRGB_LIKE = ((0.640, 0.330), (0.300, 0.600), (0.150, 0.060))

_SPECS = (
    ControlSpec("brightness", 0x10, 0, 100),
    ControlSpec("contrast", 0x12, 0, 100),
    ControlSpec("red_gain", 0x16, 0, 100),
    ControlSpec("green_gain", 0x18, 0, 100),
    ControlSpec("blue_gain", 0x1A, 0, 100),
    ControlSpec("red_offset", 0x6C, 0, 100),
    ControlSpec("green_offset", 0x6E, 0, 100),
    ControlSpec("blue_offset", 0x70, 0, 100),
)


@dataclass(frozen=True)
class PanelTruth:
    """The hidden physics of one simulated panel."""

    primaries_xy: tuple[tuple[float, float], ...] = _SRGB_LIKE
    #: Luminance of each primary at full signal, full gain, full backlight.
    channel_peak_y: tuple[float, float, float] = (60.0, 200.0, 20.0)
    channel_gamma: tuple[float, float, float] = (2.2, 2.2, 2.2)
    contrast_ratio: float = 1000.0
    backlight_floor: float = 0.08
    backlight_exponent: float = 1.4
    gain_exponent: float = 1.08
    gain_levels: int = 255
    offset_span: float = 0.002
    contrast_neutral: int = 50
    warmup_amplitude: float = 0.0
    warmup_blue_extra: float = 0.0
    warmup_tau_s: float = 600.0
    settle_s: float = 0.5
    initial: dict[str, int] = field(default_factory=dict)


def _primary_columns(primaries: tuple[tuple[float, float], ...]) -> np.ndarray:
    columns = [np.array([x / y, 1.0, (1.0 - x - y) / y]) for x, y in primaries]
    return np.column_stack(columns)


class SimulatedPanel:
    """A panel that implements PanelControls and PatchPresenter, all simulated."""

    #: Read by the report: nothing from this panel is a measurement.
    simulated = True

    def __init__(self, truth: PanelTruth, clock: Clock) -> None:
        self._truth = truth
        self._clock = clock
        self._columns = _primary_columns(truth.primaries_xy)
        self._state = {spec.name: spec.maximum if "gain" in spec.name else 50 for spec in _SPECS}
        self._state["brightness"] = 50
        self._state["contrast"] = truth.contrast_neutral
        self._state.update(truth.initial)
        self._signal: RGB = (0.0, 0.0, 0.0)
        self.write_log: list[tuple[str, int]] = []

    @property
    def write_count(self) -> int:
        return len(self.write_log)

    def controls(self) -> tuple[ControlSpec, ...]:
        return _SPECS

    def read_control(self, name: str) -> int:
        if name not in self._state:
            raise KeyError(f"the simulated panel has no control {name!r}")
        return self._state[name]

    def write_control(self, name: str, value: int) -> None:
        spec = next((s for s in _SPECS if s.name == name), None)
        if spec is None:
            raise KeyError(f"the simulated panel has no control {name!r}")
        if isinstance(value, bool) or not isinstance(value, int) or not spec.minimum <= value <= spec.maximum:
            raise ValueError(f"{name} value {value!r} is outside {spec.minimum}..{spec.maximum}")
        self._state[name] = value
        self.write_log.append((name, value))
        self._clock.sleep(self._truth.settle_s)

    def show(self, rgb: RGB) -> None:
        if any(not 0.0 <= channel <= 1.0 for channel in rgb):
            raise ValueError("patch signal must lie within 0..1")
        self._signal = (float(rgb[0]), float(rgb[1]), float(rgb[2]))

    def _backlight(self) -> float:
        truth = self._truth
        level = self._state["brightness"] / 100.0
        return truth.backlight_floor + (1.0 - truth.backlight_floor) * level**truth.backlight_exponent

    def _warmup(self) -> np.ndarray:
        truth = self._truth
        decay = math.exp(-self._clock.now() / truth.warmup_tau_s)
        base = 1.0 - truth.warmup_amplitude * decay
        return np.array([base, base, base - truth.warmup_blue_extra * decay])

    def _gain(self, name: str) -> float:
        truth = self._truth
        raw = (self._state[name] / 100.0) ** truth.gain_exponent
        return round(raw * truth.gain_levels) / truth.gain_levels

    def _channel_light(self) -> np.ndarray:
        truth = self._truth
        scale = self._state["contrast"] / truth.contrast_neutral
        light = []
        for index, channel in enumerate(("red", "green", "blue")):
            drive = min(1.0, self._signal[index] * scale)
            linear = drive ** truth.channel_gamma[index] * self._gain(f"{channel}_gain")
            lift = (self._state[f"{channel}_offset"] - 50) / 50.0 * truth.offset_span
            light.append(max(0.0, linear + lift))
        return np.array(light)

    def emitted_xyz(self) -> np.ndarray:
        """The light in front of the panel now, in cd/m2. Simulated truth."""
        truth = self._truth
        peaks = np.array(truth.channel_peak_y) * self._backlight() * self._warmup()
        signal_xyz = self._columns @ (self._channel_light() * peaks)
        leakage = self._columns @ peaks / truth.contrast_ratio
        return np.asarray(signal_xyz + leakage, dtype=np.float64)


__all__ = ["PanelTruth", "SimulatedPanel"]
