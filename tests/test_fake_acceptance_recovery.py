"""What the fake-acceptance apply does when a phase fails.

Every test here breaks one adapter call on purpose and reads the receipt the
recovery path produced. The receipt is the product's own account of how far an
apply walked, so these tests are what makes that account checkable: a phase that
never ran must not be reported as reached, and a failure after the display was
written must attempt a restore.

Concurrency is here for the same reason. Two threads redeeming one confirmation
is a failure mode, and the invariant is that exactly one of them applies.
"""

from __future__ import annotations

import threading
from pathlib import Path

import pytest

from calibrate_pro.application import composition
from calibrate_pro.application.actions import ActionDisposition
from calibrate_pro.application.outcomes import ActionOutcome, ActionSuccess
from calibrate_pro.workflow import WorkflowStage
from tests.fake_acceptance_support import (
    build_service,
    disposition,
    drive_to_confirmed,
    failing_adapter,
    phases,
    succeeded,
)


def test_capture_failure_reports_no_apply_and_attempts_no_restore(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(composition, "RecordingFakeAdapter", failing_adapter("capture"))
    service = build_service(tmp_path)
    drive_to_confirmed(service)
    result = succeeded(service.apply_confirmed_plan())
    assert phases(result.receipt) == (False, False, False, False, False, False)
    assert "capture failed" in (result.receipt.error or "")
    assert result.receipt.restore_error is None
    assert service.adapter.calls == ["capture"]
    assert service.stage is WorkflowStage.PREVIEW


def test_apply_failure_restores_and_leaves_the_session_retryable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(composition, "RecordingFakeAdapter", failing_adapter("apply"))
    service = build_service(tmp_path)
    drive_to_confirmed(service)
    result = succeeded(service.apply_confirmed_plan())
    assert phases(result.receipt) == (False, True, False, False, True, True)
    assert "apply failed" in (result.receipt.error or "")
    assert service.adapter.calls == ["capture", "apply", "restore"]
    assert service.stage is WorkflowStage.PREVIEW
    assert disposition(service, "verification.sensorless") is not ActionDisposition.ENABLED
    assert disposition(service, "fake_acceptance.apply") is not ActionDisposition.ENABLED
    assert disposition(service, "calibration.preview") is ActionDisposition.ENABLED


def test_a_failed_readback_restores_and_withholds_verification(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(composition, "RecordingFakeAdapter", failing_adapter(verify_result=False))
    service = build_service(tmp_path)
    drive_to_confirmed(service)
    result = succeeded(service.apply_confirmed_plan())
    assert phases(result.receipt) == (False, True, True, False, True, True)
    assert result.receipt.error == "verification failed"
    assert service.adapter.calls == ["capture", "apply", "verify", "restore"]
    assert disposition(service, "verification.sensorless") is not ActionDisposition.ENABLED


def test_a_non_boolean_readback_counts_as_a_failed_apply(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(composition, "RecordingFakeAdapter", failing_adapter(verify_result=1))
    service = build_service(tmp_path)
    drive_to_confirmed(service)
    result = succeeded(service.apply_confirmed_plan())
    assert phases(result.receipt) == (False, True, True, False, True, True)
    assert "exact boolean" in (result.receipt.error or "")
    assert service.adapter.calls == ["capture", "apply", "verify", "restore"]


def test_commit_failure_keeps_the_verified_receipt_and_runs_no_restore(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(composition, "RecordingFakeAdapter", failing_adapter("commit"))
    service = build_service(tmp_path)
    drive_to_confirmed(service)
    result = succeeded(service.apply_confirmed_plan())
    assert phases(result.receipt) == (False, True, True, True, False, False)
    assert "commit failed" in (result.receipt.error or "")
    assert service.adapter.calls == ["capture", "apply", "verify", "commit"]


def test_restore_failure_preserves_both_errors(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(composition, "RecordingFakeAdapter", failing_adapter("apply", restore_fails=True))
    service = build_service(tmp_path)
    drive_to_confirmed(service)
    result = succeeded(service.apply_confirmed_plan())
    assert phases(result.receipt) == (False, True, False, False, True, False)
    assert "apply failed" in (result.receipt.error or "")
    assert "restore failed" in (result.receipt.restore_error or "")
    assert service.adapter.calls == ["capture", "apply", "restore"]


def test_two_concurrent_applies_redeem_one_confirmation(tmp_path: Path) -> None:
    service = build_service(tmp_path)
    drive_to_confirmed(service)
    start = threading.Barrier(2, timeout=10)
    collected: list[ActionOutcome[object]] = []
    guard = threading.Lock()

    def attempt() -> None:
        start.wait()
        outcome = service.apply_confirmed_plan()
        with guard:
            collected.append(outcome)

    workers = [threading.Thread(target=attempt, name=f"apply-{index}") for index in range(2)]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join(timeout=30)
        assert not worker.is_alive()

    successes = [outcome for outcome in collected if isinstance(outcome, ActionSuccess)]
    assert len(successes) == 1
    assert successes[0].value.receipt.success is True
    assert len(collected) == 2
    assert service.adapter.calls.count("apply") == 1
    assert service.adapter.calls.count("commit") == 1
