"""Shared machinery for the fake-acceptance proofs.

The fixtures here build the real service, the real coordinator, and the real
recovery path. Only the display adapter is a stand-in, and it records what it
was asked to do rather than doing any of it. Nothing in this module reads a
machine or writes to one.
"""

from __future__ import annotations

import json
from pathlib import Path

from calibrate_pro.application.actions import ActionDisposition
from calibrate_pro.application.composition import (
    FAKE_JOURNAL_DIRNAME,
    build_fake_acceptance_service,
)
from calibrate_pro.application.fake_acceptance import FakeAcceptanceService, RecordingFakeAdapter
from calibrate_pro.application.outcomes import ActionError, ActionOutcome, ActionSuccess
from calibrate_pro.recovery import ApplyReceipt
from calibrate_pro.workflow import CalibrationMethod

PRESET_ID = "calibration.preset.srgb_web"
MANIFEST_NAME = "calibrate-pro-manifest.json"

#: The order the session performs actions in, and therefore the order the
#: journal records them. Exporting runs two actions, and only the second one is
#: returned to the caller.
EXPECTED_ACTION_ORDER = (
    "display.detect",
    "calibration.method.sensorless",
    PRESET_ID,
    "calibration.generate",
    "calibration.preview",
    "calibration.confirm_plan",
    "fake_acceptance.apply",
    "verification.sensorless",
    "settings.output_directory",
    "report.save",
)


class StagedFailure(RuntimeError):
    """A failure a test adapter raises on purpose. The product never raises it."""


def failing_adapter(
    phase: str | None = None,
    *,
    restore_fails: bool = False,
    verify_result: object = True,
) -> type[RecordingFakeAdapter]:
    """Build a recorder that fails one named phase and records the call anyway.

    Each override records its call before failing, so the call list shows how far
    the recovery path actually walked rather than how far it meant to.
    """

    class StagedAdapter(RecordingFakeAdapter):
        def capture(self, plan, *, authorization=None):  # type: ignore[no-untyped-def]
            snapshot = super().capture(plan, authorization=authorization)
            if phase == "capture":
                raise StagedFailure("capture failed")
            return snapshot

        def apply(self, plan):  # type: ignore[no-untyped-def]
            super().apply(plan)
            if phase == "apply":
                raise StagedFailure("apply failed")

        def verify(self, plan):  # type: ignore[no-untyped-def]
            super().verify(plan)
            if phase == "verify":
                raise StagedFailure("verify failed")
            return verify_result

        def commit(self, plan):  # type: ignore[no-untyped-def]
            super().commit(plan)
            if phase == "commit":
                raise StagedFailure("commit failed")

        def restore(self, snapshot):  # type: ignore[no-untyped-def]
            super().restore(snapshot)
            if restore_fails:
                raise StagedFailure("restore failed")

    return StagedAdapter


class ManualClock:
    """A monotonic clock a test moves by hand, so expiry needs no waiting."""

    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def succeeded(outcome: ActionOutcome[object]) -> object:
    assert isinstance(outcome, ActionSuccess), f"expected a success, got {outcome}"
    return outcome.value


def refused(outcome: ActionOutcome[object]) -> ActionError:
    assert isinstance(outcome, ActionError), f"expected a refusal, got {outcome}"
    return outcome


def phases(receipt: ApplyReceipt) -> tuple[bool, ...]:
    """Read a receipt as the tuple the recovery path is specified in."""
    return (
        receipt.success,
        receipt.captured,
        receipt.applied,
        receipt.verified,
        receipt.restore_attempted,
        receipt.restored,
    )


def build_service(tmp_path: Path, name: str = "session") -> FakeAcceptanceService:
    return build_fake_acceptance_service((tmp_path / name).resolve())


def drive_to_preview(service: FakeAcceptanceService) -> object:
    succeeded(service.detect())
    succeeded(service.select_method(CalibrationMethod.SENSORLESS))
    succeeded(service.set_target(PRESET_ID))
    succeeded(service.generate())
    return succeeded(service.preview())


def drive_to_confirmed(service: FakeAcceptanceService) -> object:
    preview = drive_to_preview(service)
    succeeded(service.confirm_plan())
    return preview


def journal_records(root: Path) -> list[dict[str, object]]:
    path = root / FAKE_JOURNAL_DIRNAME / "diagnostics.jsonl"
    text = path.read_text(encoding="utf-8")
    return [json.loads(line) for line in text.splitlines() if line.strip()]


def disposition(service: FakeAcceptanceService, action_id: str) -> ActionDisposition:
    return service.resolve(action_id).disposition
