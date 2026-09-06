"""Turning what an instrument saw into a characterization of one display.

This is the measurement contract the measured actions have been waiting for.
A sensorless bundle is built from a panel record that describes a model. A
measured bundle is built from this, which describes the unit in front of the
operator: its primaries as it actually emits them, its per-channel tone
response as it actually rolls off, and its white and black as they actually
read in cd/m2.

The run pairs a requested patch with a reading. An instrument reports the light
in front of it and knows nothing about what was asked for, so the pairing has
to happen somewhere that holds both, and that is here. A patch is shown, the
display is given time to settle, and only then is a reading taken.

A failed reading raises. The characterization routine underneath substitutes a
tristimulus of zeros for a measurement that answered nothing, which would turn a
dead instrument into a display that emits no light and hand back a profile built
from that. Raising is what keeps that branch unreachable.

What the instrument set and what it did not are named separately. Bit depth,
variable refresh, and the HDR peak cannot be read off an SDR patch ramp, so
those keep whatever provenance the detected record gave them rather than being
invented from a measurement that never covered them.

The patch geometry is recorded because it changes the answer. An OLED
dims a full white field to stay inside its power budget and holds a small
window at full output, so the same panel reads one peak on a full field and
a higher one on a ten percent window. A luminance without the geometry it
was read at cannot be reproduced, so the port says what it showed.

Ports are not owned here. Whoever opened the instrument and the patch window
closes them, because a run that closed them would take a second run's session
away from a caller measuring twice.

One arithmetic detail matters to every luminance this module reports. The
characterization routine subtracts the black reading from every ramp, so the
white it reports is white above black rather than white as the instrument saw
it. A panel record holds absolute cd/m2, so black is added back before the
peak is recorded and before contrast is divided.
"""

from __future__ import annotations

import math
import time
from collections.abc import Callable
from dataclasses import dataclass, replace
from typing import Protocol

import numpy as np

from calibrate_pro.application.instruments import InstrumentError, InstrumentPort
from calibrate_pro.calibration.native_loop import DisplayProfile, profile_display
from calibrate_pro.panels.panel_types import (
    ChromaticityCoord,
    GammaCurve,
    PanelCharacterization,
    PanelPrimaries,
)

#: Steps per channel ramp. Four ramps run, so this is a quarter of the patch
#: count. Seventeen puts a sample every sixteenth of the signal range, which
#: resolves the near-black roll-off an OLED shows without turning the run into
#: something an operator will not sit through.
DEFAULT_RAMP_STEPS = 17

#: Fewer steps than this cannot describe a tone response. Three points give a
#: black, a mid and a white and nothing to say about the shape between them.
MINIMUM_RAMP_STEPS = 5

#: How long a display is given to settle after a patch changes. An OLED
#: stabilizes faster than this and an LCD slower; the value is what the proven
#: research run used, and a caller measuring a slow panel passes its own.
SETTLE_SECONDS = 1.5

#: Below this the run did not measure a display. A dark room reads under this
#: with the instrument pointed at nothing, so a white patch that cannot clear it
#: means the sensor was not on the screen or the screen was not lit.
MINIMUM_WHITE_LUMINANCE = 0.5

#: How far below zero a black reading may sit before the run is a fault
#: rather than sensor noise. A display cannot emit negative light, so a
#: reading inside this band is reported as zero and its contrast as unknown.
BLACK_NOISE_FLOOR = -0.01

#: The band a per-channel gamma has to land in. Outside it the ramp did not
#: describe a display's tone response, whatever the arithmetic produced.
MINIMUM_GAMMA = 1.0
MAXIMUM_GAMMA = 4.0

#: Smallest xy-plane triangle the three primaries may enclose. A run whose
#: primaries collapse toward a point measured one colour three times.
MINIMUM_GAMUT_AREA = 0.01

#: Measured red x above this is a wide-gamut panel. The engine asks the same
#: question of a declared record; asking it of a measurement is what makes the
#: answer this unit's rather than its model's.
WIDE_GAMUT_RED_X = 0.66

#: Fields the instrument sets on every measured characterization.
MEASURED_FIELDS = (
    "native_primaries",
    "gamma_red",
    "gamma_green",
    "gamma_blue",
    "capabilities.max_luminance_sdr",
    "capabilities.min_luminance",
    "capabilities.wide_gamut",
)

#: Set from the measurement only when the instrument told black apart from
#: zero. An OLED often reads exactly zero, and a ratio against zero is not a
#: number, so the declared value is kept and `contrast_ratio` reports None.
CONDITIONALLY_MEASURED_FIELDS = ("capabilities.native_contrast",)


