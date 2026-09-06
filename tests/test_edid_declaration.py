"""What a display declares about itself, and what the engine refuses to build from it.

``calibrate_pro.application.declaration`` turns one EDID descriptor into a panel
record. The descriptor is a claim by the manufacturer about a model, not a
reading of the unit on the desk, so every check in that module exists to stop a
claim that describes nothing from becoming a correction matrix an operator
would then trust.

Nothing here opens a display, reads a registry, talks to a colorimeter, loads a
LUT or writes a profile. Every declaration is an in-memory contract object, and
the only record read off disk is the generic sRGB fallback the shipped panel
database already holds.

Two classes are named ``PanelCharacterization``. The application contract in
``application/contracts.py`` carries xy pairs as decimal strings, and the panel
record in ``panels/panel_types.py`` carries floats. ``declared_from`` takes one
of each, in that order, and the type check it opens with is tested here because
handing it the wrong one is the mistake the two names invite.
"""

from __future__ import annotations

from dataclasses import replace

import pytest

from calibrate_pro.application.contracts import CharacterizationKind
from calibrate_pro.application.contracts import PanelCharacterization as DeclaredContract
from calibrate_pro.application.declaration import (
    DECLARATION_NOTE,
    DeclarationRefused,
    declared_from,
    declared_label,
)
from calibrate_pro.application.detection import EDID_PROVENANCE_PREFIX
from calibrate_pro.application.measurement import (
    MAXIMUM_GAMMA,
    MINIMUM_GAMMA,
    MINIMUM_GAMUT_AREA,
    WIDE_GAMUT_RED_X,
)
from calibrate_pro.panels.panel_types import PanelCharacterization as PanelRecord
from tests.measurement_support import base_panel

#: The provenance detection writes for one display, in the shape it writes it.
PROVENANCE = "edid:DEL4231 UltraSharp U2723QE"

#: A P3-shaped declaration. The red x sits above the wide-gamut threshold, and
#: the triangle encloses far more than the minimum area, so this set reaches the
#: builder rather than a refusal.
DECLARED_RED = ("0.6800", "0.3200")
DECLARED_GREEN = ("0.2650", "0.6900")
DECLARED_BLUE = ("0.1500", "0.0600")
DECLARED_WHITE = ("0.3127", "0.3290")
DECLARED_GAMMA = "2.4000"


def _contract(**overrides: object) -> DeclaredContract:
    """A complete declaration the contract itself accepts, with fields replaced.

    Used for every case the contract's own validation lets through, so the test
    exercises an object a real detection run could have produced.
    """
    fields: dict[str, object] = {
        "kind": CharacterizationKind.EDID_DECLARED,
        "provenance": PROVENANCE,
        "red_xy": DECLARED_RED,
        "green_xy": DECLARED_GREEN,
        "blue_xy": DECLARED_BLUE,
        "white_xy": DECLARED_WHITE,
        "nominal_gamma": DECLARED_GAMMA,
    }
    fields.update(overrides)
    return DeclaredContract(**fields)  # type: ignore[arg-type]


def _unchecked_contract(**overrides: object) -> DeclaredContract:
    """The same declaration, built without the contract's own validation.

    The contract refuses a missing corner, a corner that is not a number and an
    absent gamma in ``__post_init__``, so those values cannot reach
    ``declared_from`` through the constructor. ``declared_from`` repeats the
    checks anyway because it is a public seam, and this is how the repeated
    checks are reached. The instance is a real ``DeclaredContract`` and not a
    subclass, because the builder's first line rejects anything else.
    """
    fields: dict[str, object] = {
        "kind": CharacterizationKind.EDID_DECLARED,
        "provenance": PROVENANCE,
        "red_xy": DECLARED_RED,
        "green_xy": DECLARED_GREEN,
        "blue_xy": DECLARED_BLUE,
        "white_xy": DECLARED_WHITE,
        "nominal_gamma": DECLARED_GAMMA,
    }
    fields.update(overrides)
    contract = object.__new__(DeclaredContract)
    for name, value in fields.items():
        object.__setattr__(contract, name, value)
    return contract


def _primaries(red: tuple[str, str], *, green: tuple[str, str] = DECLARED_GREEN) -> dict[str, object]:
    """Override set placing one red corner on an otherwise ordinary triangle."""
    return {"red_xy": red, "green_xy": green}


# What the label carries ----------------------------------------------------


