"""An EDID-built panel reports what EDID carries, and nothing else.

``create_from_edid`` is the fallback for a display that is not in the panel
database. EDID chromaticity gives primaries, a white point and a gamma byte. It
gives no photometry, and ``parse_edid`` does not read the CTA extension blocks
that would carry HDR static metadata, so the characterization has no evidence
for peak brightness, black level, contrast or HDR support.

Those four fields were filled in anyway, the same values for every display:
250 cd/m2 SDR peak, 400 cd/m2 HDR peak, a 0.1 cd/m2 black and 1000:1 contrast,
with ``hdr_capable`` copied from the gamut flag. Wide gamut is not HDR; a P3
SDR monitor is one and not the other. The numbers are not cosmetic. The SDR
peak divides the target luminance to produce the DDC/CI brightness byte written
to the monitor, and the black level picks the contrast byte beside it, so a
display that was never measured had its hardware driven from a constant.

The correction matrix had the same problem in a different form. It was built
from the distance of each primary to its sRGB counterpart times a fixed
coefficient, and the diagonal grew with that distance, so a panel whose red is
already more saturated than sRGB red was told to drive red harder. The matrix
is multiplied into linear RGB in ``per_display_calibration`` on the way to the
LUT loaded into the GPU. NeuraLux already knew not to trust it and recomputes
its own from the primaries, noting that stored matrices "may be incorrect".

Both are now derived or left unknown. The matrix follows from the
chromaticities by the standard route, and the four capability fields report
zero, which every consumer here reads as not known.

Honest null: the DDC/CI apply path is not exercised. ``_apply_ddc_corrections``
opens a real monitor connection, and the repo's instructions treat DDC/CI as
side-effecting code that routine test runs do not touch. These tests pin the
computation that feeds it, so no brightness or black-level byte is derived from
an unknown quantity in the first place.

PRODUCT.md: the interface must never convert modeled, simulated, replayed, or
placeholder values into apparent instrument observations.
"""

from __future__ import annotations

import numpy as np
import pytest

from calibrate_pro.calibration import multi_display
from calibrate_pro.core.color_math import primaries_to_xyz_matrix
from calibrate_pro.panels.database import PanelCharacterization, create_from_edid, get_database
from calibrate_pro.sensorless.auto_calibration import AutoCalibrationEngine, CalibrationTarget

SRGB_EDID = {
    "red": (0.6400, 0.3300),
    "green": (0.3000, 0.6000),
    "blue": (0.1500, 0.0600),
    "white": (0.3127, 0.3290),
}

P3_EDID = {
    "red": (0.6800, 0.3200),
    "green": (0.2650, 0.6900),
    "blue": (0.1500, 0.0600),
    "white": (0.3127, 0.3290),
}


def _xy(xyz: np.ndarray) -> tuple[float, float]:
    """Chromaticity of an XYZ triple."""
    total = float(xyz.sum())
    return float(xyz[0]) / total, float(xyz[1]) / total


# -------------------------------------------------------------------------
# The capability fields report "not known"
# -------------------------------------------------------------------------


@pytest.mark.parametrize("edid", [SRGB_EDID, P3_EDID], ids=["srgb", "p3"])
@pytest.mark.parametrize(
    "field",
    ["max_luminance_sdr", "max_luminance_hdr", "min_luminance", "native_contrast"],
)
def test_no_photometry_is_reported_for_an_edid_built_panel(edid, field):
    """EDID chromaticity carries no luminance and no contrast."""
    caps = create_from_edid(edid).capabilities

    assert getattr(caps, field) == 0.0


def test_a_wide_gamut_panel_is_not_reported_hdr_capable():
    """The gamut flag used to be copied into hdr_capable. They are different claims."""
    panel = create_from_edid(P3_EDID)

    assert panel.capabilities.wide_gamut is True
    assert panel.capabilities.hdr_capable is False


def test_the_gamut_is_still_read_from_the_primaries():
    """Gamut does follow from EDID, so it is kept. The primaries are the evidence."""
    assert create_from_edid(P3_EDID).capabilities.wide_gamut is True
    assert create_from_edid(SRGB_EDID).capabilities.wide_gamut is False


def test_the_notes_say_what_is_unknown():
    """A reader of the profile is told which fields carry no evidence."""
    notes = create_from_edid(P3_EDID).notes.lower()

    assert "unknown" in notes
    assert "gamma assumed" in notes


def test_a_database_panel_still_reports_its_measured_photometry():
    """The fix is about invented values, not about dropping the panel database."""
    panel = get_database().get_panel("AW3423DW")

    assert panel is not None
    assert panel.capabilities.max_luminance_hdr > 0.0
    assert panel.capabilities.max_luminance_sdr > 0.0


# -------------------------------------------------------------------------
# The correction matrix is derived from the primaries
# -------------------------------------------------------------------------


def test_a_panel_with_srgb_primaries_needs_no_correction():
    """Nothing to correct means the identity, and it falls out of the derivation."""
    matrix = np.array(create_from_edid(SRGB_EDID).color_correction_matrix)

    assert matrix == pytest.approx(np.eye(3), abs=1e-9)


