"""Checking a calibration against the display, with an instrument reading it.

The predicted path answers how well the correction chain should work by
simulating it. This answers how well it does work, by putting the reference
chart on the screen one patch at a time and reading each one back. Nothing here
consults a panel record or a model. Every figure it reports came out of the
sensor during this run.

The comparison is the standard one. Each ColorChecker swatch is sent as an sRGB
signal, the reading is normalized against the display's own measured white,
adapted from a D65 display white to D50, converted to Lab, and differenced
against the chart's D50 reference with CIEDE2000. Normalizing against measured
white is what makes the answer a colour result rather than a brightness one: a
display calibrated correctly at 120 cd/m2 and the same display at 200 read the
same here, and both read wrong if their primaries or tone response are off.

White is read from the display rather than assumed. A reference white taken
from the target would fold every luminance error into the deltas and report a
display as inaccurate for being dimmer than the number somebody typed.

One target is covered. The chart's references are D50-adapted Lab and its
swatches are sRGB-encoded, so together they describe an sRGB gamut, a D65 white
and a 2.2 tone response. A session aiming anywhere else gets no figure, because
the difference read back would be the difference between two targets rather
than the error in a calibration.

What this cannot establish is that the correction it grades is the one that is
loaded. The patch window paints through whatever gamma ramp and colour profile
Windows currently holds, so a run grades the display together with its current
state. Naming that state belongs to whoever starts the run.
"""

from __future__ import annotations

import math
from collections.abc import Callable

import numpy as np

from calibrate_pro.application.instruments import InstrumentError, InstrumentPort
from calibrate_pro.application.measurement import MINIMUM_WHITE_LUMINANCE, MeasurementRefused, PatchPort
from calibrate_pro.application.prediction import DELTA_E_UNIT, target_is_modelled
from calibrate_pro.application.results import VerificationResult, VerifiedPatch
from calibrate_pro.core.color_math import D50_WHITE, D65_WHITE, bradford_adapt, delta_e_2000, xyz_to_lab
from calibrate_pro.core.colorchecker import COLORCHECKER_PATCHES
from calibrate_pro.verification.provenance import EvidenceKind, MetricValue

#: What this verification examined. The predicted path names the plan it
#: simulated; this names the display, because that is what was in front of the
#: sensor.
VERIFICATION_SOURCE = "measured_display"

#: What the figures are, for a surface that labels them. Colour rather than
#: brightness, because every reading is scaled against the display's own
#: measured white before it is differenced.
METRIC_NAME = "colour accuracy, measured"

#: The patch sent to find the reference white every reading is scaled against.
WHITE_SIGNAL = (1.0, 1.0, 1.0)

#: Chart patches sRGB cannot reproduce. Their signals are clipped, so the
#: difference read back is the distance from the gamut to the reference rather
#: than the error in the calibration, and averaging it in would put a floor
#: under every display's score that no calibration could lift.
UNREACHABLE = tuple(patch.name for patch in COLORCHECKER_PATCHES if not patch.within_srgb)

#: Two readings closer than this in every component are the same reading. A
#: sensor that has stopped responding repeats its last answer exactly, and a run
#: of identical readings is that rather than a display showing one colour
#: twenty-four times.
IDENTICAL_READING_TOLERANCE = 1e-9

_UNCOVERED_LIMITATION = (
    "The ColorChecker reference this verification compares against describes "
    "sRGB primaries, a D65 white point and a 2.2 tone response. This target "
    "differs from that, so no measured accuracy is reported for it."
)

_UNCOVERED_METRIC = MetricValue(value=None, unit=DELTA_E_UNIT, evidence=EvidenceKind.NOT_MEASURED)


def uncovered_result() -> VerificationResult:
    """Answer for a target the reference chart does not describe."""
    return VerificationResult(
        source=VERIFICATION_SOURCE,
        evidence=EvidenceKind.NOT_MEASURED,
        average_delta_e=_UNCOVERED_METRIC,
        maximum_delta_e=_UNCOVERED_METRIC,
        patches=(),
        limitation=_UNCOVERED_LIMITATION,
    )


def measured_lab(xyz: tuple[float, float, float], white_luminance: float) -> tuple[float, float, float]:
    """Put one reading in the space the reference chart is quoted in.

    The reading is scaled so the display's own white lands at Y=1, adapted from
    a D65 display white to the D50 the chart references, and converted to Lab.
    That scaling is why the result grades colour rather than brightness.
    """
    if not math.isfinite(white_luminance) or white_luminance <= 0.0:
        raise MeasurementRefused("the display's white read as no light, so no reading can be scaled against it")
    normalized = np.array(xyz, dtype=float) / white_luminance
    adapted = bradford_adapt(normalized, D65_WHITE, D50_WHITE)
    lab = xyz_to_lab(adapted, D50_WHITE)
    return (float(lab[0]), float(lab[1]), float(lab[2]))


def _read(instrument: InstrumentPort) -> tuple[float, float, float]:
    """Take one reading, turning a dead instrument into a refusal.

    The alternative is a driver exception reaching a surface that was rendering
    accuracy figures, or a zero tristimulus standing in for a reading that never
    happened.
    """
    try:
        reading = instrument.read()
    except InstrumentError as exc:
        raise MeasurementRefused(f"the instrument stopped answering: {exc}") from exc
    return reading.xyz