def test_a_provenance_that_names_a_product_splits_into_vendor_and_that_name() -> None:
    assert declared_label("edid:DEL4231 UltraSharp U2723QE") == ("DEL", "UltraSharp U2723QE")


def test_a_provenance_with_no_product_name_falls_back_to_the_product_code() -> None:
    # No space, so nothing follows the stem and the four product-code characters
    # after the three-character vendor code become the model.
    assert declared_label("edid:DEL4231") == ("DEL", "4231")


def test_a_stem_shorter_than_the_vendor_code_is_returned_whole_as_the_model() -> None:
    # ``stem[3:]`` is empty here, so the last fallback in the chain returns the
    # stem itself rather than an empty model a record would then be keyed under.
    assert declared_label("edid:AB") == ("AB", "AB")


def test_surrounding_whitespace_is_stripped_before_the_prefix_is_checked() -> None:
    assert declared_label("  edid:DEL4231 UltraSharp  ") == ("DEL", "UltraSharp")


def test_a_product_name_keeps_its_inner_spaces_and_loses_its_outer_ones() -> None:
    assert declared_label("edid:SAM7001    Odyssey G7 34   ") == ("SAM", "Odyssey G7 34")


@pytest.mark.parametrize("provenance", ["vesa:DEL4231", "DEL4231", "EDID:DEL4231", "detector:no_panel_match"])
def test_a_provenance_without_the_edid_prefix_refuses(provenance: str) -> None:
    with pytest.raises(DeclarationRefused) as refusal:
        declared_label(provenance)
    assert f"must start with {EDID_PROVENANCE_PREFIX!r}" in str(refusal.value)


@pytest.mark.parametrize("provenance", ["edid:", "edid:   ", "   edid:  "])
def test_a_provenance_that_names_no_display_refuses(provenance: str) -> None:
    with pytest.raises(DeclarationRefused) as refusal:
        declared_label(provenance)
    assert "must name the display that declared it" in str(refusal.value)


# What a declaration builds -------------------------------------------------


def test_the_declared_record_reports_the_numbers_the_descriptor_carried() -> None:
    declared = declared_from(base_panel(), _contract())
    assert declared.provenance == PROVENANCE
    assert declared.red_xy == (0.68, 0.32)
    assert declared.green_xy == (0.265, 0.69)
    assert declared.blue_xy == (0.15, 0.06)
    assert declared.white_xy == (0.3127, 0.329)
    assert declared.gamma == 2.4


def test_the_record_is_keyed_under_the_vendor_and_product_the_label_named() -> None:
    panel = declared_from(base_panel(), _contract()).panel
    assert panel.manufacturer == "DEL"
    assert panel.model_pattern == "UltraSharp U2723QE"
    assert panel.display_name == "UltraSharp U2723QE"
    assert panel.name == "DEL UltraSharp U2723QE"


def test_the_record_carries_the_declared_primaries_and_white_point() -> None:
    primaries = declared_from(base_panel(), _contract()).panel.native_primaries
    assert primaries.red.as_tuple() == (0.68, 0.32)
    assert primaries.green.as_tuple() == (0.265, 0.69)
    assert primaries.blue.as_tuple() == (0.15, 0.06)
    assert primaries.white.as_tuple() == (0.3127, 0.329)


def test_all_three_channel_curves_carry_the_one_declared_gamma() -> None:
    # A descriptor states one transfer characteristic, not three, so the three
    # per-channel curves are the same number and carry no offset the base record
    # may have held.
    panel = declared_from(base_panel(), _contract()).panel
    for curve in (panel.gamma_red, panel.gamma_green, panel.gamma_blue):
        assert curve.gamma == 2.4
        assert curve.offset == 0.0
        assert curve.linear_portion == 0.0


def test_each_channel_carries_its_own_curve_rather_than_one_shared_object() -> None:
    # ``GammaCurve`` is a mutable dataclass, so three names pointing at one
    # instance would make a correction written to red arrive on green and blue
    # as well. The three carry the same number here because the descriptor
    # states one, which is a different fact from the three being one object.
    panel = declared_from(base_panel(), _contract()).panel
    panel.gamma_red.gamma = 9.9
    assert panel.gamma_green.gamma == 2.4
    assert panel.gamma_blue.gamma == 2.4


def test_the_record_says_in_its_notes_that_it_is_a_declaration() -> None:
    assert declared_from(base_panel(), _contract()).panel.notes == DECLARATION_NOTE


