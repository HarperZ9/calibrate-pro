"""The synthetic display the measurement tests drive, and the geometry it needs.

The display is arithmetic. It stands in for a panel and for the instrument
reading it, and it is used the one way a fake is allowed to be used in this
suite: to check that a run recovers the numbers it was built from. Nothing here
stands in for a colorimeter's accuracy.

It lives outside any one test module because more than one contract is written
against it, and a second copy would be a second display for those contracts to
disagree about.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from calibrate_pro.application.instruments import InstrumentError, InstrumentReading
from calibrate_pro.panels.panel_types import (
    ChromaticityCoord,
    DDCRecommendations,
    GammaCurve,
    PanelCapabilities,
    PanelCharacterization,
    PanelPrimaries,
)

WIDE_PRIMARIES = ((0.6800, 0.3200), (0.2650, 0.6900), (0.1500, 0.0600))
NARROW_PRIMARIES = ((0.6400, 0.3300), (0.3000, 0.6000), (0.1500, 0.0600))
D65 = (0.3127, 0.3290)


def _tristimulus(xy: tuple[float, float]) -> np.ndarray:
    """Unit-luminance XYZ for one chromaticity."""
    x, y = xy
    return np.array([x / y, 1.0, (1.0 - x - y) / y])


def _rgb_to_xyz(
    primaries: tuple[tuple[float, float], tuple[float, float], tuple[float, float]],
    white: tuple[float, float],
    white_luminance: float,
) -> np.ndarray:
    """Build the matrix whose columns are the primaries at their real levels."""
    columns = np.column_stack([_tristimulus(xy) for xy in primaries])
    target = _tristimulus(white) * white_luminance
    return columns * np.linalg.solve(columns, target)


@dataclass
class SyntheticDisplay:
    """A display made of arithmetic, and the instrument that reads it.

    The reading at full white is ``white_luminance + black_luminance``, because
    the emissive term sits on top of a black floor the panel never turns off.
    """

    primaries: tuple[tuple[float, float], tuple[float, float], tuple[float, float]] = WIDE_PRIMARIES
    white: tuple[float, float] = D65
    white_luminance: float = 250.0
    black_luminance: float = 0.05
    gamma: tuple[float, float, float] = (2.20, 2.24, 2.18)
    identity_string: str = "SyntheticDisplay probe (SN-0)"
    geometry: str = "full-field patches"
    #: Every patch this display was asked to show, in order.
    shown: list[tuple[float, float, float]] = field(default_factory=list)
    #: One entry per event, so a test can assert a patch preceded its reading.
    events: list[str] = field(default_factory=list)
    reads: int = 0
    closed: int = 0
    #: Channels whose ramp stays at black until full signal.
    dead_channels: tuple[int, ...] = ()
    #: Read index that raises instead of answering, or None.
    fails_at: int | None = None

    def __post_init__(self) -> None:
        self._matrix = _rgb_to_xyz(self.primaries, self.white, self.white_luminance)
        self._black = _tristimulus(self.white) * self.black_luminance
        self._signal = (0.0, 0.0, 0.0)

    # PatchPort ---------------------------------------------------------
    def show(self, rgb: tuple[float, float, float]) -> None:
        self._signal = rgb
        self.shown.append(rgb)
        self.events.append(f"show{rgb}")

    def describe(self) -> str:
        return self.geometry

    def close(self) -> None:
        self.closed += 1

    # InstrumentPort ----------------------------------------------------
    def identity(self) -> str:
        return self.identity_string

    def read(self) -> InstrumentReading:
        if self.fails_at is not None and self.reads == self.fails_at:
            self.reads += 1
            raise InstrumentError("the sensor dropped off the bus")
        self.reads += 1
        self.events.append("read")
        return InstrumentReading(
            instrument=self.identity_string,
            xyz=self.emit(self._signal),
            integration_seconds=0.25,
        )

    # The display itself -------------------------------------------------
    def emit(self, rgb: tuple[float, float, float]) -> tuple[float, float, float]:
        drive = []
        for index, (value, exponent) in enumerate(zip(rgb, self.gamma, strict=True)):
            level = float(value)
            if index in self.dead_channels and level < 1.0:
                level = 0.0
            drive.append(level**exponent)
        xyz = self._black + self._matrix @ np.array(drive)
        return (float(xyz[0]), float(xyz[1]), float(xyz[2]))


@dataclass
class SrgbDisplay(SyntheticDisplay):
    """A display that decodes with the sRGB curve rather than a power law.

    The piecewise curve is what a display claiming sRGB is supposed to run, and
    a pure 2.2 power law is not the same function. A test measuring the floor a
    correct display grades at wants this one; a test perturbing a tone response
    wants the power law, where the exponent is the thing being moved.
    """

    def emit(self, rgb: tuple[float, float, float]) -> tuple[float, float, float]:
        drive = []
        for index, value in enumerate(rgb):
            level = float(value)
            if index in self.dead_channels and level < 1.0:
                level = 0.0
            drive.append(level / 12.92 if level <= 0.04045 else ((level + 0.055) / 1.055) ** 2.4)
        xyz = self._black + self._matrix @ np.array(drive)
        return (float(xyz[0]), float(xyz[1]), float(xyz[2]))


def base_panel(*, wide_gamut: bool = True, native_contrast: float = 1_000_000.0) -> PanelCharacterization:
    """A detected record whose every field differs from what gets measured."""
    return PanelCharacterization(
        manufacturer="Test Manufacturing",
        model_pattern="TM-0000",
        panel_type="QD-OLED",
        native_primaries=PanelPrimaries(
            red=ChromaticityCoord(0.5, 0.5),
            green=ChromaticityCoord(0.5, 0.5),
            blue=ChromaticityCoord(0.5, 0.5),
            white=ChromaticityCoord(0.5, 0.5),
        ),
        gamma_red=GammaCurve(gamma=1.80),
        gamma_green=GammaCurve(gamma=1.80),
        gamma_blue=GammaCurve(gamma=1.80),
        capabilities=PanelCapabilities(
            max_luminance_sdr=1.0,
            max_luminance_hdr=1000.0,
            min_luminance=99.0,
            native_contrast=native_contrast,
            bit_depth=10,
            wide_gamut=wide_gamut,
            vrr_capable=True,
        ),
        color_correction_matrix=[[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]],
        ddc=DDCRecommendations(),
        display_name="Test Manufacturing TM-0000",
    )