class MeasurementRefused(RuntimeError):
    """A run could not produce a characterization, and the message says why."""


class PatchPort(Protocol):
    """Somewhere a solid colour can be put in front of the instrument."""

    def show(self, rgb: tuple[float, float, float]) -> None: ...

    def describe(self) -> str: ...

    def close(self) -> None: ...


class NoPatchPort:
    """The default, which shows nothing and refuses to pretend it did."""

    def show(self, rgb: tuple[float, float, float]) -> None:
        del rgb
        raise MeasurementRefused("this session was built without a patch window")

    def describe(self) -> str:
        return "no patch window"

    def close(self) -> None:
        return None


@dataclass(frozen=True)
class MeasuredCharacterization:
    """One display as an instrument read it, with the run that produced it."""

    panel: PanelCharacterization
    instrument: str
    steps: int
    patch_count: int
    white_luminance: float
    black_luminance: float
    #: None when black read as zero, meaning the instrument did not tell it
    #: apart from no light at all rather than meaning contrast is unbounded.
    contrast_ratio: float | None
    white_xy: tuple[float, float]
    gamma: tuple[float, float, float]
    #: What the patch port put on screen, in its own words. An OLED peak
    #: depends on it, so a report without it cannot be reproduced.
    patch_geometry: str

    @property
    def summary(self) -> str:
        """One line naming the instrument and what it read."""
        white = f"{self.white_luminance:.1f} cd/m2"
        gamma = "/".join(f"{value:.2f}" for value in self.gamma)
        return f"{self.instrument}: {self.patch_count} patches, white {white}, gamma {gamma}, {self.patch_geometry}"


def _default_settle() -> None:
    time.sleep(SETTLE_SECONDS)


def _triangle_area(a: tuple[float, float], b: tuple[float, float], c: tuple[float, float]) -> float:
    return abs((b[0] - a[0]) * (c[1] - a[1]) - (c[0] - a[0]) * (b[1] - a[1])) / 2.0


def _luminances(profile: DisplayProfile) -> tuple[float, float]:
    """Report absolute white and black in cd/m2.

    The profile carries white above black, because every ramp had the black
    reading subtracted from it. Adding black back is what turns that into the
    peak an instrument would read off a white field.

    A black that read below zero is reported as zero. A dark-calibrated sensor
    crosses zero as noise on a deep black, and a panel record holding negative
    emission would be describing something no display does.
    """
    measured_black = float(profile.black_xyz[1])
    black = max(0.0, measured_black)
    above_black = float(profile.white_Y)
    return above_black + black, black