def test_the_summary_names_the_source_and_every_declared_corner() -> None:
    declared = declared_from(base_panel(), _contract())
    assert declared.summary == (
        "edid:DEL4231 UltraSharp U2723QE: R 0.6800,0.3200 G 0.2650,0.6900 B 0.1500,0.0600 W 0.3127,0.3290, gamma 2.40"
    )


def test_building_a_declared_record_leaves_the_base_record_untouched() -> None:
    base = base_panel()
    declared_from(base, _contract())
    assert base.manufacturer == "Test Manufacturing"
    assert base.notes == ""
    assert base.color_correction_matrix == [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]]
    assert base.gamma_red.gamma == 1.80
    assert base.capabilities.wide_gamut is True
    assert base.native_primaries.red.as_tuple() == (0.5, 0.5)


# What a declaration refuses ------------------------------------------------


def test_the_panel_record_type_is_refused_where_the_contract_is_expected() -> None:
    # The two classes share a name. Handing the builder the panels-layer record
    # is the mistake that invites, and it is a TypeError rather than a refusal
    # because it is a wiring error and not a bad descriptor.
    base = base_panel()
    with pytest.raises(TypeError) as error:
        declared_from(base, base)  # type: ignore[arg-type]
    assert "must be an application PanelCharacterization" in str(error.value)
    assert isinstance(base, PanelRecord)


def test_a_subclass_of_the_contract_is_refused_because_the_check_is_exact() -> None:
    class RelaxedContract(DeclaredContract):
        pass

    impostor = RelaxedContract(
        kind=CharacterizationKind.EDID_DECLARED,
        provenance=PROVENANCE,
        red_xy=DECLARED_RED,
        green_xy=DECLARED_GREEN,
        blue_xy=DECLARED_BLUE,
        white_xy=DECLARED_WHITE,
        nominal_gamma=DECLARED_GAMMA,
    )
    with pytest.raises(TypeError) as error:
        declared_from(base_panel(), impostor)
    assert "must be an application PanelCharacterization" in str(error.value)


def test_no_characterization_at_all_is_refused_as_a_type_error() -> None:
    with pytest.raises(TypeError) as error:
        declared_from(base_panel(), None)  # type: ignore[arg-type]
    assert "must be an application PanelCharacterization" in str(error.value)


@pytest.mark.parametrize(
    "kind",
    [
        CharacterizationKind.MATCHED,
        CharacterizationKind.EXPLICIT_GENERIC,
        CharacterizationKind.MEASURED,
    ],
)
def test_a_kind_that_is_not_a_declaration_refuses(kind: CharacterizationKind) -> None:
    with pytest.raises(DeclarationRefused) as refusal:
        declared_from(base_panel(), _contract(kind=kind, provenance=f"panel:{kind.value}"))
    assert "only an EDID_DECLARED characterization describes a declaration" in str(refusal.value)


def test_an_unknown_characterization_refuses_before_its_absent_numbers_are_read() -> None:
    unknown = DeclaredContract(
        kind=CharacterizationKind.UNKNOWN,
        provenance="detector:no_panel_match",
        red_xy=None,
        green_xy=None,
        blue_xy=None,
        white_xy=None,
        nominal_gamma=None,
    )
    with pytest.raises(DeclarationRefused) as refusal:
        declared_from(base_panel(), unknown)
    assert "only an EDID_DECLARED characterization describes a declaration" in str(refusal.value)


@pytest.mark.parametrize("corner", ["red", "green", "blue", "white"])
def test_a_missing_chromaticity_corner_refuses_and_names_the_corner(corner: str) -> None:
    with pytest.raises(DeclarationRefused) as refusal:
        declared_from(base_panel(), _unchecked_contract(**{f"{corner}_xy": None}))
    assert str(refusal.value) == f"the declaration carried no {corner} chromaticity"


@pytest.mark.parametrize("pair", [("banana", "0.3300"), ("0.6400", ""), ("0.64", "0.33", "0.01"), (0.64, None)])
def test_a_corner_that_is_not_a_pair_of_numbers_refuses(pair: object) -> None:
    with pytest.raises(DeclarationRefused) as refusal:
        declared_from(base_panel(), _unchecked_contract(green_xy=pair))
    assert str(refusal.value) == "the declared green chromaticity was not a pair of numbers"


