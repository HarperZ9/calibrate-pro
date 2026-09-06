"""What a session does with a display's own declaration, and what a selection does to it.

A descriptor is a claim by the manufacturer about a model. The session layer is
where that claim is offered, accepted, labelled and dropped, and every one of
those steps has a way of going wrong that still looks like success: an offer read
off the wrong field, a record stored without the label that qualifies it, a seal
left standing over a plan built before the declaration arrived, and a display
switch that carries a claim from one monitor onto another.

Nothing here opens a display, a bus or an instrument. The dashboard is built from
contract objects, the declaration is derived from the bundled generic record the
shipped path derives it from, and the measurement is constructed directly, so the
ordering tests can hold two records at once without a colorimeter.
"""

from __future__ import annotations

import pytest

from calibrate_pro.application.assets import AssetFormat, AssetRequest, GeneratedAssets
from calibrate_pro.application.contracts import (
    CharacterizationKind,
    DashboardModel,
    DisplayObservation,
    PanelCharacterization,
)
from calibrate_pro.application.declaration import DeclaredCharacterization, declared_from
from calibrate_pro.application.measurement import MeasuredCharacterization
from calibrate_pro.application.selection import adopt
from calibrate_pro.application.session import SessionState
from calibrate_pro.panels.database import GENERIC_PANEL_KEY, get_database
from calibrate_pro.verification.provenance import EvidenceKind
from calibrate_pro.workflow import CapabilityState

#: The display every test selects unless it is testing a switch.
DECLARING_ID = "DECLARING-DISPLAY"

#: A second display, matched to a real panel record, so a switch away from the
#: declaring display lands on a kind detection alone can say.
MATCHED_ID = "MATCHED-DISPLAY"

#: A key the bundled database really holds, so the matched provenance parses.
MATCHED_PANEL_KEY = "AW3423DW"

UNKNOWN_PROVENANCE = "detector:no_panel_match"


def _capabilities() -> CapabilityState:
    """A probe that proved nothing, which is what these tests need it to be."""
    return CapabilityState(
        sensor_available=False,
        ddc_available=False,
        dwm_lut_available=False,
        dwm_state_capture_available=False,
        profile_write_available=False,
        vcgt_available=False,
    )


def _edid_offer(provenance: str = "edid:ACM1234 Example Monitor") -> PanelCharacterization:
    """The contract object a display's descriptor is carried in."""
    return PanelCharacterization(
        kind=CharacterizationKind.EDID_DECLARED,
        provenance=provenance,
        red_xy=("0.640", "0.330"),
        green_xy=("0.300", "0.600"),
        blue_xy=("0.150", "0.060"),
        white_xy=("0.3127", "0.3290"),
        nominal_gamma="2.2",
    )


def _unknown_characterization() -> PanelCharacterization:
    return PanelCharacterization(
        kind=CharacterizationKind.UNKNOWN,
        provenance=UNKNOWN_PROVENANCE,
        red_xy=None,
        green_xy=None,
        blue_xy=None,
        white_xy=None,
        nominal_gamma=None,
    )


def _matched_characterization() -> PanelCharacterization:
    return PanelCharacterization(
        kind=CharacterizationKind.MATCHED,
        provenance=f"panel-database:{MATCHED_PANEL_KEY}",
        red_xy=("0.680", "0.320"),
        green_xy=("0.265", "0.690"),
        blue_xy=("0.150", "0.060"),
        white_xy=("0.3127", "0.3290"),
        nominal_gamma="2.2",
    )


def _observation(
    display_id: str,
    *,
    characterization: PanelCharacterization | None = None,
    edid_characterization: PanelCharacterization | None = None,
) -> DisplayObservation:
    return DisplayObservation(
        platform_display_id=display_id,
        safe_label=f"Panel {display_id}",
        width_px=3440,
        height_px=1440,
        refresh_millihz=175000,
        hdr_enabled=None,
        characterization=characterization or _unknown_characterization(),
        capabilities=_capabilities(),
        evidence=("identity:qscreen_name",),
        edid_characterization=edid_characterization,
    )


def _dashboard(*displays: DisplayObservation) -> DashboardModel:
    return DashboardModel(
        displays=displays,
        selected_display_id=None,
        refreshed_utc="2026-09-06T00:00:00.000000Z",
    )


def _declaration(offer: PanelCharacterization | None = None) -> DeclaredCharacterization:
    """Build the record the shipped path builds, from the generic base it uses."""
    base = get_database().get_fallback()
    return declared_from(base, offer or _edid_offer())


