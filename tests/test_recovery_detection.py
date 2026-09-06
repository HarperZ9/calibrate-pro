"""Contract tests for immutable, read-only display recovery observations."""

from __future__ import annotations

from dataclasses import FrozenInstanceError, fields
from enum import Enum
from typing import Any

import pytest

from calibrate_pro.application.contracts import (
    CharacterizationKind,
    DashboardModel,
    DisplayObservation,
    PanelCharacterization,
)
from calibrate_pro.workflow import CapabilityState

UNKNOWN_PROVENANCE = "detector:no_panel_match"


class _OtherKind(str, Enum):
    MATCHED = "matched"


class _StringSubclass(str):
    pass


def _capabilities() -> CapabilityState:
    return CapabilityState(
        sensor_available=False,
        ddc_available=False,
        dwm_lut_available=False,
        dwm_state_capture_available=False,
        profile_write_available=False,
        vcgt_available=False,
    )


def _characterization(
    *,
    kind: CharacterizationKind = CharacterizationKind.MATCHED,
    provenance: str = "database:panel-db:test-panel",
    red_xy: tuple[str, str] | None = ("0.640", "0.330"),
    green_xy: tuple[str, str] | None = ("0.300", "0.600"),
    blue_xy: tuple[str, str] | None = ("0.150", "0.060"),
    white_xy: tuple[str, str] | None = ("0.3127", "0.3290"),
    nominal_gamma: str | None = "2.2",
) -> PanelCharacterization:
    return PanelCharacterization(
        kind=kind,
        provenance=provenance,
        red_xy=red_xy,
        green_xy=green_xy,
        blue_xy=blue_xy,
        white_xy=white_xy,
        nominal_gamma=nominal_gamma,
    )


def _unknown_characterization() -> PanelCharacterization:
    return _characterization(
        kind=CharacterizationKind.UNKNOWN,
        provenance=UNKNOWN_PROVENANCE,
        red_xy=None,
        green_xy=None,
        blue_xy=None,
        white_xy=None,
        nominal_gamma=None,
    )


def _display(
    *,
    platform_display_id: str = "DISPLAY-1",
    safe_label: str = "Example Panel",
    width_px: int = 3840,
    height_px: int = 2160,
    refresh_millihz: int = 59940,
    hdr_enabled: bool | None = None,
    characterization: PanelCharacterization | None = None,
    capabilities: CapabilityState | None = None,
    evidence: tuple[str, ...] | list[str] = ("identity:qscreen_name",),
) -> DisplayObservation:
    return DisplayObservation(
        platform_display_id=platform_display_id,
        safe_label=safe_label,
        width_px=width_px,
        height_px=height_px,
        refresh_millihz=refresh_millihz,
        hdr_enabled=hdr_enabled,
        characterization=characterization or _characterization(),
        capabilities=capabilities or _capabilities(),
        evidence=evidence,  # type: ignore[arg-type]
    )


def _dashboard(
    *,
    displays: tuple[DisplayObservation, ...] | list[DisplayObservation] | None = None,
    selected_display_id: str | None = "DISPLAY-1",
    refreshed_utc: str = "2026-07-14T12:34:56.123456Z",
) -> DashboardModel:
    return DashboardModel(
        displays=displays if displays is not None else (_display(),),  # type: ignore[arg-type]
        selected_display_id=selected_display_id,
        refreshed_utc=refreshed_utc,
    )


def test_contracts_have_the_exact_ordered_public_fields() -> None:
    assert tuple(field.name for field in fields(PanelCharacterization)) == (
        "kind",
        "provenance",
        "red_xy",
        "green_xy",
        "blue_xy",
        "white_xy",
        "nominal_gamma",
    )
    assert tuple(field.name for field in fields(DisplayObservation)) == (
        "platform_display_id",
        "safe_label",
        "width_px",
        "height_px",
        "refresh_millihz",
        "hdr_enabled",
        "characterization",
        "capabilities",
        "evidence",
    )
    assert tuple(field.name for field in fields(DashboardModel)) == (
        "displays",
        "selected_display_id",
        "refreshed_utc",
    )


@pytest.mark.parametrize("factory", (_characterization, _display, _dashboard))
def test_contracts_are_frozen(factory: Any) -> None:
    value = factory()

    with pytest.raises(FrozenInstanceError):
        value.unplanned_attribute = "mutation"