@pytest.mark.parametrize("pair", [("nan", "0.3300"), ("inf", "0.3300"), ("0.6400", "-inf")])
def test_a_corner_that_is_not_finite_refuses(pair: tuple[str, str]) -> None:
    with pytest.raises(DeclarationRefused) as refusal:
        declared_from(base_panel(), _unchecked_contract(blue_xy=pair))
    assert str(refusal.value) == "the declared blue chromaticity was not finite"


def test_three_primaries_at_the_same_point_refuse_because_they_enclose_nothing() -> None:
    collapsed = _contract(
        red_xy=("0.3000", "0.3000"),
        green_xy=("0.3000", "0.3000"),
        blue_xy=("0.3000", "0.3000"),
    )
    with pytest.raises(DeclarationRefused) as refusal:
        declared_from(base_panel(), collapsed)
    assert "the declared primaries enclose 0.0000" in str(refusal.value)
    assert "too little to be three separate colours" in str(refusal.value)


def test_a_triangle_just_under_the_minimum_area_refuses_and_prints_the_area() -> None:
    # 0.4 wide and 0.04 tall, so the area is 0.008 against a floor of 0.01.
    thin = _contract(
        red_xy=("0.1000", "0.1000"),
        green_xy=("0.5000", "0.1000"),
        blue_xy=("0.1000", "0.1400"),
    )
    with pytest.raises(DeclarationRefused) as refusal:
        declared_from(base_panel(), thin)
    assert "the declared primaries enclose 0.0080" in str(refusal.value)
    assert MINIMUM_GAMUT_AREA > 0.008


def test_a_gamma_the_descriptor_never_stated_refuses() -> None:
    with pytest.raises(DeclarationRefused) as refusal:
        declared_from(base_panel(), _unchecked_contract(nominal_gamma=None))
    assert "the declared gamma is None" in str(refusal.value)
    assert "outside the band a display responds in" in str(refusal.value)


@pytest.mark.parametrize("gamma", ["two point two", "2.2v", "", "gamma"])
def test_a_gamma_that_is_not_a_number_refuses(gamma: object) -> None:
    with pytest.raises(DeclarationRefused) as refusal:
        declared_from(base_panel(), _unchecked_contract(nominal_gamma=gamma))
    assert str(refusal.value) == "the declared gamma was not a number"


@pytest.mark.parametrize("gamma", ["0.5000", "0.9990", "0.0100"])
def test_a_gamma_below_the_band_refuses(gamma: str) -> None:
    with pytest.raises(DeclarationRefused) as refusal:
        declared_from(base_panel(), _contract(nominal_gamma=gamma))
    assert f"the declared gamma is {gamma}" in str(refusal.value)
    assert float(gamma) < MINIMUM_GAMMA


@pytest.mark.parametrize("gamma", ["4.0001", "9.0000", "100.0000"])
def test_a_gamma_above_the_band_refuses(gamma: str) -> None:
    with pytest.raises(DeclarationRefused) as refusal:
        declared_from(base_panel(), _contract(nominal_gamma=gamma))
    assert f"the declared gamma is {gamma}" in str(refusal.value)
    assert float(gamma) > MAXIMUM_GAMMA


# What the record derives from the base -------------------------------------


def test_the_base_correction_matrix_is_dropped() -> None:
    # It corrects one model toward that model's measured behaviour, and these
    # primaries came off a different display.
    base = base_panel()
    assert base.color_correction_matrix is not None
    assert declared_from(base, _contract()).panel.color_correction_matrix is None


@pytest.mark.parametrize("panel_type", ["QD-OLED", "IPS", "VA", "WOLED"])
def test_the_panel_type_is_carried_over_untouched(panel_type: str) -> None:
    # A descriptor says nothing about panel technology, and the engine reads
    # this field to decide whether to apply OLED near-black compensation, so the
    # builder deliberately leaves it as the base record had it.
    base = replace(base_panel(), panel_type=panel_type)
    assert declared_from(base, _contract()).panel.panel_type == panel_type


@pytest.mark.parametrize(
    ("red_x", "expected_wide"),
    [("0.6500", False), ("0.6600", False), ("0.6700", True)],
)
@pytest.mark.parametrize("base_wide", [True, False])
def test_wide_gamut_is_derived_from_the_red_corner_and_not_inherited(
    red_x: str, expected_wide: bool, base_wide: bool
) -> None:
    # The threshold is a strict greater-than, so a red x sitting exactly on it
    # is not wide gamut. Running both base values proves the flag is computed
    # rather than copied from the record the builder started with.
    base = base_panel(wide_gamut=base_wide)
    panel = declared_from(base, _contract(**_primaries((red_x, "0.3000")))).panel
    assert panel.capabilities.wide_gamut is expected_wide
    assert (float(red_x) > WIDE_GAMUT_RED_X) is expected_wide


