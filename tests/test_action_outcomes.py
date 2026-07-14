from __future__ import annotations

from dataclasses import dataclass, fields
from typing import NoReturn

import pytest

from calibrate_pro.application.journal import JournalRecord
from calibrate_pro.application.outcomes import (
    ActionBoundary,
    ActionError,
    ActionFailure,
    ActionOutcome,
    ActionSuccess,
)
from calibrate_pro.workflow import WorkflowStage


def _success(action_id: str, correlation_id: str, value: object = None) -> ActionSuccess[object]:
    return ActionSuccess(
        action_id=action_id,
        correlation_id=correlation_id,
        stage=WorkflowStage.PREVIEW,
        value=value,
    )


def _error(action_id: str, correlation_id: str, code: str = "JOURNAL_FAILURE") -> ActionError:
    return ActionError(
        action_id=action_id,
        code=code,
        summary="The injected journal failed.",
        retryable=True,
        next_action="Retry after diagnostics are available.",
        stage=WorkflowStage.PREVIEW,
        category="diagnostics",
        correlation_id=correlation_id,
        effect_state="none",
        published_artifact=None,
        apply_phase_flags=(),
        recovery_guarantee=None,
    )


class CorrelationIds:
    def __init__(self, value: str = "corr-0001") -> None:
        self.value = value
        self.calls = 0

    def __call__(self) -> str:
        self.calls += 1
        return self.value


class RecordingJournal:
    def __init__(self) -> None:
        self.events: list[tuple[str, object]] = []
        self.preflight_outcome: ActionOutcome[None] | None = None
        self.append_outcome: ActionOutcome[None] | None = None

    def preflight(self, action_id: str, correlation_id: str) -> ActionOutcome[None]:
        self.events.append(("preflight", (action_id, correlation_id)))
        return self.preflight_outcome or ActionSuccess(
            action_id=action_id,
            correlation_id=correlation_id,
            stage=WorkflowStage.PREVIEW,
            value=None,
        )

    def append_and_sync(self, record: JournalRecord) -> ActionOutcome[None]:
        self.events.append(("append", record))
        return self.append_outcome or ActionSuccess(
            action_id=record.action_id,
            correlation_id=record.correlation_id,
            stage=WorkflowStage(record.workflow_stage),
            value=None,
        )


def test_frozen_outcome_and_journal_record_shapes_are_exact():
    assert tuple(field.name for field in fields(ActionSuccess)) == ("action_id", "correlation_id", "stage", "value")
    assert tuple(field.name for field in fields(ActionError)) == (
        "action_id",
        "code",
        "summary",
        "retryable",
        "next_action",
        "stage",
        "category",
        "correlation_id",
        "effect_state",
        "published_artifact",
        "apply_phase_flags",
        "recovery_guarantee",
    )
    assert tuple(field.name for field in fields(JournalRecord)) == (
        "timestamp_utc",
        "correlation_id",
        "product_version",
        "runtime_mode",
        "platform_version",
        "action_id",
        "workflow_stage",
        "capability_flags",
        "outcome",
        "exception_type",
        "error_code",
        "technical_category",
        "redacted_message",
        "display_pseudonym",
        "plan_sha256",
        "asset_sha256",
        "apply_phase_flags",
        "recovery_guarantee",
        "export_basename",
        "export_sha256",
    )


def test_boundary_preserves_returned_typed_success_and_one_correlation_id():
    ids = CorrelationIds()
    journal = RecordingJournal()
    boundary = ActionBoundary(correlation_id_factory=ids, journal_sink=journal)
    expected = _success("display.detect", ids.value, {"displays": 1})

    actual = boundary.invoke("display.detect", WorkflowStage.PREVIEW, lambda: expected)

    assert actual is expected
    assert ids.calls == 1
    assert [event for event, _ in journal.events] == ["append"]
    record = journal.events[0][1]
    assert isinstance(record, JournalRecord)
    assert record.correlation_id == ids.value
    assert record.outcome == "success"


def test_boundary_converts_known_application_failure_to_stable_error():
    ids = CorrelationIds()
    journal = RecordingJournal()
    boundary = ActionBoundary(correlation_id_factory=ids, journal_sink=journal)

    def fail() -> NoReturn:
        raise ActionFailure(
            code="INVALID_ACTION_REQUEST",
            summary="The action request is invalid.",
            retryable=False,
            next_action=None,
            category="validation",
        )

    outcome = boundary.invoke("display.detect", WorkflowStage.PREVIEW, fail)

    assert isinstance(outcome, ActionError)
    assert outcome.code == "INVALID_ACTION_REQUEST"
    assert outcome.summary == "The action request is invalid."
    assert outcome.category == "validation"
    assert outcome.effect_state == "none"
    assert journal.events[-1][1].outcome == "failure"


