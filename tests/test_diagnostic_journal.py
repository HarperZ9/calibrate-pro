from __future__ import annotations

import builtins
import hashlib
import json
import os
import subprocess
import sys
import textwrap
import threading
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import FrozenInstanceError, dataclass, fields, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, cast

import pytest

import calibrate_pro.application.journal as journal_module
import calibrate_pro.application.outcomes as outcomes_module
from calibrate_pro.application.journal import (
    DiagnosticJournal,
    JournalRecord,
    resolve_diagnostic_root,
)
from calibrate_pro.application.outcomes import (
    ActionBoundary,
    ActionError,
    ActionFailure,
    ActionSuccess,
)
from calibrate_pro.workflow import WorkflowStage

ALLOWLISTED_FIELDS = (
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


def _record(correlation_id: str = "correlation-Δ") -> JournalRecord:
    return JournalRecord(
        timestamp_utc="2026-07-13T12:34:56Z",
        correlation_id=correlation_id,
        product_version="1.2.3",
        runtime_mode="source",
        platform_version="Windows-Ü",
        action_id="diagnostics.test",
        workflow_stage="detect",
        capability_flags=(("hdr", True),),
        outcome="success",
        exception_type=None,
        error_code=None,
        technical_category=None,
        redacted_message=None,
        display_pseudonym=None,
        plan_sha256=None,
        asset_sha256=("ab" * 32,),
        apply_phase_flags=(("captured", True),),
        recovery_guarantee="restored",
        export_basename="report.zip",
        export_sha256="cd" * 32,
    )


def test_journal_record_field_order_is_the_exact_allowlist() -> None:
    assert tuple(field.name for field in fields(JournalRecord)) == ALLOWLISTED_FIELDS


def test_resolve_diagnostic_root_uses_absolute_local_app_data(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))

    assert resolve_diagnostic_root() == tmp_path / "Build Universe" / "Calibrate Pro" / "Diagnostics"


@pytest.mark.parametrize("value", ["", "   ", "relative-root"])
def test_resolve_diagnostic_root_rejects_empty_or_non_absolute_values(
    monkeypatch: pytest.MonkeyPatch,
    value: str,
) -> None:
    monkeypatch.setenv("LOCALAPPDATA", value)

    with pytest.raises(ValueError, match="LOCALAPPDATA"):
        resolve_diagnostic_root()


def test_resolve_diagnostic_root_rejects_missing_value(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("LOCALAPPDATA", raising=False)

    with pytest.raises(ValueError, match="LOCALAPPDATA"):
        resolve_diagnostic_root()


def test_preflight_returns_matching_typed_outcomes(tmp_path: Path) -> None:
    journal = DiagnosticJournal(tmp_path / "ok")
    success = journal.preflight("diagnostics.test", "correlation-ok")

    assert isinstance(success, ActionSuccess)
    assert (success.action_id, success.correlation_id, success.value) == (
        "diagnostics.test",
        "correlation-ok",
        None,
    )
    journal.cancel_preflight("diagnostics.test", "correlation-ok")

    blocker = tmp_path / "blocker"
    blocker.write_text("not a directory", encoding="utf-8")
    failure = DiagnosticJournal(blocker / "child").preflight(
        "diagnostics.test",
        "correlation-failed",
    )

    assert isinstance(failure, ActionError)
    assert (failure.action_id, failure.correlation_id, failure.category) == (
        "diagnostics.test",
        "correlation-failed",
        "diagnostics",
    )


def test_preflight_creates_one_physically_allocated_identity_free_reservation(
    tmp_path: Path,
) -> None:
    journal = DiagnosticJournal(tmp_path)

    outcome = journal.preflight("report.save", "correlation-reserved")

    assert isinstance(outcome, ActionSuccess)
    stages = list(tmp_path.glob(".diagnostics.reserve.*.tmp"))
    assert len(stages) == 1
    assert stages[0].stat().st_size == 1_048_576
    assert "report.save" not in stages[0].name
    assert "correlation-reserved" not in stages[0].name
    if os.name == "nt":
        with pytest.raises(PermissionError):
            stages[0].read_bytes()
    journal.cancel_preflight("report.save", "correlation-reserved")


def test_preflight_rotates_for_reserved_capacity_before_the_effect(tmp_path: Path) -> None:
    journal = DiagnosticJournal(tmp_path)
    journal.path.write_bytes(b"x" * (1_048_576 - 32_768))

    outcome = journal.preflight("report.save", "near-threshold-correlation")

    assert isinstance(outcome, ActionSuccess)
    assert journal.path.read_bytes() == b""
    assert journal.archive_paths[0].stat().st_size == 1_048_576 - 32_768
    assert len(list(tmp_path.glob(".diagnostics.reserve.*.tmp"))) == 1
    journal.cancel_preflight("report.save", "near-threshold-correlation")


def test_reservation_requires_exact_identity_and_is_consumed_once(tmp_path: Path) -> None:
    journal = DiagnosticJournal(tmp_path)
    assert isinstance(journal.preflight("report.save", "exact-correlation"), ActionSuccess)

    mismatch = journal.append_and_sync(
        replace(
            _record(),
            action_id="report.save",
            correlation_id="wrong-correlation",
        )
    )

    assert isinstance(mismatch, ActionError)
    assert len(list(tmp_path.glob(".diagnostics.reserve.*.tmp"))) == 1

    exact = journal.append_and_sync(
        replace(
            _record(),
            action_id="report.save",
            correlation_id="exact-correlation",
        )
    )
    repeated = journal.append_and_sync(
        replace(
            _record(),
            action_id="report.save",
            correlation_id="exact-correlation",
        )
    )

    assert isinstance(exact, ActionSuccess)
    assert isinstance(repeated, ActionError)
    assert not list(tmp_path.glob(".diagnostics.reserve.*.tmp"))


def test_boundary_cancels_successful_preflight_before_propagating_base_exception() -> None:
    events: list[tuple[str, str, str]] = []

    class CancellableJournal:
        def preflight(self, action_id: str, correlation_id: str) -> ActionSuccess[None]:
            events.append(("preflight", action_id, correlation_id))
            return ActionSuccess(action_id, correlation_id, WorkflowStage.PREVIEW, None)

        def append_and_sync(self, record: JournalRecord) -> ActionSuccess[None]:
            events.append(("append", record.action_id, record.correlation_id))
            return ActionSuccess(
                record.action_id,
                record.correlation_id,
                WorkflowStage(record.workflow_stage),
                None,
            )

        def cancel_preflight(self, action_id: str, correlation_id: str) -> None:
            events.append(("cancel", action_id, correlation_id))

    boundary = ActionBoundary(lambda: "cancel-correlation", CancellableJournal())

    with pytest.raises(KeyboardInterrupt):
        boundary.invoke(
            "report.save",
            WorkflowStage.PREVIEW,
            lambda: (_ for _ in ()).throw(KeyboardInterrupt()),
        )

    assert events == [
        ("preflight", "report.save", "cancel-correlation"),
        ("cancel", "report.save", "cancel-correlation"),
    ]


def test_duplicate_and_ninth_reservations_fail_with_staged_bytes_bounded(
    tmp_path: Path,
) -> None:
    journals = [DiagnosticJournal(tmp_path) for _ in range(9)]
    outcomes = [
        journal.preflight("report.save", f"bounded-correlation-{index}") for index, journal in enumerate(journals[:8])
    ]
    duplicate = DiagnosticJournal(tmp_path).preflight(
        "report.save",
        "bounded-correlation-0",
    )
    ninth = journals[8].preflight("report.save", "bounded-correlation-8")

    assert all(isinstance(outcome, ActionSuccess) for outcome in outcomes)
    assert isinstance(duplicate, ActionError)
    assert isinstance(ninth, ActionError)
    stages = list(tmp_path.glob(".diagnostics.reserve.*.tmp"))
    assert len(stages) == 8
    assert sum(stage.stat().st_size for stage in stages) == 8 * 1_048_576

    for index, journal in enumerate(journals[:8]):
        journal.cancel_preflight("report.save", f"bounded-correlation-{index}")
    assert not list(tmp_path.glob(".diagnostics.reserve.*.tmp"))


def _record_with_encoded_size(byte_length: int, correlation_id: str) -> JournalRecord:
    base = replace(
        _record(correlation_id),
        action_id="report.save",
        redacted_message="",
    )
    base_size = len(journal_module._encode_record(base).encode("utf-8"))
    assert base_size <= byte_length
    record = replace(base, redacted_message="x" * (byte_length - base_size))
    assert len(journal_module._encode_record(record).encode("utf-8")) == byte_length
    return record


def test_reserved_record_exact_bound_commits_and_plus_one_writes_compact_failure(
    tmp_path: Path,
) -> None:
    journal = DiagnosticJournal(tmp_path)
    exact = _record_with_encoded_size(65_536, "exact-bound-correlation")
    assert isinstance(
        journal.preflight("report.save", "exact-bound-correlation"),
        ActionSuccess,
    )

    exact_outcome = journal.append_and_sync(exact)

    assert isinstance(exact_outcome, ActionSuccess)
    assert journal.path.stat().st_size == 65_536

    oversized = _record_with_encoded_size(65_537, "oversized-bound-correlation")
    assert isinstance(
        journal.preflight("report.save", "oversized-bound-correlation"),
        ActionSuccess,
    )

    oversized_outcome = journal.append_and_sync(oversized)

    assert isinstance(oversized_outcome, ActionError)
    assert oversized_outcome.code == "DIAGNOSTIC_RECORD_BOUND_EXCEEDED"
    records = _json_lines(journal.path)
    assert records[-1]["correlation_id"] == "oversized-bound-correlation"
    assert records[-1]["outcome"] == "failure"
    assert records[-1]["error_code"] == "DIAGNOSTIC_RECORD_BOUND_EXCEEDED"
    assert records[-1]["redacted_message"] != oversized.redacted_message
    assert not list(tmp_path.glob(".diagnostics.reserve.*.tmp"))


def test_oversized_unknown_workflow_stage_still_has_a_bounded_failure_receipt(
    tmp_path: Path,
) -> None:
    journal = DiagnosticJournal(tmp_path)
    correlation_id = "oversized-workflow-correlation"
    unterminated_private_key = "-----BEGIN PRIVATE KEY-----\n" + "DIRECTSECRETMATERIAL" * 5_000
    record = replace(
        _record(correlation_id),
        action_id="report.save",
        workflow_stage="x" * 70_000,
        platform_version=unterminated_private_key,
        recovery_guarantee=unterminated_private_key,
    )
    assert isinstance(journal.preflight("report.save", correlation_id), ActionSuccess)

    try:
        outcome = journal.append_and_sync(record)

        assert isinstance(outcome, ActionError)
        assert outcome.code == "DIAGNOSTIC_RECORD_BOUND_EXCEEDED"
        persisted = _json_lines(journal.path)[-1]
        assert persisted["workflow_stage"] == WorkflowStage.DETECT.value
        assert persisted["platform_version"] == "platform-version-omitted"
        assert persisted["recovery_guarantee"] is None
        assert len(journal.path.read_bytes()) <= 65_536
        assert b"BEGIN PRIVATE KEY" not in journal.path.read_bytes()
        assert b"DIRECTSECRETMATERIAL" not in journal.path.read_bytes()
    finally:
        journal.cancel_preflight("report.save", correlation_id)


def test_oversized_reserved_boundary_receipt_preserves_exact_published_effect(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    journal = DiagnosticJournal(tmp_path)
    boundary = ActionBoundary(lambda: "published-bound-correlation", journal)
    published = ("report.json", "b" * 64)

    @dataclass(frozen=True)
    class Evidence:
        published_artifact: tuple[str, str]

    real_record = boundary._record

    def oversized_record(**kwargs: Any) -> JournalRecord:
        return replace(real_record(**kwargs), redacted_message="x" * 70_000)

    monkeypatch.setattr(boundary, "_record", oversized_record)

    outcome = boundary.invoke(
        "report.save",
        WorkflowStage.PREVIEW,
        lambda: ActionSuccess(
            "report.save",
            "published-bound-correlation",
            WorkflowStage.PREVIEW,
            Evidence(published),
        ),
    )

    assert isinstance(outcome, ActionError)
    assert outcome.code == "ACTION_COMPLETED_DIAGNOSTICS_FAILED"
    assert outcome.effect_state == "local_write_published"
    assert outcome.published_artifact == published
    record = _json_lines(journal.path)[-1]
    assert (record["export_basename"], record["export_sha256"]) == published
    assert record["error_code"] == "DIAGNOSTIC_RECORD_BOUND_EXCEEDED"
    assert not list(tmp_path.glob(".diagnostics.reserve.*.tmp"))


def test_boundary_bounds_ordinary_action_failure_before_record_construction_without_secret_fragments(
    tmp_path: Path,
) -> None:
    journal = DiagnosticJournal(tmp_path)
    boundary = ActionBoundary(lambda: "bounded-failure-correlation", journal)
    private_key = "-----BEGIN PRIVATE KEY-----\n" + "SENSITIVEKEYMATERIAL" * 5_000 + "\n-----END PRIVATE KEY-----"
    oversized_code = "錯" * 400
    oversized_category = "類" * 400
    oversized_flags = tuple(((f"phase-{index}-" + "秘密" * 80), index % 2 == 0) for index in range(40))
    published = ("bounded-report.json", "a" * 64)

    def fail() -> Any:
        raise ActionFailure(
            code=oversized_code,
            summary=private_key,
            retryable=False,
            next_action=None,
            category=oversized_category,
            effect_state="local_write_published",
            published_artifact=published,
            apply_phase_flags=oversized_flags,
            recovery_guarantee=private_key,
        )

    outcome = boundary.invoke("report.save", WorkflowStage.PREVIEW, fail)

    assert isinstance(outcome, ActionError)
    assert outcome.code == oversized_code
    assert outcome.summary == private_key
    assert outcome.category == oversized_category
    assert outcome.published_artifact == published
    assert outcome.apply_phase_flags == oversized_flags
    assert outcome.recovery_guarantee == private_key
    raw = journal.path.read_bytes()
    record = _json_lines(journal.path)[-1]
    assert len(raw) < 65_536
    assert len(record["redacted_message"].encode("utf-8")) <= 8_192
    assert len(record["error_code"].encode("utf-8")) <= 256
    assert len(record["technical_category"].encode("utf-8")) <= 256
    assert len(record["exception_type"].encode("utf-8")) <= 256
    assert record["apply_phase_flags"] == []
    assert record["recovery_guarantee"] is None
    assert (record["export_basename"], record["export_sha256"]) == published
    assert b"BEGIN PRIVATE KEY" not in raw
    assert b"SENSITIVEKEYMATERIAL" not in raw
    assert "秘密".encode() not in raw
    assert not list(tmp_path.glob(".diagnostics.reserve.*.tmp"))


def test_boundary_bounds_dynamic_exception_type_and_rejects_oversized_correlation(
    tmp_path: Path,
) -> None:
    exception_journal = DiagnosticJournal(tmp_path / "exception")
    exception_boundary = ActionBoundary(lambda: "bounded-exception-correlation", exception_journal)
    oversized_exception = type("Oversized" + "X" * 2_000, (Exception,), {})

    def fail() -> Any:
        raise oversized_exception("private exception detail")

    exception_outcome = exception_boundary.invoke(
        "report.save",
        WorkflowStage.PREVIEW,
        fail,
    )

    assert isinstance(exception_outcome, ActionError)
    exception_record = _json_lines(exception_journal.path)[-1]
    assert len(exception_record["exception_type"].encode("utf-8")) <= 256
    assert len(exception_journal.path.read_bytes()) < 65_536

    correlation_journal = DiagnosticJournal(tmp_path / "correlation")
    operation_invoked = False
    oversized_correlation = "關" * 300

    def operation() -> ActionSuccess[None]:
        nonlocal operation_invoked
        operation_invoked = True
        return ActionSuccess(
            "display.detect",
            oversized_correlation,
            WorkflowStage.PREVIEW,
            None,
        )

    correlation_outcome = ActionBoundary(
        lambda: oversized_correlation,
        correlation_journal,
    ).invoke("display.detect", WorkflowStage.PREVIEW, operation)

    assert isinstance(correlation_outcome, ActionError)
    assert correlation_outcome.code == "CORRELATION_ID_UNAVAILABLE"
    assert not operation_invoked
    correlation_record = _json_lines(correlation_journal.path)[-1]
    assert len(correlation_record["correlation_id"].encode("utf-8")) <= 512


def test_boundary_preserves_valid_fake_apply_evidence_and_drops_overbound_evidence(
    tmp_path: Path,
) -> None:
    @dataclass(frozen=True)
    class FakeEvidence:
        apply_phase_flags: tuple[tuple[str, bool], ...]
        recovery_guarantee: str

    valid_flags = (
        ("captured", True),
        ("applied", True),
        ("verified", True),
        ("restore_attempted", False),
        ("restored", False),
    )
    valid_journal = DiagnosticJournal(tmp_path / "valid")
    valid_boundary = ActionBoundary(lambda: "valid-fake-correlation", valid_journal)
    valid_outcome = valid_boundary.invoke(
        "fake_acceptance.apply",
        WorkflowStage.PREVIEW,
        lambda: ActionSuccess(
            "fake_acceptance.apply",
            "valid-fake-correlation",
            WorkflowStage.PREVIEW,
            FakeEvidence(valid_flags, "in_process_best_effort"),
        ),
    )

    assert isinstance(valid_outcome, ActionSuccess)
    valid_record = _json_lines(valid_journal.path)[-1]
    assert valid_record["apply_phase_flags"] == [list(pair) for pair in valid_flags]
    assert valid_record["recovery_guarantee"] == "in_process_best_effort"
    assert len(valid_journal.path.read_bytes()) < 65_536

    invalid_flags = tuple((("oversized-secret-key-" + "K" * 200), True) for _ in range(40))
    invalid_recovery = "-----BEGIN PRIVATE KEY-----" + "R" * 70_000
    invalid_journal = DiagnosticJournal(tmp_path / "invalid")
    invalid_boundary = ActionBoundary(lambda: "invalid-fake-correlation", invalid_journal)
    invalid_outcome = invalid_boundary.invoke(
        "fake_acceptance.apply",
        WorkflowStage.PREVIEW,
        lambda: ActionSuccess(
            "fake_acceptance.apply",
            "invalid-fake-correlation",
            WorkflowStage.PREVIEW,
            FakeEvidence(invalid_flags, invalid_recovery),
        ),
    )

    assert isinstance(invalid_outcome, ActionSuccess)
    invalid_raw = invalid_journal.path.read_bytes()
    invalid_record = _json_lines(invalid_journal.path)[-1]
    assert invalid_record["apply_phase_flags"] == []
    assert invalid_record["recovery_guarantee"] is None
    assert b"oversized-secret-key" not in invalid_raw
    assert b"BEGIN PRIVATE KEY" not in invalid_raw
    assert len(invalid_raw) < 65_536


def test_boundary_preserves_valid_export_and_drops_invalid_export_evidence(
    tmp_path: Path,
) -> None:
    @dataclass(frozen=True)
    class ExportEvidence:
        published_artifact: tuple[str, str]

    valid = ("valid-report.json", "b" * 64)
    valid_journal = DiagnosticJournal(tmp_path / "valid-export")
    valid_outcome = ActionBoundary(lambda: "valid-export-correlation", valid_journal).invoke(
        "report.save",
        WorkflowStage.PREVIEW,
        lambda: ActionSuccess(
            "report.save",
            "valid-export-correlation",
            WorkflowStage.PREVIEW,
            ExportEvidence(valid),
        ),
    )
    assert isinstance(valid_outcome, ActionSuccess)
    valid_record = _json_lines(valid_journal.path)[-1]
    assert (valid_record["export_basename"], valid_record["export_sha256"]) == valid

    invalid_journal = DiagnosticJournal(tmp_path / "invalid-export")
    invalid_outcome = ActionBoundary(
        lambda: "invalid-export-correlation",
        invalid_journal,
    ).invoke(
        "report.save",
        WorkflowStage.PREVIEW,
        lambda: ActionSuccess(
            "report.save",
            "invalid-export-correlation",
            WorkflowStage.PREVIEW,
            ExportEvidence(("../private-report.json", "z" * 64)),
        ),
    )
    assert isinstance(invalid_outcome, ActionSuccess)
    invalid_record = _json_lines(invalid_journal.path)[-1]
    assert invalid_record["export_basename"] is None
    assert invalid_record["export_sha256"] is None


def test_boundary_worst_case_json_escaping_stays_inside_reserved_record_budget(
    tmp_path: Path,
) -> None:
    correlation_id = "\0" * outcomes_module._BOUNDARY_IDENTITY_MAX_BYTES
    message = "\0" * outcomes_module._BOUNDARY_MESSAGE_MAX_BYTES
    error_code = "\0" * outcomes_module._BOUNDARY_SCALAR_MAX_BYTES
    category = "\0" * outcomes_module._BOUNDARY_SCALAR_MAX_BYTES
    recovery = "\0" * outcomes_module._BOUNDARY_RECOVERY_MAX_BYTES
    phase_flags = tuple(
        ("\0" * outcomes_module._BOUNDARY_PHASE_KEY_MAX_BYTES, True)
        for _ in range(outcomes_module._BOUNDARY_PHASE_FLAG_MAX_COUNT)
    )
    journal = DiagnosticJournal(tmp_path)
    boundary = ActionBoundary(lambda: correlation_id, journal)

    def fail() -> Any:
        raise ActionFailure(
            code=error_code,
            summary=message,
            retryable=False,
            next_action=None,
            category=category,
            effect_state="fake_apply_attempted",
            apply_phase_flags=phase_flags,
            recovery_guarantee=recovery,
        )

    outcome = boundary.invoke("fake_acceptance.apply", WorkflowStage.PREVIEW, fail)

    assert isinstance(outcome, ActionError)
    assert outcome.code == error_code
    record = _json_lines(journal.path)[-1]
    assert record["error_code"] != "DIAGNOSTIC_RECORD_BOUND_EXCEEDED"
    assert record["apply_phase_flags"] == [list(pair) for pair in phase_flags]
    assert len(journal.path.read_bytes()) <= 65_536


def test_preflight_physically_fills_and_syncs_the_entire_reserved_stage(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    written_bytes = 0
    fsync_calls = 0
    real_write_all = journal_module._write_all
    real_fsync = journal_module.os.fsync

    def write_spy(file_descriptor: int, payload: bytes) -> None:
        nonlocal written_bytes
        written_bytes += len(payload)
        real_write_all(file_descriptor, payload)

    def fsync_spy(file_descriptor: int) -> None:
        nonlocal fsync_calls
        fsync_calls += 1
        real_fsync(file_descriptor)

    monkeypatch.setattr(journal_module, "_write_all", write_spy)
    monkeypatch.setattr(journal_module.os, "fsync", fsync_spy)
    journal = DiagnosticJournal(tmp_path)

    outcome = journal.preflight("report.save", "fill-and-sync-correlation")

    try:
        assert isinstance(outcome, ActionSuccess)
        assert written_bytes == 1_048_576
        assert fsync_calls >= 2
        assert next(tmp_path.glob(".diagnostics.reserve.*.tmp")).stat().st_size == 1_048_576
    finally:
        journal.cancel_preflight("report.save", "fill-and-sync-correlation")


@pytest.mark.parametrize("fault", ["open", "write", "lock", "fsync", "rotation"])
def test_every_predictable_preflight_fault_blocks_and_cleans_before_operation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    fault: str,
) -> None:
    journal = DiagnosticJournal(tmp_path)
    if fault == "rotation":
        journal.path.write_bytes(b"x" * (1_048_576 - 32_768))

    with monkeypatch.context() as injected:
        if fault == "open":
            real_open = journal_module.os.open

            def fail_stage_open(path: str, flags: int, mode: int = 0o777) -> int:
                if ".diagnostics.reserve." in os.fspath(path):
                    raise OSError("injected reservation open failure")
                return real_open(path, flags, mode)

            injected.setattr(journal_module.os, "open", fail_stage_open)
        elif fault == "write":
            real_write_all = journal_module._write_all

            def fail_stage_write(file_descriptor: int, payload: bytes) -> None:
                if len(payload) == 65_536:
                    raise OSError("injected reservation allocation failure")
                real_write_all(file_descriptor, payload)

            injected.setattr(journal_module, "_write_all", fail_stage_write)
        elif fault == "lock":
            real_lock = journal_module._lock_file_descriptor
            lock_calls = 0

            def fail_stage_lock(file_descriptor: int) -> None:
                nonlocal lock_calls
                lock_calls += 1
                if lock_calls == 2:
                    raise OSError("injected reservation lock failure")
                real_lock(file_descriptor)

            injected.setattr(journal_module, "_lock_file_descriptor", fail_stage_lock)
        elif fault == "fsync":
            real_fsync = journal_module.os.fsync
            fsync_calls = 0

            def fail_stage_fsync(file_descriptor: int) -> None:
                nonlocal fsync_calls
                fsync_calls += 1
                if fsync_calls == 2:
                    raise OSError("injected reservation fsync failure")
                real_fsync(file_descriptor)

            injected.setattr(journal_module.os, "fsync", fail_stage_fsync)
        else:
            injected.setattr(
                journal,
                "_rotate",
                lambda: (_ for _ in ()).throw(OSError("injected preflight rotation failure")),
            )

        outcome = journal.preflight("report.save", f"preflight-fault-{fault}")

    assert isinstance(outcome, ActionError)
    assert outcome.code == "DIAGNOSTIC_JOURNAL_UNAVAILABLE"
    assert not list(tmp_path.glob(".diagnostics.reserve.*.tmp"))
    retry = journal.preflight("report.save", f"preflight-retry-{fault}")
    try:
        assert isinstance(retry, ActionSuccess)
    finally:
        journal.cancel_preflight("report.save", f"preflight-retry-{fault}")


def test_unlocked_partial_reservation_stage_is_reaped_before_new_reservation(
    tmp_path: Path,
) -> None:
    tmp_path.mkdir(parents=True, exist_ok=True)
    abandoned = tmp_path / (".diagnostics.reserve." + "a" * 32 + ".tmp")
    abandoned.write_bytes(b"")
    journal = DiagnosticJournal(tmp_path)

    outcome = journal.preflight("report.save", "partial-stage-recovery")

    try:
        assert isinstance(outcome, ActionSuccess)
        assert not abandoned.exists()
        assert len(list(tmp_path.glob(".diagnostics.reserve.*.tmp"))) == 1
    finally:
        journal.cancel_preflight("report.save", "partial-stage-recovery")


@pytest.mark.parametrize("stage_kind", ["live-malformed-size", "ambiguous-lock"])
def test_live_malformed_or_ambiguous_reservation_fails_closed_and_is_retained(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    stage_kind: str,
) -> None:
    tmp_path.mkdir(parents=True, exist_ok=True)
    stage = tmp_path / (".diagnostics.reserve." + "a" * 32 + ".tmp")
    stage.write_bytes(b"x" if stage_kind == "live-malformed-size" else bytes(1_048_576))
    live_descriptor: int | None = None
    if stage_kind == "live-malformed-size":
        live_descriptor = os.open(os.fspath(stage), os.O_RDWR | getattr(os, "O_BINARY", 0))
        journal_module._lock_file_descriptor(live_descriptor)
    if stage_kind == "ambiguous-lock":
        real_lock_once = journal_module._lock_file_descriptor_once

        def ambiguous_for_stage(file_descriptor: int) -> str:
            if os.fstat(file_descriptor).st_size == 1_048_576:
                return "ambiguous"
            return real_lock_once(file_descriptor)

        monkeypatch.setattr(journal_module, "_lock_file_descriptor_once", ambiguous_for_stage)

    try:
        outcome = DiagnosticJournal(tmp_path).preflight(
            "report.save",
            f"{stage_kind}-correlation",
        )

        assert isinstance(outcome, ActionError)
        assert outcome.code == "DIAGNOSTIC_JOURNAL_UNAVAILABLE"
        assert stage.exists()
    finally:
        if live_descriptor is not None:
            journal_module._unlock_file_descriptor(live_descriptor)
            os.close(live_descriptor)
        stage.unlink(missing_ok=True)


@pytest.mark.parametrize(
    ("busy_seconds", "acquires"),
    [(1.5, True), (7.5, True), (8.5, False)],
)
def test_a_busy_root_lock_is_waited_out_across_the_queue_the_design_admits(
    monkeypatch: pytest.MonkeyPatch,
    busy_seconds: float,
    acquires: bool,
) -> None:
    """A lock held by another process is contention, not an unavailable journal.

    Each holder stages a journal-sized reservation and fsyncs it before it
    releases, so a caller behind a full queue waits for every one of them. A
    deadline that expires first is reported to the operator as an unavailable
    journal, and the action that wanted a receipt does not get one.

    The wait is driven off a clock the test owns rather than a real disk, so
    the case names the duration it is asserting about. The 1.5 s case is the
    one that matters for the regression: it is inside the queue the design
    admits and outside a flat one-second deadline.
    """

    class _Clock:
        def __init__(self) -> None:
            self.now = 0.0

        def monotonic(self) -> float:
            return self.now

        def sleep(self, seconds: float) -> None:
            self.now += seconds

    clock = _Clock()
    monkeypatch.setattr(journal_module, "time", clock)
    monkeypatch.setattr(
        journal_module,
        "_lock_file_descriptor_once",
        lambda file_descriptor: "busy" if clock.now < busy_seconds else "acquired",
    )

    if acquires:
        assert journal_module._lock_file_descriptor(-1) is None
        assert clock.now >= busy_seconds
    else:
        with pytest.raises(TimeoutError):
            journal_module._lock_file_descriptor(-1)


@pytest.mark.parametrize(
    ("fault", "call_number"),
    [("write", 1), ("fsync", 1), ("fsync", 2), ("truncate", 1), ("replace", 1)],
)
def test_reserved_final_fault_preserves_prior_active_and_releases_reservation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    fault: str,
    call_number: int,
) -> None:
    journal = DiagnosticJournal(tmp_path)
    assert isinstance(journal.append_and_sync(_record("prior-final-fault")), ActionSuccess)
    prior = journal.path.read_bytes()
    correlation_id = f"reserved-final-{fault}-{call_number}"
    assert isinstance(journal.preflight("report.save", correlation_id), ActionSuccess)
    record = replace(_record(correlation_id), action_id="report.save")

    with monkeypatch.context() as injected:
        calls = 0
        if fault == "write":
            real = journal_module.os.write
            attribute = "write"
        elif fault == "fsync":
            real = journal_module.os.fsync
            attribute = "fsync"
        elif fault == "truncate":
            real = journal_module.os.ftruncate
            attribute = "ftruncate"
        else:
            real = journal_module.os.replace
            attribute = "replace"

        def fail_selected(*args: Any) -> Any:
            nonlocal calls
            calls += 1
            if calls == call_number:
                raise OSError(f"injected reserved {fault} failure")
            return real(*args)

        injected.setattr(journal_module.os, attribute, fail_selected)
        outcome = journal.append_and_sync(record)

    assert isinstance(outcome, ActionError)
    assert outcome.code == "DIAGNOSTIC_JOURNAL_WRITE_FAILED"
    assert journal.path.read_bytes() == prior
    assert not list(tmp_path.glob(".diagnostics.reserve.*.tmp"))
    assert isinstance(journal.append_and_sync(record), ActionError)
    retry = journal.preflight("report.save", f"retry-{correlation_id}")
    try:
        assert isinstance(retry, ActionSuccess)
    finally:
        journal.cancel_preflight("report.save", f"retry-{correlation_id}")


@pytest.mark.parametrize("injected", [RuntimeError("encode fault"), KeyboardInterrupt()])
def test_reserved_compact_second_encode_fault_always_releases_reservation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    injected: BaseException,
) -> None:
    journal = DiagnosticJournal(tmp_path)
    assert isinstance(journal.append_and_sync(_record("prior-compact-encode")), ActionSuccess)
    prior = journal.path.read_bytes()
    correlation_id = f"compact-encode-{type(injected).__name__}"
    oversized = _record_with_encoded_size(65_537, correlation_id)
    assert isinstance(journal.preflight("report.save", correlation_id), ActionSuccess)
    real_encode = journal_module._encode_record
    encode_calls = 0

    def fail_second_encode(record: JournalRecord, redactor: Any = None) -> str:
        nonlocal encode_calls
        encode_calls += 1
        if encode_calls == 2:
            raise injected
        return real_encode(record, redactor)

    with monkeypatch.context() as fault:
        fault.setattr(journal_module, "_encode_record", fail_second_encode)
        if isinstance(injected, Exception):
            try:
                outcome: object = journal.append_and_sync(oversized)
            except Exception as error:
                outcome = error
        else:
            with pytest.raises(type(injected)):
                journal.append_and_sync(oversized)
            outcome = None

    if isinstance(injected, Exception):
        assert isinstance(outcome, ActionError)
        assert outcome.code == "DIAGNOSTIC_JOURNAL_WRITE_FAILED"
    assert encode_calls == 2
    assert journal.path.read_bytes() == prior
    assert not list(tmp_path.glob(".diagnostics.reserve.*.tmp"))

    retry = journal.preflight("report.save", correlation_id)
    try:
        assert isinstance(retry, ActionSuccess)
    finally:
        journal.cancel_preflight("report.save", correlation_id)