def _measurement() -> MeasuredCharacterization:
    """A run with no instrument behind it, used only to hold the MEASURED label."""
    return MeasuredCharacterization(
        panel=get_database().get_fallback(),
        instrument="tests:no instrument was opened",
        steps=5,
        patch_count=15,
        white_luminance=120.0,
        black_luminance=0.12,
        contrast_ratio=1000.0,
        white_xy=(0.3127, 0.3290),
        gamma=(2.2, 2.2, 2.2),
        patch_geometry="tests:no window was opened",
    )


def _generated_bundle() -> GeneratedAssets:
    """A bundle with the labels a sensorless build carries and no run behind it."""
    return GeneratedAssets(
        request=AssetRequest(
            display_id=DECLARING_ID,
            panel_key=GENERIC_PANEL_KEY,
            preset_id="calibration.preset.srgb_web",
            formats=(AssetFormat.CUBE,),
            lut_size=17,
        ),
        assets={AssetFormat.CUBE: b'TITLE "tests"\n'},
        panel_name="Generic sRGB",
        characterization_kind=CharacterizationKind.EXPLICIT_GENERIC,
        evidence_kind=EvidenceKind.NOT_MEASURED,
        gamut_mode="clamp",
        tone_response="srgb",
        applied_gamma_exponent=2.2,
        white_point="D65",
    )


def _sealed_session(state: SessionState) -> None:
    """Put a session into the state a generated, confirmed plan leaves it in."""
    state.generated = _generated_bundle()
    state.sealed_plan_sha256 = "b" * 64
    state.sealed_plan_actuatable = True
    state.capability_generation = 4
    state.sealed_capability_generation = 4
    state.confirmation_state = "confirmed"


def _selected_session(
    *,
    edid: PanelCharacterization | None = None,
    second_display: bool = False,
) -> SessionState:
    """A session with the declaring display detected and selected."""
    displays = [_observation(DECLARING_ID, edid_characterization=edid if edid is not None else _edid_offer())]
    if second_display:
        displays.append(_observation(MATCHED_ID, characterization=_matched_characterization()))
    state = SessionState()
    state.dashboard = _dashboard(*displays)
    state.selected_display_id = DECLARING_ID
    return state


def test_declaration_offer_reads_the_selected_displays_descriptor() -> None:
    offer = _edid_offer()
    state = _selected_session(edid=offer)

    assert state.declaration_offer is offer


def test_declaration_offer_is_not_the_resolved_characterization() -> None:
    """FALSE-SUCCESS CONTROL.

    Catches an implementation that answers with ``observation.characterization``
    instead of ``observation.edid_characterization``. Both fields hold the same
    contract type, so a wrong field still returns a well-formed object and every
    "an offer exists" assertion elsewhere in this file would still pass. Here the
    display's resolved characterization is MATCHED and its descriptor is
    EDID_DECLARED, so the two cannot be confused.
    """
    offer = _edid_offer()
    matched = _matched_characterization()
    state = SessionState()
    state.dashboard = _dashboard(_observation(DECLARING_ID, characterization=matched, edid_characterization=offer))
    state.selected_display_id = DECLARING_ID

    assert state.declaration_offer is offer
    assert state.declaration_offer is not matched
    assert state.declaration_offer.kind is CharacterizationKind.EDID_DECLARED


def test_declaration_offer_is_none_when_no_display_is_selected() -> None:
    state = _selected_session()
    state.selected_display_id = None

    assert state.declaration_offer is None


def test_declaration_offer_is_none_for_an_id_the_dashboard_never_reported() -> None:
    state = _selected_session()
    state.selected_display_id = "DISPLAY-THAT-WAS-NEVER-DETECTED"

    assert state.declaration_offer is None


def test_declaration_offer_is_none_before_a_detection() -> None:
    state = SessionState()
    state.selected_display_id = DECLARING_ID

    assert state.dashboard is None
    assert state.declaration_offer is None


def test_declaration_offer_is_none_when_the_display_declared_nothing() -> None:
    state = _selected_session(edid=None)
    state.dashboard = _dashboard(_observation(DECLARING_ID))

    assert state.declaration_offer is None