def _require_usable(profile: DisplayProfile) -> None:
    """Refuse a profile that arithmetic produced but a display did not.

    Every check here guards a way a broken run still yields a well-formed
    profile. The gamma estimate falls back to 2.2 when a ramp carries no usable
    midpoint, so a run that measured nothing four times over would otherwise
    hand back a plausible display with a textbook tone response.
    """
    white, black = _luminances(profile)
    if not math.isfinite(white) or white < MINIMUM_WHITE_LUMINANCE:
        raise MeasurementRefused(
            f"white measured {white:.4f} cd/m2, below the {MINIMUM_WHITE_LUMINANCE} floor a lit display clears"
        )
    measured_black = float(profile.black_xyz[1])
    if not math.isfinite(measured_black) or measured_black < BLACK_NOISE_FLOOR:
        raise MeasurementRefused(
            f"black measured {measured_black:.5f} cd/m2, further below zero than sensor noise reaches"
        )
    if float(profile.white_Y) <= 0.0:
        raise MeasurementRefused("white measured no brighter than black, so the ramp did not describe a display")
    for name, curve in (("red", profile.trc_r), ("green", profile.trc_g), ("blue", profile.trc_b)):
        midpoint = float(curve[len(curve) // 2])
        if not 0.0 < midpoint < 1.0:
            raise MeasurementRefused(f"the {name} ramp carried no usable midpoint, so its gamma was never measured")
    for name, gamma in (("red", profile.gamma_r), ("green", profile.gamma_g), ("blue", profile.gamma_b)):
        value = float(gamma)
        if not math.isfinite(value) or not MINIMUM_GAMMA <= value <= MAXIMUM_GAMMA:
            raise MeasurementRefused(f"{name} gamma measured {value:.3f}, outside the band a display responds in")
    primaries = (profile.red_xy, profile.green_xy, profile.blue_xy)
    for name, coordinate in zip(("red", "green", "blue"), primaries, strict=True):
        if coordinate == (0.0, 0.0):
            raise MeasurementRefused(f"the {name} primary carried no chromaticity")
    area = _triangle_area(*primaries)
    if area < MINIMUM_GAMUT_AREA:
        raise MeasurementRefused(f"the measured primaries enclose {area:.4f}, too little to be three separate colours")


def characterization_from(base: PanelCharacterization, profile: DisplayProfile) -> PanelCharacterization:
    """Replace the modelled fields a measurement covered, keeping the rest.

    The correction matrix is dropped rather than carried. It corrects a panel
    record toward its model's measured behaviour, and this record now holds the
    unit's own, so applying both would correct twice for one error.
    """
    white, black = _luminances(profile)
    capabilities = replace(
        base.capabilities,
        max_luminance_sdr=white,
        min_luminance=black,
        wide_gamut=profile.red_xy[0] > WIDE_GAMUT_RED_X,
    )
    if black > 0.0:
        capabilities = replace(capabilities, native_contrast=white / black)
    return replace(
        base,
        native_primaries=PanelPrimaries(
            red=ChromaticityCoord(*profile.red_xy),
            green=ChromaticityCoord(*profile.green_xy),
            blue=ChromaticityCoord(*profile.blue_xy),
            white=ChromaticityCoord(*profile.white_xy),
        ),
        gamma_red=GammaCurve(gamma=float(profile.gamma_r)),
        gamma_green=GammaCurve(gamma=float(profile.gamma_g)),
        gamma_blue=GammaCurve(gamma=float(profile.gamma_b)),
        capabilities=capabilities,
        color_correction_matrix=None,
    )


def measure_characterization(
    *,
    instrument: InstrumentPort,
    patches: PatchPort,
    base: PanelCharacterization,
    steps: int = DEFAULT_RAMP_STEPS,
    settle: Callable[[], None] | None = None,
    progress: Callable[[str, float], None] | None = None,
) -> MeasuredCharacterization:
    """Run the patch ramps and return what the instrument made of them."""
    if type(steps) is not int or steps < MINIMUM_RAMP_STEPS:
        raise MeasurementRefused(f"a ramp needs at least {MINIMUM_RAMP_STEPS} steps to describe a tone response")
    if steps % 2 == 0:
        # The gamma estimate reads the middle sample and divides by the log of
        # one half, which is only the exponent when that sample sits at half
        # signal. An even count has no sample there, so an even ramp reports a
        # gamma the display does not have.
        raise MeasurementRefused("a ramp needs an odd step count so one patch lands at half signal")
    wait = _default_settle if settle is None else settle

    def display_fn(red: float, green: float, blue: float) -> None:
        patches.show((float(red), float(green), float(blue)))
        wait()

    def measure_fn(red: float, green: float, blue: float) -> np.ndarray:
        # The requested patch is not passed on. An instrument reports the light
        # in front of it, and handing it the colour that was asked for would
        # let a port answer with the request instead of the reading.
        del red, green, blue
        try:
            reading = instrument.read()
        except InstrumentError as exc:
            raise MeasurementRefused(f"the instrument stopped answering: {exc}") from exc
        return np.array(reading.xyz, dtype=float)

    profile = profile_display(measure_fn, display_fn, n_steps=steps, progress_fn=progress)
    _require_usable(profile)
    white, black = _luminances(profile)
    return MeasuredCharacterization(
        panel=characterization_from(base, profile),
        instrument=instrument.identity(),
        steps=steps,
        patch_count=steps * 4,
        white_luminance=white,
        black_luminance=black,
        contrast_ratio=(white / black) if black > 0.0 else None,
        white_xy=profile.white_xy,
        gamma=(float(profile.gamma_r), float(profile.gamma_g), float(profile.gamma_b)),
        patch_geometry=patches.describe(),
    )


__all__ = [
    "BLACK_NOISE_FLOOR",
    "CONDITIONALLY_MEASURED_FIELDS",
    "DEFAULT_RAMP_STEPS",
    "MAXIMUM_GAMMA",
    "MEASURED_FIELDS",
    "MINIMUM_GAMMA",
    "MINIMUM_GAMUT_AREA",
    "MINIMUM_RAMP_STEPS",
    "MINIMUM_WHITE_LUMINANCE",
    "SETTLE_SECONDS",
    "WIDE_GAMUT_RED_X",
    "MeasuredCharacterization",
    "MeasurementRefused",
    "NoPatchPort",
    "PatchPort",
    "characterization_from",
    "measure_characterization",
]
