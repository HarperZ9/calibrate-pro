"""The fake-acceptance composition, driven end to end.

Production performs no physical mutation, so the apply stage would otherwise
ship with no coverage at all. These tests drive the real service, the real
actuation coordinator, and the real recovery path against a recording adapter,
which makes the ordering and the gating observable without a display attached.

None of this is evidence that a monitor was calibrated. What it establishes is
that the session performs its steps in one order, refuses an unconfirmed apply,
and redeems exactly one confirmation. What happens when a phase fails is covered
in test_fake_acceptance_recovery.py; coordinator and receipt semantics are
unit-tested in test_workflow.py.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, replace
from pathlib import Path

import pytest

from calibrate_pro.actuation import ActuationCoordinator
from calibrate_pro.application.actions import ActionDisposition
from calibrate_pro.application.composition import (
    FAKE_JOURNAL_DIRNAME,
    build_fake_acceptance_service,
    load_fake_display,
)
from calibrate_pro.application.contracts import CharacterizationKind
from calibrate_pro.application.fake_acceptance import (
    APPLY_NOT_AUTHORIZED,
    NO_CONFIRMATION_TOKEN,
    FakeAcceptanceService,
)
from calibrate_pro.application.outcomes import ActionOutcome, ActionSuccess
from calibrate_pro.application.runner import ACTION_NOT_AVAILABLE
from calibrate_pro.recovery import RecoveryGuarantee
from calibrate_pro.verification.provenance import EvidenceKind
from calibrate_pro.workflow import CalibrationMethod, WorkflowStage
from tests.fake_acceptance_support import (
    EXPECTED_ACTION_ORDER,
    MANIFEST_NAME,
    PRESET_ID,
    ManualClock,
    build_service,
    disposition,
    drive_to_confirmed,
    drive_to_preview,
    journal_records,
    phases,
    refused,
    succeeded,
)


@dataclass(frozen=True)
class CompletedRun:
    """One finished slice, kept so several tests can read it without rerunning."""

    root: Path
    export_directory: Path
    service: FakeAcceptanceService
    outcomes: tuple[ActionSuccess, ...]

    def outcome(self, action_id: str) -> ActionSuccess:
        for candidate in self.outcomes:
            if candidate.action_id == action_id:
                return candidate
        raise AssertionError(f"the run performed no {action_id} action")


@pytest.fixture(scope="module")
def completed_run(tmp_path_factory: pytest.TempPathFactory) -> CompletedRun:
    root = (tmp_path_factory.mktemp("fake-acceptance") / "session").resolve()
    export_directory = root / "exports"
    service = build_fake_acceptance_service(root)
    outcomes: list[ActionSuccess] = []

    def step(outcome: ActionOutcome[object]) -> None:
        assert isinstance(outcome, ActionSuccess), f"the slice stopped at {outcome}"
        outcomes.append(outcome)

    step(service.detect())
    step(service.select_method(CalibrationMethod.SENSORLESS))
    step(service.set_target(PRESET_ID))
    step(service.generate())
    step(service.preview())
    step(service.confirm_plan())
    step(service.apply_confirmed_plan())
    step(service.verify())
    step(service.export(export_directory))
    return CompletedRun(
        root=root,
        export_directory=export_directory,
        service=service,
        outcomes=tuple(outcomes),
    )


def test_the_slice_detects_generates_applies_verifies_and_exports(completed_run: CompletedRun) -> None:
    performed = tuple(outcome.action_id for outcome in completed_run.outcomes)
    returned = tuple(action for action in EXPECTED_ACTION_ORDER if action != "settings.output_directory")
    assert performed == returned
    assert completed_run.service.stage is WorkflowStage.SAVE_REPORT


def test_detection_selects_the_bundled_display_and_rejects_nothing(completed_run: CompletedRun) -> None:
    summary = completed_run.outcome("display.detect").value
    assert summary.selected_display_id == load_fake_display().device_name
    assert summary.rejected == ()
    assert summary.capability_generation == 1
    assert [entry.platform_display_id for entry in summary.dashboard.displays] == [load_fake_display().device_name]


def test_generation_names_the_matched_panel_and_calls_the_numbers_estimated(
    completed_run: CompletedRun,
) -> None:
    result = completed_run.outcome("calibration.generate").value
    assert result.filenames == ("Calibrate_Pro.icc", "Calibrate_Pro.cube")
    assert result.characterization_kind is CharacterizationKind.MATCHED
    assert result.evidence_kind is EvidenceKind.ESTIMATED
    assert result.panel_name


def test_preview_and_confirmation_report_that_no_display_was_written(
    completed_run: CompletedRun,
) -> None:
    preview = completed_run.outcome("calibration.preview").value
    decision = completed_run.outcome("calibration.confirm_plan").value
    generated = completed_run.outcome("calibration.generate").value
    assert preview.physical_apply_performed is False
    assert decision.physical_apply_performed is False
    assert decision.accepted is True
    assert preview.plan_sha256 == decision.plan_sha256 == generated.plan_sha256


def test_apply_drives_capture_apply_verify_commit_in_that_order(completed_run: CompletedRun) -> None:
    assert completed_run.service.adapter.calls == ["capture", "apply", "verify", "commit"]


def test_a_successful_apply_records_every_phase_and_attempts_no_restore(
    completed_run: CompletedRun,
) -> None:
    result = completed_run.outcome("fake_acceptance.apply").value
    assert result.physical_apply_performed is False
    assert phases(result.receipt) == (True, True, True, True, False, False)
    assert result.receipt.error is None
    assert result.receipt.restore_error is None
    assert result.receipt.recovery_guarantee is RecoveryGuarantee.IN_PROCESS_BEST_EFFORT
    assert result.plan_sha256 == completed_run.outcome("calibration.preview").value.plan_sha256


def test_verification_reports_estimated_accuracy_read_from_the_generated_plan(
    completed_run: CompletedRun,
) -> None:
    result = completed_run.outcome("verification.sensorless").value
    assert result.source == "generated_plan"
    assert result.evidence is EvidenceKind.ESTIMATED
    assert result.covered is True
    assert result.limitation is None
    assert result.patch_count > 0
    assert result.average_delta_e.evidence is EvidenceKind.ESTIMATED
    assert result.average_delta_e.value <= result.maximum_delta_e.value


def test_the_export_writes_every_named_file_and_a_manifest_that_matches(
    completed_run: CompletedRun,
) -> None:
    bundle = completed_run.outcome("report.save").value
    directory = Path(bundle.directory)
    assert directory == completed_run.export_directory
    assert bundle.manifest_filename == MANIFEST_NAME
    assert bundle.evidence_kind == "estimated"
    assert bundle.characterization_kind == "matched"
    published = {asset.filename for asset in bundle.assets}
    assert published == set(completed_run.outcome("calibration.generate").value.filenames)
    for asset in bundle.assets:
        assert (directory / asset.filename).stat().st_size == asset.byte_count
    manifest = json.loads((directory / MANIFEST_NAME).read_text(encoding="utf-8"))
    assert manifest


def test_every_journal_record_carries_its_own_action_and_correlation_id(
    completed_run: CompletedRun,
) -> None:
    records = journal_records(completed_run.root)
    assert [record["action_id"] for record in records] == list(EXPECTED_ACTION_ORDER)
    for outcome in completed_run.outcomes:
        matching = [record for record in records if record["action_id"] == outcome.action_id]
        assert len(matching) == 1
        assert matching[0]["correlation_id"] == outcome.correlation_id
    assert len({record["correlation_id"] for record in records}) == len(records)


def test_the_apply_record_names_the_fake_runtime_and_the_phases_it_reached(
    completed_run: CompletedRun,
) -> None:
    records = {record["action_id"]: record for record in journal_records(completed_run.root)}
    apply_record = records["fake_acceptance.apply"]
    assert apply_record["runtime_mode"] == "fake_acceptance"
    assert apply_record["recovery_guarantee"] == RecoveryGuarantee.IN_PROCESS_BEST_EFFORT.value
    assert {name: value for name, value in apply_record["apply_phase_flags"]} == {
        "captured": True,
        "applied": True,
        "verified": True,
        "restore_attempted": False,
        "restored": False,
    }
    assert records["report.save"]["export_basename"] == MANIFEST_NAME
    assert records["display.detect"]["runtime_mode"] != "fake_acceptance"


def test_the_journal_records_no_filesystem_path(completed_run: CompletedRun) -> None:
    text = (completed_run.root / FAKE_JOURNAL_DIRNAME / "diagnostics.jsonl").read_text(encoding="utf-8")
    assert str(completed_run.root) not in text
    assert str(completed_run.export_directory) not in text


def test_apply_is_refused_while_the_plan_is_only_previewed(tmp_path: Path) -> None:
    service = build_service(tmp_path)
    drive_to_preview(service)
    assert refused(service.apply_confirmed_plan()).code == ACTION_NOT_AVAILABLE
    assert service.adapter.calls == []
    assert service.stage is WorkflowStage.PREVIEW


def test_redemption_refuses_a_confirmation_the_session_no_longer_holds(tmp_path: Path) -> None:
    service = build_service(tmp_path)
    drive_to_confirmed(service)
    # The manifest still enables the action here, so this exercises the guard
    # inside the redemption rather than the resolver standing in front of it.
    service._token = None
    assert refused(service.apply_confirmed_plan()).code == NO_CONFIRMATION_TOKEN
    assert service.adapter.calls == []


def test_declining_a_plan_leaves_no_confirmation_to_redeem(tmp_path: Path) -> None:
    service = build_service(tmp_path)
    drive_to_preview(service)
    decision = succeeded(service.confirm_plan(accepted=False))
    assert decision.accepted is False
    assert refused(service.apply_confirmed_plan()).code == ACTION_NOT_AVAILABLE
    assert service.adapter.calls == []
    assert service.stage is WorkflowStage.PREVIEW


def test_an_expired_confirmation_is_refused_and_a_fresh_preview_recovers(tmp_path: Path) -> None:
    service = build_service(tmp_path)
    clock = ManualClock()
    # Replacing the coordinator before the confirmation is minted is the only
    # seam that reaches its clock. Everything after this is the shipped path.
    service._coordinator = ActuationCoordinator(
        service.adapter,
        service._capabilities_for,
        confirmation_ttl_seconds=1.0,
        clock=clock,
    )
    drive_to_confirmed(service)
    clock.now = 2.0
    error = refused(service.apply_confirmed_plan())
    assert error.code == APPLY_NOT_AUTHORIZED
    assert error.summary == "confirmation token is expired and consumed"
    assert service.adapter.calls == []
    assert service.stage is WorkflowStage.PREVIEW
    assert disposition(service, "fake_acceptance.apply") is not ActionDisposition.ENABLED
    assert disposition(service, "verification.sensorless") is not ActionDisposition.ENABLED

    succeeded(service.preview())
    succeeded(service.confirm_plan())
    result = succeeded(service.apply_confirmed_plan())
    assert result.receipt.success is True
    assert service.adapter.calls == ["capture", "apply", "verify", "commit"]


def test_a_confirmation_is_bound_to_the_plan_that_was_previewed(tmp_path: Path) -> None:
    service = build_service(tmp_path)
    preview = drive_to_confirmed(service)
    service._sealed_plan = replace(preview.plan, target_gamma="2.4")
    error = refused(service.apply_confirmed_plan())
    assert error.code == APPLY_NOT_AUTHORIZED
    assert error.summary == "confirmation token is bound to a different plan and is consumed"
    assert service.adapter.calls == []


def test_detecting_again_drops_the_confirmation_and_the_seal(tmp_path: Path) -> None:
    service = build_service(tmp_path)
    drive_to_confirmed(service)
    summary = succeeded(service.detect())
    assert summary.capability_generation == 2
    assert service._token is None
    assert refused(service.apply_confirmed_plan()).code == ACTION_NOT_AVAILABLE
    assert service.adapter.calls == []
    assert service.stage is WorkflowStage.METHOD