def test_boundary_converts_unexpected_exception_and_never_reports_success():
    journal = RecordingJournal()
    boundary = ActionBoundary(correlation_id_factory=CorrelationIds(), journal_sink=journal)

    def fail() -> NoReturn:
        raise RuntimeError("private implementation detail")

    outcome = boundary.invoke("display.detect", WorkflowStage.PREVIEW, fail)

    assert isinstance(outcome, ActionError)
    assert outcome.code == "UNEXPECTED_ACTION_FAILURE"
    assert outcome.summary == "The action could not be completed."
    assert outcome.effect_state == "none"
    record = journal.events[-1][1]
    assert record.outcome == "failure"
    assert record.exception_type == "RuntimeError"


@pytest.mark.parametrize("interruption", [KeyboardInterrupt(), SystemExit(2)])
def test_boundary_never_swallows_process_control_exceptions(interruption: BaseException):
    boundary = ActionBoundary(correlation_id_factory=CorrelationIds(), journal_sink=RecordingJournal())

    def stop() -> NoReturn:
        raise interruption

    with pytest.raises(type(interruption)):
        boundary.invoke("display.detect", WorkflowStage.PREVIEW, stop)


@pytest.mark.parametrize("action_id", ["report.save", "fake_acceptance.apply"])
def test_boundary_preflights_before_receipt_required_local_effect(action_id: str):
    journal = RecordingJournal()
    boundary = ActionBoundary(correlation_id_factory=CorrelationIds(), journal_sink=journal)
    operation_events: list[str] = []

    def operation() -> ActionSuccess[None]:
        operation_events.append("operation")
        journal.events.append(("operation", None))
        return _success(action_id, "corr-0001", None)

    boundary.invoke(action_id, WorkflowStage.PREVIEW, operation)

    assert [event for event, _ in journal.events] == ["preflight", "operation", "append"]
    assert operation_events == ["operation"]


def test_preflight_failure_blocks_operation_with_no_effect():
    journal = RecordingJournal()
    journal.preflight_outcome = _error("report.save", "corr-0001")
    boundary = ActionBoundary(correlation_id_factory=CorrelationIds(), journal_sink=journal)
    invoked = False

    def operation() -> ActionSuccess[None]:
        nonlocal invoked
        invoked = True
        return _success("report.save", "corr-0001", None)

    outcome = boundary.invoke("report.save", WorkflowStage.PREVIEW, operation)

    assert isinstance(outcome, ActionError)
    assert outcome.code == "DIAGNOSTIC_JOURNAL_UNAVAILABLE"
    assert outcome.effect_state == "none"
    assert not invoked
    assert [event for event, _ in journal.events] == ["preflight"]


@dataclass(frozen=True)
class PublishedEvidence:
    published_artifact: tuple[str, str]


@dataclass(frozen=True)
class FakeApplyEvidence:
    apply_phase_flags: tuple[tuple[str, bool], ...]
    recovery_guarantee: str


def test_final_sync_failure_preserves_published_local_artifact_evidence():
    journal = RecordingJournal()
    journal.append_outcome = _error("report.save", "corr-0001")
    boundary = ActionBoundary(correlation_id_factory=CorrelationIds(), journal_sink=journal)
    evidence = PublishedEvidence(("report.json", "b" * 64))

    outcome = boundary.invoke(
        "report.save",
        WorkflowStage.PREVIEW,
        lambda: _success("report.save", "corr-0001", evidence),
    )

    assert isinstance(outcome, ActionError)
    assert outcome.code == "ACTION_COMPLETED_DIAGNOSTICS_FAILED"
    assert outcome.effect_state == "local_write_published"
    assert outcome.published_artifact == evidence.published_artifact
    assert outcome.apply_phase_flags == ()
    assert outcome.recovery_guarantee is None


def test_final_sync_failure_preserves_exact_fake_apply_evidence():
    journal = RecordingJournal()
    journal.append_outcome = _error("fake_acceptance.apply", "corr-0001")
    boundary = ActionBoundary(correlation_id_factory=CorrelationIds(), journal_sink=journal)
    evidence = FakeApplyEvidence(
        apply_phase_flags=(("captured", True), ("applied", True), ("verified", False), ("restored", True)),
        recovery_guarantee="in_process_best_effort",
    )

    outcome = boundary.invoke(
        "fake_acceptance.apply",
        WorkflowStage.PREVIEW,
        lambda: _success("fake_acceptance.apply", "corr-0001", evidence),
    )

    assert isinstance(outcome, ActionError)
    assert outcome.code == "ACTION_COMPLETED_DIAGNOSTICS_FAILED"
    assert outcome.effect_state == "fake_apply_attempted"
    assert outcome.published_artifact is None
    assert outcome.apply_phase_flags == evidence.apply_phase_flags
    assert outcome.recovery_guarantee == evidence.recovery_guarantee
