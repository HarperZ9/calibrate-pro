"""Phase 0 type foundations for the functional-recovery application layer."""

from __future__ import annotations

from enum import Enum

from calibrate_pro.verification.provenance import EvidenceKind


class CharacterizationKind(str, Enum):
    """The source of a display characterization used by Phase 0/1."""

    MATCHED = "matched"
    EXPLICIT_GENERIC = "explicit_generic"
    UNKNOWN = "unknown"


PHASE_ONE_EVIDENCE_KINDS = frozenset(
    {
        EvidenceKind.NOT_MEASURED,
        EvidenceKind.ESTIMATED,
        EvidenceKind.MEASURED,
    }
)


__all__ = ["CharacterizationKind", "EvidenceKind", "PHASE_ONE_EVIDENCE_KINDS"]
