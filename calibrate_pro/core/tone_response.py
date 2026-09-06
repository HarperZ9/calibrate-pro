"""Tone responses the calibration can actually drive a display to.

Three of the four curves here are not power laws. sRGB is piecewise, with a
linear segment below 0.04045 that a 2.2 exponent misses by about 0.005 in the
shadows. L* follows CIE lightness. BT.1886 becomes a 2.4 power law only when
the black level is zero, and departs from it as soon as a real panel black is
measured. So a single exponent cannot carry this axis, and the engine takes a
curve.

Two of the catalogue transfer functions are deliberately absent. PQ returns
absolute luminance up to 10,000 cd/m2 and HLG up to 1,000, and normalising
either into the 0 to 1 signal the SDR pipeline uses would describe an HDR
curve while applying an SDR one. HDR targets stay declared closed until the
apply path carries absolute luminance.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from calibrate_pro.targets.gamma import bt1886_eotf, l_star_eotf, power_eotf, srgb_eotf

POWER = "power"
SRGB = "srgb"
L_STAR = "l_star"
BT1886 = "bt1886"

_KINDS = frozenset({POWER, SRGB, L_STAR, BT1886})


@dataclass(frozen=True)
class ToneResponse:
    """One tone response, decoding a 0 to 1 signal to 0 to 1 relative light.

    Held as a kind and its parameters rather than as a stored callable, so two
    tone responses built the same way compare equal, a plan can be written to
    disk, and a manifest can name what it applied.
    """

    label: str
    kind: str = POWER
    exponent: float = 2.2
    black_luminance: float = 0.0
    peak_luminance: float = 100.0

    def __post_init__(self) -> None:
        if self.kind not in _KINDS:
            raise ValueError(
                f"Unknown tone response kind {self.kind!r}. This build carries {', '.join(sorted(_KINDS))}."
            )
        if self.kind in {POWER, BT1886} and not 1.0 <= self.exponent <= 3.2:
            raise ValueError(
                f"A tone response exponent of {self.exponent} is outside the 1.0 to 3.2 range this build applies."
            )
        if self.kind == BT1886:
            if self.peak_luminance <= 0.0:
                raise ValueError("BT.1886 needs a peak luminance above zero.")
            if not 0.0 <= self.black_luminance < self.peak_luminance:
                raise ValueError(
                    f"A BT.1886 black of {self.black_luminance} cd/m2 is not below its peak of {self.peak_luminance}."
                )

    def to_linear(self, signal: np.ndarray) -> np.ndarray:
        """Decode signal to relative light, normalised so full drive reaches 1.0.

        The normalisation is what makes these curves interchangeable with the
        power law the LUT engine used to hard-code. bt1886_eotf answers in
        cd/m2 and reaches 100 at full drive; handed to the engine unscaled it
        would ask the panel for a hundred times the light it can emit.
        """
        values = np.asarray(signal, dtype=np.float64)
        decoded = self._decode(values)
        peak = float(self._decode(np.array([1.0]))[0])
        if peak <= 0.0:
            raise ValueError(f"Tone response {self.label!r} emits no light at full drive.")
        return np.asarray(decoded / peak, dtype=np.float64)

    def _decode(self, values: np.ndarray) -> np.ndarray:
        if self.kind == POWER:
            return np.asarray(power_eotf(values, self.exponent))
        if self.kind == SRGB:
            return np.asarray(srgb_eotf(values))
        if self.kind == L_STAR:
            return np.asarray(l_star_eotf(values))
        return np.asarray(bt1886_eotf(values, L_W=self.peak_luminance, L_B=self.black_luminance, gamma=self.exponent))

    @property
    def is_power_law(self) -> bool:
        """Whether this curve is exactly ``signal ** exponent``.

        A caller that has a power law should hand the engine its exponent
        rather than this object. Both reach the same numbers, but the
        exponent goes through one call to :func:`numpy.power` where the curve
        goes through two, and the shipped presets are digest-sealed against
        the single call.
        """
        return self.kind == POWER

    @property
    def nominal_exponent(self) -> float:
        """The power law that comes closest, for a reader that only takes one number.

        Reported rather than applied. The correction uses :meth:`to_linear`,
        so this number never stands in for the curve; it exists because some
        formats carry a single gamma field and something has to go in it.
        """
        if self.kind == POWER:
            return self.exponent
        mid = float(self.to_linear(np.array([0.5]))[0])
        return float(np.log(mid) / np.log(0.5))

    def table(self, points: int = 1024) -> np.ndarray:
        """Sample the curve across the full signal range."""
        if points < 2:
            raise ValueError(f"A tone response table needs at least two points, not {points}.")
        return self.to_linear(np.linspace(0.0, 1.0, points))


def power_law(exponent: float, label: str | None = None) -> ToneResponse:
    """A plain power law, the shape most calibration targets still use."""
    return ToneResponse(label=label or f"{exponent:g}", kind=POWER, exponent=exponent)


def bt1886(black_luminance: float, peak_luminance: float = 100.0) -> ToneResponse:
    """BT.1886 for a measured black level.

    With a black of zero this is a 2.4 power law, which is the assumption the
    presets shipped under. A panel with a real black of 0.05 cd/m2 follows a
    visibly different curve in the bottom two stops, and that is the whole
    reason the standard exists.
    """
    return ToneResponse(
        label="BT.1886",
        kind=BT1886,
        exponent=2.4,
        black_luminance=black_luminance,
        peak_luminance=peak_luminance,
    )