@pytest.mark.parametrize("kind", ("matched", _OtherKind.MATCHED, None, 1))
def test_characterization_kind_requires_the_canonical_enum(kind: object) -> None:
    with pytest.raises(TypeError):
        _characterization(kind=kind)  # type: ignore[arg-type]


@pytest.mark.parametrize("provenance", ("", "   ", 1, None, _StringSubclass("database:test")))
def test_characterization_provenance_requires_a_nonblank_exact_string(provenance: object) -> None:
    with pytest.raises(TypeError):
        _characterization(provenance=provenance)  # type: ignore[arg-type]


@pytest.mark.parametrize("kind", (CharacterizationKind.MATCHED, CharacterizationKind.EXPLICIT_GENERIC))
@pytest.mark.parametrize("missing_field", ("red_xy", "green_xy", "blue_xy", "white_xy", "nominal_gamma"))
def test_complete_characterizations_require_every_numeric_field(
    kind: CharacterizationKind,
    missing_field: str,
) -> None:
    arguments: dict[str, object] = {"kind": kind}
    arguments[missing_field] = None

    with pytest.raises(ValueError):
        _characterization(**arguments)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("kind", "provenance"),
    (
        (CharacterizationKind.MATCHED, "database:panel-db:record-7"),
        (CharacterizationKind.EXPLICIT_GENERIC, "user:explicit_generic_srgb"),
        (CharacterizationKind.EXPLICIT_GENERIC, "user:custom_generic_display_p3"),
    ),
)
def test_complete_characterizations_accept_explicit_nonblank_provenance(
    kind: CharacterizationKind,
    provenance: str,
) -> None:
    value = _characterization(kind=kind, provenance=provenance)

    assert value.kind is kind
    assert value.provenance == provenance


@pytest.mark.parametrize(
    "field_value",
    (
        ["0.64", "0.33"],
        ("0.64",),
        ("0.64", "0.33", "0.03"),
        (0.64, "0.33"),
        (_StringSubclass("0.64"), "0.33"),
    ),
)
def test_coordinates_require_exact_two_string_tuples(field_value: object) -> None:
    with pytest.raises(TypeError):
        _characterization(red_xy=field_value)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "field_value",
    (
        ("not-a-decimal", "0.33"),
        ("NaN", "0.33"),
        ("sNaN", "0.33"),
        ("Infinity", "0.33"),
        ("-0.01", "0.33"),
        ("1.01", "0"),
        ("0.7", "0.4"),
    ),
)
def test_coordinates_require_finite_decimal_values_in_the_chromaticity_triangle(
    field_value: tuple[str, str],
) -> None:
    with pytest.raises(ValueError):
        _characterization(red_xy=field_value)


@pytest.mark.parametrize("field_value", (("0", "0"), ("1", "0"), ("1e-1", "9e-1")))
def test_coordinates_accept_decimal_boundary_and_exponent_strings(field_value: tuple[str, str]) -> None:
    value = _characterization(red_xy=field_value)

    assert value.red_xy == field_value


@pytest.mark.parametrize("gamma", (0, 2.2, None, _StringSubclass("2.2")))
def test_complete_gamma_requires_an_exact_string(gamma: object) -> None:
    with pytest.raises((TypeError, ValueError)):
        _characterization(nominal_gamma=gamma)  # type: ignore[arg-type]


@pytest.mark.parametrize("gamma", ("", "not-a-decimal", "NaN", "Infinity", "0", "-2.2"))
def test_complete_gamma_requires_a_positive_finite_decimal(gamma: str) -> None:
    with pytest.raises(ValueError):
        _characterization(nominal_gamma=gamma)


@pytest.mark.parametrize("gamma", ("2.2", "+2.20", "22e-1"))
def test_complete_gamma_preserves_valid_decimal_strings(gamma: str) -> None:
    value = _characterization(nominal_gamma=gamma)

    assert value.nominal_gamma == gamma


def test_unknown_characterization_uses_one_explicit_stable_provenance() -> None:
    value = _unknown_characterization()

    assert value.provenance == "detector:no_panel_match"


@pytest.mark.parametrize("provenance", ("unknown", "detector:unknown", "database:no-match", ""))
def test_unknown_characterization_rejects_other_provenance(provenance: str) -> None:
    with pytest.raises((TypeError, ValueError)):
        _characterization(
            kind=CharacterizationKind.UNKNOWN,
            provenance=provenance,
            red_xy=None,
            green_xy=None,
            blue_xy=None,
            white_xy=None,
            nominal_gamma=None,
        )


