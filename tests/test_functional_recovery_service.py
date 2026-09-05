"""The session this product actually ships, and the write it cannot perform.

The production composition holds no display adapter. That is the claim these
tests hold to: the class exposes no apply method, the built service carries no
adapter or coordinator attribute, building one loads no adapter, hardware, or
platform module, and the fake-only apply action never resolves to an enabled
control no matter what stage the session reaches.

The rest of the file drives a production session the whole way through, so the
refusal is shown to be a boundary rather than an unfinished path. Confirming a
plan here is an acknowledgement, and it goes straight to verification.
"""

from __future__ import annotations

import inspect
import json
import subprocess
import sys
import textwrap
from collections.abc import Sequence
from pathlib import Path
from uuid import uuid4

import pytest

from calibrate_pro.application.actions import ActionDisposition, ActionRegistry
from calibrate_pro.application.assets import AssetGenerator
from calibrate_pro.application.composition import build_production_service, load_fake_display
from calibrate_pro.application.detection import DeniedCapabilityProbe, DisplayDetector
from calibrate_pro.application.journal import DiagnosticJournal
from calibrate_pro.application.outcomes import ActionBoundary, ActionError, ActionOutcome, ActionSuccess
from calibrate_pro.application.runner import ACTION_NOT_AVAILABLE, IssuedCorrelationId, SessionActionRunner
from calibrate_pro.application.service import FunctionalRecoveryService
from calibrate_pro.application.session import SessionState
from calibrate_pro.panels.database import get_database
from calibrate_pro.panels.detection import DisplayInfo
from calibrate_pro.sensorless.neuralux import SensorlessEngine
from calibrate_pro.verification.provenance import EvidenceKind
from calibrate_pro.workflow import CalibrationMethod, WorkflowStage

PRESET_ID = "calibration.preset.srgb_web"
MANIFEST_NAME = "calibrate-pro-manifest.json"

#: The five calls a display adapter answers. An object in the session that
#: answered all of them would be a route to a physical write, so the test looks
#: for the shape rather than for a particular class.
ADAPTER_SHAPE = ("capture", "apply", "verify", "commit", "restore")

#: Packages that reach hardware. None of them may be imported as a consequence
#: of building the session this product ships.
SIDE_EFFECTING_PACKAGES = ("calibrate_pro.adapters", "calibrate_pro.hardware", "calibrate_pro.platform")


def succeeded(outcome: ActionOutcome[object]) -> object:
    assert isinstance(outcome, ActionSuccess), f"expected a success, got {outcome}"
    return outcome.value


def refused(outcome: ActionOutcome[object]) -> ActionError:
    assert isinstance(outcome, ActionError), f"expected a refusal, got {outcome}"
    return outcome


def synthetic_production_service(root: Path) -> FunctionalRecoveryService:
    """Wire the production class over a synthetic display.

    This is the production composition with its enumerator and its journal root
    replaced, which is what lets the session be driven at all. Detecting through
    the shipped ``build_production_service`` would probe the machine running the
    tests, and the repository treats that as side-effecting code.
    """
    display = load_fake_display()
    state = SessionState()
    journal = DiagnosticJournal(root)
    registry = ActionRegistry.load_default()
    correlation_ids = IssuedCorrelationId(lambda: uuid4().hex)
    runner = SessionActionRunner(state, registry, ActionBoundary(correlation_ids, journal, registry), correlation_ids)
    database = get_database()
    engine = SensorlessEngine(database)

    def enumerate_one_display() -> Sequence[DisplayInfo]:
        return (display,)

    detector = DisplayDetector(
        enumerator=enumerate_one_display,
        capability_probe=DeniedCapabilityProbe("this session probes no hardware"),
        database=database,
        enumerator_name="tests.synthetic_production",
    )
    return FunctionalRecoveryService(
        state=state,
        runner=runner,
        detector=detector,
        generator=AssetGenerator(engine, database),
        engine=engine,
    )


@pytest.fixture
def service(tmp_path: Path) -> FunctionalRecoveryService:
    return synthetic_production_service(tmp_path / "diagnostics")


def drive_to_preview(service: FunctionalRecoveryService) -> object:
    succeeded(service.detect())
    succeeded(service.select_method(CalibrationMethod.SENSORLESS))
    succeeded(service.set_target(PRESET_ID))
    succeeded(service.generate())
    return succeeded(service.preview())


def test_the_production_class_exposes_no_apply_method() -> None:
    assert not hasattr(FunctionalRecoveryService, "apply_confirmed_plan")
    # The class does have a ``verify`` method, and it is the session's own
    # sensorless verification rather than a display readback. What would make it
    # a route to a display is answering the whole adapter protocol, so that is
    # what the check asks.
    missing = [call for call in ADAPTER_SHAPE if not hasattr(FunctionalRecoveryService, call)]
    assert missing


def test_a_production_session_carries_no_display_adapter(service: FunctionalRecoveryService) -> None:
    held = vars(service)
    assert "_adapter" not in held
    assert "_coordinator" not in held
    for name, value in held.items():
        missing = [call for call in ADAPTER_SHAPE if not callable(getattr(value, call, None))]
        assert missing, f"{name} answers every display adapter call"


