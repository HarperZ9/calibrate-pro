"""Phase 0 type foundations for the functional-recovery application layer."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
from enum import Enum
from typing import TypeVar, cast

from calibrate_pro.verification.provenance import EvidenceKind
from calibrate_pro.workflow import CapabilityState


class CharacterizationKind(str, Enum):
    """Where a session's description of a display came from.

    The first three describe a model. A matched record names the product, the
    generic record names a nominal sRGB panel, and unknown names nothing.
    MEASURED is the one member that describes the unit on the desk, and it is
    reachable only through an instrument run, so no path that resolves a panel
    from a database can produce it.
    """

    MATCHED = "matched"
    EXPLICIT_GENERIC = "explicit_generic"
    MEASURED = "measured"
    UNKNOWN = "unknown"


PHASE_ONE_EVIDENCE_KINDS = frozenset(
    {
        EvidenceKind.NOT_MEASURED,
        EvidenceKind.ESTIMATED,
        EvidenceKind.MEASURED,
    }
)


_UNKNOWN_PROVENANCE = "detector:no_panel_match"
_UTC_Z_RE = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.(?P<fraction>\d+))?Z")
_SequenceMember = TypeVar("_SequenceMember")


def _require_nonblank_exact_string(value: object, *, field_name: str) -> None:
    if type(value) is not str or not value.strip():
        raise TypeError(f"{field_name} must be a nonblank exact string")


def _parse_decimal_string(value: object, *, field_name: str) -> Decimal:
    if type(value) is not str:
        raise TypeError(f"{field_name} must be an exact string")
    if not value or value != value.strip():
        raise ValueError(f"{field_name} must be a decimal string")
    try:
        parsed = Decimal(value)
    except InvalidOperation as exc:
        raise ValueError(f"{field_name} must be a decimal string") from exc
    if not parsed.is_finite():
        raise ValueError(f"{field_name} must be finite")
    return parsed


def _validate_xy(value: object, *, field_name: str) -> None:
    if value is None:
        return
    if type(value) is not tuple or len(value) != 2:
        raise TypeError(f"{field_name} must be an exact two-string tuple or None")
    x = _parse_decimal_string(value[0], field_name=f"{field_name}[0]")
    y = _parse_decimal_string(value[1], field_name=f"{field_name}[1]")
    if not (Decimal(0) <= x <= Decimal(1)) or not (Decimal(0) <= y <= Decimal(1)):
        raise ValueError(f"{field_name} components must be in [0, 1]")
    if x + y > Decimal(1):
        raise ValueError(f"{field_name} must satisfy x + y <= 1")


def _freeze_sequence(
    value: object,
    *,
    field_name: str,
    member_type: type[_SequenceMember],
) -> tuple[_SequenceMember, ...]:
    if type(value) not in {list, tuple}:
        raise TypeError(f"{field_name} must be a list or tuple")
    sequence = cast("list[object] | tuple[object, ...]", value)
    frozen = tuple(sequence)
    if any(type(member) is not member_type for member in frozen):
        raise TypeError(f"{field_name} contains an invalid member")
    return cast("tuple[_SequenceMember, ...]", frozen)


@dataclass(frozen=True)
class PanelCharacterization:
    """An explicitly sourced panel characterization or an explicit unknown."""

    kind: CharacterizationKind
    provenance: str
    red_xy: tuple[str, str] | None
    green_xy: tuple[str, str] | None
    blue_xy: tuple[str, str] | None
    white_xy: tuple[str, str] | None
    nominal_gamma: str | None

    def __post_init__(self) -> None:
        if type(self.kind) is not CharacterizationKind:
            raise TypeError("kind must be CharacterizationKind")
        _require_nonblank_exact_string(self.provenance, field_name="provenance")
        numeric_fields = (
            ("red_xy", self.red_xy),
            ("green_xy", self.green_xy),
            ("blue_xy", self.blue_xy),
            ("white_xy", self.white_xy),
        )
        for field_name, value in numeric_fields:
            _validate_xy(value, field_name=field_name)
        gamma = None
        if self.nominal_gamma is not None:
            gamma = _parse_decimal_string(self.nominal_gamma, field_name="nominal_gamma")
            if gamma <= Decimal(0):
                raise ValueError("nominal_gamma must be positive")

        values = tuple(value for _, value in numeric_fields) + (self.nominal_gamma,)
        if self.kind is CharacterizationKind.UNKNOWN:
            if self.provenance != _UNKNOWN_PROVENANCE:
                raise ValueError(f"UNKNOWN provenance must be {_UNKNOWN_PROVENANCE!r}")
            if any(value is not None for value in values):
                raise ValueError("UNKNOWN characterization cannot contain numeric data")
        elif any(value is None for value in values):
            raise ValueError("complete characterization requires primaries, white point, and gamma")


@dataclass(frozen=True)
class DisplayObservation:
    """One immutable display observation built without opening a writer."""

    platform_display_id: str
    safe_label: str
    width_px: int
    height_px: int
    refresh_millihz: int
    hdr_enabled: bool | None
    characterization: PanelCharacterization
    capabilities: CapabilityState
    evidence: tuple[str, ...]

    def __post_init__(self) -> None:
        _require_nonblank_exact_string(self.platform_display_id, field_name="platform_display_id")
        _require_nonblank_exact_string(self.safe_label, field_name="safe_label")
        for field_name, value in (
            ("width_px", self.width_px),
            ("height_px", self.height_px),
            ("refresh_millihz", self.refresh_millihz),
        ):
            if type(value) is not int:
                raise TypeError(f"{field_name} must be an exact integer")
            if value <= 0:
                raise ValueError(f"{field_name} must be positive")
        if self.hdr_enabled is not None and type(self.hdr_enabled) is not bool:
            raise TypeError("hdr_enabled must be an exact boolean or None")
        if type(self.characterization) is not PanelCharacterization:
            raise TypeError("characterization must be PanelCharacterization")
        if type(self.capabilities) is not CapabilityState:
            raise TypeError("capabilities must be the canonical CapabilityState")
        frozen_evidence = _freeze_sequence(self.evidence, field_name="evidence", member_type=str)
        for entry in frozen_evidence:
            _require_nonblank_exact_string(entry, field_name="evidence entry")
        object.__setattr__(self, "evidence", frozen_evidence)


@dataclass(frozen=True)
class DashboardModel:
    """A complete dashboard snapshot replaced only as one immutable unit."""

    displays: tuple[DisplayObservation, ...]
    selected_display_id: str | None
    refreshed_utc: str

    def __post_init__(self) -> None:
        frozen_displays = _freeze_sequence(self.displays, field_name="displays", member_type=DisplayObservation)
        object.__setattr__(self, "displays", frozen_displays)
        display_ids = tuple(display.platform_display_id for display in frozen_displays)
        if len(display_ids) != len(set(display_ids)):
            raise ValueError("dashboard display IDs must be unique")
        if self.selected_display_id is not None:
            _require_nonblank_exact_string(self.selected_display_id, field_name="selected_display_id")
            if self.selected_display_id not in display_ids:
                raise ValueError("selected_display_id must identify a dashboard display")
        if type(self.refreshed_utc) is not str:
            raise TypeError("refreshed_utc must be an exact string")
        shape = _UTC_Z_RE.fullmatch(self.refreshed_utc)
        if shape is None:
            raise ValueError("refreshed_utc must be a parseable UTC timestamp ending in Z")
        # The fractional part is normalised to microseconds before parsing because
        # datetime.fromisoformat disagrees with itself across the interpreters this
        # package supports: 3.10 accepts only 3 or 6 fractional digits, and 3.11 onward
        # accepts any width and truncates past 6. Handing it a fixed width means the set
        # of timestamps this contract accepts is the set the pattern above describes,
        # rather than a set that moves with the runtime. Truncation, not rounding, keeps
        # the parsed instant identical to what 3.11 onward already produced.
        fraction = shape.group("fraction")
        microseconds = "" if fraction is None else f".{fraction[:6].ljust(6, '0')}"
        try:
            parsed = datetime.fromisoformat(f"{self.refreshed_utc[:19]}{microseconds}+00:00")
        except ValueError as exc:
            raise ValueError("refreshed_utc must be a parseable UTC timestamp ending in Z") from exc
        if parsed.utcoffset() != timedelta(0):
            raise ValueError("refreshed_utc must represent UTC")


__all__ = [
    "CharacterizationKind",
    "DashboardModel",
    "DisplayObservation",
    "EvidenceKind",
    "PHASE_ONE_EVIDENCE_KINDS",
    "PanelCharacterization",
]