@pytest.mark.parametrize(
    ("field_name", "field_value"),
    (
        ("red_xy", ("0.64", "0.33")),
        ("green_xy", ("0.30", "0.60")),
        ("blue_xy", ("0.15", "0.06")),
        ("white_xy", ("0.3127", "0.3290")),
        ("nominal_gamma", "2.2"),
    ),
)
def test_unknown_characterization_rejects_every_numeric_field(
    field_name: str,
    field_value: object,
) -> None:
    arguments: dict[str, object] = {
        "kind": CharacterizationKind.UNKNOWN,
        "provenance": UNKNOWN_PROVENANCE,
        "red_xy": None,
        "green_xy": None,
        "blue_xy": None,
        "white_xy": None,
        "nominal_gamma": None,
    }
    arguments[field_name] = field_value

    with pytest.raises(ValueError):
        _characterization(**arguments)  # type: ignore[arg-type]


@pytest.mark.parametrize("field_name", ("platform_display_id", "safe_label"))
@pytest.mark.parametrize("field_value", ("", "   ", 7, None, _StringSubclass("display")))
def test_display_required_strings_are_nonblank_and_exact(field_name: str, field_value: object) -> None:
    arguments: dict[str, object] = {field_name: field_value}

    with pytest.raises(TypeError):
        _display(**arguments)  # type: ignore[arg-type]


@pytest.mark.parametrize("field_name", ("width_px", "height_px", "refresh_millihz"))
@pytest.mark.parametrize("field_value", (True, False, 1.0, "1", None))
def test_display_dimensions_and_refresh_require_exact_integers(field_name: str, field_value: object) -> None:
    arguments: dict[str, object] = {field_name: field_value}

    with pytest.raises(TypeError):
        _display(**arguments)  # type: ignore[arg-type]


@pytest.mark.parametrize("field_name", ("width_px", "height_px", "refresh_millihz"))
@pytest.mark.parametrize("field_value", (0, -1))
def test_display_dimensions_and_refresh_are_positive(field_name: str, field_value: int) -> None:
    arguments = {field_name: field_value}

    with pytest.raises(ValueError):
        _display(**arguments)


@pytest.mark.parametrize("hdr_enabled", (True, False, None))
def test_hdr_preserves_true_false_and_unknown(hdr_enabled: bool | None) -> None:
    value = _display(hdr_enabled=hdr_enabled)

    assert value.hdr_enabled is hdr_enabled


@pytest.mark.parametrize("hdr_enabled", (0, 1, "unknown", object()))
def test_hdr_rejects_non_boolean_non_none_values(hdr_enabled: object) -> None:
    with pytest.raises(TypeError):
        _display(hdr_enabled=hdr_enabled)  # type: ignore[arg-type]


def test_display_requires_the_exact_characterization_contract() -> None:
    with pytest.raises(TypeError):
        _display(characterization="matched")  # type: ignore[arg-type]


def test_display_requires_the_canonical_capability_state() -> None:
    with pytest.raises(TypeError):
        _display(capabilities=(False, False, False, False, False, False))  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "evidence", ({"identity:qscreen_name"}, iter(("identity:qscreen_name",)), "identity:qscreen_name")
)
def test_evidence_accepts_only_producer_sequences_that_can_be_frozen(evidence: object) -> None:
    with pytest.raises(TypeError):
        _display(evidence=evidence)  # type: ignore[arg-type]


@pytest.mark.parametrize("entry", ("", "   ", 1, None, _StringSubclass("identity:qscreen_name")))
def test_evidence_entries_are_nonblank_exact_strings(entry: object) -> None:
    with pytest.raises(TypeError):
        _display(evidence=(entry,))  # type: ignore[arg-type]


def test_evidence_is_defensively_copied_to_a_tuple() -> None:
    producer_evidence = ["identity:qscreen_name"]

    value = _display(evidence=producer_evidence)
    producer_evidence.append("hdr:enabled")

    assert type(value.evidence) is tuple
    assert value.evidence == ("identity:qscreen_name",)