def test_record_declaration_refuses_the_offer_contract() -> None:
    """The contract and the built record are different types with one name.

    ``declaration_offer`` hands back an application ``PanelCharacterization``,
    and the record the session holds is a ``DeclaredCharacterization`` built from
    it. Handing the offer straight to ``record_declaration`` is the mistake the
    type check exists for, so that is what is handed to it here.
    """
    state = _selected_session()

    with pytest.raises(TypeError) as error:
        state.record_declaration(_edid_offer())  # type: ignore[arg-type]

    assert "declared must be a DeclaredCharacterization" in str(error.value)
    assert state.declared_characterization is None
    assert state.characterization_kind is None


def test_record_declaration_refuses_before_a_display_is_selected() -> None:
    state = SessionState()

    with pytest.raises(ValueError) as error:
        state.record_declaration(_declaration())

    assert "a declaration cannot be recorded before a display is selected" in str(error.value)
    assert state.declared_characterization is None
    assert state.declared_display_id is None


def test_record_declaration_sets_the_record_the_display_and_the_kind_together() -> None:
    state = _selected_session()
    declared = _declaration()

    state.record_declaration(declared)

    assert state.declared_characterization is declared
    assert state.declared_display_id == DECLARING_ID
    assert state.characterization_kind is CharacterizationKind.EDID_DECLARED
    assert state.declaration_matches_selection is True


def test_record_declaration_breaks_the_seal() -> None:
    """FALSE-SUCCESS CONTROL.

    Catches a ``record_declaration`` that stores the record and skips
    ``invalidate_seal``. Every assertion about the record itself would still
    pass, and the session would go on offering export and apply for a bundle
    generated before the declaration arrived. Asserting ``seal_intact`` alone is
    not enough either, so the generated bytes and the confirmation are checked:
    a stub that only cleared ``sealed_capability_generation`` would leave an
    exportable bundle in memory.
    """
    state = _selected_session()
    _sealed_session(state)
    assert state.seal_intact is True
    assert state.export_source_ready is True

    state.record_declaration(_declaration())

    assert state.seal_intact is False
    assert state.sealed_plan_sha256 is None
    assert state.sealed_capability_generation is None
    assert state.sealed_plan_actuatable is False
    assert state.generated is None
    assert state.export_source_ready is False
    assert state.confirmation_state == "expired"


def test_discard_declaration_clears_both_fields() -> None:
    state = _selected_session()
    state.record_declaration(_declaration())

    state.discard_declaration()

    assert state.declared_characterization is None
    assert state.declared_display_id is None
    assert state.declaration_matches_selection is False


def test_declaration_matches_selection_only_for_the_display_it_came_from() -> None:
    state = _selected_session(second_display=True)
    state.record_declaration(_declaration())
    assert state.declaration_matches_selection is True

    state.selected_display_id = MATCHED_ID

    assert state.declared_display_id == DECLARING_ID
    assert state.declaration_matches_selection is False


def test_declaration_matches_selection_is_false_with_no_declaration_held() -> None:
    state = _selected_session()

    assert state.declared_characterization is None
    assert state.declaration_matches_selection is False


def test_a_held_declaration_outranks_the_panel_key() -> None:
    """FALSE-SUCCESS CONTROL.

    Catches an implementation that reads the panel key first. The session below
    holds a real matched key and a declaration for the same display, which is
    exactly the state a matched display leaves behind after the operator accepts
    its descriptor. Answering MATCHED there would report a nominal record for a
    display whose own declared numbers the session is building from, and no test
    that sets only one of the two fields can see it.
    """
    state = _selected_session()
    state.selected_panel_key = MATCHED_PANEL_KEY
    state.record_declaration(_declaration())

    assert state.selected_panel_key == MATCHED_PANEL_KEY
    assert state.characterization_without_measurement is CharacterizationKind.EDID_DECLARED


def test_a_declaration_for_another_display_does_not_outrank_the_panel_key() -> None:
    state = _selected_session(second_display=True)
    state.record_declaration(_declaration())
    state.selected_display_id = MATCHED_ID
    state.selected_panel_key = MATCHED_PANEL_KEY

    assert state.characterization_without_measurement is CharacterizationKind.MATCHED


def test_characterization_without_measurement_reports_the_generic_key() -> None:
    state = _selected_session()
    state.selected_panel_key = GENERIC_PANEL_KEY

    assert state.characterization_without_measurement is CharacterizationKind.EXPLICIT_GENERIC


def test_characterization_without_measurement_reports_unknown_and_nothing() -> None:
    state = _selected_session()
    assert state.selected_panel_key is None
    assert state.characterization_without_measurement is CharacterizationKind.UNKNOWN

    state.selected_display_id = None
    assert state.characterization_without_measurement is None


