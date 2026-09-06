"""The calibrating session, driven end to end against a recording adapter.

Everything here is the shipped calibration path: the service the Windows
composition builds, the same coordinator, the same staging and the same seal.
One collaborator is a stand-in. A recorder takes the display adapter's place,
so the phases and their order are observable without a display being written.

These tests reach what no other suite covers. The fake-acceptance proofs drive
`fake_acceptance.apply`, which the resolver treats as a separate action with a
separate qualification, so a green fake suite says nothing about whether a
session holding an actuation route resolves and runs `calibration.apply`.

None of this establishes that a monitor was calibrated. What it establishes is
that a confirmed plan reaches an adapter once, in one order, that the receipt
and not the intent decides what gets reported, and that a session whose probe
found no writable route never reaches an apply at all.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import pytest

from calibrate_pro.application.actions import ActionDisposition
from calibrate_pro.application.assets import AssetGenerator
from calibrate_pro.application.calibration import CALIBRATION_APPLY_ACTION, CalibrationApplyService
from calibrate_pro.application.composition import _runner as build_runner
from calibrate_pro.application.composition import load_fake_display
from calibrate_pro.application.detection import DisplayDetector, ReadOnlyCapabilityProbe
from calibrate_pro.application.fake_acceptance import RecordingFakeAdapter
from calibrate_pro.application.journal import DiagnosticBundleManager, DiagnosticJournal
from calibrate_pro.application.session import SessionState
from calibrate_pro.panels.database import get_database
from calibrate_pro.panels.detection import DisplayInfo
from calibrate_pro.sensorless.neuralux import SensorlessEngine
from calibrate_pro.workflow import CalibrationMethod
from tests.fake_acceptance_support import PRESET_ID, failing_adapter, refused, succeeded

#: What the probe reports for a capability this file wired no check for. The
#: string names the test rather than a machine, so a report read out of a
#: failure never reads as though hardware answered.
ABSENT_REASON = "the test wired no check for this capability"


def _writable(_display: DisplayInfo) -> bool:
    """Report a writable route without opening anything."""
    return True


@dataclass(frozen=True)
class Harness:
    """One session, the recorder it drives, and the journal it writes."""

    service: CalibrationApplyService
    adapter: RecordingFakeAdapter
    journal_path: Path


def build_harness(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    adapter_type: type[RecordingFakeAdapter] = RecordingFakeAdapter,
    writable: bool = True,
) -> Harness:
    """Wire what the Windows composition wires, with the display left out.

    Redirecting LOCALAPPDATA moves both roots this session writes under. The
    journal resolves its root from that variable and so does the staging
    directory a sealed plan pins, so redirecting one and not the other would
    leave real files under the operator's profile.
    """
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    check = _writable if writable else None
    database = get_database()
    engine = SensorlessEngine(database)
    detector = DisplayDetector(
        enumerator=lambda: (load_fake_display(),),
        capability_probe=ReadOnlyCapabilityProbe(
            dwm_lut=check,
            dwm_state_capture=check,
            profile_write=check,
            vcgt=check,
            absent_reason=ABSENT_REASON,
        ),
        database=database,
        enumerator_name="tests.test_calibration_apply:fake-display",
    )
    state = SessionState(actuation_route=True)
    journal = DiagnosticJournal()
    adapter = adapter_type()
    service = CalibrationApplyService(
        adapter=adapter,
        state=state,
        runner=build_runner(state, journal),
        bundles=DiagnosticBundleManager(journal),
        detector=detector,
        generator=AssetGenerator(engine, database),
        engine=engine,
    )
    return Harness(service=service, adapter=adapter, journal_path=journal.path)


def disposition(service: CalibrationApplyService, action_id: str) -> ActionDisposition:
    return service.resolve(action_id).disposition


def drive_to_preview(service: CalibrationApplyService) -> object:
    succeeded(service.detect())
    succeeded(service.select_method(CalibrationMethod.SENSORLESS))
    succeeded(service.set_target(PRESET_ID))
    succeeded(service.generate())
    return succeeded(service.preview())


def drive_to_confirmed(service: CalibrationApplyService) -> object:
    preview = drive_to_preview(service)
    succeeded(service.confirm_plan())
    return preview


def journal_records(path: Path) -> list[dict[str, object]]:
    text = path.read_text(encoding="utf-8")
    return [json.loads(line) for line in text.splitlines() if line.strip()]


def test_the_apply_is_offered_only_once_a_previewed_plan_is_confirmed(tmp_path, monkeypatch):
    """Walk the stages and read the control at each one.

    A confirmation is what separates a plan the operator looked at from a plan
    the operator accepted, so the control has to stay refused through preview
    and become available only after the decision.
    """
    harness = build_harness(tmp_path, monkeypatch)
    service = harness.service

    assert disposition(service, CALIBRATION_APPLY_ACTION) is ActionDisposition.DISABLED
    drive_to_preview(service)
    assert disposition(service, CALIBRATION_APPLY_ACTION) is ActionDisposition.DISABLED
    succeeded(service.confirm_plan())
    assert disposition(service, CALIBRATION_APPLY_ACTION) is ActionDisposition.ENABLED


def test_a_confirmed_plan_reaches_the_adapter_in_the_recovery_order(tmp_path, monkeypatch):
    """Capture comes before the write, and the write before the verify.

    The order is the recovery guarantee. Nothing can be put back that was not
    captured first, so a run that wrote before it captured would leave the
    display with no state to restore.
    """
    harness = build_harness(tmp_path, monkeypatch)
    drive_to_confirmed(harness.service)
    assert harness.adapter.calls == []

    succeeded(harness.service.apply_confirmed_plan())

    assert harness.adapter.calls == ["capture", "apply", "verify", "commit"]


def test_the_result_reports_the_display_was_changed_and_names_the_routes(tmp_path, monkeypatch):
    """Read the receipt the way a surface reads it.

    ``physical_apply_performed`` and ``routes`` are what the calibrate page
    renders, so they are asserted here rather than the receipt fields behind
    them.
    """
    harness = build_harness(tmp_path, monkeypatch)
    drive_to_confirmed(harness.service)

    result = succeeded(harness.service.apply_confirmed_plan())

    assert result.physical_apply_performed is True
    assert result.routes == ("icc", "dwm_lut")
    assert result.apply_phase_flags == (
        ("captured", True),
        ("applied", True),
        ("verified", True),
        ("restore_attempted", False),
        ("restored", False),
    )


def test_the_journal_records_the_physical_apply_under_its_own_action(tmp_path, monkeypatch):
    """A written display and a recorded one are separate rows.

    The fake composition's id must not appear on this path. If it did, a reader
    could not tell from the journal which of the two sessions produced a run.
    """
    harness = build_harness(tmp_path, monkeypatch)
    drive_to_confirmed(harness.service)
    succeeded(harness.service.apply_confirmed_plan())

    records = journal_records(harness.journal_path)
    applies = [record for record in records if record["action_id"] == CALIBRATION_APPLY_ACTION]

    assert [record["outcome"] for record in applies] == ["success"]
    assert not [record for record in records if record["action_id"] == "fake_acceptance.apply"]


def test_the_session_records_the_digest_of_the_plan_it_applied(tmp_path, monkeypatch):
    """What was applied is pinned to what was previewed.

    The digest is read off the session because that is what the resolver reads
    when it decides whether verification describes the plan now on the display.
    """
    harness = build_harness(tmp_path, monkeypatch)
    preview = drive_to_confirmed(harness.service)

    result = succeeded(harness.service.apply_confirmed_plan())

    assert result.plan_sha256 == preview.plan_sha256
    assert harness.service._state.applied_plan_sha256 == preview.plan_sha256


def test_verification_stays_available_after_the_apply_spends_the_confirmation(tmp_path, monkeypatch):
    """An apply consumes the token, and verification still has to run.

    Refusing verification here would leave the operator holding a changed
    display and no way to ask what the change was predicted to do.
    """
    harness = build_harness(tmp_path, monkeypatch)
    drive_to_confirmed(harness.service)
    succeeded(harness.service.apply_confirmed_plan())

    assert disposition(harness.service, "verification.sensorless") is ActionDisposition.ENABLED
    succeeded(harness.service.verify())


def test_one_confirmation_redeems_exactly_once(tmp_path, monkeypatch):
    """A spent token cannot drive a second write.

    The adapter's call list is checked after the refusal because a refusal that
    still reached the adapter would have changed the display twice while
    reporting that it changed it once.
    """
    harness = build_harness(tmp_path, monkeypatch)
    drive_to_confirmed(harness.service)
    succeeded(harness.service.apply_confirmed_plan())
    after_first = list(harness.adapter.calls)

    refused(harness.service.apply_confirmed_plan())

    assert harness.adapter.calls == after_first


def test_a_display_with_no_writable_route_still_generates_a_bundle(tmp_path, monkeypatch):
    """A machine that cannot be written to still gets its calibration.

    ``actuation_route`` says a composition wired an adapter. It is half the
    apply qualification, and this is the other half failing: the probe found
    nothing this build can capture and put back.

    Generation still has to succeed. The bundle is what a colour-managed
    application loads, and withholding it because the compositor route was
    missing would take the product away from every operator whose display
    this build cannot drive. What the failure costs is the apply, and the
    reason travels with the result rather than being discarded.
    """
    harness = build_harness(tmp_path, monkeypatch, writable=False)
    service = harness.service
    succeeded(service.detect())
    succeeded(service.select_method(CalibrationMethod.SENSORLESS))
    succeeded(service.set_target(PRESET_ID))

    result = succeeded(service.generate())

    assert result.filenames
    assert result.apply_note is not None
    assert disposition(service, CALIBRATION_APPLY_ACTION) is ActionDisposition.DISABLED
    succeeded(service.preview())
    succeeded(service.confirm_plan())
    assert disposition(service, CALIBRATION_APPLY_ACTION) is ActionDisposition.DISABLED
    refused(service.apply_confirmed_plan())
    assert harness.adapter.calls == []


def test_a_write_that_failed_reports_a_display_that_was_not_changed(tmp_path, monkeypatch):
    """The heading a surface renders comes from the receipt, so fail the write.

    This is the false-success control for the whole path. A session built to
    drive a display would report every apply as a success if the result read
    the composition instead of the receipt.
    """
    harness = build_harness(tmp_path, monkeypatch, adapter_type=failing_adapter("apply"))
    drive_to_confirmed(harness.service)

    result = succeeded(harness.service.apply_confirmed_plan())

    assert result.physical_apply_performed is False
    assert harness.adapter.calls == ["capture", "apply", "restore"]