def test_failed_abandoned_stage_unlink_repeatedly_fails_closed_without_growth(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tmp_path.mkdir(parents=True, exist_ok=True)
    abandoned = tmp_path / (".diagnostics.reserve." + "d" * 32 + ".tmp")
    abandoned.write_bytes(bytes(1_048_576))
    journal = DiagnosticJournal(tmp_path)
    real_unlink = journal_module.os.unlink

    def fail_abandoned_unlink(path: str | os.PathLike[str]) -> None:
        if Path(path) == abandoned:
            raise OSError("injected abandoned-stage unlink failure")
        real_unlink(path)

    try:
        with monkeypatch.context() as fault:
            fault.setattr(journal_module.os, "unlink", fail_abandoned_unlink)
            first = journal.preflight("report.save", "unlink-failure-first")
            second = journal.preflight("report.save", "unlink-failure-second")

            assert isinstance(first, ActionError)
            assert isinstance(second, ActionError)
            assert first.code == second.code == "DIAGNOSTIC_JOURNAL_UNAVAILABLE"
            stages = list(tmp_path.glob(".diagnostics.reserve.*.tmp"))
            assert stages == [abandoned]
            assert sum(stage.stat().st_size for stage in stages) == 1_048_576

        recovered = journal.preflight("report.save", "unlink-recovered")
        try:
            assert isinstance(recovered, ActionSuccess)
            assert not abandoned.exists()
            assert len(list(tmp_path.glob(".diagnostics.reserve.*.tmp"))) == 1
        finally:
            journal.cancel_preflight("report.save", "unlink-recovered")
    finally:
        journal.cancel_preflight("report.save", "unlink-failure-first")
        journal.cancel_preflight("report.save", "unlink-failure-second")
        abandoned.unlink(missing_ok=True)


def test_overlong_text_is_rejected_before_encoding_adjacent_bytes_length(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    text = "abcde"
    encoded = b"abcde"
    events: list[str] = []
    real_len = builtins.len

    def len_spy(value: Any) -> int:
        if value is text:
            events.append("str")
        elif value == encoded and type(value) is bytes:
            events.append("bytes")
        return real_len(value)

    with monkeypatch.context() as instrumented:
        instrumented.setattr(builtins, "len", len_spy)
        accepted = outcomes_module._is_bounded_utf8_text(text, 4)

    assert accepted is False
    assert events == ["str"]


def test_twenty_sequential_receipt_actions_do_not_rotate_per_action(tmp_path: Path) -> None:
    journal = DiagnosticJournal(tmp_path)
    next_id = 0
    current_id = ""
    rotations = 0
    real_rotate = journal._rotate

    def correlation_factory() -> str:
        nonlocal next_id, current_id
        current_id = f"sequential-correlation-{next_id}"
        next_id += 1
        return current_id

    def rotate_spy() -> None:
        nonlocal rotations
        rotations += 1
        real_rotate()

    journal._rotate = rotate_spy  # type: ignore[method-assign]
    boundary = ActionBoundary(correlation_factory, journal)

    outcomes = [
        boundary.invoke(
            "report.save",
            WorkflowStage.PREVIEW,
            lambda: ActionSuccess(
                "report.save",
                current_id,
                WorkflowStage.PREVIEW,
                None,
            ),
        )
        for _ in range(20)
    ]

    assert all(isinstance(outcome, ActionSuccess) for outcome in outcomes)
    assert rotations < 20
    assert len(_json_lines(journal.path)) == 20
    assert not list(tmp_path.glob(".diagnostics.reserve.*.tmp"))


def test_boundary_rotates_and_creates_stage_only_before_the_local_effect(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    journal = DiagnosticJournal(tmp_path)
    journal.path.write_bytes(b"x" * (1_048_576 - 32_768))
    events: list[tuple[str, bool]] = []
    effect_started = False
    real_rotate = journal._rotate
    real_create = journal._create_reservation
    real_open = journal_module.os.open

    def rotate_spy() -> None:
        events.append(("rotate", effect_started))
        real_rotate()

    def create_spy(action_id: str, correlation_id: str) -> Any:
        events.append(("stage", effect_started))
        return real_create(action_id, correlation_id)

    def open_spy(path: str, flags: int, mode: int = 0o777) -> int:
        if effect_started and os.fspath(path).endswith(".tmp"):
            pytest.fail("reserved finalization created a sibling temp after the effect")
        return real_open(path, flags, mode)

    journal._rotate = rotate_spy  # type: ignore[method-assign]
    journal._create_reservation = create_spy  # type: ignore[method-assign]
    monkeypatch.setattr(journal_module.os, "open", open_spy)
    monkeypatch.setattr(
        journal,
        "_append_atomically",
        lambda _line: pytest.fail("reserved finalization used the normal append temp"),
    )
    boundary = ActionBoundary(lambda: "ordered-correlation", journal)

    def operation() -> ActionSuccess[None]:
        nonlocal effect_started
        effect_started = True
        events.append(("effect", True))
        return ActionSuccess(
            "report.save",
            "ordered-correlation",
            WorkflowStage.PREVIEW,
            None,
        )

    outcome = boundary.invoke("report.save", WorkflowStage.PREVIEW, operation)

    assert isinstance(outcome, ActionSuccess)
    assert events == [("rotate", False), ("stage", False), ("effect", True)]
    assert not list(tmp_path.glob(".diagnostics.reserve.*.tmp"))


def test_full_reservation_identity_matrix_preserves_unrelated_read_only_append(
    tmp_path: Path,
) -> None:
    journal = DiagnosticJournal(tmp_path)
    action_id = "report.save"
    correlation_id = "identity-matrix-correlation"
    assert isinstance(journal.preflight(action_id, correlation_id), ActionSuccess)

    try:
        wrong_action = journal.append_and_sync(replace(_record(correlation_id), action_id="report.export"))
        wrong_correlation = journal.append_and_sync(replace(_record("identity-matrix-wrong"), action_id=action_id))
        duplicate = DiagnosticJournal(tmp_path).preflight(action_id, correlation_id)
        unrelated = journal.append_and_sync(
            replace(
                _record("identity-matrix-unrelated"),
                action_id="display.detect",
            )
        )

        assert isinstance(wrong_action, ActionError)
        assert isinstance(wrong_correlation, ActionError)
        assert isinstance(duplicate, ActionError)
        assert isinstance(unrelated, ActionSuccess)
        assert len(list(tmp_path.glob(".diagnostics.reserve.*.tmp"))) == 1

        exact_record = replace(_record(correlation_id), action_id=action_id)
        assert isinstance(journal.append_and_sync(exact_record), ActionSuccess)
        assert isinstance(journal.append_and_sync(exact_record), ActionError)
    finally:
        journal.cancel_preflight(action_id, correlation_id)


@pytest.mark.parametrize("identity_gap", ["exact", "partial"])
def test_normal_append_rechecks_identity_after_matching_preflight_enters_gap(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    identity_gap: str,
) -> None:
    normal_journal = DiagnosticJournal(tmp_path)
    reserving_journal = DiagnosticJournal(tmp_path)
    normal_key = ("report.save", "identity-gap-normal")
    reserved_key = normal_key if identity_gap == "exact" else (normal_key[0], "identity-gap-partial")
    classification_complete = threading.Event()
    allow_root_entry = threading.Event()
    real_exclusive_root = normal_journal._exclusive_root

    @contextmanager
    def paused_exclusive_root() -> Any:
        classification_complete.set()
        assert allow_root_entry.wait(timeout=10.0)
        with real_exclusive_root():
            yield

    monkeypatch.setattr(normal_journal, "_exclusive_root", paused_exclusive_root)
    normal_record = replace(
        _record(normal_key[1]),
        action_id=normal_key[0],
    )
    try:
        with ThreadPoolExecutor(max_workers=1) as executor:
            pending = executor.submit(normal_journal.append_and_sync, normal_record)
            assert classification_complete.wait(timeout=10.0)
            reserved = reserving_journal.preflight(*reserved_key)
            assert isinstance(reserved, ActionSuccess)
            allow_root_entry.set()
            raced_outcome = pending.result(timeout=10.0)

        assert isinstance(raced_outcome, ActionError)
        assert raced_outcome.code == "DIAGNOSTIC_RESERVATION_MISMATCH"
        assert len(list(tmp_path.glob(".diagnostics.reserve.*.tmp"))) == 1

        reserved_record = replace(
            _record(reserved_key[1]),
            action_id=reserved_key[0],
        )
        assert isinstance(reserving_journal.append_and_sync(reserved_record), ActionSuccess)
        assert isinstance(reserving_journal.append_and_sync(reserved_record), ActionError)
        records = _json_lines(reserving_journal.path)
        assert [record["correlation_id"] for record in records] == [reserved_key[1]]
    finally:
        allow_root_entry.set()
        reserving_journal.cancel_preflight(*reserved_key)


def test_multiple_instances_and_threads_share_the_eight_reservation_cap(
    tmp_path: Path,
) -> None:
    journals = [DiagnosticJournal(tmp_path) for _ in range(9)]
    correlations = [f"thread-reservation-{index}" for index in range(9)]
    try:
        with ThreadPoolExecutor(max_workers=8) as executor:
            reservations = list(
                executor.map(
                    lambda pair: pair[0].preflight("report.save", pair[1]),
                    zip(journals[:8], correlations[:8], strict=True),
                )
            )
        ninth = journals[8].preflight("report.save", correlations[8])

        assert all(isinstance(outcome, ActionSuccess) for outcome in reservations)
        assert isinstance(ninth, ActionError)
        assert len(list(tmp_path.glob(".diagnostics.reserve.*.tmp"))) == 8

        with ThreadPoolExecutor(max_workers=8) as executor:
            appends = list(
                executor.map(
                    lambda pair: pair[0].append_and_sync(replace(_record(pair[1]), action_id="report.save")),
                    zip(journals[:8], correlations[:8], strict=True),
                )
            )
        assert all(isinstance(outcome, ActionSuccess) for outcome in appends)
        assert len(_json_lines(journals[0].path)) == 8
        assert not list(tmp_path.glob(".diagnostics.reserve.*.tmp"))
    finally:
        for journal, correlation_id in zip(journals, correlations, strict=True):
            journal.cancel_preflight("report.save", correlation_id)


def test_real_reservations_cancel_on_system_exit_record_build_and_effect_recovery_faults(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    system_journal = DiagnosticJournal(tmp_path / "system-exit")
    with pytest.raises(SystemExit):
        ActionBoundary(lambda: "system-exit-correlation", system_journal).invoke(
            "report.save",
            WorkflowStage.PREVIEW,
            lambda: (_ for _ in ()).throw(SystemExit(2)),
        )
    assert not list((tmp_path / "system-exit").glob(".diagnostics.reserve.*.tmp"))

    record_journal = DiagnosticJournal(tmp_path / "record-build")
    record_boundary = ActionBoundary(lambda: "record-build-correlation", record_journal)
    monkeypatch.setattr(
        record_boundary,
        "_record",
        lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("record build fault")),
    )
    record_outcome = record_boundary.invoke(
        "report.save",
        WorkflowStage.PREVIEW,
        lambda: ActionSuccess(
            "report.save",
            "record-build-correlation",
            WorkflowStage.PREVIEW,
            None,
        ),
    )
    assert isinstance(record_outcome, ActionError)
    assert not list((tmp_path / "record-build").glob(".diagnostics.reserve.*.tmp"))

    effect_journal = DiagnosticJournal(tmp_path / "effect-recovery")
    effect_boundary = ActionBoundary(lambda: "effect-recovery-correlation", effect_journal)
    monkeypatch.setattr(
        effect_boundary,
        "_effect_evidence",
        lambda *_args: (_ for _ in ()).throw(RuntimeError("effect fault")),
    )
    monkeypatch.setattr(
        effect_boundary,
        "_recover_effect_evidence",
        lambda *_args: (_ for _ in ()).throw(RuntimeError("effect recovery fault")),
    )
    with pytest.raises(RuntimeError, match="effect recovery fault"):
        effect_boundary.invoke(
            "report.save",
            WorkflowStage.PREVIEW,
            lambda: ActionSuccess(
                "report.save",
                "effect-recovery-correlation",
                WorkflowStage.PREVIEW,
                None,
            ),
        )
    assert not list((tmp_path / "effect-recovery").glob(".diagnostics.reserve.*.tmp"))


def test_cancel_preflight_is_idempotent_and_allows_a_fresh_reservation(tmp_path: Path) -> None:
    journal = DiagnosticJournal(tmp_path)
    assert isinstance(journal.preflight("report.save", "cancel-idempotent"), ActionSuccess)

    journal.cancel_preflight("report.save", "cancel-idempotent")
    journal.cancel_preflight("report.save", "cancel-idempotent")
    retry = journal.preflight("report.save", "cancel-idempotent")

    try:
        assert isinstance(retry, ActionSuccess)
        assert len(list(tmp_path.glob(".diagnostics.reserve.*.tmp"))) == 1
    finally:
        journal.cancel_preflight("report.save", "cancel-idempotent")


def test_normal_append_rotates_without_consuming_live_reserved_capacity(tmp_path: Path) -> None:
    journal = DiagnosticJournal(tmp_path)
    seed = _record_with_encoded_size(900_000, "normal-interleave-seed")
    assert isinstance(journal.append_and_sync(seed), ActionSuccess)
    assert isinstance(
        journal.preflight("report.save", "normal-interleave-reserved"),
        ActionSuccess,
    )
    try:
        normal = replace(
            _record_with_encoded_size(100_000, "normal-interleave-read-only"),
            action_id="display.detect",
        )
        normal_outcome = journal.append_and_sync(normal)
        reserved_outcome = journal.append_and_sync(
            replace(
                _record("normal-interleave-reserved"),
                action_id="report.save",
            )
        )

        assert isinstance(normal_outcome, ActionSuccess)
        assert isinstance(reserved_outcome, ActionSuccess)
        active_correlations = [record["correlation_id"] for record in _json_lines(journal.path)]
        assert active_correlations == [
            "normal-interleave-read-only",
            "normal-interleave-reserved",
        ]
        assert _json_lines(journal.archive_paths[0])[0]["correlation_id"] == "normal-interleave-seed"
    finally:
        journal.cancel_preflight("report.save", "normal-interleave-reserved")


def test_bundle_preview_excludes_live_reservation_stages(tmp_path: Path) -> None:
    journal = DiagnosticJournal(tmp_path)
    assert isinstance(journal.append_and_sync(_record("bundle-stage-log")), ActionSuccess)
    assert isinstance(journal.preflight("report.save", "bundle-stage-live"), ActionSuccess)
    try:
        preview = journal_module.DiagnosticBundleManager(
            journal,
            token_factory=lambda: "bundle-stage-token",
        ).preview()

        assert [member.basename for member in preview.members] == ["diagnostics.jsonl"]
        assert all("reserve" not in member.basename for member in preview.members)
    finally:
        journal.cancel_preflight("report.save", "bundle-stage-live")


def _read_child_line_with_timeout(process: subprocess.Popen[str]) -> str:
    assert process.stdout is not None
    executor = ThreadPoolExecutor(max_workers=1)
    future = executor.submit(process.stdout.readline)
    try:
        return future.result(timeout=10.0).strip()
    except TimeoutError:
        process.kill()
        process.wait(timeout=10.0)
        raise
    finally:
        executor.shutdown(wait=True, cancel_futures=True)


def _popen_test_child(script: str, *arguments: str) -> subprocess.Popen[str]:
    return subprocess.Popen(
        [sys.executable, "-c", script, *arguments],
        cwd=Path(__file__).resolve().parents[1],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )


@pytest.mark.skipif(os.name != "nt", reason="Windows reservation lock contract")
def test_windows_subprocess_live_stage_is_retained_then_reaped_after_owner_death(
    tmp_path: Path,
) -> None:
    script = textwrap.dedent(
        """
        import sys
        from pathlib import Path
        from calibrate_pro.application.journal import DiagnosticJournal

        journal = DiagnosticJournal(Path(sys.argv[1]))
        outcome = journal.preflight("report.save", "child-live-correlation")
        print(type(outcome).__name__, flush=True)
        sys.stdin.readline()
        """
    )
    child = _popen_test_child(script, str(tmp_path))
    parent = DiagnosticJournal(tmp_path)
    try:
        assert _read_child_line_with_timeout(child) == "ActionSuccess"
        child_stages = list(tmp_path.glob(".diagnostics.reserve.*.tmp"))
        assert len(child_stages) == 1
        child_stage = child_stages[0]

        parent_outcome = parent.preflight("report.save", "parent-live-correlation")
        try:
            assert isinstance(parent_outcome, ActionSuccess)
            assert child_stage.exists()
            assert len(list(tmp_path.glob(".diagnostics.reserve.*.tmp"))) == 2
        finally:
            parent.cancel_preflight("report.save", "parent-live-correlation")

        child.terminate()
        child.wait(timeout=10.0)
        restarted = DiagnosticJournal(tmp_path)
        restart_outcome = restarted.preflight("report.save", "after-child-crash")
        try:
            assert isinstance(restart_outcome, ActionSuccess)
            assert not child_stage.exists()
            assert len(list(tmp_path.glob(".diagnostics.reserve.*.tmp"))) == 1
        finally:
            restarted.cancel_preflight("report.save", "after-child-crash")
    finally:
        if child.poll() is None:
            child.kill()
            child.wait(timeout=10.0)


@pytest.mark.skipif(os.name != "nt", reason="Windows reservation lock contract")
def test_windows_restart_reaps_partial_stage_left_by_crash_during_preallocation(
    tmp_path: Path,
) -> None:
    script = textwrap.dedent(
        """
        import os
        import sys
        from pathlib import Path
        import calibrate_pro.application.journal as module

        real_write_all = module._write_all
        def crash_during_fill(file_descriptor, payload):
            if len(payload) == 65_536:
                os.write(file_descriptor, payload[:1024])
                os._exit(23)
            real_write_all(file_descriptor, payload)
        module._write_all = crash_during_fill
        module.DiagnosticJournal(Path(sys.argv[1])).preflight(
            "report.save", "partial-crash-correlation"
        )
        """
    )
    child = _popen_test_child(script, str(tmp_path))
    try:
        assert child.wait(timeout=10.0) == 23
        abandoned = list(tmp_path.glob(".diagnostics.reserve.*.tmp"))
        assert len(abandoned) == 1
        assert 0 < abandoned[0].stat().st_size < 1_048_576

        journal = DiagnosticJournal(tmp_path)
        outcome = journal.preflight("report.save", "partial-crash-restart")
        try:
            assert isinstance(outcome, ActionSuccess)
            assert not abandoned[0].exists()
            assert len(list(tmp_path.glob(".diagnostics.reserve.*.tmp"))) == 1
        finally:
            journal.cancel_preflight("report.save", "partial-crash-restart")
    finally:
        if child.poll() is None:
            child.kill()
            child.wait(timeout=10.0)


@pytest.mark.skipif(os.name != "nt", reason="Windows reservation lock contract")
def test_windows_cross_process_reserved_appends_have_no_lost_updates(
    tmp_path: Path,
) -> None:
    script = textwrap.dedent(
        """
        import sys
        from pathlib import Path
        from calibrate_pro.application.journal import DiagnosticJournal, JournalRecord

        root = Path(sys.argv[1])
        correlation_id = sys.argv[2]
        journal = DiagnosticJournal(root)
        preflight = journal.preflight("report.save", correlation_id)
        print(type(preflight).__name__, flush=True)
        sys.stdin.readline()
        record = JournalRecord(
            timestamp_utc="2026-07-14T00:00:00Z",
            correlation_id=correlation_id,
            product_version="test",
            runtime_mode="source",
            platform_version="Windows-test",
            action_id="report.save",
            workflow_stage="detect",
            capability_flags=(),
            outcome="success",
            exception_type=None,
            error_code=None,
            technical_category=None,
            redacted_message=None,
            display_pseudonym=None,
            plan_sha256=None,
            asset_sha256=(),
            apply_phase_flags=(),
            recovery_guarantee=None,
            export_basename=None,
            export_sha256=None,
        )
        outcome = journal.append_and_sync(record)
        print(type(outcome).__name__, flush=True)
        """
    )
    correlations = [f"cross-process-{index}" for index in range(4)]
    children = [_popen_test_child(script, str(tmp_path), value) for value in correlations]
    try:
        assert [_read_child_line_with_timeout(child) for child in children] == ["ActionSuccess"] * 4
        assert len(list(tmp_path.glob(".diagnostics.reserve.*.tmp"))) == 4
        for child in children:
            assert child.stdin is not None
            child.stdin.write("GO\n")
            child.stdin.flush()
        final_lines: list[str] = []
        for child in children:
            assert child.wait(timeout=20.0) == 0
            assert child.stdout is not None
            final_lines.append(child.stdout.read().strip())
            assert child.stderr is not None
            assert child.stderr.read() == ""

        assert final_lines == ["ActionSuccess"] * 4
        records = _json_lines(tmp_path / "diagnostics.jsonl")
        assert {record["correlation_id"] for record in records} == set(correlations)
        assert len(records) == 4
        assert not list(tmp_path.glob(".diagnostics.reserve.*.tmp"))
    finally:
        for child in children:
            if child.poll() is None:
                child.kill()
                child.wait(timeout=10.0)


def test_append_writes_one_strict_utf8_json_line_with_only_allowlisted_fields(
    tmp_path: Path,
) -> None:
    journal = DiagnosticJournal(tmp_path)
    record = _record()

    outcome = journal.append_and_sync(record)

    assert isinstance(outcome, ActionSuccess)
    raw = journal.path.read_bytes()
    assert raw.endswith(b"\n")
    assert raw.count(b"\n") == 1
    assert "Δ".encode() in raw
    assert b"\\u0394" not in raw
    decoded = json.loads(raw.decode("utf-8"))
    assert tuple(decoded) == ALLOWLISTED_FIELDS
    assert decoded == {
        "timestamp_utc": "2026-07-13T12:34:56Z",
        "correlation_id": "correlation-Δ",
        "product_version": "1.2.3",
        "runtime_mode": "source",
        "platform_version": "Windows-Ü",
        "action_id": "diagnostics.test",
        "workflow_stage": "detect",
        "capability_flags": [["hdr", True]],
        "outcome": "success",
        "exception_type": None,
        "error_code": None,
        "technical_category": None,
        "redacted_message": None,
        "display_pseudonym": None,
        "plan_sha256": None,
        "asset_sha256": ["ab" * 32],
        "apply_phase_flags": [["captured", True]],
        "recovery_guarantee": "restored",
        "export_basename": "report.zip",
        "export_sha256": "cd" * 32,
    }
    assert (
        outcome.action_id,
        outcome.correlation_id,
        outcome.stage,
        outcome.value,
    ) == (
        "diagnostics.test",
        "correlation-Δ",
        WorkflowStage.DETECT,
        None,
    )


def test_append_rejects_unsupported_object_before_attribute_access_or_io(tmp_path: Path) -> None:
    class AttributeTrap:
        def __getattribute__(self, name: str) -> object:
            raise AssertionError(f"unexpected attribute access: {name}")

    root = tmp_path / "unsupported"

    with pytest.raises(TypeError, match="exact JournalRecord"):
        DiagnosticJournal(root).append_and_sync(cast(JournalRecord, AttributeTrap()))

    assert not root.exists()


def test_append_rejects_journal_record_subclass_before_io(tmp_path: Path) -> None:
    class JournalRecordSubclass(JournalRecord):
        pass

    base = _record()
    subclass = JournalRecordSubclass(**{field.name: getattr(base, field.name) for field in fields(JournalRecord)})
    root = tmp_path / "subclass"

    with pytest.raises(TypeError, match="exact JournalRecord"):
        DiagnosticJournal(root).append_and_sync(subclass)

    assert not root.exists()


def test_new_instance_appends_and_both_records_remain_decodable(tmp_path: Path) -> None:
    first = DiagnosticJournal(tmp_path)
    assert isinstance(first.append_and_sync(_record("correlation-one")), ActionSuccess)

    restarted = DiagnosticJournal(tmp_path)
    assert isinstance(
        restarted.append_and_sync(replace(_record(), correlation_id="correlation-two")),
        ActionSuccess,
    )

    records = [json.loads(line) for line in restarted.path.read_text(encoding="utf-8").splitlines()]
    assert [record["correlation_id"] for record in records] == [
        "correlation-one",
        "correlation-two",
    ]
    assert all(tuple(record) == ALLOWLISTED_FIELDS for record in records)


def test_append_writes_then_fsyncs_and_replaces_before_constructing_success(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    events: list[str] = []
    real_write = journal_module.os.write
    real_fsync = journal_module.os.fsync
    real_replace = journal_module.os.replace

    def write_spy(file_descriptor: int, payload: bytes) -> int:
        events.append("write")
        return real_write(file_descriptor, payload)

    def fsync_spy(file_descriptor: int) -> None:
        events.append("fsync")
        real_fsync(file_descriptor)

    def replace_spy(source: Path, destination: Path) -> None:
        events.append("replace")
        real_replace(source, destination)

    real_success = ActionSuccess

    def success_spy(**kwargs: object) -> ActionSuccess[None]:
        events.append("success")
        return real_success(**kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(journal_module.os, "write", write_spy)
    monkeypatch.setattr(journal_module.os, "fsync", fsync_spy)
    monkeypatch.setattr(journal_module.os, "replace", replace_spy)
    monkeypatch.setattr(journal_module, "ActionSuccess", success_spy)

    outcome = DiagnosticJournal(tmp_path).append_and_sync(_record())

    assert isinstance(outcome, real_success)
    assert events == ["write", "fsync", "replace", "success"]


def test_fsync_failure_returns_matching_error_and_never_success(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    record = _record("correlation-fsync-failed")

    def fail_fsync(_fd: int) -> None:
        raise OSError("fault injection")

    monkeypatch.setattr(journal_module.os, "fsync", fail_fsync)

    outcome = DiagnosticJournal(tmp_path).append_and_sync(record)

    assert isinstance(outcome, ActionError)
    assert (
        outcome.action_id,
        outcome.correlation_id,
        outcome.stage,
        outcome.code,
        outcome.retryable,
        outcome.effect_state,
    ) == (
        record.action_id,
        record.correlation_id,
        WorkflowStage(record.workflow_stage),
        "DIAGNOSTIC_JOURNAL_WRITE_FAILED",
        True,
        "none",
    )
    assert outcome.category == "diagnostics"


def test_oversized_encoded_record_is_rejected_without_filesystem_changes(tmp_path: Path) -> None:
    root = tmp_path / "oversized"
    record = replace(
        _record(),
        correlation_id="\u00e9" * 600_000,
    )
    encoded = journal_module._encode_record(record)

    assert len(encoded) < 1_048_576
    assert len(encoded.encode("utf-8")) > 1_048_576

    outcome = DiagnosticJournal(root).append_and_sync(record)

    assert isinstance(outcome, ActionError)
    assert outcome.code == "DIAGNOSTIC_RECORD_TOO_LARGE"
    assert not root.exists()


def test_exact_byte_limit_is_allowed_then_preflight_rotates_it(tmp_path: Path) -> None:
    journal = DiagnosticJournal(tmp_path)
    empty_id_record = _record("")
    empty_id_size = len(journal_module._encode_record(empty_id_record).encode("utf-8"))
    record = replace(empty_id_record, correlation_id="x" * (1_048_576 - empty_id_size))
    assert len(journal_module._encode_record(record).encode("utf-8")) == 1_048_576

    appended = journal.append_and_sync(record)

    assert isinstance(appended, ActionSuccess)
    assert journal.path.stat().st_size == 1_048_576
    assert not any(path.exists() for path in journal.archive_paths)

    restarted = DiagnosticJournal(tmp_path)
    preflight = restarted.preflight(
        "diagnostics.test",
        "correlation-exact-limit-restart",
    )

    assert isinstance(preflight, ActionSuccess)
    assert journal.path.read_bytes() == b""
    assert journal.archive_paths[0].stat().st_size == 1_048_576
    restarted.cancel_preflight("diagnostics.test", "correlation-exact-limit-restart")


def test_threshold_rotation_retains_active_plus_five_deterministic_archives(
    tmp_path: Path,
) -> None:
    journal = DiagnosticJournal(tmp_path)
    large_id = "x" * (1_048_576 // 2)

    for generation in range(6):
        outcome = journal.append_and_sync(replace(_record(), correlation_id=f"{generation}-{large_id}"))
        assert isinstance(outcome, ActionSuccess)

    assert journal.path.exists()
    assert tuple(path.name for path in journal.archive_paths) == (
        "diagnostics.1.jsonl",
        "diagnostics.2.jsonl",
        "diagnostics.3.jsonl",
        "diagnostics.4.jsonl",
        "diagnostics.5.jsonl",
    )
    assert all(path.exists() for path in journal.archive_paths)
    assert len(list(tmp_path.glob("diagnostics.*.jsonl"))) == 5


def test_rotation_replace_failure_preserves_prior_active_bytes_and_returns_error(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    journal = DiagnosticJournal(tmp_path)
    prior = b"{}\n" * (1_048_576 // 3)
    journal.path.write_bytes(prior)

    def fail_replace(_source: Path, _destination: Path) -> None:
        raise OSError("injected replace fault")

    monkeypatch.setattr(journal_module.os, "replace", fail_replace)

    outcome = journal.append_and_sync(_record("correlation-after-threshold"))

    assert isinstance(outcome, ActionError)
    assert outcome.code == "DIAGNOSTIC_JOURNAL_WRITE_FAILED"
    assert journal.path.read_bytes() == prior


def _seed_full_rotation_set(journal: DiagnosticJournal) -> tuple[bytes, ...]:
    journal.path.parent.mkdir(parents=True, exist_ok=True)
    active = (
        json.dumps(
            {"marker": "active", "padding": "x" * (1_048_576 - 128)},
            separators=(",", ":"),
        ).encode("utf-8")
        + b"\n"
    )
    assert len(active) <= 1_048_576
    assert len(active) + len(journal_module._encode_record(_record()).encode("utf-8")) > 1_048_576
    journal.path.write_bytes(active)
    archives: list[bytes] = []
    for generation, path in enumerate(journal.archive_paths, start=1):
        payload = json.dumps({"marker": f"archive-{generation}"}, separators=(",", ":")).encode("utf-8") + b"\n"
        path.write_bytes(payload)
        archives.append(payload)
    return (active, *archives)


def _all_sibling_bytes(root: Path) -> bytes:
    return b"".join(path.read_bytes() for path in root.iterdir() if path.is_file())


def _json_lines(path: Path) -> list[dict[str, object]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


@pytest.mark.parametrize("replace_failure_call", range(1, 12))
def test_every_rotation_replace_failure_recovers_with_exact_generation_policy(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    replace_failure_call: int,
) -> None:
    journal = DiagnosticJournal(tmp_path)
    _seed_full_rotation_set(journal)
    real_replace = journal_module.os.replace
    replace_calls = 0

    def fail_selected_replace(source: Path, destination: Path) -> None:
        nonlocal replace_calls
        replace_calls += 1
        if replace_calls == replace_failure_call:
            raise OSError(f"injected replace fault at call {replace_failure_call}")
        real_replace(source, destination)

    monkeypatch.setattr(journal_module.os, "replace", fail_selected_replace)

    outcome = journal.append_and_sync(_record(f"failed-record-{replace_failure_call}"))

    assert isinstance(outcome, ActionError)
    assert outcome.code == "DIAGNOSTIC_JOURNAL_WRITE_FAILED"
    assert replace_calls == replace_failure_call

    monkeypatch.setattr(journal_module.os, "replace", real_replace)
    restarted = DiagnosticJournal(tmp_path)
    recovered = restarted.preflight(
        "diagnostics.test",
        f"recovery-{replace_failure_call}",
    )

    assert isinstance(recovered, ActionSuccess)
    restarted.cancel_preflight("diagnostics.test", f"recovery-{replace_failure_call}")
    assert not [path for path in tmp_path.iterdir() if path.name.endswith(".tmp")]
    paths = (restarted.path, *restarted.archive_paths)
    markers_by_path = {path.name: [record["marker"] for record in _json_lines(path)] for path in paths}
    assert markers_by_path == {
        "diagnostics.jsonl": [],
        "diagnostics.1.jsonl": ["active"],
        "diagnostics.2.jsonl": ["archive-1"],
        "diagnostics.3.jsonl": ["archive-2"],
        "diagnostics.4.jsonl": ["archive-3"],
        "diagnostics.5.jsonl": ["archive-4"],
    }
    retained_markers = [marker for markers in markers_by_path.values() for marker in markers]
    assert all(retained_markers.count(marker) == 1 for marker in retained_markers)
    assert "archive-5" not in retained_markers

    appended = restarted.append_and_sync(_record(f"post-recovery-{replace_failure_call}"))

    assert isinstance(appended, ActionSuccess)
    resulting_records = [record for path in paths for record in _json_lines(path)]
    assert resulting_records
    assert all(path.read_bytes().endswith(b"\n") for path in paths if path.exists())
    assert (
        sum(record.get("correlation_id") == f"post-recovery-{replace_failure_call}" for record in resulting_records)
        == 1
    )
    assert not any(
        record.get("correlation_id") == f"failed-record-{replace_failure_call}" for record in resulting_records
    )


def test_mid_rotation_replace_fault_recovers_on_restart_without_losing_prior_records(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    journal = DiagnosticJournal(tmp_path)
    durable_payloads = _seed_full_rotation_set(journal)
    real_replace = journal_module.os.replace
    replace_calls = 0

    def fail_third_replace(source: Path, destination: Path) -> None:
        nonlocal replace_calls
        replace_calls += 1
        if replace_calls == 3:
            raise OSError("injected mid-rotation replace fault")
        real_replace(source, destination)

    monkeypatch.setattr(journal_module.os, "replace", fail_third_replace)

    outcome = journal.append_and_sync(_record("correlation-mid-rotation-fault"))

    assert isinstance(outcome, ActionError)
    combined_after_failure = _all_sibling_bytes(tmp_path)
    assert all(payload in combined_after_failure for payload in durable_payloads)

    restarted = DiagnosticJournal(tmp_path)
    recovered = restarted.preflight("diagnostics.test", "correlation-restart")

    assert isinstance(recovered, ActionSuccess)
    restarted.cancel_preflight("diagnostics.test", "correlation-restart")
    combined_after_restart = _all_sibling_bytes(tmp_path)
    assert all(payload in combined_after_restart for payload in durable_payloads[:-1])
    assert durable_payloads[-1] not in combined_after_restart
    assert not list(tmp_path.glob("*.tmp"))


def test_rotation_unlink_fault_returns_error_and_preserves_prior_bytes(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    journal = DiagnosticJournal(tmp_path)
    durable_payloads = _seed_full_rotation_set(journal)

    def fail_unlink(_path: Path) -> None:
        raise OSError("injected unlink fault")

    monkeypatch.setattr(journal_module.os, "unlink", fail_unlink)

    outcome = journal.append_and_sync(_record("correlation-unlink-fault"))

    assert isinstance(outcome, ActionError)
    combined = _all_sibling_bytes(tmp_path)
    assert all(payload in combined for payload in durable_payloads)


def test_partial_append_write_fault_preserves_prior_active_bytes(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    journal = DiagnosticJournal(tmp_path)
    assert isinstance(journal.append_and_sync(_record("durable-before-write-fault")), ActionSuccess)
    prior = journal.path.read_bytes()
    real_write = journal_module.os.write
    write_calls = 0

    def partial_then_fail(file_descriptor: int, payload: bytes) -> int:
        nonlocal write_calls
        write_calls += 1
        if write_calls == 1:
            return real_write(file_descriptor, payload[: max(1, len(payload) // 2)])
        raise OSError("injected partial write fault")

    monkeypatch.setattr(journal_module.os, "write", partial_then_fail)

    outcome = journal.append_and_sync(_record("correlation-partial-write-fault"))

    assert isinstance(outcome, ActionError)
    assert journal.path.read_bytes() == prior


def test_append_fsync_fault_preserves_prior_active_bytes(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    journal = DiagnosticJournal(tmp_path)
    assert isinstance(journal.append_and_sync(_record("durable-before-fsync-fault")), ActionSuccess)
    prior = journal.path.read_bytes()

    def fail_fsync(_file_descriptor: int) -> None:
        raise OSError("injected append fsync fault")

    monkeypatch.setattr(journal_module.os, "fsync", fail_fsync)

    outcome = journal.append_and_sync(_record("correlation-append-fsync-fault"))

    assert isinstance(outcome, ActionError)
    assert journal.path.read_bytes() == prior


def test_append_publish_replace_fault_preserves_prior_active_bytes(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    journal = DiagnosticJournal(tmp_path)
    assert isinstance(journal.append_and_sync(_record("durable-before-publish-fault")), ActionSuccess)
    prior = journal.path.read_bytes()

    def fail_replace(_source: Path, _destination: Path) -> None:
        raise OSError("injected append publish fault")

    monkeypatch.setattr(journal_module.os, "replace", fail_replace)

    outcome = journal.append_and_sync(_record("correlation-publish-fault"))

    assert isinstance(outcome, ActionError)
    assert journal.path.read_bytes() == prior


def test_restart_removes_stale_append_temp_after_partial_write_and_unlink_fault(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    journal = DiagnosticJournal(tmp_path)
    assert isinstance(journal.append_and_sync(_record("durable-before-stale-temp")), ActionSuccess)
    prior = journal.path.read_bytes()
    real_write = journal_module.os.write
    real_unlink = journal_module.os.unlink
    write_calls = 0

    def partial_then_fail(file_descriptor: int, payload: bytes) -> int:
        nonlocal write_calls
        write_calls += 1
        if write_calls == 1:
            return real_write(file_descriptor, payload[: max(1, len(payload) // 2)])
        raise OSError("injected stale-temp write fault")

    def fail_unlink(_path: Path) -> None:
        raise OSError("injected stale-temp unlink fault")

    monkeypatch.setattr(journal_module.os, "write", partial_then_fail)
    monkeypatch.setattr(journal_module.os, "unlink", fail_unlink)

    outcome = journal.append_and_sync(_record("failed-stale-temp-record"))

    assert isinstance(outcome, ActionError)
    assert outcome.code == "DIAGNOSTIC_JOURNAL_WRITE_FAILED"
    assert journal.path.read_bytes() == prior
    append_temp = tmp_path / ".diagnostics.append.tmp"
    assert append_temp.exists()

    monkeypatch.setattr(journal_module.os, "write", real_write)
    monkeypatch.setattr(journal_module.os, "unlink", real_unlink)
    restarted = DiagnosticJournal(tmp_path)
    recovered = restarted.preflight("diagnostics.test", "recover-stale-append-temp")

    assert isinstance(recovered, ActionSuccess)
    assert not append_temp.exists()
    assert restarted.path.read_bytes() == prior
    restarted.cancel_preflight("diagnostics.test", "recover-stale-append-temp")

    appended = restarted.append_and_sync(_record("after-stale-temp-recovery"))

    assert isinstance(appended, ActionSuccess)
    records = _json_lines(restarted.path)
    assert [record["correlation_id"] for record in records] == [
        "durable-before-stale-temp",
        "after-stale-temp-recovery",
    ]


def test_preflight_prunes_archive_generations_beyond_five_on_restart(tmp_path: Path) -> None:
    journal = DiagnosticJournal(tmp_path)
    tmp_path.mkdir(parents=True, exist_ok=True)
    journal.path.write_bytes(b"")
    for generation in range(1, 8):
        (tmp_path / f"diagnostics.{generation}.jsonl").write_text(
            json.dumps({"generation": generation}) + "\n",
            encoding="utf-8",
        )

    restarted = DiagnosticJournal(tmp_path)
    outcome = restarted.preflight(
        "diagnostics.test",
        "correlation-prune-restart",
    )

    assert isinstance(outcome, ActionSuccess)
    assert tuple(path.name for path in journal.archive_paths if path.exists()) == (
        "diagnostics.1.jsonl",
        "diagnostics.2.jsonl",
        "diagnostics.3.jsonl",
        "diagnostics.4.jsonl",
        "diagnostics.5.jsonl",
    )
    restarted.cancel_preflight("diagnostics.test", "correlation-prune-restart")
    assert len(list(tmp_path.glob("diagnostics.*.jsonl"))) == 5


def test_two_threads_append_complete_decodable_lines_with_bounded_archives(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    journals = (DiagnosticJournal(tmp_path), DiagnosticJournal(tmp_path))
    start = threading.Barrier(3)
    real_write = journal_module.os.write

    def slow_write(file_descriptor: int, payload: bytes) -> int:
        time.sleep(0.005)
        return real_write(file_descriptor, payload)

    monkeypatch.setattr(journal_module.os, "write", slow_write)

    def append_batch(worker: int) -> list[ActionSuccess[None] | ActionError]:
        start.wait()
        outcomes: list[ActionSuccess[None] | ActionError] = []
        for generation in range(8):
            outcomes.append(journals[worker].append_and_sync(_record(f"thread-{worker}-{generation}-" + "x" * 400_000)))
        return outcomes

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(append_batch, worker) for worker in range(2)]
        start.wait()
        outcomes = [outcome for future in futures for outcome in future.result()]

    assert all(isinstance(outcome, ActionSuccess) for outcome in outcomes)
    existing_paths = [path for path in (journals[0].path, *journals[0].archive_paths) if path.exists()]
    assert len(existing_paths[1:]) <= 5
    decoded = [json.loads(line.decode("utf-8")) for path in existing_paths for line in path.read_bytes().splitlines()]
    assert decoded
    assert all(tuple(record) == ALLOWLISTED_FIELDS for record in decoded)


def test_injected_redactor_removes_combined_sensitive_values_deterministically() -> None:
    username = "Casey.Test"
    home = r"C:\Users\Casey.Test"
    environment_value = "InjectedEnvironmentValue-987654"
    combined = (
        "ordinary diagnostic retained; "
        "password=PasswordValue-12345; API_KEY: ApiTokenValue-67890; "
        "Bearer BearerTokenValue-24680; confirmation-token=ConfirmValue-13579; "
        "-----BEGIN PRIVATE KEY-----\nPrivateKeyMaterial-112233\n"
        "-----END PRIVATE KEY-----; "
        f"username={username}; home={home}; "
        r"windows=C:\Users\Casey.Test\Documents\report.icc; "
        "posix=/home/casey/private/trace.log; "
        f"environment={environment_value}; "
        "EDID=00FFFFFFFFFFFF0010AC123456789ABC; "
        "serial-number: MonitorSerial-445566; "
        r"device=\\?\DISPLAY#DEL40A9#5&ABCDEF&0&UID4352"
    )
    forbidden = (
        "PasswordValue-12345",
        "ApiTokenValue-67890",
        "BearerTokenValue-24680",
        "ConfirmValue-13579",
        "PrivateKeyMaterial-112233",
        username,
        home,
        environment_value,
        "00FFFFFFFFFFFF0010AC123456789ABC",
        "MonitorSerial-445566",
        r"\\?\DISPLAY#DEL40A9#5&ABCDEF&0&UID4352",
    )
    redactor = journal_module.DiagnosticRedactor(
        username=username,
        home=home,
        environment={
            "CALIBRATE_SYNTHETIC_SECRET": environment_value,
            "EMPTY_VALUE": "",
            "TRIVIAL_VALUE": "x",
        },
    )

    redacted = redactor.redact(combined)

    assert redactor.redact(redacted) == redacted
    assert "ordinary diagnostic retained" in redacted
    assert "report.icc" in redacted
    assert "trace.log" in redacted
    assert all(fragment.casefold() not in redacted.casefold() for fragment in forbidden)


def test_append_persists_redacted_copy_across_active_and_archive_without_mutation(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    username = "Archive.User"
    home = r"C:\Users\Archive.User"
    environment_value = "ArchiveEnvironmentValue-998877"
    sensitive = (
        "useful archive diagnostic; "
        f"password=ArchivePassword-123; user={username}; home={home}; "
        f"env={environment_value}; "
        r"path=C:\Users\Archive.User\Desktop\archive-report.json; "
        "serial=ArchiveSerial-456; "
        r"device=\\?\DISPLAY#ARCHIVE#123"
    )
    record = replace(
        _record("archive-correlation"),
        platform_version=sensitive,
        capability_flags=((sensitive, True),),
        redacted_message=sensitive,
    )
    source_snapshot = record
    root = tmp_path / "redacted-rotation"
    redactor = journal_module.DiagnosticRedactor(
        username=username,
        home=home,
        environment={"CALIBRATE_ARCHIVE_SECRET": environment_value},
    )
    journal = DiagnosticJournal(root, redactor=redactor)

    first = journal.append_and_sync(record)
    monkeypatch.setattr(
        journal_module,
        "DIAGNOSTIC_JOURNAL_MAX_BYTES",
        journal.path.stat().st_size + 1,
    )
    second = journal.append_and_sync(record)

    assert isinstance(first, ActionSuccess)
    assert isinstance(second, ActionSuccess)
    assert record is source_snapshot
    assert record.platform_version == sensitive
    persisted_paths = [path for path in (journal.path, *journal.archive_paths) if path.exists()]
    assert [path.name for path in persisted_paths[:2]] == [
        "diagnostics.jsonl",
        "diagnostics.1.jsonl",
    ]
    persisted = b"".join(path.read_bytes() for path in persisted_paths)
    for fragment in (
        "ArchivePassword-123",
        username,
        home,
        environment_value,
        "ArchiveSerial-456",
        r"\\?\DISPLAY#ARCHIVE#123",
    ):
        assert fragment.encode("utf-8").lower() not in persisted.lower()
    assert b"archive-report.json" in persisted
    assert b"useful archive diagnostic" in persisted


def test_invalid_exact_field_types_and_tuple_shapes_are_rejected_before_io(
    tmp_path: Path,
) -> None:
    class StringSubclass(str):
        pass

    record = _record()
    invalid_records = (
        ("timestamp_utc", replace(record, timestamp_utc=StringSubclass("timestamp"))),
        ("runtime_mode", replace(record, runtime_mode=cast(Any, "unsupported"))),
        ("outcome", replace(record, outcome=cast(Any, "partial"))),
        ("capability_flags", replace(record, capability_flags=cast(Any, [("hdr", True)]))),
        ("capability_flags", replace(record, capability_flags=cast(Any, (("hdr", 1),)))),
        ("capability_flags", replace(record, capability_flags=cast(Any, (("hdr",),)))),
        ("asset_sha256", replace(record, asset_sha256=cast(Any, ["digest"]))),
        ("apply_phase_flags", replace(record, apply_phase_flags=cast(Any, ((1, True),)))),
    )

    for index, (field_name, invalid_record) in enumerate(invalid_records):
        root = tmp_path / f"invalid-{index}"
        with pytest.raises(TypeError, match=field_name):
            DiagnosticJournal(root).append_and_sync(invalid_record)
        assert not root.exists()


def test_adversarial_scalars_are_redacted_and_export_is_a_safe_basename(
    tmp_path: Path,
) -> None:
    username = "Eve"
    home = r"C:\Users\Eve"
    environment_value = "Injected-Environment-Secret-ABC987"
    digest = "a3" * 32
    sensitive = (
        "ordinary diagnostic retained; "
        'PaSsWoRd: "Password With Spaces 123"; '
        "API-Key=sk-SyntheticApiKey-123456; SECRET: SyntheticSecret-987654; "
        "bEaReR SyntheticBearer-246810; CONFIRMATION_TOKEN: Confirm-135791; "
        "-----BEGIN RSA PRIVATE KEY-----\nPrivate-Key-Body-1122\n"
        "-----END RSA PRIVATE KEY-----; "
        f"user={username.upper()}; home={home}; "
        r'windows="C:\Users\Eve\Private Folder\report.icc"; '
        r'unc="\\server\share\private\unc.txt"; '
        "posix='/Users/Eve/Private Folder/trace.log'; "
        f"environment={environment_value.swapcase()}; "
        "EDID blob: 00 FF FF FF FF FF FF 00 10 AC 12 34 56 78 9A BC; "
        "Serial Number: Monitor Serial 445566; "
        r"pnp=MONITOR\ACME123\5&ABCDEF&0&UID4352"
    )
    record = JournalRecord(
        timestamp_utc=sensitive,
        correlation_id=sensitive,
        product_version=sensitive,
        runtime_mode="frozen",
        platform_version=sensitive,
        action_id=sensitive,
        workflow_stage=sensitive,
        capability_flags=((sensitive, True),),
        outcome="failure",
        exception_type=sensitive,
        error_code=sensitive,
        technical_category=sensitive,
        redacted_message=sensitive,
        display_pseudonym=digest,
        plan_sha256=digest,
        asset_sha256=(digest, "b4" * 32),
        apply_phase_flags=((sensitive, False),),
        recovery_guarantee=sensitive,
        export_basename=r"..\..\Users\Eve\Desktop\bundle.zip",
        export_sha256=digest,
    )
    redactor = journal_module.DiagnosticRedactor(
        username=username,
        home=home,
        environment={
            "CALIBRATE_SYNTHETIC_SECRET": environment_value,
            "EMPTY": "",
            "TRIVIAL": "x",
            "COMMON_BOOLEAN": "true",
        },
    )
    journal = DiagnosticJournal(tmp_path, redactor=redactor)

    outcome = journal.append_and_sync(record)

    assert isinstance(outcome, ActionSuccess)
    payload = json.loads(journal.path.read_text(encoding="utf-8"))
    persisted = journal.path.read_bytes().lower()
    for fragment in (
        "Password With Spaces 123",
        "sk-SyntheticApiKey-123456",
        "SyntheticSecret-987654",
        "SyntheticBearer-246810",
        "Confirm-135791",
        "Private-Key-Body-1122",
        username,
        home,
        environment_value,
        "00 FF FF FF FF FF FF 00 10 AC 12 34 56 78 9A BC",
        "Monitor Serial 445566",
        r"MONITOR\ACME123\5&ABCDEF&0&UID4352",
        r"C:\Users\Eve\Private Folder",
        r"\\server\share\private",
        "/Users/Eve/Private Folder",
    ):
        assert fragment.encode("utf-8").lower() not in persisted
    assert b"ordinary diagnostic retained" in persisted
    assert all(name.encode("utf-8") in persisted for name in ("report.icc", "unc.txt", "trace.log"))
    assert payload["plan_sha256"] == digest
    assert payload["asset_sha256"][0] == digest
    assert payload["display_pseudonym"] == digest
    assert payload["export_sha256"] == digest
    assert payload["export_basename"] == "bundle.zip"
    assert record.timestamp_utc == sensitive


def test_byte_redaction_reuses_scalar_rules_and_fails_closed_for_invalid_utf8() -> None:
    environment_value = "ByteEnvironmentSecret-554433"
    redactor = journal_module.DiagnosticRedactor(
        username="Byte.User",
        home=r"C:\Users\Byte.User",
        environment={"CALIBRATE_BYTE_SECRET": environment_value},
    )
    valid_source = (f"ordinary byte diagnostic; password=BytePassword-123; environment={environment_value}").encode()
    invalid_source = b"invalid-prefix-\xff" + environment_value.encode("utf-8")

    valid_redacted = redactor.redact_bytes(valid_source)
    invalid_redacted = redactor.redact_bytes(invalid_source)

    assert valid_redacted.decode("utf-8") == redactor.redact(valid_source.decode("utf-8"))
    assert b"ordinary byte diagnostic" in valid_redacted
    assert b"BytePassword-123" not in valid_redacted
    assert environment_value.encode("utf-8") not in valid_redacted
    assert invalid_redacted == journal_module.INVALID_UTF8_REDACTION_MARKER.encode("utf-8")
    assert invalid_redacted.decode("utf-8")
    assert not any(byte in invalid_redacted for byte in (b"invalid-prefix", b"\xff", b"ByteEnvironment"))


def test_forbidden_fragments_never_reach_active_or_any_rotated_archive(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    environment_value = "RotatedEnvironmentSecret-123987"
    standalone_token = "sk-proj-StandaloneSyntheticToken-887766"
    sensitive = (
        "ordinary rotated diagnostic; password=RotatedPassword-123; "
        f"standalone={standalone_token}; environment={environment_value}; "
        r"path=C:\Users\Rotate.User\Diagnostics\rotated.log; "
        "raw-edid-hex=00FFFFFFFFFFFF0010AC998877665544; "
        "serial-number=RotatedSerial-456; "
        r"device=\\?\USB#VID_1234&PID_5678#RotatedDevice"
    )
    redactor = journal_module.DiagnosticRedactor(
        username="Rotate.User",
        home=r"C:\Users\Rotate.User",
        environment={"CALIBRATE_ROTATED_SECRET": environment_value},
    )
    journal = DiagnosticJournal(tmp_path, redactor=redactor)
    record = replace(_record("rotated-correlation"), redacted_message=sensitive)

    first = journal.append_and_sync(record)
    assert isinstance(first, ActionSuccess)
    monkeypatch.setattr(
        journal_module,
        "DIAGNOSTIC_JOURNAL_MAX_BYTES",
        journal.path.stat().st_size + 1,
    )
    for _ in range(5):
        assert isinstance(journal.append_and_sync(record), ActionSuccess)

    persisted_paths = (journal.path, *journal.archive_paths)
    assert all(path.exists() for path in persisted_paths)
    forbidden = (
        "RotatedPassword-123",
        standalone_token,
        environment_value,
        "Rotate.User",
        r"C:\Users\Rotate.User\Diagnostics",
        "00FFFFFFFFFFFF0010AC998877665544",
        "RotatedSerial-456",
        r"\\?\USB#VID_1234&PID_5678#RotatedDevice",
    )
    for path in persisted_paths:
        payload = path.read_bytes()
        payload.decode("utf-8", errors="strict")
        assert b"ordinary rotated diagnostic" in payload
        assert b"rotated.log" in payload
        assert all(fragment.encode("utf-8").lower() not in payload.lower() for fragment in forbidden)


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        (
            r"C:\Users\Path User\Private Folder\windows.log",
            "[REDACTED_PATH:windows.log]",
        ),
        (
            r"\\server\Private Share\folder\unc.log",
            "[REDACTED_PATH:unc.log]",
        ),
        (
            "/home/path user/private folder/posix.log",
            "[REDACTED_PATH:posix.log]",
        ),
        ("C:\\", journal_module.REDACTED_PATH_MARKER),
        ("/", journal_module.REDACTED_PATH_MARKER),
    ],
)
def test_absolute_path_scalar_preserves_only_safe_basename(
    source: str,
    expected: str,
) -> None:
    redactor = journal_module.DiagnosticRedactor(
        username="Path.User",
        home=r"C:\Users\Path.User",
        environment={},
    )

    assert redactor.redact(source) == expected


def test_every_record_field_has_an_exact_runtime_validation_policy(tmp_path: Path) -> None:
    class StringSubclass(str):
        pass

    record = _record()
    invalid_by_field: dict[str, object] = {
        "timestamp_utc": StringSubclass(record.timestamp_utc),
        "correlation_id": 7,
        "product_version": b"1.2.3",
        "runtime_mode": "unsupported",
        "platform_version": False,
        "action_id": StringSubclass(record.action_id),
        "workflow_stage": 3.14,
        "capability_flags": ((StringSubclass("hdr"), True),),
        "outcome": "partial",
        "exception_type": 1,
        "error_code": b"ERROR",
        "technical_category": False,
        "redacted_message": 42,
        "display_pseudonym": StringSubclass("display"),
        "plan_sha256": 123,
        "asset_sha256": ["digest"],
        "apply_phase_flags": (("captured", 1),),
        "recovery_guarantee": b"restored",
        "export_basename": Path("report.zip"),
        "export_sha256": 999,
    }
    assert tuple(invalid_by_field) == ALLOWLISTED_FIELDS

    for index, (field_name, invalid_value) in enumerate(invalid_by_field.items()):
        root = tmp_path / f"field-{index}"
        invalid_record = replace(record, **cast(Any, {field_name: invalid_value}))
        with pytest.raises(TypeError, match=field_name):
            DiagnosticJournal(root).append_and_sync(invalid_record)
        assert not root.exists()


def test_task2_compatible_empty_scalar_and_tuple_shapes_remain_persistable(
    tmp_path: Path,
) -> None:
    record = JournalRecord(
        timestamp_utc="",
        correlation_id="",
        product_version="",
        runtime_mode="source",
        platform_version="",
        action_id="",
        workflow_stage="",
        capability_flags=(),
        outcome="success",
        exception_type=None,
        error_code=None,
        technical_category=None,
        redacted_message=None,
        display_pseudonym=None,
        plan_sha256=None,
        asset_sha256=(),
        apply_phase_flags=(),
        recovery_guarantee=None,
        export_basename=None,
        export_sha256=None,
    )

    outcome = DiagnosticJournal(tmp_path).append_and_sync(record)

    assert isinstance(outcome, ActionSuccess)
    payload = json.loads((tmp_path / "diagnostics.jsonl").read_text(encoding="utf-8"))
    assert payload["capability_flags"] == []
    assert payload["asset_sha256"] == []
    assert payload["apply_phase_flags"] == []


def test_default_redactor_uses_deterministic_user_home_and_environment_snapshot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    username = "Default.User"
    home = r"C:\Users\Default.User"
    environment_value = "DefaultEnvironmentSecret-667788"
    monkeypatch.setattr(journal_module.getpass, "getuser", lambda: username)
    monkeypatch.setattr(journal_module.os.path, "expanduser", lambda _value: home)
    monkeypatch.setattr(
        journal_module.os,
        "environ",
        {
            "CALIBRATE_DEFAULT_SECRET": environment_value,
            "EMPTY": "",
            "TRIVIAL": "x",
            "COMMON": "true",
        },
    )
    source = f"ordinary x true; user={username}; home={home}; environment={environment_value}"

    redacted = journal_module.DiagnosticRedactor().redact(source)

    assert "ordinary x true" in redacted
    assert username.casefold() not in redacted.casefold()
    assert home.casefold() not in redacted.casefold()
    assert environment_value.casefold() not in redacted.casefold()


def test_non_utf8_scalar_is_rejected_with_field_error_before_root_creation(
    tmp_path: Path,
) -> None:
    root = tmp_path / "invalid-unicode"
    record = replace(_record(), redacted_message="invalid-surrogate-\ud800")

    with pytest.raises(TypeError, match="redacted_message"):
        DiagnosticJournal(root).append_and_sync(record)

    assert not root.exists()


def test_embedded_absolute_paths_are_consumed_without_partial_tail_leaks() -> None:
    redactor = journal_module.DiagnosticRedactor(
        username="Path.Review",
        home=r"C:\Users\Path.Review",
        environment={},
    )
    source = (
        r"ordinary retained; path=C:\Program Files\Acme\trace.log; "
        r"unc=\\server\share\dir\file.txt; root=/etc; suffix retained"
    )

    redacted = redactor.redact(source)

    assert "ordinary retained" in redacted
    assert "suffix retained" in redacted
    assert "[REDACTED_PATH:trace.log]" in redacted
    assert "[REDACTED_PATH:file.txt]" in redacted
    assert "[REDACTED_PATH:etc]" in redacted
    assert r"C:\Program Files\Acme" not in redacted
    assert r"Files\Acme\trace.log" not in redacted
    assert r"\\server\share\dir" not in redacted
    assert "/etc" not in redacted


def test_labeled_device_instance_values_redact_without_bus_allowlist() -> None:
    redactor = journal_module.DiagnosticRedactor(
        username="Device.Review",
        home=r"C:\Users\Device.Review",
        environment={},
    )
    device_values = (
        r"PCI\VEN_1234&DEV_5678\SERIALABC",
        r"SWD\MMDEVAPI\{DEVICE-GUID}",
        r"ROOT\DISPLAY\0000",
    )
    source = (
        f"ordinary retained; pnp={device_values[0]}; "
        f"device-instance: {device_values[1]}; device_path={device_values[2]}"
    )

    redacted = redactor.redact(source)

    assert "ordinary retained" in redacted
    assert redacted.count(journal_module.REDACTED_DEVICE_MARKER) == 3
    assert all(value.casefold() not in redacted.casefold() for value in device_values)


def test_canonical_sha256_values_bypass_environment_redaction_and_persist_verbatim(
    tmp_path: Path,
) -> None:
    digest = "a3" * 32
    record = replace(
        _record(),
        plan_sha256=digest,
        asset_sha256=(digest, "b4" * 32),
        export_sha256="c5" * 32,
    )
    redactor = journal_module.DiagnosticRedactor(
        username="Digest.Review",
        home=r"C:\Users\Digest.Review",
        environment={"COLLIDING_DIGEST": digest},
    )

    outcome = DiagnosticJournal(tmp_path, redactor=redactor).append_and_sync(record)

    assert isinstance(outcome, ActionSuccess)
    payload = json.loads((tmp_path / "diagnostics.jsonl").read_text(encoding="utf-8"))
    assert payload["plan_sha256"] == digest
    assert payload["asset_sha256"] == [digest, "b4" * 32]
    assert payload["export_sha256"] == "c5" * 32


@pytest.mark.parametrize(
    ("field_name", "invalid_value"),
    [
        ("plan_sha256", "A3" * 32),
        ("plan_sha256", "a" * 63),
        ("asset_sha256", ("asset-digest",)),
        ("export_sha256", "g5" * 32),
    ],
)
def test_noncanonical_sha256_is_rejected_before_root_creation(
    tmp_path: Path,
    field_name: str,
    invalid_value: object,
) -> None:
    root = tmp_path / field_name
    record = replace(_record(), **cast(Any, {field_name: invalid_value}))

    with pytest.raises(TypeError, match=field_name):
        DiagnosticJournal(root).append_and_sync(record)

    assert not root.exists()


def test_defined_redaction_markers_are_protected_from_sensitive_value_collisions() -> None:
    dynamic_path_marker = "[REDACTED_PATH:safe.log]"
    markers = " ".join(
        (
            journal_module.REDACTION_MARKER,
            journal_module.REDACTED_PATH_MARKER,
            dynamic_path_marker,
            journal_module.REDACTED_DEVICE_MARKER,
            journal_module.INVALID_UTF8_REDACTION_MARKER,
        )
    )
    redactor = journal_module.DiagnosticRedactor(
        username="Marker.Review",
        home=r"C:\Users\Marker.Review",
        environment={
            "COLLIDE_REDACTED": "REDACTED",
            "COLLIDE_PATH": "REDACTED_PATH",
            "COLLIDE_DEVICE": "REDACTED_DEVICE",
            "COLLIDE_UTF8": "REDACTED_INVALID_UTF8",
        },
    )

    once = redactor.redact(markers)

    assert once == markers
    assert redactor.redact(once) == markers


@pytest.mark.parametrize(
    ("source", "forbidden"),
    [
        (
            'ordinary retained; json={"password":"Correct Horse Battery Staple"}',
            ("Correct", "Horse", "Battery", "Staple"),
        ),
        (
            "ordinary retained; password=Correct Horse Battery Staple",
            ("Correct", "Horse", "Battery", "Staple"),
        ),
        (
            r"ordinary retained; pnp_path=PCI\VEN_1234&DEV_5678\SERIAL-SECRET",
            (r"PCI\VEN_1234&DEV_5678\SERIAL-SECRET", "SERIAL-SECRET"),
        ),
        (
            "ordinary retained; password=[REDACTED_PATH:plain-secret-value]",
            ("plain-secret-value",),
        ),
        (
            r"ordinary retained; path=[REDACTED_PATH:folder\marker-secret.txt]",
            (r"folder\marker-secret.txt", "marker-secret.txt"),
        ),
    ],
)
def test_final_review_redaction_bypasses_are_removed(
    source: str,
    forbidden: tuple[str, ...],
) -> None:
    redactor = journal_module.DiagnosticRedactor(
        username="Final.Review",
        home=r"C:\Users\Final.Review",
        environment={},
    )

    redacted = redactor.redact(source)

    assert "ordinary retained" in redacted
    assert all(fragment.casefold() not in redacted.casefold() for fragment in forbidden)


def test_final_review_fragments_never_reach_journals_or_second_pass_bytes(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    sensitive = (
        'ordinary retained; json={"password":"Correct Horse Battery Staple"}; '
        "password=Correct Horse Battery Staple; "
        r"pnp_path=PCI\VEN_1234&DEV_5678\SERIAL-SECRET; "
        "password=[REDACTED_PATH:plain-secret-value]; "
        r"path=[REDACTED_PATH:folder\marker-secret.txt]"
    )
    forbidden = (
        "Correct",
        "Horse",
        "Battery",
        "Staple",
        r"PCI\VEN_1234&DEV_5678\SERIAL-SECRET",
        "SERIAL-SECRET",
        "plain-secret-value",
        r"folder\marker-secret.txt",
        "marker-secret.txt",
    )
    redactor = journal_module.DiagnosticRedactor(
        username="Final.Review",
        home=r"C:\Users\Final.Review",
        environment={},
    )
    journal = DiagnosticJournal(tmp_path, redactor=redactor)
    record = replace(_record("final-review-correlation"), redacted_message=sensitive)

    assert isinstance(journal.append_and_sync(record), ActionSuccess)
    monkeypatch.setattr(
        journal_module,
        "DIAGNOSTIC_JOURNAL_MAX_BYTES",
        journal.path.stat().st_size + 1,
    )
    for _ in range(5):
        assert isinstance(journal.append_and_sync(record), ActionSuccess)

    persisted_paths = (journal.path, *journal.archive_paths)
    assert all(path.exists() for path in persisted_paths)
    for path in persisted_paths:
        payload = path.read_bytes()
        payload.decode("utf-8", errors="strict")
        assert b"ordinary retained" in payload
        assert all(fragment.encode().lower() not in payload.lower() for fragment in forbidden)

    second_pass = redactor.redact_bytes(sensitive.encode())
    second_pass.decode("utf-8", errors="strict")
    assert b"ordinary retained" in second_pass
    assert all(fragment.encode().lower() not in second_pass.lower() for fragment in forbidden)


@pytest.mark.parametrize(
    ("source", "forbidden"),
    [
        ("[REDACTED_PATH:sk-abcdefghijklmnop]", ("sk-abcdefghijklmnop",)),
        ("[REDACTED_PATH:plain-secret-value]", ("plain-secret-value",)),
        (
            r'ordinary retained; json={"password":"foo\"bar SECRETTAIL"}',
            ("foo", "bar", "SECRETTAIL"),
        ),
        (
            r"ordinary retained; password='foo\'bar SECRETTAIL'",
            ("foo", "bar", "SECRETTAIL"),
        ),
    ],
)
def test_sensitive_path_markers_and_escaped_credential_values_are_fully_redacted(
    source: str,
    forbidden: tuple[str, ...],
) -> None:
    redactor = journal_module.DiagnosticRedactor(
        username="Escaped.Review",
        home=r"C:\Users\Escaped.Review",
        environment={"COLLIDING_MARKER_VALUE": "plain-secret-value"},
    )

    redacted = redactor.redact(source)

    assert all(fragment.casefold() not in redacted.casefold() for fragment in forbidden)
    assert redactor.redact(redacted) == redacted


def test_marker_and_escaped_quote_fragments_never_reach_archives_or_byte_pass(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    sensitive = (
        "ordinary retained; [REDACTED_PATH:sk-abcdefghijklmnop]; "
        "[REDACTED_PATH:plain-secret-value]; "
        r'json={"password":"foo\"bar SECRETTAIL"}; '
        r"password='single\'quote SINGLETail'"
    )
    forbidden = (
        "sk-abcdefghijklmnop",
        "plain-secret-value",
        "foo",
        "bar",
        "SECRETTAIL",
        "single",
        "quote",
        "SINGLETail",
    )
    redactor = journal_module.DiagnosticRedactor(
        username="Escaped.Review",
        home=r"C:\Users\Escaped.Review",
        environment={"COLLIDING_MARKER_VALUE": "plain-secret-value"},
    )
    journal = DiagnosticJournal(tmp_path, redactor=redactor)
    record = replace(_record("escaped-review-correlation"), redacted_message=sensitive)

    assert isinstance(journal.append_and_sync(record), ActionSuccess)
    monkeypatch.setattr(
        journal_module,
        "DIAGNOSTIC_JOURNAL_MAX_BYTES",
        journal.path.stat().st_size + 1,
    )
    for _ in range(5):
        assert isinstance(journal.append_and_sync(record), ActionSuccess)

    persisted_paths = (journal.path, *journal.archive_paths)
    assert all(path.exists() for path in persisted_paths)
    for path in persisted_paths:
        payload = path.read_bytes()
        payload.decode("utf-8", errors="strict")
        assert b"ordinary retained" in payload
        assert all(fragment.encode().lower() not in payload.lower() for fragment in forbidden)

    second_pass = redactor.redact_bytes(sensitive.encode())
    second_pass.decode("utf-8", errors="strict")
    assert b"ordinary retained" in second_pass
    assert all(fragment.encode().lower() not in second_pass.lower() for fragment in forbidden)


class _VerifiedSaltStore:
    def __init__(self, result: object) -> None:
        self.result = result
        self.calls = 0

    def load_or_create_verified_salt(self) -> object:
        self.calls += 1
        return self.result


class _RaisingVerifiedSaltStore:
    def __init__(self, secret: str) -> None:
        self.secret = secret

    def load_or_create_verified_salt(self) -> bytes:
        raise OSError(self.secret)


def test_display_pseudonymizer_uses_domain_separated_hmac_sha256_stably() -> None:
    salt = bytes(range(32))
    store = _VerifiedSaltStore(salt)
    pseudonymizer = journal_module.DisplayPseudonymizer(cast(Any, store))
    raw_identifier = r"DISPLAY\\QSCREEN-Δ"

    first = pseudonymizer.pseudonymize(raw_identifier)
    second = pseudonymizer.pseudonymize(raw_identifier)

    assert first == "05dca3bd88fca4e8ad860f456897e12fc224ec755113a3af4592baf1a11991d5"
    assert second == first
    assert first != journal_module.hashlib.sha256(raw_identifier.encode("utf-8")).hexdigest()
    assert store.calls == 2


@pytest.mark.parametrize(
    "store_result",
    [None, bytearray(b"s" * 32), b"s" * 31, b"s" * 33],
)
def test_display_pseudonymizer_fails_closed_for_unverified_salt_results(
    store_result: object,
) -> None:
    pseudonymizer = journal_module.DisplayPseudonymizer(cast(Any, _VerifiedSaltStore(store_result)))

    assert pseudonymizer.pseudonymize("display-1") is None


def test_display_pseudonymizer_fails_closed_without_exposing_store_exception() -> None:
    secret = "salt-value-that-must-not-escape"
    pseudonymizer = journal_module.DisplayPseudonymizer(cast(Any, _RaisingVerifiedSaltStore(secret)))

    assert pseudonymizer.pseudonymize("display-1") is None
    assert secret not in repr(pseudonymizer)


def test_display_pseudonymizer_rejects_bad_identifiers_before_store_access() -> None:
    class StringSubclass(str):
        pass

    store = _VerifiedSaltStore(b"s" * 32)
    pseudonymizer = journal_module.DisplayPseudonymizer(cast(Any, store))

    with pytest.raises(TypeError, match="exact str"):
        pseudonymizer.pseudonymize(cast(Any, StringSubclass("display-subclass")))

    assert pseudonymizer.pseudonymize("") is None
    assert pseudonymizer.pseudonymize("   ") is None
    assert pseudonymizer.pseudonymize("invalid-\ud800") is None
    assert store.calls == 0


def test_default_private_salt_path_is_absolute_and_outside_diagnostics(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))

    diagnostics = resolve_diagnostic_root()
    salt_path = journal_module.resolve_private_salt_path()

    assert salt_path.is_absolute()
    assert salt_path == diagnostics.parent / "Private" / "display-pseudonym.salt"
    assert diagnostics not in salt_path.parents


def test_for_current_user_has_no_non_windows_fallback_but_injection_still_works(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(journal_module.os, "name", "posix")

    assert journal_module.DisplayPseudonymizer.for_current_user().pseudonymize("display") is None
    injected = journal_module.DisplayPseudonymizer(cast(Any, _VerifiedSaltStore(b"v" * 32)))
    assert injected.pseudonymize("display") is not None


class _RecordingPrivateSaltBackend:
    def __init__(self, result: object = "candidate") -> None:
        self.result = result
        self.calls: list[tuple[Path, bytes]] = []

    def load_or_create_verified(self, path: Path, candidate_salt: bytes) -> object:
        self.calls.append((path, candidate_salt))
        return candidate_salt if self.result == "candidate" else self.result


class _RaisingPrivateSaltBackend:
    def load_or_create_verified(self, path: Path, candidate_salt: bytes) -> bytes:
        raise OSError(f"private salt backend failed for {path.name}")


def test_windows_private_salt_store_generates_exact_candidate_for_verified_backend(
    tmp_path: Path,
) -> None:
    salt = bytes(range(32))
    backend = _RecordingPrivateSaltBackend()
    path = tmp_path / "Private" / "display-pseudonym.salt"
    store = journal_module.WindowsPrivateSaltStore(
        path,
        random_bytes=lambda size: salt if size == 32 else b"",
        backend=cast(Any, backend),
    )

    result = store.load_or_create_verified_salt()

    assert result == salt
    assert store.path == path
    assert backend.calls == [(path, salt)]
    assert salt.hex() not in repr(store)


@pytest.mark.parametrize(
    "generated",
    [None, bytearray(b"s" * 32), b"s" * 31, b"s" * 33],
)
def test_windows_private_salt_store_rejects_invalid_random_output_before_backend(
    tmp_path: Path,
    generated: object,
) -> None:
    backend = _RecordingPrivateSaltBackend()
    store = journal_module.WindowsPrivateSaltStore(
        tmp_path / "salt",
        random_bytes=lambda _size: cast(Any, generated),
        backend=cast(Any, backend),
    )

    assert store.load_or_create_verified_salt() is None
    assert backend.calls == []


@pytest.mark.parametrize(
    "backend",
    [
        _RecordingPrivateSaltBackend(None),
        _RecordingPrivateSaltBackend(bytearray(b"s" * 32)),
        _RecordingPrivateSaltBackend(b"s" * 31),
        _RecordingPrivateSaltBackend(b"s" * 33),
        _RaisingPrivateSaltBackend(),
    ],
)
def test_windows_private_salt_store_fails_closed_for_backend_result(
    tmp_path: Path,
    backend: object,
) -> None:
    store = journal_module.WindowsPrivateSaltStore(
        tmp_path / "salt",
        random_bytes=lambda _size: b"c" * 32,
        backend=cast(Any, backend),
    )

    assert store.load_or_create_verified_salt() is None


def test_windows_private_salt_store_rejects_relative_path() -> None:
    with pytest.raises(ValueError, match="absolute"):
        journal_module.WindowsPrivateSaltStore(Path("relative-salt"))


@pytest.mark.parametrize(
    "actual_sddl",
    [
        "O:S-1-5-21-2000D:P(A;;FA;;;S-1-5-21-1000)",
        "O:S-1-5-21-1000",
        "O:S-1-5-21-1000D:NO_ACCESS_CONTROL",
        "O:S-1-5-21-1000D:(A;;FA;;;S-1-5-21-1000)",
        "O:S-1-5-21-1000D:P(A;ID;FA;;;S-1-5-21-1000)",
        "O:S-1-5-21-1000D:P(A;;FA;;;S-1-5-21-1000)(A;;FR;;;WD)",
        "O:S-1-5-21-1000D:P(A;;FA;;;S-1-5-21-1000)(A;;FR;;;AU)",
        "O:S-1-5-21-1000D:P(A;;FA;;;S-1-5-21-1000)(A;;FR;;;BU)",
        "O:S-1-5-21-1000D:P(XA;;FA;;;S-1-5-21-1000;(@User.x))",
        "O:S-1-5-21-1000D:P(D;;FR;;;WD)(A;;FA;;;S-1-5-21-1000)",
    ],
)
def test_private_salt_descriptor_policy_rejects_every_nonexact_acl(
    actual_sddl: str,
) -> None:
    expected = "O:S-1-5-21-1000D:P(A;;FA;;;S-1-5-21-1000)"

    assert not journal_module._private_salt_descriptor_is_exact(actual_sddl, expected)


def test_private_salt_descriptor_policy_accepts_only_exact_current_user_acl() -> None:
    expected = "O:S-1-5-21-1000D:P(A;;FA;;;S-1-5-21-1000)"

    assert journal_module._private_salt_descriptor_is_exact(expected, expected)


def test_private_salt_file_metadata_policy_accepts_one_exact_regular_file() -> None:
    metadata = journal_module._WindowsSaltFileMetadata(
        file_type=1,
        file_attributes=2,
        link_count=1,
        byte_length=32,
    )

    assert journal_module._private_salt_file_metadata_is_safe(metadata)


@pytest.mark.parametrize(
    "overrides",
    [
        {"file_type": 0},
        {"file_type": 2},
        {"file_attributes": 0x10},
        {"file_attributes": 0x400},
        {"link_count": 0},
        {"link_count": 2},
        {"byte_length": 0},
        {"byte_length": 31},
        {"byte_length": 33},
    ],
)
def test_private_salt_file_metadata_policy_rejects_unsafe_or_inconclusive_state(
    overrides: dict[str, int],
) -> None:
    values = {
        "file_type": 1,
        "file_attributes": 2,
        "link_count": 1,
        "byte_length": 32,
    }
    values.update(overrides)
    metadata = journal_module._WindowsSaltFileMetadata(**values)

    assert not journal_module._private_salt_file_metadata_is_safe(metadata)


@pytest.mark.parametrize(
    "unexpected_attribute",
    [
        0x00000001,  # read-only
        0x00000004,  # system
        0x00000040,  # device
        0x00000080,  # normal
        0x00000100,  # temporary
        0x00000200,  # sparse
        0x00000800,  # compressed
        0x00001000,  # offline
        0x00004000,  # encrypted
        0x00008000,  # integrity stream
        0x00010000,  # virtual
        0x00020000,  # no scrub data
        0x00040000,  # recall on open / extended attributes
        0x00080000,  # pinned
        0x00100000,  # unpinned
        0x00400000,  # recall on data access
    ],
)
def test_private_salt_file_metadata_rejects_every_nonallowlisted_attribute_bit(
    unexpected_attribute: int,
) -> None:
    metadata = journal_module._WindowsSaltFileMetadata(
        file_type=1,
        file_attributes=0x00002022 | unexpected_attribute,
        link_count=1,
        byte_length=32,
    )

    assert not journal_module._private_salt_file_metadata_is_safe(metadata)


@pytest.mark.skipif(journal_module.os.name != "nt", reason="Windows security descriptors")
def test_ctypes_windows_private_salt_backend_creates_reopens_and_verifies(
    tmp_path: Path,
) -> None:
    path = tmp_path / "Private" / "display-pseudonym.salt"
    first_candidate = bytes(range(32))
    first = journal_module.WindowsPrivateSaltStore(
        path,
        random_bytes=lambda _size: first_candidate,
    ).load_or_create_verified_salt()
    second = journal_module.WindowsPrivateSaltStore(
        path,
        random_bytes=lambda _size: b"z" * 32,
    ).load_or_create_verified_salt()

    assert first == first_candidate
    assert second == first_candidate
    assert path.read_bytes() == first_candidate


@pytest.mark.skipif(journal_module.os.name != "nt", reason="Windows security descriptors")
def test_ctypes_windows_private_salt_backend_rejects_changed_file_size(
    tmp_path: Path,
) -> None:
    path = tmp_path / "Private" / "display-pseudonym.salt"
    store = journal_module.WindowsPrivateSaltStore(
        path,
        random_bytes=lambda _size: b"q" * 32,
    )
    assert store.load_or_create_verified_salt() == b"q" * 32

    with path.open("r+b") as salt_file:
        salt_file.seek(0)
        salt_file.write(b"short")
        salt_file.truncate()
        salt_file.flush()
        journal_module.os.fsync(salt_file.fileno())

    assert store.load_or_create_verified_salt() is None


def test_pseudonym_persistence_scan_excludes_raw_identifier_and_salt_from_all_generations(
    tmp_path: Path,
) -> None:
    raw_identifier = r"DISPLAY\\ACME\\SECRET-SERIAL-9988"
    salt = b"private-salt-material-32-bytes!!"
    pseudonym = journal_module.DisplayPseudonymizer(cast(Any, _VerifiedSaltStore(salt))).pseudonymize(raw_identifier)
    assert pseudonym is not None
    assert len(pseudonym) == 64
    assert pseudonym == pseudonym.lower()

    journal = DiagnosticJournal(tmp_path)
    for generation in range(7):
        outcome = journal.append_and_sync(
            replace(
                _record(f"pseudonym-generation-{generation}"),
                redacted_message="rotation-filler-" + ("x" * 600_000),
                display_pseudonym=pseudonym,
            )
        )
        assert isinstance(outcome, ActionSuccess)

    bundle_eligible_paths = (journal.path, *journal.archive_paths)
    assert all(path.exists() for path in bundle_eligible_paths)
    for path in bundle_eligible_paths:
        payload = path.read_bytes()
        assert raw_identifier.encode("utf-8") not in payload
        assert salt not in payload
        assert salt.hex().encode("ascii") not in payload
        assert pseudonym.encode("ascii") in payload
        decoded = json.loads(payload.decode("utf-8"))
        assert decoded["display_pseudonym"] == pseudonym

    assert {
        "DisplayPseudonymizer",
        "PrivateSaltStore",
        "WindowsPrivateSaltStore",
        "resolve_private_salt_path",
    }.issubset(journal_module.__all__)


@pytest.mark.parametrize(
    "invalid_pseudonym",
    [
        "raw-display-identifier",
        "A" * 64,
        "a" * 63,
        "a" * 65,
        "g" * 64,
    ],
)
def test_display_pseudonym_rejects_noncanonical_values_before_io(
    tmp_path: Path,
    invalid_pseudonym: str,
) -> None:
    root = tmp_path / invalid_pseudonym[:12]

    with pytest.raises(TypeError, match="display_pseudonym"):
        DiagnosticJournal(root).append_and_sync(replace(_record(), display_pseudonym=invalid_pseudonym))

    assert not root.exists()


def test_display_pseudonym_rejects_string_subclass_before_io(tmp_path: Path) -> None:
    class StringSubclass(str):
        pass

    root = tmp_path / "subclass"
    with pytest.raises(TypeError, match="display_pseudonym"):
        DiagnosticJournal(root).append_and_sync(
            replace(
                _record(),
                display_pseudonym=cast(Any, StringSubclass("a" * 64)),
            )
        )

    assert not root.exists()


def test_valid_display_pseudonym_bypasses_environment_redaction_collision(
    tmp_path: Path,
) -> None:
    pseudonym = "ab" * 32
    journal = DiagnosticJournal(
        tmp_path,
        redactor=journal_module.DiagnosticRedactor(
            username="Collision.User",
            home=r"C:\Users\Collision.User",
            environment={"COLLIDING_SECRET": pseudonym},
        ),
    )

    outcome = journal.append_and_sync(replace(_record(), display_pseudonym=pseudonym))

    assert isinstance(outcome, ActionSuccess)
    payload = json.loads(journal.path.read_text(encoding="utf-8"))
    assert payload["display_pseudonym"] == pseudonym


class _DelayedWinnerSaltBackend:
    def __init__(self) -> None:
        self._state_lock = threading.Lock()
        self.first_entered = threading.Event()
        self.release_first = threading.Event()
        self.winner: bytes | None = None
        self.calls: list[bytes] = []

    def load_or_create_verified(self, _path: Path, candidate_salt: bytes) -> bytes:
        with self._state_lock:
            self.calls.append(candidate_salt)
            is_first = len(self.calls) == 1
            if not is_first and self.winner is None:
                return candidate_salt
        if is_first:
            self.first_entered.set()
            assert self.release_first.wait(timeout=2)
            with self._state_lock:
                self.winner = candidate_salt
        assert self.winner is not None
        return self.winner


def test_same_process_first_run_serializes_and_reuses_first_verified_salt(
    tmp_path: Path,
) -> None:
    backend = _DelayedWinnerSaltBackend()
    path = tmp_path / "Private" / "display-pseudonym.salt"
    second_generated = threading.Event()
    first_store = journal_module.WindowsPrivateSaltStore(
        path,
        random_bytes=lambda _size: b"1" * 32,
        backend=cast(Any, backend),
    )
    second_store = journal_module.WindowsPrivateSaltStore(
        path,
        random_bytes=lambda _size: (second_generated.set(), b"2" * 32)[1],
        backend=cast(Any, backend),
    )

    with ThreadPoolExecutor(max_workers=2) as executor:
        first_future = executor.submit(first_store.load_or_create_verified_salt)
        assert backend.first_entered.wait(timeout=2)
        second_future = executor.submit(second_store.load_or_create_verified_salt)
        assert second_generated.wait(timeout=2)
        backend.release_first.set()
        first = first_future.result(timeout=2)
        second = second_future.result(timeout=2)

    assert first == b"1" * 32
    assert second == first
    assert backend.calls == [b"1" * 32, b"2" * 32]


class _DeterministicClock:
    def __init__(self) -> None:
        self.now = 10.0
        self.sleeps: list[float] = []

    def monotonic(self) -> float:
        return self.now

    def sleep(self, duration: float) -> None:
        self.sleeps.append(duration)
        self.now += duration


def test_private_salt_reopen_wait_is_bounded_and_fails_closed() -> None:
    clock = _DeterministicClock()
    calls = 0

    def sharing_violation() -> tuple[int | None, int]:
        nonlocal calls
        calls += 1
        return None, 32

    handle = journal_module._wait_for_private_salt_handle(
        sharing_violation,
        monotonic=clock.monotonic,
        sleeper=clock.sleep,
        timeout_seconds=0.025,
        retry_interval_seconds=0.01,
    )

    assert handle is None
    assert calls == 4
    assert clock.sleeps == pytest.approx([0.01, 0.01, 0.005])
    assert clock.now == pytest.approx(10.025)


def test_private_salt_reopen_wait_accepts_delayed_winner_before_deadline() -> None:
    clock = _DeterministicClock()
    attempts = iter(((None, 32), (None, 33), (8675309, 0)))

    handle = journal_module._wait_for_private_salt_handle(
        lambda: next(attempts),
        monotonic=clock.monotonic,
        sleeper=clock.sleep,
        timeout_seconds=2.0,
        retry_interval_seconds=0.01,
    )

    assert handle == 8675309
    assert clock.sleeps == [0.01, 0.01]


class _BundleClock:
    def __init__(self) -> None:
        self.monotonic_value = 100.0
        self.utc_value = datetime(2026, 7, 14, 12, 0, tzinfo=timezone.utc)

    def monotonic(self) -> float:
        return self.monotonic_value

    def utc_now(self) -> datetime:
        return self.utc_value


def test_bundle_preview_contract_is_exact_immutable_and_second_redacted(
    tmp_path: Path,
) -> None:
    member_type = journal_module.BundleMemberPreview
    preview_type = journal_module.BundlePreview
    receipt_type = journal_module.DiagnosticBundleReceipt

    assert tuple(field.name for field in fields(member_type)) == (
        "basename",
        "byte_length",
        "sha256",
    )
    assert tuple(field.name for field in fields(preview_type)) == (
        "token",
        "members",
        "expires_utc",
    )
    assert tuple(field.name for field in fields(receipt_type)) == (
        "published_path",
        "bundle_sha256",
        "byte_length",
        "member_hashes",
        "readback_verified",
    )

    journal = DiagnosticJournal(tmp_path)
    tmp_path.mkdir(parents=True, exist_ok=True)
    active_bytes = b"password=private-value\n"
    invalid_utf8 = b"\xff\xfeprivate"
    journal.path.write_bytes(active_bytes)
    journal.archive_paths[1].write_bytes(invalid_utf8)
    (tmp_path / "display-pseudonym.salt").write_bytes(b"salt-must-not-enter")
    (tmp_path / ".diagnostics.append.tmp").write_bytes(b"temp-must-not-enter")
    (tmp_path / "unrelated.jsonl").write_bytes(b"unrelated")
    redactor = journal_module.DiagnosticRedactor(
        username="Bundle.User",
        home=r"C:\Users\Bundle.User",
        environment={},
    )
    clock = _BundleClock()
    manager = journal_module.DiagnosticBundleManager(
        journal,
        redactor=redactor,
        token_factory=lambda: "opaque-token-1",
        monotonic=clock.monotonic,
        utc_now=clock.utc_now,
        ttl_seconds=60.0,
    )

    preview = manager.preview()

    expected_payloads = {
        "diagnostics.2.jsonl": journal_module.INVALID_UTF8_REDACTION_MARKER.encode("utf-8"),
        "diagnostics.jsonl": redactor.redact_bytes(active_bytes),
    }
    assert preview.token == "opaque-token-1"
    assert preview.expires_utc == "2026-07-14T12:01:00Z"
    assert tuple(member.basename for member in preview.members) == tuple(sorted(expected_payloads))
    assert preview.members == tuple(
        member_type(
            basename=basename,
            byte_length=len(expected_payloads[basename]),
            sha256=hashlib.sha256(expected_payloads[basename]).hexdigest(),
        )
        for basename in sorted(expected_payloads)
    )
    with pytest.raises(FrozenInstanceError):
        preview.token = "changed"  # type: ignore[misc]


def test_bundle_preview_grant_replaces_expires_and_is_not_restart_persistent(
    tmp_path: Path,
) -> None:
    journal = DiagnosticJournal(tmp_path)
    assert isinstance(journal.append_and_sync(_record("bundle-token-state")), ActionSuccess)
    tokens = iter(("first-token", "second-token"))
    clock = _BundleClock()
    manager = journal_module.DiagnosticBundleManager(
        journal,
        token_factory=lambda: next(tokens),
        monotonic=clock.monotonic,
        utc_now=clock.utc_now,
        ttl_seconds=30.0,
    )

    first = manager.preview()
    second = manager.preview()

    assert not manager.preview_is_live(first.token)
    assert manager.preview_is_live(second.token)
    clock.monotonic_value = 130.0
    assert not manager.preview_is_live(second.token)
    restarted = journal_module.DiagnosticBundleManager(journal)
    assert not restarted.preview_is_live(second.token)


def test_bundle_tokens_are_bounded_urlsafe_and_invalid_callers_preserve_live_grant(
    tmp_path: Path,
) -> None:
    journal = DiagnosticJournal(tmp_path)
    assert isinstance(journal.append_and_sync(_record("bundle-token-validation")), ActionSuccess)
    manager = journal_module.DiagnosticBundleManager(
        journal,
        token_factory=lambda: "valid-token_1",
    )
    preview = manager.preview()

    for invalid_token in ("snowman-☃", " token ", "\t", "a" * 257):
        assert not manager.preview_is_live(invalid_token)
        with pytest.raises(ActionFailure) as failure:
            manager.create(invalid_token, tmp_path / "invalid-token.zip")
        assert failure.value.code == "DIAGNOSTIC_BUNDLE_TOKEN_INVALID"
        assert manager.preview_is_live(preview.token)

    invalid_factory = journal_module.DiagnosticBundleManager(
        journal,
        token_factory=lambda: "factory-☃",
    )
    with pytest.raises(ActionFailure) as failure:
        invalid_factory.preview()
    assert failure.value.code == "DIAGNOSTIC_BUNDLE_PREVIEW_FAILED"


def test_bundle_preview_rejects_nonfinite_computed_deadline(tmp_path: Path) -> None:
    journal = DiagnosticJournal(tmp_path)
    assert isinstance(journal.append_and_sync(_record("bundle-deadline")), ActionSuccess)
    manager = journal_module.DiagnosticBundleManager(
        journal,
        token_factory=lambda: "deadline-token",
        monotonic=lambda: 1e308,
        utc_now=lambda: datetime(2026, 7, 14, tzinfo=timezone.utc),
        ttl_seconds=1e308,
    )

    with pytest.raises(ActionFailure) as failure:
        manager.preview()
    assert failure.value.code == "DIAGNOSTIC_BUNDLE_PREVIEW_FAILED"
    assert not manager.preview_is_live("deadline-token")


def test_folder_opener_is_called_only_for_the_exact_action(tmp_path: Path) -> None:
    journal = DiagnosticJournal(tmp_path)
    calls: list[Path] = []
    manager = journal_module.DiagnosticBundleManager(
        journal,
        folder_opener=calls.append,
    )

    with pytest.raises(ActionFailure) as wrong:
        manager.open_folder("diagnostics.bundle.preview")
    assert wrong.value.code == "DIAGNOSTIC_FOLDER_ACTION_INVALID"
    assert calls == []

    manager.open_folder("diagnostics.folder.open")
    assert calls == [tmp_path]


def test_bundle_create_consumes_exact_token_and_publishes_verified_deterministic_zip(
    tmp_path: Path,
) -> None:
    journal_root = tmp_path / "journal"
    journal = DiagnosticJournal(journal_root)
    journal_root.mkdir()
    raw_payloads = {
        "diagnostics.1.jsonl": b"token=SecretBundleToken-123456\n",
        "diagnostics.jsonl": b"\xff\xfeinvalid-private-bytes",
    }
    for basename, payload in raw_payloads.items():
        (journal_root / basename).write_bytes(payload)
    redactor = journal_module.DiagnosticRedactor(
        username="Bundle.User",
        home=r"C:\Users\Bundle.User",
        environment={},
    )
    manager = journal_module.DiagnosticBundleManager(
        journal,
        redactor=redactor,
        token_factory=lambda: "exact-create-token",
        monotonic=lambda: 10.0,
        utc_now=lambda: datetime(2026, 7, 14, tzinfo=timezone.utc),
    )
    preview = manager.preview()
    destination = tmp_path / "diagnostics-bundle.zip"

    receipt = manager.create(preview.token, destination)

    expected_payloads = {basename: redactor.redact_bytes(payload) for basename, payload in raw_payloads.items()}
    assert receipt.published_path == destination
    assert receipt.byte_length == destination.stat().st_size
    assert receipt.bundle_sha256 == hashlib.sha256(destination.read_bytes()).hexdigest()
    assert receipt.member_hashes == tuple(
        (basename, hashlib.sha256(expected_payloads[basename]).hexdigest()) for basename in sorted(expected_payloads)
    )
    assert receipt.readback_verified is True
    with zipfile.ZipFile(destination, "r") as archive:
        assert archive.comment == b""
        assert archive.namelist() == sorted(expected_payloads)
        assert archive.testzip() is None
        for info in archive.infolist():
            assert info.compress_type == zipfile.ZIP_STORED
            assert info.date_time == (1980, 1, 1, 0, 0, 0)
            assert info.extra == b""
            assert info.comment == b""
            assert info.external_attr >> 16 == 0o100600
            assert archive.read(info) == expected_payloads[info.filename]
    assert not manager.preview_is_live(preview.token)
    with pytest.raises(ActionFailure) as replay:
        manager.create(preview.token, tmp_path / "replay.zip")
    assert replay.value.code == "DIAGNOSTIC_BUNDLE_TOKEN_INVALID"
    assert not list(tmp_path.glob(".calibrate-pro-diagnostic-bundle.*.tmp"))


def test_bundle_wrong_token_relative_and_existing_destinations_leave_grant_live(
    tmp_path: Path,
) -> None:
    journal = DiagnosticJournal(tmp_path / "journal")
    assert isinstance(journal.append_and_sync(_record("bundle-gates")), ActionSuccess)
    manager = journal_module.DiagnosticBundleManager(
        journal,
        token_factory=lambda: "live-token",
    )
    preview = manager.preview()

    with pytest.raises(ActionFailure) as wrong:
        manager.create("wrong-token", tmp_path / "wrong.zip")
    assert wrong.value.code == "DIAGNOSTIC_BUNDLE_TOKEN_INVALID"
    assert manager.preview_is_live(preview.token)

    with pytest.raises(ActionFailure) as relative:
        manager.create(preview.token, Path("relative.zip"))
    assert relative.value.code == "DIAGNOSTIC_BUNDLE_DESTINATION_INVALID"
    assert manager.preview_is_live(preview.token)

    existing = tmp_path / "existing.zip"
    existing.write_bytes(b"user-owned")
    with pytest.raises(ActionFailure) as collision:
        manager.create(preview.token, existing)
    assert collision.value.code == "DIAGNOSTIC_BUNDLE_DESTINATION_EXISTS"
    assert existing.read_bytes() == b"user-owned"
    assert manager.preview_is_live(preview.token)

    receipt = manager.create(preview.token, tmp_path / "accepted.zip")
    assert receipt.readback_verified


def test_bundle_expired_stale_and_restart_tokens_fail_before_temp_creation(
    tmp_path: Path,
) -> None:
    journal = DiagnosticJournal(tmp_path / "journal")
    assert isinstance(journal.append_and_sync(_record("bundle-stale")), ActionSuccess)
    clock = _BundleClock()
    tokens = iter(("expired-token", "stale-token"))
    manager = journal_module.DiagnosticBundleManager(
        journal,
        token_factory=lambda: next(tokens),
        monotonic=clock.monotonic,
        utc_now=clock.utc_now,
        ttl_seconds=5.0,
    )

    expired = manager.preview()
    clock.monotonic_value += 5.0
    with pytest.raises(ActionFailure) as expired_failure:
        manager.create(expired.token, tmp_path / "expired.zip")
    assert expired_failure.value.code == "DIAGNOSTIC_BUNDLE_PREVIEW_EXPIRED"

    clock.monotonic_value = 100.0
    stale = manager.preview()
    with journal.path.open("ab") as stream:
        stream.write(b"journal changed\n")
    with pytest.raises(ActionFailure) as stale_failure:
        manager.create(stale.token, tmp_path / "stale.zip")
    assert stale_failure.value.code == "DIAGNOSTIC_BUNDLE_PREVIEW_STALE"

    restarted = journal_module.DiagnosticBundleManager(journal)
    with pytest.raises(ActionFailure) as restart_failure:
        restarted.create(stale.token, tmp_path / "restart.zip")
    assert restart_failure.value.code == "DIAGNOSTIC_BUNDLE_TOKEN_INVALID"
    assert not list(tmp_path.glob(".calibrate-pro-diagnostic-bundle.*.tmp"))
    assert not (tmp_path / "expired.zip").exists()
    assert not (tmp_path / "stale.zip").exists()
    assert not (tmp_path / "restart.zip").exists()


def test_bundle_preview_rejects_empty_or_symlinked_allowlisted_inventory(
    tmp_path: Path,
) -> None:
    empty = journal_module.DiagnosticBundleManager(DiagnosticJournal(tmp_path / "empty"))
    with pytest.raises(ActionFailure) as empty_failure:
        empty.preview()
    assert empty_failure.value.code == "DIAGNOSTIC_BUNDLE_EMPTY"

    root = tmp_path / "symlink"
    root.mkdir()
    outside = tmp_path / "outside.jsonl"
    outside.write_bytes(b"outside")
    try:
        os.symlink(outside, root / "diagnostics.jsonl")
    except OSError as error:
        pytest.skip(f"symlink creation is unavailable: {error}")
    manager = journal_module.DiagnosticBundleManager(DiagnosticJournal(root))
    with pytest.raises(ActionFailure) as invalid:
        manager.preview()
    assert invalid.value.code == "DIAGNOSTIC_BUNDLE_SOURCE_INVALID"


def test_boundary_diagnostic_preview_finalizes_after_its_own_record_sync(
    tmp_path: Path,
) -> None:
    journal = DiagnosticJournal(tmp_path)
    manager = journal_module.DiagnosticBundleManager(
        journal,
        token_factory=lambda: "post-sync-token",
        monotonic=lambda: 20.0,
        utc_now=lambda: datetime(2026, 7, 14, tzinfo=timezone.utc),
    )
    boundary = ActionBoundary(lambda: "post-sync-correlation", journal)

    outcome = boundary.invoke_diagnostic_preview(WorkflowStage.PREVIEW, manager.preview)

    assert isinstance(outcome, ActionSuccess)
    assert outcome.action_id == "diagnostics.bundle.preview"
    assert outcome.correlation_id == "post-sync-correlation"
    assert outcome.stage is WorkflowStage.PREVIEW
    assert outcome.value.token == "post-sync-token"
    assert manager.preview_is_live(outcome.value.token)
    records = _json_lines(journal.path)
    assert [(record["action_id"], record["outcome"]) for record in records] == [
        ("diagnostics.bundle.preview", "success")
    ]


def test_boundary_diagnostic_preview_correlation_or_sync_failure_never_finalizes(
    tmp_path: Path,
) -> None:
    finalizer_calls = 0

    def finalizer() -> object:
        nonlocal finalizer_calls
        finalizer_calls += 1
        return object()

    correlation_journal = DiagnosticJournal(tmp_path / "correlation")

    def fail_correlation() -> str:
        raise RuntimeError("private correlation detail")

    correlation = ActionBoundary(fail_correlation, correlation_journal).invoke_diagnostic_preview(
        WorkflowStage.PREVIEW,
        finalizer,
    )
    assert isinstance(correlation, ActionError)
    assert correlation.code == "CORRELATION_ID_UNAVAILABLE"
    assert finalizer_calls == 0

    class RejectingJournal:
        def preflight(self, action_id: str, correlation_id: str) -> ActionSuccess[None]:
            return ActionSuccess(action_id, correlation_id, WorkflowStage.PREVIEW, None)

        def append_and_sync(self, record: JournalRecord) -> ActionError:
            return ActionError(
                action_id=record.action_id,
                code="DIAGNOSTIC_JOURNAL_WRITE_FAILED",
                summary="The diagnostic record could not be synchronized.",
                retryable=True,
                next_action=None,
                stage=WorkflowStage(record.workflow_stage),
                category="diagnostics",
                correlation_id=record.correlation_id,
                effect_state="none",
                published_artifact=None,
                apply_phase_flags=(),
                recovery_guarantee=None,
            )

    sync = ActionBoundary(lambda: "sync-correlation", RejectingJournal()).invoke_diagnostic_preview(
        WorkflowStage.PREVIEW,
        finalizer,
    )
    assert isinstance(sync, ActionError)
    assert sync.code == "DIAGNOSTIC_JOURNAL_UNAVAILABLE"
    assert finalizer_calls == 0


def test_boundary_diagnostic_preview_finalization_failure_records_correction_and_no_token(
    tmp_path: Path,
) -> None:
    journal = DiagnosticJournal(tmp_path)

    def fail_token() -> str:
        raise RuntimeError("private token detail")

    manager = journal_module.DiagnosticBundleManager(journal, token_factory=fail_token)
    boundary = ActionBoundary(lambda: "finalize-correlation", journal)

    outcome = boundary.invoke_diagnostic_preview(WorkflowStage.PREVIEW, manager.preview)

    assert isinstance(outcome, ActionError)
    assert outcome.code == "DIAGNOSTIC_BUNDLE_PREVIEW_FAILED"
    assert outcome.correlation_id == "finalize-correlation"
    assert not manager.preview_is_live("unissued-token")
    records = _json_lines(journal.path)
    assert [record["outcome"] for record in records] == ["success", "failure"]
    assert {record["correlation_id"] for record in records} == {"finalize-correlation"}
    assert records[-1]["error_code"] == "DIAGNOSTIC_BUNDLE_PREVIEW_FAILED"


def test_bundle_preview_activation_is_exception_atomic(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    journal = DiagnosticJournal(tmp_path)
    assert isinstance(journal.append_and_sync(_record("atomic-preview")), ActionSuccess)
    manager = journal_module.DiagnosticBundleManager(
        journal,
        token_factory=lambda: "never-live-token",
        monotonic=lambda: 10.0,
        utc_now=lambda: datetime(2026, 7, 14, tzinfo=timezone.utc),
    )

    def fail_preview(**_kwargs: object) -> object:
        raise RuntimeError("injected result construction failure")

    monkeypatch.setattr(journal_module, "BundlePreview", fail_preview)

    with pytest.raises(RuntimeError, match="result construction"):
        manager.preview()
    assert not manager.preview_is_live("never-live-token")


def test_boundary_diagnostic_preview_scrubs_raw_finalizer_exception_and_records_identity(
    tmp_path: Path,
) -> None:
    journal = DiagnosticJournal(tmp_path)
    boundary = ActionBoundary(lambda: "raw-finalizer-correlation", journal)

    def fail() -> object:
        raise RuntimeError("private raw finalizer detail")

    outcome = boundary.invoke_diagnostic_preview(WorkflowStage.PREVIEW, fail)

    assert isinstance(outcome, ActionError)
    assert outcome.code == "DIAGNOSTIC_BUNDLE_PREVIEW_FAILED"
    assert outcome.summary == "The diagnostic bundle preview could not be created."
    assert "private raw finalizer detail" not in repr(outcome)
    records = _json_lines(journal.path)
    assert [record["outcome"] for record in records] == ["success", "failure"]
    assert records[-1]["exception_type"] == "RuntimeError"
    assert records[-1]["error_code"] == "DIAGNOSTIC_BUNDLE_PREVIEW_FAILED"
    assert {(record["action_id"], record["workflow_stage"], record["correlation_id"]) for record in records} == {
        ("diagnostics.bundle.preview", "preview", "raw-finalizer-correlation")
    }


def test_boundary_diagnostic_preview_failed_correction_sync_returns_sync_failure() -> None:
    class FailSecondSync:
        def __init__(self) -> None:
            self.records: list[JournalRecord] = []

        def preflight(self, action_id: str, correlation_id: str) -> ActionSuccess[None]:
            return ActionSuccess(action_id, correlation_id, WorkflowStage.PREVIEW, None)

        def append_and_sync(self, record: JournalRecord) -> ActionSuccess[None] | ActionError:
            self.records.append(record)
            if len(self.records) == 1:
                return ActionSuccess(
                    record.action_id,
                    record.correlation_id,
                    WorkflowStage(record.workflow_stage),
                    None,
                )
            return ActionError(
                action_id=record.action_id,
                code="DIAGNOSTIC_JOURNAL_WRITE_FAILED",
                summary="The diagnostic record could not be synchronized.",
                retryable=True,
                next_action=None,
                stage=WorkflowStage(record.workflow_stage),
                category="diagnostics",
                correlation_id=record.correlation_id,
                effect_state="none",
                published_artifact=None,
                apply_phase_flags=(),
                recovery_guarantee=None,
            )

    journal = FailSecondSync()
    boundary = ActionBoundary(lambda: "correction-sync-correlation", journal)

    def fail() -> object:
        raise RuntimeError("private correction detail")

    outcome = boundary.invoke_diagnostic_preview(WorkflowStage.PREVIEW, fail)

    assert isinstance(outcome, ActionError)
    assert outcome.code == "ACTION_COMPLETED_DIAGNOSTICS_FAILED"
    assert len(journal.records) == 2
    assert [record.outcome for record in journal.records] == ["success", "failure"]
    assert {record.correlation_id for record in journal.records} == {"correction-sync-correlation"}


@pytest.mark.parametrize("process_exception", [KeyboardInterrupt, SystemExit])
def test_boundary_diagnostic_preview_propagates_process_control_exceptions(
    tmp_path: Path,
    process_exception: type[BaseException],
) -> None:
    journal = DiagnosticJournal(tmp_path / process_exception.__name__)
    boundary = ActionBoundary(lambda: "process-correlation", journal)

    def interrupt() -> object:
        raise process_exception()

    with pytest.raises(process_exception):
        boundary.invoke_diagnostic_preview(WorkflowStage.PREVIEW, interrupt)

    records = _json_lines(journal.path)
    assert [record["outcome"] for record in records] == ["success"]


def _prepared_bundle_manager(
    tmp_path: Path,
    *,
    token: str = "fault-token",
    **manager_kwargs: object,
) -> tuple[object, object]:
    journal = DiagnosticJournal(tmp_path / "journal")
    assert isinstance(journal.append_and_sync(_record("bundle-fault")), ActionSuccess)
    manager = journal_module.DiagnosticBundleManager(
        journal,
        token_factory=lambda: token,
        **cast(Any, manager_kwargs),
    )
    preview = manager.preview()
    return manager, preview


@pytest.mark.parametrize("fault_phase", ["temp_open", "zip_write", "fsync"])
def test_bundle_prepublication_faults_leave_no_destination_or_temp_and_consume_token(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    fault_phase: str,
) -> None:
    manager, preview = _prepared_bundle_manager(tmp_path)
    destination = tmp_path / f"{fault_phase}.zip"
    if fault_phase == "temp_open":
        real_open = journal_module.os.open

        def fail_temp_open(path: object, flags: int, mode: int = 0o777) -> int:
            if flags & os.O_CREAT:
                raise OSError("injected temp open fault")
            return real_open(path, flags, mode)

        monkeypatch.setattr(journal_module.os, "open", fail_temp_open)
    elif fault_phase == "zip_write":
        monkeypatch.setattr(
            journal_module.zipfile.ZipFile,
            "writestr",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("injected write fault")),
        )
    else:
        monkeypatch.setattr(
            journal_module.os,
            "fsync",
            lambda _fd: (_ for _ in ()).throw(OSError("injected fsync fault")),
        )

    with pytest.raises(ActionFailure) as failure:
        manager.create(preview.token, destination)  # type: ignore[attr-defined]

    assert failure.value.code == "DIAGNOSTIC_BUNDLE_CREATE_FAILED"
    assert failure.value.effect_state == "none"
    assert failure.value.published_artifact is None
    assert str(destination) not in str(failure.value)
    assert preview.token not in str(failure.value)
    assert not destination.exists()
    assert not list(tmp_path.glob(".calibrate-pro-diagnostic-bundle.*.tmp"))
    with pytest.raises(ActionFailure) as replay:
        manager.create(preview.token, tmp_path / "replay.zip")  # type: ignore[attr-defined]
    assert replay.value.code == "DIAGNOSTIC_BUNDLE_TOKEN_INVALID"


def test_bundle_atomic_publish_failure_before_publish_leaves_no_destination(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager, preview = _prepared_bundle_manager(tmp_path)
    destination = tmp_path / "publish-failed.zip"
    publish_primitive = "rename" if os.name == "nt" else "link"
    monkeypatch.setattr(
        journal_module.os,
        publish_primitive,
        lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("publish fault")),
    )

    with pytest.raises(ActionFailure) as failure:
        manager.create(preview.token, destination)  # type: ignore[attr-defined]

    assert failure.value.code == "DIAGNOSTIC_BUNDLE_CREATE_FAILED"
    assert failure.value.effect_state == "none"
    assert failure.value.published_artifact is None
    assert not destination.exists()
    assert not list(tmp_path.glob(".calibrate-pro-diagnostic-bundle.*.tmp"))


def test_bundle_atomic_publish_postcommit_fault_preserves_exact_effect_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager, preview = _prepared_bundle_manager(tmp_path)
    destination = tmp_path / "published-then-failed.zip"
    publish_primitive = "rename" if os.name == "nt" else "link"
    real_publish = getattr(journal_module.os, publish_primitive)

    def publish_then_fail(*args: object, **kwargs: object) -> None:
        real_publish(*args, **kwargs)
        raise OSError("postcommit publish fault")

    monkeypatch.setattr(journal_module.os, publish_primitive, publish_then_fail)

    with pytest.raises(ActionFailure) as failure:
        manager.create(preview.token, destination)  # type: ignore[attr-defined]

    published_sha256 = hashlib.sha256(destination.read_bytes()).hexdigest()
    assert failure.value.code == "DIAGNOSTIC_BUNDLE_READBACK_FAILED"
    assert failure.value.effect_state == "local_write_published"
    assert failure.value.published_artifact == (destination.name, published_sha256)
    assert not list(tmp_path.glob(".calibrate-pro-diagnostic-bundle.*.tmp"))


def test_bundle_postpublish_readback_fault_preserves_exact_effect_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager, preview = _prepared_bundle_manager(tmp_path)
    destination = tmp_path / "published-readback-failed.zip"
    real_verify = manager._verify_zip  # type: ignore[attr-defined]
    calls = 0

    def fail_destination_readback(path: Path, payloads: object) -> tuple[int, str]:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("injected destination readback fault")
        return real_verify(path, payloads)

    monkeypatch.setattr(manager, "_verify_zip", fail_destination_readback)

    with pytest.raises(ActionFailure) as failure:
        manager.create(preview.token, destination)  # type: ignore[attr-defined]

    published_sha256 = hashlib.sha256(destination.read_bytes()).hexdigest()
    assert failure.value.code == "DIAGNOSTIC_BUNDLE_READBACK_FAILED"
    assert failure.value.effect_state == "local_write_published"
    assert failure.value.published_artifact == (destination.name, published_sha256)
    assert destination.exists()
    assert not list(tmp_path.glob(".calibrate-pro-diagnostic-bundle.*.tmp"))


def test_bundle_broken_destination_entry_is_never_replaced(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager, preview = _prepared_bundle_manager(tmp_path)
    destination = tmp_path / "broken-link.zip"
    real_lexists = journal_module.os.path.lexists
    publish_calls = 0

    def lexists(path: object) -> bool:
        return os.fspath(path) == os.fspath(destination) or real_lexists(path)

    def forbidden_publish(*_args: object, **_kwargs: object) -> None:
        nonlocal publish_calls
        publish_calls += 1
        raise AssertionError("broken destination must be rejected before publication")

    monkeypatch.setattr(journal_module.os.path, "lexists", lexists)
    publish_primitive = "rename" if os.name == "nt" else "link"
    monkeypatch.setattr(journal_module.os, publish_primitive, forbidden_publish)

    with pytest.raises(ActionFailure) as failure:
        manager.create(preview.token, destination)  # type: ignore[attr-defined]

    assert failure.value.code == "DIAGNOSTIC_BUNDLE_DESTINATION_EXISTS"
    assert publish_calls == 0
    assert manager.preview_is_live(preview.token)  # type: ignore[attr-defined]


def test_bundle_atomic_publish_race_preserves_unrelated_destination(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager, preview = _prepared_bundle_manager(tmp_path)
    destination = tmp_path / "raced.zip"
    unrelated_bytes = b"unrelated-user-file"
    real_lexists = journal_module.os.path.lexists
    destination_checks = 0

    def racing_lexists(path: object) -> bool:
        nonlocal destination_checks
        if os.fspath(path) == os.fspath(destination):
            destination_checks += 1
            if destination_checks == 2:
                destination.write_bytes(unrelated_bytes)
                return False
        return real_lexists(path)

    monkeypatch.setattr(journal_module.os.path, "lexists", racing_lexists)

    with pytest.raises(ActionFailure) as failure:
        manager.create(preview.token, destination)  # type: ignore[attr-defined]

    assert failure.value.code == "DIAGNOSTIC_BUNDLE_DESTINATION_EXISTS"
    assert failure.value.effect_state == "none"
    assert failure.value.published_artifact is None
    assert destination.read_bytes() == unrelated_bytes
    assert not list(tmp_path.glob(".calibrate-pro-diagnostic-bundle.*.tmp"))


def test_bundle_cleanup_removes_only_provably_dead_process_temp(
    tmp_path: Path,
) -> None:
    dead_pid = 999_999_991
    active_pid = 4242
    manager, preview = _prepared_bundle_manager(
        tmp_path,
        process_is_alive=lambda pid: pid == active_pid,
    )
    dead_temp = tmp_path / (f".calibrate-pro-diagnostic-bundle.{dead_pid}.{'a' * 32}.tmp")
    active_temp = tmp_path / (f".calibrate-pro-diagnostic-bundle.{active_pid}.{'b' * 32}.tmp")
    unrelated = tmp_path / ".calibrate-pro-diagnostic-bundle.not-owned.tmp"
    dead_temp.write_bytes(b"stale")
    active_temp.write_bytes(b"active")
    unrelated.write_bytes(b"unrelated")

    receipt = manager.create(preview.token, tmp_path / "cleaned.zip")  # type: ignore[attr-defined]

    assert receipt.readback_verified
    assert not dead_temp.exists()
    assert active_temp.read_bytes() == b"active"
    assert unrelated.read_bytes() == b"unrelated"


def test_bundle_zip_bytes_are_deterministic_across_independent_managers(
    tmp_path: Path,
) -> None:
    outputs: list[bytes] = []
    for run in ("first", "second"):
        root = tmp_path / run / "journal"
        root.mkdir(parents=True)
        (root / "diagnostics.jsonl").write_bytes(b"one\n")
        (root / "diagnostics.3.jsonl").write_bytes(b"two\n")
        manager = journal_module.DiagnosticBundleManager(
            DiagnosticJournal(root),
            token_factory=lambda: "token",
            monotonic=lambda: 1.0,
            utc_now=lambda: datetime(2026, 7, 14, tzinfo=timezone.utc),
        )
        preview = manager.preview()
        destination = tmp_path / run / "bundle.zip"
        manager.create(preview.token, destination)
        outputs.append(destination.read_bytes())

    assert outputs[0] == outputs[1]


@pytest.mark.parametrize("process_exception", [KeyboardInterrupt, SystemExit])
def test_folder_opener_propagates_process_control_exception(
    tmp_path: Path,
    process_exception: type[BaseException],
) -> None:
    def interrupt(_path: Path) -> None:
        raise process_exception()

    manager = journal_module.DiagnosticBundleManager(
        DiagnosticJournal(tmp_path),
        folder_opener=interrupt,
    )
    with pytest.raises(process_exception):
        manager.open_folder("diagnostics.folder.open")


def test_folder_opener_exception_is_typed_and_preview_create_never_call_it(
    tmp_path: Path,
) -> None:
    opener_calls = 0

    def fail_opener(_path: Path) -> None:
        nonlocal opener_calls
        opener_calls += 1
        raise OSError("private opener detail")

    journal = DiagnosticJournal(tmp_path / "journal")
    assert isinstance(journal.append_and_sync(_record("no-process-launch")), ActionSuccess)
    manager = journal_module.DiagnosticBundleManager(
        journal,
        token_factory=lambda: "no-launch-token",
        folder_opener=fail_opener,
    )
    preview = manager.preview()
    manager.create(preview.token, tmp_path / "no-launch.zip")
    assert opener_calls == 0

    with pytest.raises(ActionFailure) as failure:
        manager.open_folder("diagnostics.folder.open")
    assert failure.value.code == "DIAGNOSTIC_FOLDER_OPEN_FAILED"
    assert "private opener detail" not in str(failure.value)
    assert opener_calls == 1