def test_dashboard_accepts_an_empty_unselected_snapshot() -> None:
    value = _dashboard(displays=(), selected_display_id=None)

    assert value.displays == ()
    assert value.selected_display_id is None


def test_dashboard_displays_are_defensively_copied_to_a_tuple() -> None:
    first = _display()
    producer_displays = [first]

    value = _dashboard(displays=producer_displays)
    producer_displays.append(_display(platform_display_id="DISPLAY-2"))

    assert type(value.displays) is tuple
    assert value.displays == (first,)


@pytest.mark.parametrize("displays", ({_display()}, iter((_display(),)), "not-displays"))
def test_dashboard_rejects_non_sequence_display_collections(displays: object) -> None:
    with pytest.raises(TypeError):
        _dashboard(displays=displays)  # type: ignore[arg-type]


def test_dashboard_requires_exact_display_observation_members() -> None:
    with pytest.raises(TypeError):
        _dashboard(displays=("DISPLAY-1",))  # type: ignore[arg-type]


def test_dashboard_display_ids_must_be_unique() -> None:
    with pytest.raises(ValueError):
        _dashboard(displays=(_display(), _display()))


def test_dashboard_selected_display_must_exist() -> None:
    with pytest.raises(ValueError):
        _dashboard(selected_display_id="DISPLAY-2")


@pytest.mark.parametrize("selected_display_id", ("", "   ", 1, _StringSubclass("DISPLAY-1")))
def test_dashboard_selected_display_id_is_none_or_a_nonblank_exact_string(selected_display_id: object) -> None:
    with pytest.raises(TypeError):
        _dashboard(selected_display_id=selected_display_id)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "refreshed_utc",
    (
        "2026-07-14T12:34:56Z",
        "2026-07-14T12:34:56.123456Z",
        "2026-07-14T12:34:56.123456789Z",
    ),
)
def test_dashboard_accepts_parseable_utc_z_timestamps(refreshed_utc: str) -> None:
    value = _dashboard(refreshed_utc=refreshed_utc)

    assert value.refreshed_utc == refreshed_utc


@pytest.mark.parametrize("digits", tuple(range(1, 10)))
def test_dashboard_accepts_every_fractional_width_on_every_supported_interpreter(digits: int) -> None:
    """Fractional width is where the contract used to change shape under the runtime.

    ``datetime.fromisoformat`` took only 3 or 6 fractional digits through 3.10 and
    started accepting any width, truncating past 6, in 3.11. The pattern this contract
    advertises allows any width, so on 3.10 a timestamp the pattern accepted was then
    rejected by the parse behind it. Six of these nine widths failed there and passed
    everywhere else, which is a supported interpreter disagreeing about what the
    product accepts. Widths are checked one by one rather than at the two boundaries,
    because the two rules that disagreed each carved out a different middle.
    """
    refreshed_utc = f"2026-07-14T12:34:56.{'1' * digits}Z"

    assert _dashboard(refreshed_utc=refreshed_utc).refreshed_utc == refreshed_utc


def test_dashboard_still_rejects_a_calendar_date_that_cannot_exist_with_a_fraction() -> None:
    """Normalising the fraction must not normalise away the calendar check with it.

    The parse is the only thing that rejects a month of 13 or a February 30th, and it
    now runs against a rewritten string. This holds it to the same answer.
    """
    with pytest.raises(ValueError):
        _dashboard(refreshed_utc="2026-02-30T12:34:56.123456789Z")


@pytest.mark.parametrize(
    "refreshed_utc",
    (
        "",
        "2026-07-14",
        "2026-07-14Z",
        "2026-07-14 12:34:56Z",
        "2026-07-14T12:34:56z",
        "2026-07-14T12:34:56+00:00",
        "2026-07-14T12:34:56-07:00",
        "2026-13-14T12:34:56Z",
        "not-a-timestamp",
    ),
)
def test_dashboard_rejects_noncanonical_or_unparseable_utc_values(refreshed_utc: str) -> None:
    with pytest.raises(ValueError):
        _dashboard(refreshed_utc=refreshed_utc)


@pytest.mark.parametrize("refreshed_utc", (None, 1, _StringSubclass("2026-07-14T12:34:56Z")))
def test_dashboard_timestamp_requires_an_exact_string(refreshed_utc: object) -> None:
    with pytest.raises(TypeError):
        _dashboard(refreshed_utc=refreshed_utc)  # type: ignore[arg-type]
