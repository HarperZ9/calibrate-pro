"""The two characterization records refuse impossible values at construction.

``declared_from`` and the instrument run are the front doors, and both produce
valid records. These gates build each record by hand with values a front door
refuses, because a record that can exist in a state the module calls impossible
makes every guarantee depend on the caller having used the front door.

Nothing here opens a display or an instrument.
"""

from __future__ import annotations

from dataclasses import replace

import pytest

from calibrate_pro.application.declaration import DeclarationRefused, DeclaredCharacterization
from calibrate_pro.application.measurement import MeasuredCharacterization, MeasurementRefused
from calibrate_pro.panels.database import get_database
from tests.test_edid_session import _declaration, _measurement

GOOD_DECLARED = _declaration()
GOOD_MEASURED = _measurement()


def test_control_the_records_the_front_doors_build_still_construct() -> None:
    assert replace(GOOD_DECLARED) == GOOD_DECLARED
    assert replace(GOOD_MEASURED) == GOOD_MEASURED


def test_a_provenance_naming_a_unit_is_refused_because_it_no_longer_matches_the_record() -> None:
    with pytest.raises(DeclarationRefused, match="provenance"):
        replace(GOOD_DECLARED, provenance="edid:ACM1234 WideVision 27 SN-UNIT-90210")


@pytest.mark.parametrize("provenance", ["panel-database:AW3423DW", "edid:", "edid:   ", "ACM1234"])
def test_a_provenance_that_is_not_a_declaration_is_refused(provenance: str) -> None:
    with pytest.raises(DeclarationRefused):
        replace(GOOD_DECLARED, provenance=provenance)


def test_collapsed_primaries_with_an_absurd_gamma_are_refused_in_the_products_words() -> None:
    with pytest.raises(DeclarationRefused) as refusal:
        replace(
            GOOD_DECLARED,
            red_xy=(0.5, 0.5),
            green_xy=(0.5, 0.5),
            blue_xy=(0.5, 0.5),
            gamma=99.0,
        )
    assert "too little to be three separate colours" in str(refusal.value)


def test_an_absurd_gamma_alone_is_refused_by_name() -> None:
    with pytest.raises(DeclarationRefused, match="gamma"):
        replace(GOOD_DECLARED, gamma=99.0)


@pytest.mark.parametrize("gamma", [float("nan"), float("inf"), 0.5, 4.5])
def test_a_gamma_outside_the_band_or_not_finite_is_refused(gamma: float) -> None:
    with pytest.raises(DeclarationRefused, match="gamma"):
        replace(GOOD_DECLARED, gamma=gamma)


@pytest.mark.parametrize("corner", ["red_xy", "green_xy", "blue_xy", "white_xy"])
@pytest.mark.parametrize("pair", [(float("nan"), 0.3), (0.3, float("inf"))])
def test_a_corner_that_is_not_finite_is_refused(corner: str, pair: tuple[float, float]) -> None:
    with pytest.raises(DeclarationRefused, match="finite"):
        replace(GOOD_DECLARED, **{corner: pair})


def test_declared_numbers_that_disagree_with_the_panel_record_are_refused() -> None:
    with pytest.raises(DeclarationRefused, match="panel"):
        replace(GOOD_DECLARED, red_xy=(0.70, 0.29))


def test_a_declaration_without_a_panel_record_is_refused() -> None:
    with pytest.raises(TypeError):
        replace(GOOD_DECLARED, panel=None)


def test_a_degenerate_declaration_never_reaches_the_engine() -> None:
    """The refusal comes at construction, so the generator is never handed a singular gamut."""
    with pytest.raises(DeclarationRefused):
        DeclaredCharacterization(
            panel=get_database().get_fallback(),
            provenance="edid:ACM1234 Example Monitor",
            red_xy=(0.5, 0.5),
            green_xy=(0.5, 0.5),
            blue_xy=(0.5, 0.5),
            white_xy=(0.3127, 0.3290),
            gamma=99.0,
        )


MEASURED_BAD = [
    ("instrument", ""),
    ("instrument", "   "),
    ("instrument", 7),
    ("steps", 3),
    ("steps", 6),
    ("steps", 5.0),
    ("patch_count", 0),
    ("white_luminance", float("nan")),
    ("white_luminance", 0.1),
    ("black_luminance", -1.0),
    ("black_luminance", float("inf")),
    ("contrast_ratio", 0.0),
    ("contrast_ratio", float("nan")),
    ("white_xy", (float("nan"), 0.3)),
    ("white_xy", (0.3,)),
    ("gamma", (2.2, 2.2)),
    ("gamma", (2.2, 2.2, 0.5)),
    ("gamma", (2.2, float("nan"), 2.2)),
    ("gamma", (2.2, 2.2, 4.5)),
    ("patch_geometry", ""),
]


@pytest.mark.parametrize(("field_name", "value"), MEASURED_BAD, ids=[f"{n}={v!r}" for n, v in MEASURED_BAD])
def test_a_measured_record_with_a_value_the_run_refuses_is_refused(field_name: str, value: object) -> None:
    with pytest.raises(MeasurementRefused):
        replace(GOOD_MEASURED, **{field_name: value})


def test_a_measured_record_whose_panel_primaries_collapse_is_refused() -> None:
    from calibrate_pro.panels.panel_types import ChromaticityCoord, PanelPrimaries

    point = ChromaticityCoord(0.5, 0.5)
    collapsed = replace(
        GOOD_MEASURED.panel,
        native_primaries=PanelPrimaries(red=point, green=point, blue=point, white=point),
    )
    with pytest.raises(MeasurementRefused, match="three separate colours"):
        replace(GOOD_MEASURED, panel=collapsed)


def test_a_measured_record_may_report_an_unknown_contrast() -> None:
    assert replace(GOOD_MEASURED, black_luminance=0.0, contrast_ratio=None).contrast_ratio is None


def test_the_type_of_the_measured_record_is_unchanged() -> None:
    assert type(GOOD_MEASURED) is MeasuredCharacterization
