"""What a measured verification is allowed to report, and when it refuses.

This is the path that puts a number in front of an operator and calls it
measured. Three things have to hold for that number to mean anything.

It has to be a colour result rather than a brightness one, so the same display
at two luminances grades the same. It has to grade against a target the chart
describes, so a session aiming somewhere else gets no figure rather than the
distance between two targets. And it has to refuse whenever the run did not
happen: a dead instrument, a dark screen, a sensor repeating its last answer.

The controls at the end are the point. Each drives a run that the arithmetic
turns into a well-formed accuracy figure, and asserts the contract refused it.
"""

from __future__ import annotations

import math

import pytest

from calibrate_pro.application.instruments import InstrumentError
from calibrate_pro.application.measured_verification import (
    IDENTICAL_READING_TOLERANCE,
    UNREACHABLE,
    VERIFICATION_SOURCE,
    WHITE_SIGNAL,
    measured_lab,
    uncovered_result,
    verify_measured,
)
from calibrate_pro.application.measurement import MINIMUM_WHITE_LUMINANCE, MeasurementRefused
from calibrate_pro.core.colorchecker import COLORCHECKER_PATCHES
from calibrate_pro.verification.provenance import EvidenceKind
from tests.measurement_support import NARROW_PRIMARIES, SrgbDisplay, SyntheticDisplay

MODELLED = "calibration.preset.srgb_web"
UNMODELLED = "calibration.preset.dci_p3"

#: Every catalogued target the chart does not describe, plus one that is not a
#: preset at all. A run reaching for any of these must report no figure rather
#: than the distance between two targets.
UNCOVERED_PRESETS = (
    "calibration.preset.rec709",
    "calibration.preset.dci_p3",
    "calibration.preset.photography",
    "calibration.preset.does.not.exist",
)


def srgb_display(**kwargs: object) -> SrgbDisplay:
    """A display that is already right: sRGB primaries, sRGB curve, D65."""
    settings: dict[str, object] = {"white_luminance": 120.0, "black_luminance": 0.0}
    settings.update(kwargs)
    return SrgbDisplay(primaries=NARROW_PRIMARIES, **settings)  # type: ignore[arg-type]


def run(display: SyntheticDisplay, *, preset: str = MODELLED, **kwargs: object):
    return verify_measured(
        instrument=display,
        patches=display,
        preset_id=preset,
        settle=lambda: None,
        **kwargs,  # type: ignore[arg-type]
    )


def graded(result) -> list:
    return [patch for patch in result.patches if patch.within_target_gamut]


# What a correct display reads ----------------------------------------------


def test_a_display_that_already_reproduces_srgb_grades_at_the_arithmetic_floor() -> None:
    """The number an operator sees when nothing is wrong.

    A chart whose signals did not correspond to its references put 2.27 dE2000
    average on this display and told the operator their calibration was
    mediocre. What is left here is the rounding in three-decimal signals.
    """
    result = run(srgb_display())

    assert result.evidence is EvidenceKind.MEASURED
    assert result.source == VERIFICATION_SOURCE
    assert result.average_delta_e.value == pytest.approx(0.05, abs=0.02)
    assert result.maximum_delta_e.value == pytest.approx(0.13, abs=0.05)
    assert result.limitation is None


def test_the_same_display_at_two_luminances_grades_the_same() -> None:
    """Normalizing against measured white is what makes this a colour result."""
    dim = run(srgb_display(white_luminance=120.0))
    bright = run(srgb_display(white_luminance=200.0))

    assert dim.average_delta_e.value == pytest.approx(bright.average_delta_e.value, abs=1e-9)
    assert dim.maximum_delta_e.value == pytest.approx(bright.maximum_delta_e.value, abs=1e-9)


def test_a_tone_response_error_moves_the_figure_off_the_floor() -> None:
    """The floor has to be small enough that a real error is separable from it."""
    correct = run(srgb_display())
    skewed = run(
        SyntheticDisplay(
            primaries=NARROW_PRIMARIES,
            white_luminance=120.0,
            black_luminance=0.0,
            gamma=(2.25, 2.20, 2.15),
        )
    )

    assert skewed.average_delta_e.value > correct.average_delta_e.value * 4