@pytest.mark.parametrize(
    ("channel", "signal", "expected_xy"),
    [
        ("red", (1.0, 0.0, 0.0), (0.6400, 0.3300)),
        ("green", (0.0, 1.0, 0.0), (0.3000, 0.6000)),
        ("blue", (0.0, 0.0, 1.0), (0.1500, 0.0600)),
        ("white", (1.0, 1.0, 1.0), (0.3127, 0.3290)),
    ],
)
def test_corrected_srgb_signal_reproduces_srgb_on_a_wide_gamut_panel(channel, signal, expected_xy):
    """The decisive check: drive the panel through the matrix and measure where it lands.

    An sRGB primary sent through the correction matrix becomes a native drive
    triple. Pushing that triple through the panel's own primaries gives the XYZ
    the display would emit, and it must land on the sRGB primary that was asked
    for. The matrix this replaced misses every one of these.
    """
    matrix = np.array(create_from_edid(P3_EDID).color_correction_matrix)
    native_to_xyz = primaries_to_xyz_matrix(P3_EDID["red"], P3_EDID["green"], P3_EDID["blue"], P3_EDID["white"])

    emitted = native_to_xyz @ (matrix @ np.array(signal))

    assert _xy(emitted) == pytest.approx(expected_xy, abs=1e-6)


def test_a_wider_primary_is_driven_down_not_up():
    """Direction check, independent of the round trip.

    A panel whose red is more saturated than sRGB red must use less than a full
    red drive to hit sRGB red. The replaced matrix scaled the diagonal up with
    the distance from sRGB, which is the opposite.
    """
    matrix = np.array(create_from_edid(P3_EDID).color_correction_matrix)

    assert matrix[0][0] < 1.0


def test_white_stays_neutral_through_the_correction():
    """Equal drive in, equal drive out: the matrix must not tint the white point."""
    matrix = np.array(create_from_edid(P3_EDID).color_correction_matrix)

    assert matrix @ np.ones(3) == pytest.approx(np.ones(3), abs=1e-9)


@pytest.mark.parametrize(
    ("name", "edid"),
    [
        (
            "collinear primaries",
            {
                "red": (0.3000, 0.3000),
                "green": (0.3000, 0.3000),
                "blue": (0.3000, 0.3000),
                "white": (0.3127, 0.3290),
            },
        ),
        (
            "a primary on y=0",
            {
                "red": (0.6400, 0.0000),
                "green": (0.3000, 0.6000),
                "blue": (0.1500, 0.0600),
                "white": (0.3127, 0.3290),
            },
        ),
    ],
)
def test_degenerate_primaries_yield_no_matrix_rather_than_a_wrong_one(name, edid):
    """No matrix is available, and None says so. Identity would claim otherwise."""
    panel = create_from_edid(edid)

    assert isinstance(panel, PanelCharacterization)
    assert panel.color_correction_matrix is None


# -------------------------------------------------------------------------
# Consumers read zero as "not known"
# -------------------------------------------------------------------------


def test_no_ddc_brightness_is_computed_from_an_unknown_peak():
    """The brightness byte is a percentage of the panel's peak. Without one, none."""
    corrections = AutoCalibrationEngine()._calculate_corrections(create_from_edid(P3_EDID), CalibrationTarget())

    assert corrections["ddc_brightness"] is None


def test_an_unknown_black_level_is_not_read_as_an_oled():
    """Zero marks "not known", not a perfect black, so it takes the LCD setting."""
    corrections = AutoCalibrationEngine()._calculate_corrections(create_from_edid(P3_EDID), CalibrationTarget())

    assert corrections["panel_min_luminance"] == 0.0
    assert corrections["ddc_contrast"] == 75


def test_a_database_panel_still_gets_a_brightness_and_an_oled_contrast():
    """The guard must not disable the path for a panel that was measured."""
    panel = get_database().get_panel("AW3423DW")
    assert panel is not None
    assert panel.capabilities.min_luminance < 0.01, "AW3423DW is the OLED case"

    corrections = AutoCalibrationEngine()._calculate_corrections(panel, CalibrationTarget())

    assert isinstance(corrections["ddc_brightness"], int)
    assert 0 <= corrections["ddc_brightness"] <= 100
    assert corrections["ddc_contrast"] == 85


def _entry(index: int, name: str, panel) -> dict:
    return {"index": index, "name": name, "panel": panel}


def test_matching_a_display_with_no_known_peak_does_not_divide_by_zero():
    """Every peak unknown: the shared target is the default, and the plan says so."""
    result = multi_display.analyze_matching([_entry(0, "EDID display", create_from_edid(P3_EDID))])

    assert result.matched_luminance == multi_display.DEFAULT_MATCHED_LUMINANCE
    assert result.per_display[0].brightness_adjustment is None
    assert any("No display reports a peak brightness" in note for note in result.notes)


def test_a_display_with_no_known_peak_does_not_constrain_the_others():
    """A measured display still sets the target; the unmeasured one is noted."""
    measured = get_database().get_panel("AW3423DW")
    assert measured is not None

    result = multi_display.analyze_matching(
        [_entry(0, "AW3423DW", measured), _entry(1, "EDID display", create_from_edid(P3_EDID))]
    )

    assert result.matched_luminance == pytest.approx(measured.capabilities.max_luminance_sdr * 0.8)
    assert result.per_display[0].brightness_adjustment is not None
    assert result.per_display[1].brightness_adjustment is None
    assert any("do not constrain" in note for note in result.notes)