def test_invalidate_measurement_falls_back_to_the_held_declaration() -> None:
    state = _selected_session()
    state.record_declaration(_declaration())
    state.record_measurement(_measurement())
    assert state.characterization_kind is CharacterizationKind.MEASURED

    state.invalidate_measurement()

    assert state.measured_characterization is None
    assert state.declared_characterization is not None
    assert state.characterization_kind is CharacterizationKind.EDID_DECLARED


def test_to_context_reports_an_offer_the_session_has_not_accepted() -> None:
    state = _selected_session()

    context = state.to_context()

    assert state.declared_characterization is None
    assert context.edid_declaration_available is True
    assert context.characterization_kind is None


def test_to_context_still_reports_the_offer_after_the_session_accepted_it() -> None:
    state = _selected_session()
    state.record_declaration(_declaration())

    context = state.to_context()

    assert context.edid_declaration_available is True
    assert context.characterization_kind is CharacterizationKind.EDID_DECLARED


def test_to_context_reports_no_offer_from_a_display_that_declared_nothing() -> None:
    """FALSE-SUCCESS CONTROL.

    Catches ``edid_declaration_available`` wired to the accepted record rather
    than to the display's offer. The session below holds a declaration and is
    selected on a display that declared nothing, so an implementation reading
    ``declared_characterization is not None`` answers True and would offer the
    operator a control to accept a descriptor no display presented. Paired with
    the test above, which holds an offer and no record, this pins the flag to the
    display in both directions.
    """
    state = SessionState()
    state.dashboard = _dashboard(_observation(DECLARING_ID))
    state.selected_display_id = DECLARING_ID
    state.record_declaration(_declaration())

    context = state.to_context()

    assert state.declared_characterization is not None
    assert state.declaration_offer is None
    assert context.edid_declaration_available is False


def test_adopting_the_same_display_keeps_the_declaration_and_restores_the_kind() -> None:
    state = _selected_session(second_display=True)
    declared = _declaration()
    state.record_declaration(declared)

    adopt(state, DECLARING_ID)

    assert state.declared_characterization is declared
    assert state.declared_display_id == DECLARING_ID
    assert state.characterization_kind is CharacterizationKind.EDID_DECLARED


def test_adopting_a_different_display_drops_the_declaration() -> None:
    state = _selected_session(second_display=True)
    state.record_declaration(_declaration())

    adopt(state, MATCHED_ID)

    assert state.declared_characterization is None
    assert state.declared_display_id is None
    assert state.selected_display_id == MATCHED_ID
    assert state.characterization_kind is CharacterizationKind.MATCHED
    assert state.selected_panel_key == MATCHED_PANEL_KEY


def test_adopting_no_display_drops_the_declaration() -> None:
    state = _selected_session()
    state.record_declaration(_declaration())

    adopt(state, None)

    assert state.selected_display_id is None
    assert state.declared_characterization is None
    assert state.declared_display_id is None
    assert state.characterization_kind is None


def test_adopt_carries_the_declaration_before_the_measurement() -> None:
    """FALSE-SUCCESS CONTROL.

    Catches ``_carry_or_drop_measurement`` running before
    ``_carry_or_drop_declaration``. Both records belong to the display being
    re-adopted, so both are legitimately kept and the only visible difference is
    the label left behind. With the order reversed the declaration assignment
    lands last and the session reports EDID_DECLARED over a run an instrument
    took, silently downgrading a measured session to a declared one while every
    record it holds stays correct.
    """
    state = _selected_session()
    declared = _declaration()
    measured = _measurement()
    state.record_declaration(declared)
    state.record_measurement(measured)
    assert state.characterization_kind is CharacterizationKind.MEASURED

    adopt(state, DECLARING_ID)

    assert state.declared_characterization is declared
    assert state.measured_characterization is measured
    assert state.characterization_kind is CharacterizationKind.MEASURED


def test_adopting_a_different_display_drops_both_records() -> None:
    state = _selected_session(second_display=True)
    state.record_declaration(_declaration())
    state.record_measurement(_measurement())

    adopt(state, MATCHED_ID)

    assert state.declared_characterization is None
    assert state.declared_display_id is None
    assert state.measured_characterization is None
    assert state.measured_display_id is None
    assert state.characterization_kind is CharacterizationKind.MATCHED