def test_a_wide_gamut_display_left_uncorrected_grades_far_worse_than_a_correct_one() -> None:
    """The error this product exists to remove has to be the one it measures.

    A wide-gamut panel showing sRGB content without a clamp oversaturates every
    swatch that has any saturation to oversaturate. Most of the chart is
    low-chroma, so the average lands near 2 while the saturated end runs past 4.
    """
    correct = run(srgb_display())
    uncorrected = run(SrgbDisplay(white_luminance=120.0, black_luminance=0.0))

    assert uncorrected.average_delta_e.value > 2.0, "an unclamped wide gamut is a visible error"
    assert uncorrected.maximum_delta_e.value > 4.0
    assert uncorrected.average_delta_e.value > correct.average_delta_e.value * 20
    worst = max(graded(uncorrected), key=lambda patch: patch.delta_e.value)
    assert worst.name == "Yellow", "the saturated patches are where an unclamped gamut shows"


# The whole chart, and the part of it sRGB cannot reach ----------------------


def test_every_chart_patch_is_reported() -> None:
    result = run(srgb_display())

    assert len(result.patches) == len(COLORCHECKER_PATCHES)
    assert [patch.name for patch in result.patches] == [patch.name for patch in COLORCHECKER_PATCHES]


def test_a_patch_outside_the_target_gamut_is_reported_and_left_out_of_the_average() -> None:
    """Averaging an unreachable patch in would floor every display's score."""
    result = run(srgb_display())

    excluded = [patch for patch in result.patches if not patch.within_target_gamut]
    assert [patch.name for patch in excluded] == list(UNREACHABLE)
    assert excluded, "the chart has a patch sRGB cannot reproduce, and the test depends on it"
    assert excluded[0].delta_e.value > 2.0, "the clipped signal cannot reach its reference"
    assert result.maximum_delta_e.value < excluded[0].delta_e.value
    assert all(patch.delta_e.value <= result.maximum_delta_e.value for patch in graded(result))


def test_the_detail_says_how_many_patches_set_the_figures_and_which_did_not() -> None:
    result = run(srgb_display())

    assert f"over the {len(graded(result))} patches" in result.detail
    for name in UNREACHABLE:
        assert name in result.detail
    assert "left out of the average" in result.detail


def test_the_detail_names_the_geometry_the_patches_were_shown_in() -> None:
    display = srgb_display()
    display.geometry = "a 10 percent window"

    assert "a 10 percent window" in run(display).detail


# A target the chart does not describe --------------------------------------


def test_a_target_the_chart_does_not_describe_reports_no_figure() -> None:
    display = srgb_display()

    result = run(display, preset=UNMODELLED)

    assert result.evidence is EvidenceKind.NOT_MEASURED
    assert result.average_delta_e.value is None
    assert result.maximum_delta_e.value is None
    assert result.patches == ()
    assert result.limitation is not None
    assert "no measured accuracy is reported" in result.limitation


@pytest.mark.parametrize("preset", UNCOVERED_PRESETS)
def test_an_uncovered_target_touches_neither_port(preset: str) -> None:
    """Refused before the run, not after spending the operator's time on it."""
    display = srgb_display()

    result = run(display, preset=preset)

    assert result.evidence is EvidenceKind.NOT_MEASURED
    assert display.shown == []
    assert display.reads == 0


def test_the_uncovered_answer_is_the_one_the_module_publishes() -> None:
    published = uncovered_result()

    assert published.evidence is EvidenceKind.NOT_MEASURED
    assert published.limitation == run(srgb_display(), preset=UNMODELLED).limitation


# The order the run happens in ----------------------------------------------


def test_white_is_read_first_and_every_patch_is_shown_before_it_is_read() -> None:
    display = srgb_display()

    run(display)

    assert display.shown[0] == WHITE_SIGNAL
    assert display.shown[1:] == [patch.srgb for patch in COLORCHECKER_PATCHES]
    assert len(display.events) == 2 * len(display.shown)
    for index in range(0, len(display.events), 2):
        assert display.events[index].startswith("show")
        assert display.events[index + 1] == "read"


def test_the_run_does_not_close_the_ports_it_was_handed() -> None:
    """Whoever opened them closes them, which is what lets a caller verify twice."""
    display = srgb_display()

    run(display)
    run(display)

    assert display.closed == 0


