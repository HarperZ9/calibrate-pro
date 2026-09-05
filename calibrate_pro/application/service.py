"""The one session service every surface drives.

A surface calls a method here and renders what comes back. It never reaches a
detector, a generator, an exporter, or the workflow state machine on its own,
so every state change in a session passes through one resolver, one action
boundary, and one journal.

This class performs no physical mutation. It holds no adapter, it has no method
that writes to a display, and the module imports nothing that can. The fake
composition subclasses it to prove an apply path end to end; production runs the
class as written, and confirmation is an acknowledgement rather than a write.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from calibrate_pro.application.assets import AssetGenerator, ExportBundle
from calibrate_pro.application.contracts import CharacterizationKind
from calibrate_pro.application.detection import DisplayDetector
from calibrate_pro.application.exporting import choose_directory, export_bundle, export_single_format
from calibrate_pro.application.generation import generate_bundle
from calibrate_pro.application.outcomes import ActionError, ActionOutcome
from calibrate_pro.application.planning import target_for
from calibrate_pro.application.prediction import predict_accuracy
from calibrate_pro.application.profile_actions import ProfileActions
from calibrate_pro.application.refusals import (
    no_display_selected,
    no_sealed_plan,
    transition_rejected,
)
from calibrate_pro.application.results import (
    DetectionSummary,
    DisplaySelection,
    ExportDirectory,
    GenerationResult,
    HdrDisplayState,
    HdrStatus,
    MethodSelection,
    PlanDecision,
    PlanPreview,
    TargetSelection,
    VerificationResult,
)
from calibrate_pro.application.runner import SessionActionRunner
from calibrate_pro.application.selection import DENIED_CAPABILITIES, adopt, current_selection
from calibrate_pro.application.session import SessionState
from calibrate_pro.application.surface import SurfaceActions
from calibrate_pro.panels.database import GENERIC_PANEL_KEY
from calibrate_pro.sensorless.neuralux import SensorlessEngine
from calibrate_pro.workflow import ApplyPlan, CalibrationMethod, WorkflowController, WorkflowStage


class FunctionalRecoveryService(ProfileActions, SurfaceActions):
    """One calibration session, driven one action at a time."""

    def __init__(
        self,
        *,
        state: SessionState,
        runner: SessionActionRunner,
        detector: DisplayDetector,
        generator: AssetGenerator,
        engine: SensorlessEngine,
        lut_size: int = 33,
    ) -> None:
        self._state = state
        self._runner = runner
        self._detector = detector
        self._generator = generator
        self._engine = engine
        self._lut_size = lut_size
        self._controller = WorkflowController(DENIED_CAPABILITIES)
        self._sealed_plan: ApplyPlan | None = None

    # -- session state, detection, and selection ----------------------------

    @property
    def stage(self) -> WorkflowStage:
        return self._state.stage

    def detect(self) -> ActionOutcome[DetectionSummary]:
        return self._runner.run("display.detect", self._detect)

    def _detect(self) -> DetectionSummary:
        result = self._detector.detect()
        state = self._state
        state.dashboard = result.dashboard
        state.capability_generation += 1
        self._reset_downstream()
        self._adopt(result.dashboard.selected_display_id)
        return DetectionSummary(
            dashboard=result.dashboard,
            rejected=tuple((entry.platform_display_id, entry.reason) for entry in result.rejected),
            capability_generation=state.capability_generation,
        )

    def select_display(self, display_id: str) -> ActionOutcome[DisplaySelection]:
        return self._runner.run("workflow.select_display", lambda: self._select_display(display_id))

    def _select_display(self, display_id: str) -> DisplaySelection:
        self._reset_downstream()
        self._adopt(display_id)
        return current_selection(self._state)

    def use_generic_characterization(self) -> ActionOutcome[DisplaySelection]:
        return self._runner.run("display.characterization.use_generic", self._use_generic)

    def _use_generic(self) -> DisplaySelection:
        self._state.selected_panel_key = GENERIC_PANEL_KEY
        self._state.characterization_kind = CharacterizationKind.EXPLICIT_GENERIC
        return current_selection(self._state)

    def open_calibration(self) -> ActionOutcome[DisplaySelection]:
        """Open the calibration view. It reads state and changes none of it."""
        return self._runner.run("calibration.open_for_display", lambda: current_selection(self._state))

    def _reset_downstream(self) -> None:
        """Drop everything a change of display or machine state invalidated."""
        state = self._state
        state.invalidate_seal()
        self._sealed_plan = None
        state.selected_method = None
        state.selected_preset_id = None

    def _adopt(self, display_id: str | None) -> None:
        self._controller = adopt(self._state, display_id)
        self._sync_stage()

    # -- method and target --------------------------------------------------

    def select_method(self, method: CalibrationMethod) -> ActionOutcome[MethodSelection]:
        return self._runner.run(f"calibration.method.{method.value}", lambda: self._select_method(method))

    def _select_method(self, method: CalibrationMethod) -> MethodSelection:
        self._transition(lambda: self._controller.select_method(method))
        state = self._state
        state.selected_method = method
        state.selected_preset_id = None
        state.invalidate_seal()
        self._sealed_plan = None
        return MethodSelection(method=method, stage=state.stage)

    def set_target(self, preset_id: str) -> ActionOutcome[TargetSelection]:
        return self._runner.run(preset_id, lambda: self._set_target(preset_id))

    def _set_target(self, preset_id: str) -> TargetSelection:
        state = self._state
        state.selected_preset_id = preset_id
        state.invalidate_seal()
        self._sealed_plan = None
        self._transition(self._controller.invalidate_preview)
        gamut, white_point, tone_response = target_for(preset_id)
        return TargetSelection(
            preset_id=preset_id,
            gamut=gamut,
            white_point=white_point,
            tone_response=tone_response,
        )

    # -- generation, preview, decision --------------------------------------

    def generate(self) -> ActionOutcome[GenerationResult]:
        return self._runner.run("calibration.generate", self._generate)

    def _generate(self) -> GenerationResult:
        result, plan = generate_bundle(self._state, self._generator, self._lut_size)
        self._sealed_plan = plan
        return result

    def preview(self) -> ActionOutcome[PlanPreview]:
        return self._runner.run("calibration.preview", self._preview)

    def _preview(self) -> PlanPreview:
        plan = self._require_sealed_plan()
        self._transition(lambda: self._controller.set_preview(plan))
        self._state.confirmation_state = "live"
        return PlanPreview(plan=plan, plan_sha256=self._require_digest())

    def confirm_plan(self, *, accepted: bool = True) -> ActionOutcome[PlanDecision]:
        if accepted:
            return self._runner.run("calibration.confirm_plan", self._accept_plan)
        return self._runner.run("calibration.decline_plan", self._decline_plan)

    def _accept_plan(self) -> PlanDecision:
        digest = self._require_digest()
        self._transition(self._acknowledge)
        self._state.confirmation_state = "confirmed"
        return PlanDecision(accepted=True, plan_sha256=digest)

    def _decline_plan(self) -> PlanDecision:
        digest = self._require_digest()
        self._transition(self._controller.invalidate_preview)
        self._state.confirmation_state = "none"
        return PlanDecision(accepted=False, plan_sha256=digest)

    def _acknowledge(self) -> None:
        """Accept a plan nothing will write, and go straight to verification.

        The fake composition overrides this to enter the apply stage, which is
        the only place an adapter is ever driven. Production never reaches that
        stage, so the stage itself records whether a write was attempted.
        """
        self._controller.acknowledge_without_apply()

    # -- verification -------------------------------------------------------

    def verify(self) -> ActionOutcome[VerificationResult]:
        return self._runner.run("verification.sensorless", self._verify)

    def _verify(self) -> VerificationResult:
        state = self._state
        preset_id = state.selected_preset_id
        if preset_id is None:
            raise no_sealed_plan()
        panel, _kind = self._generator.resolve_panel(state.selected_panel_key or GENERIC_PANEL_KEY)
        result = predict_accuracy(self._engine, panel, preset_id)
        state.verification_evidence = result.evidence
        self._transition(self._controller.verify_complete)
        return result

    def hdr_status(self) -> ActionOutcome[HdrStatus]:
        """Report the HDR switch positions the last detection pass observed."""
        return self._runner.run("display.hdr_status", self._hdr_status)

    def _hdr_status(self) -> HdrStatus:
        dashboard = self._state.dashboard
        if dashboard is None:
            raise no_display_selected()
        return HdrStatus(
            displays=tuple(
                HdrDisplayState(
                    display_id=entry.platform_display_id,
                    safe_label=entry.safe_label,
                    hdr_enabled=entry.hdr_enabled,
                )
                for entry in dashboard.displays
            ),
            observed_utc=dashboard.refreshed_utc,
        )

    # -- export -------------------------------------------------------------

    def set_export_directory(self, directory: str | Path) -> ActionOutcome[ExportDirectory]:
        return self._runner.run(
            "settings.output_directory", lambda: choose_directory(self._state, directory)
        )

    def export(self, directory: str | Path | None = None) -> ActionOutcome[ExportBundle]:
        """Publish the sealed bundle, optionally choosing the directory first.

        Choosing a directory is its own action with its own journal record. It
        runs first and its refusal is returned unchanged, so an export never
        appears to have been attempted against a directory that was rejected.
        """
        if directory is not None:
            chosen = self.set_export_directory(directory)
            if isinstance(chosen, ActionError):
                return chosen
        return self._runner.run("report.save", lambda: export_bundle(self._state))

    def export_format(self, export_name: str) -> ActionOutcome[ExportBundle]:
        """Publish one generated format into a directory named for that format."""
        return self._runner.run(
            f"export.active.{export_name}", lambda: export_single_format(self._state, export_name)
        )

    # -- shared helpers -----------------------------------------------------

    def _require_sealed_plan(self) -> ApplyPlan:
        plan = self._sealed_plan
        if plan is None:
            raise no_sealed_plan()
        return plan

    def _require_digest(self) -> str:
        digest = self._state.sealed_plan_sha256
        if digest is None:
            raise no_sealed_plan()
        return digest

    def _transition(self, change: Callable[[], None]) -> None:
        """Run one workflow transition and report a refusal as a refusal.

        The state machine raises on an illegal transition. Converting that into
        a typed policy failure keeps it out of the unexpected-error path, where
        it would be journaled as a defect rather than as a rule doing its job.
        """
        try:
            change()
        except ValueError as exc:
            raise transition_rejected(str(exc)) from exc
        self._sync_stage()

    def _sync_stage(self) -> None:
        self._state.stage = self._controller.stage


__all__ = ["FunctionalRecoveryService"]