def test_building_the_shipped_session_loads_no_adapter_or_hardware_module() -> None:
    probe = textwrap.dedent(
        """
        import json, sys
        from calibrate_pro.application.composition import build_production_service
        service = build_production_service()
        prefixes = sys.argv[1:]
        loaded = sorted(m for m in sys.modules if any(m == p or m.startswith(p + ".") for p in prefixes))
        print(json.dumps({"loaded": loaded, "attributes": sorted(vars(service))}))
        """
    )
    command = [sys.executable, "-c", probe, *SIDE_EFFECTING_PACKAGES]
    completed = subprocess.run(command, capture_output=True, text=True, check=True)
    report = json.loads(completed.stdout.strip().splitlines()[-1])
    assert report["loaded"] == []
    assert "_adapter" not in report["attributes"]
    assert "_coordinator" not in report["attributes"]


def test_the_shipped_builder_accepts_no_adapter_to_inject() -> None:
    assert inspect.signature(build_production_service).parameters == {}


def test_the_fake_only_apply_never_becomes_available(service: FunctionalRecoveryService) -> None:
    seen = []
    for step in (
        lambda: service.detect(),
        lambda: service.select_method(CalibrationMethod.SENSORLESS),
        lambda: service.set_target(PRESET_ID),
        lambda: service.generate(),
        lambda: service.preview(),
        lambda: service.confirm_plan(),
        lambda: service.verify(),
    ):
        assert service.resolve("fake_acceptance.apply").disposition is not ActionDisposition.ENABLED
        succeeded(step())
        seen.append(service.stage)
    assert service.resolve("fake_acceptance.apply").disposition is not ActionDisposition.ENABLED
    assert WorkflowStage.SAVE_REPORT in seen


def test_confirming_a_plan_writes_nothing_and_goes_straight_to_verification(
    service: FunctionalRecoveryService,
) -> None:
    preview = drive_to_preview(service)
    assert service.stage is WorkflowStage.PREVIEW
    decision = succeeded(service.confirm_plan())
    assert decision.accepted is True
    assert decision.physical_apply_performed is False
    assert decision.plan_sha256 == preview.plan_sha256
    assert service.stage is WorkflowStage.VERIFY


def test_declining_a_plan_returns_the_session_to_the_preview_step(
    service: FunctionalRecoveryService,
) -> None:
    drive_to_preview(service)
    decision = succeeded(service.confirm_plan(accepted=False))
    assert decision.accepted is False
    assert decision.physical_apply_performed is False
    assert service.stage is WorkflowStage.PREVIEW
    assert refused(service.verify()).code == ACTION_NOT_AVAILABLE
    assert service.resolve("calibration.preview").disposition is ActionDisposition.ENABLED


def test_verification_reads_the_generated_plan_and_stays_estimated(
    service: FunctionalRecoveryService,
) -> None:
    drive_to_preview(service)
    succeeded(service.confirm_plan())
    result = succeeded(service.verify())
    assert result.source == "generated_plan"
    assert result.evidence is EvidenceKind.ESTIMATED
    assert result.average_delta_e.evidence is EvidenceKind.ESTIMATED
    assert result.maximum_delta_e.evidence is EvidenceKind.ESTIMATED
    assert result.patch_count > 0


def test_the_session_exports_the_bundle_it_generated(service: FunctionalRecoveryService, tmp_path: Path) -> None:
    drive_to_preview(service)
    succeeded(service.confirm_plan())
    generated = succeeded(service.verify())
    assert generated.covered is True
    directory = tmp_path / "exports"
    bundle = succeeded(service.export(directory))
    assert Path(bundle.directory) == directory
    assert bundle.manifest_filename == MANIFEST_NAME
    assert bundle.evidence_kind == "estimated"
    for asset in bundle.assets:
        assert (directory / asset.filename).stat().st_size == asset.byte_count
    assert (directory / MANIFEST_NAME).is_file()


def test_exporting_before_a_directory_is_chosen_is_refused_and_writes_nothing(
    service: FunctionalRecoveryService, tmp_path: Path
) -> None:
    drive_to_preview(service)
    succeeded(service.confirm_plan())
    succeeded(service.verify())
    assert refused(service.export()).code == ACTION_NOT_AVAILABLE
    assert sorted(path.name for path in tmp_path.iterdir()) == ["diagnostics"]


def test_a_directory_that_cannot_be_created_is_recorded_invalid_and_blocks_the_save(
    service: FunctionalRecoveryService, tmp_path: Path
) -> None:
    drive_to_preview(service)
    succeeded(service.confirm_plan())
    succeeded(service.verify())
    unreachable = tmp_path / "absent-parent" / "exports"
    outcome = service.export(unreachable)
    assert refused(outcome).code == ACTION_NOT_AVAILABLE
    assert service.resolve("report.save").disposition is not ActionDisposition.ENABLED
    assert not unreachable.exists()


def test_the_journal_never_records_the_fake_runtime_for_a_production_session(
    service: FunctionalRecoveryService, tmp_path: Path
) -> None:
    drive_to_preview(service)
    succeeded(service.confirm_plan())
    succeeded(service.verify())
    succeeded(service.export(tmp_path / "exports"))
    lines = (tmp_path / "diagnostics" / "diagnostics.jsonl").read_text(encoding="utf-8").splitlines()
    records = [json.loads(line) for line in lines if line.strip()]
    assert [record["action_id"] for record in records] == [
        "display.detect",
        "calibration.method.sensorless",
        PRESET_ID,
        "calibration.generate",
        "calibration.preview",
        "calibration.confirm_plan",
        "verification.sensorless",
        "settings.output_directory",
        "report.save",
    ]
    assert {record["runtime_mode"] for record in records} == {"source"}
    assert all(record["apply_phase_flags"] == [] for record in records)
    assert all(record["recovery_guarantee"] is None for record in records)
