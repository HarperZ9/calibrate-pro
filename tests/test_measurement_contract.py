"""What a measurement run has to be true of before it may claim a display.

The synthetic display here is arithmetic, and it is used the one way a fake is
allowed to be used in this suite: to check that a run recovers the numbers it
was given. Nothing in this file stands in for a colorimeter's accuracy, and no
test here says a real instrument would produce these values.

The controls at the end are the point of the module. Each one drives a run that
the underlying characterization routine happily turns into a well-formed
profile, and asserts the contract refused it.
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from calibrate_pro.application.measurement import (
    DEFAULT_RAMP_STEPS,
    MINIMUM_RAMP_STEPS,
    MINIMUM_WHITE_LUMINANCE,
    MeasurementRefused,
    NoPatchPort,
    characterization_from,
    measure_characterization,
)
from calibrate_pro.calibration.native_loop import profile_display
from calibrate_pro.panels.panel_types import PanelCharacterization
from tests.measurement_support import (
    D65,
    NARROW_PRIMARIES,
    WIDE_PRIMARIES,
    SyntheticDisplay,
    base_panel,
)


def run(display: SyntheticDisplay, *, base: PanelCharacterization | None = None, steps: int = DEFAULT_RAMP_STEPS):
    """Drive one measurement against a synthetic display, settling instantly."""
    return measure_characterization(
        instrument=display,
        patches=display,
        base=base if base is not None else base_panel(),
        steps=steps,
        settle=lambda: display.events.append("settle"),
    )


# What a run recovers ------------------------------------------------------


def test_the_measured_primaries_are_the_ones_the_display_emitted() -> None:
    display = SyntheticDisplay()
    measured = run(display).panel.native_primaries
    for coordinate, expected in (
        (measured.red, WIDE_PRIMARIES[0]),
        (measured.green, WIDE_PRIMARIES[1]),
        (measured.blue, WIDE_PRIMARIES[2]),
        (measured.white, D65),
    ):
        assert coordinate.x == pytest.approx(expected[0], abs=1e-6)
        assert coordinate.y == pytest.approx(expected[1], abs=1e-6)


def test_the_measured_gamma_is_the_one_the_display_emitted() -> None:
    display = SyntheticDisplay(gamma=(2.05, 2.35, 2.50))
    result = run(display)
    assert result.gamma == pytest.approx((2.05, 2.35, 2.50), abs=1e-9)
    panel = result.panel
    assert (panel.gamma_red.gamma, panel.gamma_green.gamma, panel.gamma_blue.gamma) == pytest.approx(
        (2.05, 2.35, 2.50), abs=1e-9
    )


def test_white_and_black_are_reported_as_the_instrument_would_read_them() -> None:
    display = SyntheticDisplay(white_luminance=180.0, black_luminance=0.2)
    result = run(display)
    assert result.white_luminance == pytest.approx(180.2, abs=1e-6)
    assert result.black_luminance == pytest.approx(0.2, abs=1e-6)
    assert result.panel.capabilities.max_luminance_sdr == pytest.approx(180.2, abs=1e-6)
    assert result.panel.capabilities.min_luminance == pytest.approx(0.2, abs=1e-6)


def test_contrast_is_measured_white_over_measured_black() -> None:
    display = SyntheticDisplay(white_luminance=200.0, black_luminance=0.25)
    result = run(display)
    assert result.contrast_ratio == pytest.approx(200.25 / 0.25, rel=1e-9)
    assert result.panel.capabilities.native_contrast == pytest.approx(200.25 / 0.25, rel=1e-9)


def test_a_black_that_read_as_zero_reports_no_contrast_and_keeps_the_declared_one() -> None:
    display = SyntheticDisplay(black_luminance=0.0)
    result = run(display, base=base_panel(native_contrast=1_500_000.0))
    assert result.black_luminance == 0.0
    assert result.contrast_ratio is None
    assert result.panel.capabilities.native_contrast == 1_500_000.0


def test_every_patch_is_shown_and_settled_before_it_is_read() -> None:
    display = SyntheticDisplay()
    run(display, steps=5)
    assert display.events[:6] == [
        "show(0.0, 0.0, 0.0)",
        "settle",
        "read",
        "show(0.25, 0.25, 0.25)",
        "settle",
        "read",
    ]
    assert display.events.count("read") == 20


def test_the_run_measures_four_ramps_of_the_requested_length() -> None:
    display = SyntheticDisplay()
    result = run(display, steps=9)
    assert result.steps == 9
    assert result.patch_count == 36
    assert len(display.shown) == 36
    assert display.reads == 36


def test_the_run_leaves_both_ports_open_for_its_caller_to_close() -> None:
    display = SyntheticDisplay()
    run(display, steps=5)
    assert display.closed == 0


def test_the_summary_names_the_instrument_and_what_it_read() -> None:
    display = SyntheticDisplay(white_luminance=120.0, black_luminance=0.0, gamma=(2.2, 2.2, 2.2))
    summary = run(display, steps=5).summary
    assert summary == (
        "SyntheticDisplay probe (SN-0): 20 patches, white 120.0 cd/m2, gamma 2.20/2.20/2.20, full-field patches"
    )


def test_the_patch_geometry_the_port_reported_is_what_the_result_carries() -> None:
    """An OLED peak depends on the patch size, so the number needs it beside it."""
    display = SyntheticDisplay(geometry="10% window on black")
    result = run(display, steps=5)
    assert result.patch_geometry == "10% window on black"
    assert "10% window on black" in result.summary


# What a run carries over rather than inventing -----------------------------


def test_fields_no_patch_ramp_covers_keep_the_detected_record_they_came_from() -> None:
    display = SyntheticDisplay()
    base = base_panel()
    panel = run(display, base=base).panel
    assert panel.manufacturer == "Test Manufacturing"
    assert panel.model_pattern == "TM-0000"
    assert panel.panel_type == "QD-OLED"
    assert panel.display_name == "Test Manufacturing TM-0000"
    assert panel.ddc is base.ddc
    assert panel.capabilities.bit_depth == 10
    assert panel.capabilities.vrr_capable is True
    assert panel.capabilities.max_luminance_hdr == 1000.0


def test_the_declared_correction_matrix_is_dropped_rather_than_applied_twice() -> None:
    display = SyntheticDisplay()
    base = base_panel()
    assert base.color_correction_matrix is not None
    assert run(display, base=base).panel.color_correction_matrix is None


def test_wide_gamut_follows_the_measured_red_rather_than_the_declared_flag() -> None:
    wide = run(SyntheticDisplay(primaries=WIDE_PRIMARIES), base=base_panel(wide_gamut=False))
    narrow = run(SyntheticDisplay(primaries=NARROW_PRIMARIES), base=base_panel(wide_gamut=True))
    assert wide.panel.capabilities.wide_gamut is True
    assert narrow.panel.capabilities.wide_gamut is False


def test_the_detected_record_is_left_as_it_was_found() -> None:
    display = SyntheticDisplay()
    base = base_panel()
    run(display, base=base)
    assert base.capabilities.max_luminance_sdr == 1.0
    assert base.gamma_red.gamma == 1.80
    assert base.color_correction_matrix == [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]]


# False-success controls ----------------------------------------------------


def test_an_instrument_that_stops_answering_refuses_instead_of_profiling_black() -> None:
    """The routine underneath reads a failed measurement as a black patch.

    A run that lost its sensor halfway would otherwise finish, and every patch
    after the failure would report a display emitting no light at all.
    """
    display = SyntheticDisplay(fails_at=20)
    with pytest.raises(MeasurementRefused) as refusal:
        run(display, steps=17)
    assert "stopped answering" in str(refusal.value)
    assert len(display.shown) == 21, "the run kept showing patches after the instrument failed"


def test_a_dead_channel_refuses_rather_than_reporting_a_textbook_gamma() -> None:
    """The gamma estimate answers 2.2 when a ramp carries no usable midpoint.

    This test drives the underlying routine first and asserts it produces that
    number, so the refusal below is measured against the wrong answer it
    prevents rather than against nothing.
    """
    display = SyntheticDisplay(dead_channels=(0,))
    profile = profile_display(
        lambda r, g, b: np.array(display.emit((r, g, b))),
        lambda r, g, b: None,
        n_steps=17,
    )
    assert profile.gamma_r == 2.2, "the underlying estimate no longer reports its fallback"

    with pytest.raises(MeasurementRefused) as refusal:
        run(SyntheticDisplay(dead_channels=(0,)))
    assert "red ramp carried no usable midpoint" in str(refusal.value)


def test_three_channels_that_emit_nearly_one_colour_refuse_as_a_degenerate_gamut() -> None:
    crowded = ((0.3400, 0.3300), (0.3000, 0.3300), (0.3200, 0.3600))
    with pytest.raises(MeasurementRefused) as refusal:
        run(SyntheticDisplay(primaries=crowded, white=(0.3200, 0.3400)))
    assert "too little to be three separate colours" in str(refusal.value)


def test_a_display_too_dim_to_clear_the_floor_refuses() -> None:
    display = SyntheticDisplay(white_luminance=MINIMUM_WHITE_LUMINANCE / 2.0, black_luminance=0.0)
    with pytest.raises(MeasurementRefused) as refusal:
        run(display)
    assert "below the" in str(refusal.value)


def test_a_gamma_outside_the_band_a_display_responds_in_refuses() -> None:
    with pytest.raises(MeasurementRefused) as refusal:
        run(SyntheticDisplay(gamma=(2.2, 2.2, 6.0)))
    assert "blue gamma measured" in str(refusal.value)


def test_a_session_with_no_patch_window_refuses_before_it_reads_anything() -> None:
    display = SyntheticDisplay()
    with pytest.raises(MeasurementRefused) as refusal:
        measure_characterization(
            instrument=display,
            patches=NoPatchPort(),
            base=base_panel(),
            steps=5,
            settle=lambda: None,
        )
    assert "without a patch window" in str(refusal.value)
    assert display.reads == 0


# What a run refuses to start ----------------------------------------------


@pytest.mark.parametrize("steps", [0, 1, 3, MINIMUM_RAMP_STEPS - 1, -5])
def test_a_ramp_shorter_than_the_minimum_refuses(steps: int) -> None:
    display = SyntheticDisplay()
    with pytest.raises(MeasurementRefused) as refusal:
        run(display, steps=steps)
    assert f"at least {MINIMUM_RAMP_STEPS} steps" in str(refusal.value)
    assert display.shown == []


@pytest.mark.parametrize("steps", [6, 16, 32])
def test_an_even_ramp_refuses_because_no_patch_lands_at_half_signal(steps: int) -> None:
    display = SyntheticDisplay()
    with pytest.raises(MeasurementRefused) as refusal:
        run(display, steps=steps)
    assert "odd step count" in str(refusal.value)
    assert display.shown == []


@pytest.mark.parametrize("steps", [True, 17.0, "17", None])
def test_a_step_count_that_is_not_an_exact_integer_refuses(steps: object) -> None:
    display = SyntheticDisplay()
    with pytest.raises(MeasurementRefused):
        run(display, steps=steps)  # type: ignore[arg-type]
    assert display.shown == []


# The conversion on its own -------------------------------------------------


def test_the_conversion_reports_the_same_panel_the_run_does() -> None:
    display = SyntheticDisplay()
    result = run(display, steps=9)
    replay = SyntheticDisplay(
        primaries=display.primaries,
        white=display.white,
        white_luminance=display.white_luminance,
        black_luminance=display.black_luminance,
        gamma=display.gamma,
    )
    profile = profile_display(
        lambda r, g, b: np.array(replay.emit((r, g, b))),
        lambda r, g, b: None,
        n_steps=9,
    )
    direct = characterization_from(base_panel(), profile)
    assert direct.native_primaries.red.x == pytest.approx(result.panel.native_primaries.red.x, abs=1e-12)
    assert direct.gamma_green.gamma == pytest.approx(result.panel.gamma_green.gamma, abs=1e-12)
    assert direct.capabilities.max_luminance_sdr == pytest.approx(result.white_luminance, abs=1e-12)
    assert math.isfinite(direct.capabilities.native_contrast)