def _show_and_read(
    instrument: InstrumentPort,
    patches: PatchPort,
    signal: tuple[float, float, float],
    settle: Callable[[], None],
) -> tuple[float, float, float]:
    """Put one patch on screen, let the panel reach it, then read it."""
    patches.show(signal)
    settle()
    return _read(instrument)


def _require_responding(readings: list[tuple[float, float, float]]) -> None:
    """Refuse a run whose readings never changed.

    Twenty-four different swatches cannot read the same, so a run that produced
    one repeated tristimulus measured the instrument rather than the display.
    Without this the deltas still compute and are still reported as measured.
    """
    first = readings[0]
    for reading in readings[1:]:
        if any(abs(value - other) > IDENTICAL_READING_TOLERANCE for value, other in zip(reading, first, strict=True)):
            return
    raise MeasurementRefused("every patch returned the same tristimulus, so the instrument was not reading the screen")


def _gamut_note(graded: int) -> str:
    """Say how many patches set the figures, and which one the target cannot reach.

    An operator reading a patch grid needs this to make sense of a swatch that
    reads high on a display that is calibrated correctly, and a reader comparing
    two runs needs the denominator stated rather than inferred from the count.
    """
    if not UNREACHABLE:
        return f"All {graded} patches are inside the target's gamut."
    named = ", ".join(UNREACHABLE)
    verb = "lies" if len(UNREACHABLE) == 1 else "lie"
    return (
        f"The figures above are over the {graded} patches sRGB can reproduce. "
        f"{named} {verb} outside it, so the reading is reported for the patch and left out of the average."
    )


def verify_measured(
    *,
    instrument: InstrumentPort,
    patches: PatchPort,
    preset_id: str,
    settle: Callable[[], None],
    progress: Callable[[str, float], None] | None = None,
) -> VerificationResult:
    """Read the reference chart off the display and report what it measured.

    Ports are not owned here. Whoever opened the instrument and the patch window
    closes them, which is what lets a caller verify twice without reopening a
    session in between.
    """
    if not target_is_modelled(preset_id):
        # Refused before either port is touched. A run that measured the display
        # and then discarded every figure would have spent the operator's time
        # to arrive at the answer this gives immediately.
        return uncovered_result()
    white_xyz = _show_and_read(instrument, patches, WHITE_SIGNAL, settle)
    white_luminance = white_xyz[1]
    if not math.isfinite(white_luminance) or white_luminance < MINIMUM_WHITE_LUMINANCE:
        raise MeasurementRefused(
            f"white read {white_luminance:.4f} cd/m2, below the {MINIMUM_WHITE_LUMINANCE} floor a lit display clears"
        )
    identity = instrument.identity()
    readings: list[tuple[float, float, float]] = []
    verified: list[VerifiedPatch] = []
    total = len(COLORCHECKER_PATCHES)
    for index, patch in enumerate(COLORCHECKER_PATCHES):
        if progress is not None:
            progress(patch.name, index / total)
        xyz = _show_and_read(instrument, patches, patch.srgb, settle)
        readings.append(xyz)
        lab = measured_lab(xyz, white_luminance)
        delta = float(delta_e_2000(np.array(lab), np.array(patch.lab_d50)))
        if not math.isfinite(delta):
            raise MeasurementRefused(f"the {patch.name} patch produced no usable difference from its reference")
        verified.append(
            VerifiedPatch(
                name=patch.name,
                reference_srgb=patch.srgb,
                displayed_lab=lab,
                delta_e=MetricValue(value=delta, unit=DELTA_E_UNIT, evidence=EvidenceKind.MEASURED, source=identity),
                within_target_gamut=patch.within_srgb,
            )
        )
    _require_responding(readings)
    if progress is not None:
        progress("complete", 1.0)
    deltas = [
        patch.delta_e.value for patch in verified if patch.delta_e.value is not None and patch.within_target_gamut
    ]
    if not deltas:
        raise MeasurementRefused("no chart patch this target can reproduce produced a usable difference")
    return VerificationResult(
        source=VERIFICATION_SOURCE,
        evidence=EvidenceKind.MEASURED,
        average_delta_e=MetricValue(
            value=sum(deltas) / len(deltas),
            unit=DELTA_E_UNIT,
            evidence=EvidenceKind.MEASURED,
            source=identity,
        ),
        maximum_delta_e=MetricValue(
            value=max(deltas),
            unit=DELTA_E_UNIT,
            evidence=EvidenceKind.MEASURED,
            source=identity,
        ),
        patches=tuple(verified),
        limitation=None,
        metric=METRIC_NAME,
        detail=(
            f"{total} ColorChecker patches read as {patches.describe()}, scaled to the display's "
            f"measured white. {_gamut_note(len(deltas))}"
        ),
    )


__all__ = [
    "IDENTICAL_READING_TOLERANCE",
    "METRIC_NAME",
    "VERIFICATION_SOURCE",
    "WHITE_SIGNAL",
    "measured_lab",
    "uncovered_result",
    "verify_measured",
]