def test_progress_reports_every_patch_and_finishes_at_one() -> None:
    seen: list[tuple[str, float]] = []

    run(srgb_display(), progress=lambda name, fraction: seen.append((name, fraction)))

    assert [name for name, _ in seen[:-1]] == [patch.name for patch in COLORCHECKER_PATCHES]
    assert seen[0][1] == 0.0
    assert seen[-1] == ("complete", 1.0)
    assert all(0.0 <= fraction <= 1.0 for _, fraction in seen)


# Controls: runs that produce a figure and must not ------------------------


def test_a_dark_display_refuses_rather_than_scaling_against_no_light() -> None:
    display = srgb_display(white_luminance=MINIMUM_WHITE_LUMINANCE / 2)

    with pytest.raises(MeasurementRefused) as refusal:
        run(display)

    assert "below the" in str(refusal.value)
    assert display.reads == 1, "the run stops at the white reading rather than measuring the chart"


def test_an_instrument_that_repeats_its_last_answer_refuses() -> None:
    """A sensor that has stopped reading still produces well-formed deltas."""

    class Stuck(SrgbDisplay):
        def emit(self, rgb: tuple[float, float, float]) -> tuple[float, float, float]:
            return super().emit((0.5, 0.5, 0.5))

    with pytest.raises(MeasurementRefused) as refusal:
        run(Stuck(primaries=NARROW_PRIMARIES, white_luminance=120.0, black_luminance=0.0))

    assert "not reading the screen" in str(refusal.value)


def test_two_readings_further_apart_than_the_tolerance_are_not_a_stuck_sensor() -> None:
    """The control has to distinguish a stuck sensor from a display that is dim."""

    class BarelyMoving(SrgbDisplay):
        def emit(self, rgb: tuple[float, float, float]) -> tuple[float, float, float]:
            base = super().emit((1.0, 1.0, 1.0))
            nudge = IDENTICAL_READING_TOLERANCE * 100 * sum(rgb)
            return (base[0] + nudge, base[1], base[2])

    result = run(BarelyMoving(primaries=NARROW_PRIMARIES, white_luminance=120.0, black_luminance=0.0))

    assert result.evidence is EvidenceKind.MEASURED


def test_an_instrument_that_drops_off_the_bus_refuses() -> None:
    display = srgb_display()
    display.fails_at = 5

    with pytest.raises(MeasurementRefused) as refusal:
        run(display)

    assert "stopped answering" in str(refusal.value)


def test_an_instrument_that_fails_on_the_white_reading_refuses_before_the_chart() -> None:
    display = srgb_display()
    display.fails_at = 0

    with pytest.raises(MeasurementRefused):
        run(display)

    assert display.shown == [WHITE_SIGNAL]


def test_the_refusal_carries_what_the_driver_said() -> None:
    display = srgb_display()
    display.fails_at = 3

    with pytest.raises(MeasurementRefused) as refusal:
        run(display)

    assert "dropped off the bus" in str(refusal.value)
    assert isinstance(refusal.value.__cause__, InstrumentError)


# Scaling one reading -------------------------------------------------------


def test_a_reading_is_quoted_in_the_space_the_chart_is_quoted_in() -> None:
    """The display's own white lands on the chart's white, at L* 100."""
    white = (0.95047 * 120.0, 1.0 * 120.0, 1.08883 * 120.0)

    lightness, a_star, b_star = measured_lab(white, 120.0)

    assert lightness == pytest.approx(100.0, abs=0.01)
    assert a_star == pytest.approx(0.0, abs=0.02)
    assert b_star == pytest.approx(0.0, abs=0.02)


@pytest.mark.parametrize("luminance", [0.0, -1.0, math.nan, math.inf])
def test_a_white_of_no_light_refuses_rather_than_dividing_by_it(luminance: float) -> None:
    with pytest.raises(MeasurementRefused) as refusal:
        measured_lab((1.0, 1.0, 1.0), luminance)
    assert "no light" in str(refusal.value)


def test_scaling_is_what_makes_the_answer_independent_of_brightness() -> None:
    reading = (0.95047, 1.0, 1.08883)

    dim = measured_lab(reading, 1.0)
    bright = measured_lab(tuple(value * 3.0 for value in reading), 3.0)

    assert dim == pytest.approx(bright, abs=1e-9)