def test_every_capability_other_than_wide_gamut_survives_unchanged() -> None:
    base = base_panel(wide_gamut=False, native_contrast=1234.0)
    panel = declared_from(base, _contract()).panel
    assert panel.capabilities == replace(base.capabilities, wide_gamut=True)
    assert panel.capabilities.native_contrast == 1234.0
    assert panel.capabilities.max_luminance_sdr == 1.0
    assert panel.capabilities.min_luminance == 99.0
    assert panel.capabilities.vrr_capable is True


# False-success controls ----------------------------------------------------


def test_control_the_record_does_not_pick_up_bare_capability_defaults(srgb_panel: PanelRecord) -> None:
    """Catches a builder that assembles a fresh record instead of deriving one.

    ``PanelCapabilities()`` defaults claim HDR, wide gamut, ten bits and a
    million to one. A descriptor says none of those things. An implementation
    that constructed ``PanelCharacterization(...)`` from the declared numbers,
    rather than calling ``replace`` on the base record, would take those
    defaults and every assertion below would flip. So would one that started
    from ``base_panel()``-style optimistic capabilities instead of the caller's
    record.
    """
    panel = declared_from(srgb_panel, _contract()).panel
    assert panel.capabilities.hdr_capable is False
    assert panel.capabilities.bit_depth == 8
    assert panel.capabilities.native_contrast == 1000.0
    assert panel.capabilities.max_luminance_sdr == 250.0
    assert panel.capabilities.vrr_capable is False
    # The shared fixture record must come back out the way it went in.
    assert srgb_panel.capabilities.wide_gamut is False
    assert srgb_panel.manufacturer == "Generic"
    assert srgb_panel.notes.startswith("Generic sRGB panel.")


def test_control_a_triangle_just_over_the_minimum_area_is_accepted() -> None:
    """Catches a gamut check that refuses everything, or one with no threshold.

    The refusal tests above pass against a builder that raises
    ``DeclarationRefused`` unconditionally. This one is the same shape of
    triangle scaled to 0.02, just over the 0.01 floor, and it has to build.
    """
    wide_enough = _contract(
        red_xy=("0.1000", "0.1000"),
        green_xy=("0.5000", "0.1000"),
        blue_xy=("0.1000", "0.2000"),
    )
    panel = declared_from(base_panel(), wide_enough).panel
    assert panel.native_primaries.blue.as_tuple() == (0.1, 0.2)
    assert panel.capabilities.wide_gamut is False


@pytest.mark.parametrize("gamma", ["1.0000", "4.0000", "2.2000"])
def test_control_a_gamma_inside_the_band_is_accepted_at_both_edges(gamma: str) -> None:
    """Catches a band check narrower than the constants say, and an always-refuse stub.

    Both endpoints are inclusive in the production comparison. A builder using
    strict inequalities, or one refusing every gamma, fails here while still
    passing every out-of-band test above.
    """
    declared = declared_from(base_panel(), _contract(nominal_gamma=gamma))
    assert declared.gamma == float(gamma)
    assert declared.panel.gamma_blue.gamma == float(gamma)
    assert MINIMUM_GAMMA <= declared.gamma <= MAXIMUM_GAMMA


def test_control_the_label_split_is_not_the_whole_provenance_echoed_back() -> None:
    """Catches a label splitter that returns the raw string, or a fixed pair.

    A stub returning ``(provenance, provenance)`` satisfies "it returned two
    strings". These assertions pin the exact split and prove the prefix, the
    vendor code and the product code each land where the record keys them.
    """
    vendor, model = declared_label(PROVENANCE)
    assert vendor == "DEL"
    assert model == "UltraSharp U2723QE"
    assert EDID_PROVENANCE_PREFIX not in vendor
    assert EDID_PROVENANCE_PREFIX not in model
    assert "4231" not in model
    other_vendor, other_model = declared_label("edid:SAM7001 Odyssey G7")
    assert (other_vendor, other_model) == ("SAM", "Odyssey G7")
