"""Gates over the EDID declaration path that fail against a wrong implementation.

Each one asserts a property of the result that a wrong implementation does not
have, rather than the identity of a call or an equality between a constant and
itself. Nothing here reads a display or an instrument.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from calibrate_pro.application import declaration as declaration_module
from calibrate_pro.application.contracts import CharacterizationKind
from calibrate_pro.application.contracts import PanelCharacterization as DeclaredContract
from calibrate_pro.application.declaration import (
    DeclarationRefused,
    declared_from,
)
from calibrate_pro.application.measurement import MINIMUM_GAMUT_AREA
from calibrate_pro.panels.database import get_database
from tests.test_edid_surfaces import declared_session, succeeded


def _contract(red: tuple[str, str], green: tuple[str, str], blue: tuple[str, str]) -> DeclaredContract:
    return DeclaredContract(
        kind=CharacterizationKind.EDID_DECLARED,
        provenance="edid:ACM1234 Example Monitor",
        red_xy=red,
        green_xy=green,
        blue_xy=blue,
        white_xy=("0.3127", "0.3290"),
        nominal_gamma="2.2",
    )


# -- the generic base --------------------------------------------------------


def test_the_session_builds_a_declaration_on_the_generic_panel_and_no_other(tmp_path: Path) -> None:
    """Every field the descriptor does not cover is the neutral panel's, written out here.

    The values are the generic sRGB record's, stated as literals so that a
    declaration built on another display's record (a QD-OLED here) is caught by
    what it carries: panel technology, peak luminance, contrast, HDR and VRR.
    """
    service, state = declared_session(tmp_path)
    succeeded(service.use_edid_characterization())

    panel = state.declared_characterization.panel
    assert panel.panel_type == "IPS"
    assert panel.capabilities.max_luminance_sdr == 250.0
    assert panel.capabilities.native_contrast == 1000.0
    assert panel.capabilities.bit_depth == 8
    assert panel.capabilities.hdr_capable is False
    assert panel.capabilities.vrr_capable is False
    assert panel.capabilities.local_dimming is False
    # The control: the other display's record really does differ on these, so
    # the assertions above can tell the two bases apart.
    other = get_database().get_panel("AW3423DW")
    assert other is not None
    assert (other.panel_type, other.capabilities.hdr_capable) != ("IPS", False)


# -- the note ----------------------------------------------------------------


def test_the_record_says_in_its_notes_that_it_is_a_declaration_and_not_a_reading() -> None:
    """Asserts what the note must tell a reader, so editing the constant cannot move the test with it."""
    notes = declared_from(
        get_database().get_fallback(), _contract(("0.68", "0.32"), ("0.265", "0.69"), ("0.15", "0.06"))
    ).panel.notes
    text = notes.lower()
    assert "declared" in text
    assert "descriptor" in text
    assert "not a reading" in text
    assert "model" in text
    assert "measured" not in text


# -- the gamut-area floor ----------------------------------------------------


def test_the_floor_is_exactly_one_hundredth_of_the_xy_plane() -> None:
    assert MINIMUM_GAMUT_AREA == 0.01


@pytest.mark.parametrize(("height", "accepted"), [("0.099", False), ("0.101", True)])
def test_triangles_just_either_side_of_the_floor(height: str, accepted: bool) -> None:
    """Base 0.2 and height h enclose 0.1 * h, so these are 0.0099 and 0.0101."""
    contract = _contract(("0.1", "0.1"), ("0.3", "0.1"), ("0.1", str(round(0.1 + float(height), 3))))
    base = get_database().get_fallback()
    if accepted:
        assert declared_from(base, contract).gamma == 2.2
    else:
        with pytest.raises(DeclarationRefused, match="too little to be three separate colours"):
            declared_from(base, contract)


def test_a_declaration_sitting_exactly_on_the_floor_is_accepted(monkeypatch: pytest.MonkeyPatch) -> None:
    """The comparison is strict: area equal to the floor passes, so `<=` would refuse it.

    The floor is replaced by a dyadic value and the triangle is chosen to enclose
    exactly that value, because 0.01 has no exact binary form and an exact tie
    cannot be built from it.
    """
    monkeypatch.setattr(declaration_module, "MINIMUM_GAMUT_AREA", 0.125)
    on_the_floor = _contract(("0.0", "0.0"), ("0.5", "0.0"), ("0.0", "0.5"))
    record = declared_from(get_database().get_fallback(), on_the_floor)
    assert record.red_xy == (0.0, 0.0)

    just_under = _contract(("0.0", "0.0"), ("0.5", "0.0"), ("0.0", "0.49"))
    with pytest.raises(DeclarationRefused):
        declared_from(get_database().get_fallback(), just_under)
