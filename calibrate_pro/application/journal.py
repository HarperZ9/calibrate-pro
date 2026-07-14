"""Type-only diagnostic journal boundary for the functional-recovery layer."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal, Protocol

if TYPE_CHECKING:
    from calibrate_pro.application.outcomes import ActionOutcome


@dataclass(frozen=True)
class JournalRecord:
    timestamp_utc: str
    correlation_id: str
    product_version: str
    runtime_mode: Literal["source", "frozen", "fake_acceptance"]
    platform_version: str
    action_id: str
    workflow_stage: str
    capability_flags: tuple[tuple[str, bool], ...]
    outcome: Literal["success", "failure"]
    exception_type: str | None
    error_code: str | None
    technical_category: str | None
    redacted_message: str | None
    display_pseudonym: str | None
    plan_sha256: str | None
    asset_sha256: tuple[str, ...]
    apply_phase_flags: tuple[tuple[str, bool], ...]
    recovery_guarantee: str | None
    export_basename: str | None
    export_sha256: str | None


class JournalSink(Protocol):
    def preflight(self, action_id: str, correlation_id: str) -> ActionOutcome[None]: ...

    def append_and_sync(self, record: JournalRecord) -> ActionOutcome[None]: ...


__all__ = ["JournalRecord", "JournalSink"]
