"""The one session service every surface drives.

A surface calls a method here and renders what comes back. It never reaches a
detector, a generator, an exporter, or the workflow state machine on its own,
so every state change in a session passes through one resolver, one action
boundary, and one journal.

This class performs no physical mutation. It holds no adapter that writes to a
display and it has no method that does. Two subclasses add one. The fake
composition records what an apply would do, and the calibration composition
sends it to the display. Both adapters arrive from the composition layer, so a
session built without one is never handed one, and a build with no write route
runs this class as written.

A measurement run is the one place this class reaches outside the process. It
opens the colorimeter the composition wired and puts a patch window on the
display being measured. Neither changes display state: the window paints a
colour and the instrument reads the light, and both close before the run
returns. The Qt window and the platform gamma table reader are imported inside
the method bodies that need them, so a session that only publishes files never
loads either, and the shipped build can still prove that.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from calibrate_pro.application.assets import AssetGenerator, ExportBundle
from calibrate_pro.application.contracts import CharacterizationKind
from calibrate_pro.application.correction_state import qualify_uncorrected
from calibrate_pro.application.detection import DisplayDetector
from calibrate_pro.application.diagnostics import DiagnosticsActions
from calibrate_pro.application.exporting import export_bundle, export_single_format
from calibrate_pro.application.generation import generate_bundle
from calibrate_pro.application.instruments import (
    InstrumentPort,
    InstrumentSource,
    InstrumentUnavailable,
    NoInstrumentSource,
)
from calibrate_pro.application.journal import DiagnosticBundleManager
from calibrate_pro.application.measured_verification import uncovered_result
from calibrate_pro.application.measured_verification import verify_measured as measured_accuracy
from calibrate_pro.application.measurement import (
    DEFAULT_RAMP_STEPS,
    SETTLE_SECONDS,
    MeasuredCharacterization,
    MeasurementRefused,
    PatchPort,
    measure_characterization,
)
from calibrate_pro.application.outcomes import ActionError, ActionOutcome
from calibrate_pro.application.panel_profiles import PanelProfileActions
from calibrate_pro.application.planning import target_for
from calibrate_pro.application.prediction import predict_accuracy, target_is_modelled
from calibrate_pro.application.preferences import PreferenceActions
from calibrate_pro.application.profile_actions import ProfileActions
from calibrate_pro.application.refusals import (
    measurement_refused,
    no_display_selected,
    no_sealed_plan,
    transition_rejected,
)
from calibrate_pro.application.results import (
    DetectionSummary,
    DisplaySelection,
    GenerationResult,
    HdrDisplayState,
    HdrStatus,
    MeasurementSummary,
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
from calibrate_pro.panels.database import GENERIC_PANEL_KEY, PanelCharacterization
from calibrate_pro.sensorless.neuralux import SensorlessEngine
from calibrate_pro.workflow import ApplyPlan, CalibrationMethod, WorkflowController, WorkflowStage


class FunctionalRecoveryService(
    ProfileActions,
    PanelProfileActions,
    SurfaceActions,
    DiagnosticsActions,
    PreferenceActions,
):
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
        bundles: DiagnosticBundleManager | None = None,
        instruments: InstrumentSource | None = None,
    ) -> None:
        self._state = state
        self._runner = runner
        self._detector = detector
        self._generator = generator
        self._engine = engine
        self._lut_size = lut_size
        self._bundles = bundles
        self._instruments = instruments if instruments is not None else NoInstrumentSource()
        self._controller = WorkflowController(DENIED_CAPABILITIES)
        self._sealed_plan: ApplyPlan | None = None

    # -- session state, detection, and selection ----------------------------

    @property
    def stage(self) -> WorkflowStage:
        return self._state.stage

    @property
    def selection(self) -> DisplaySelection | None:
        """Describe the display this session holds, or None if it holds none.

        Reading is not an action and nothing is journalled here. A surface needs
        this because a detection pass adopts a display on its own: no control
        performed that adoption, so no outcome carried the characterization out
        to be rendered. Deriving it from the observation instead would put the
        surface one step behind the session, which is the whole difficulty. A
        matched panel the session cannot name is adopted as uncharacterized, and
        a session that took the generic path holds a kind the observation never
        carried.
        """
        if self._state.selected_display_id is None or self._state.dashboard is None:
            return None
        return current_selection(self._state)

    def detect(self) -> ActionOutcome[DetectionSummary]:
        return self._runner.run("display.detect", self._detect)

    def _detect(self) -> DetectionSummary:
        result = self._detector.detect()
        state = self._state
        state.dashboard = result.dashboard
        state.capability_generation += 1
        state.instrument_identity = self._instrument_identity()
        self._reset_downstream()
        self._adopt(result.dashboard.selected_display_id)
        return DetectionSummary(
            dashboard=result.dashboard,
            rejected=tuple((entry.platform_display_id, entry.reason) for entry in result.rejected),
            capability_generation=state.capability_generation,
        )

    def _instrument_identity(self) -> str | None:
        """Name the instrument the source found, or None when it found none.

        A source that raises has not found a device. The identity is read at
        detection so that it moves with the rest of the machine picture rather
        than being resolved later against a colorimeter that has since been
        unplugged.
        """
        try:
            if not self._instruments.present():
                return None
            described = self._instruments.describe()
        except Exception:
            return None
        if type(described) is not str or not described.strip():
            return None
        return described

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

    # -- measurement --------------------------------------------------------

    def measure(
        self,
        *,
        steps: int = DEFAULT_RAMP_STEPS,
        window_fraction: float = 1.0,
        progress: Callable[[str, float], None] | None = None,
    ) -> ActionOutcome[MeasurementSummary]:
        """Read the selected display with the instrument this session found.

        The run replaces the panel record this session would otherwise generate
        from, so it breaks any seal the session was holding. That is why the
        gate offers it only while nothing is sealed: a run taken afterwards
        would drop a bundle the operator is standing in front of.
        """
        return self._runner.run(
            "calibration.measure",
            lambda: self._measure(steps=steps, window_fraction=window_fraction, progress=progress),
        )

    def _measure(
        self,
        *,
        steps: int,
        window_fraction: float,
        progress: Callable[[str, float], None] | None,
    ) -> MeasurementSummary:
        state = self._state
        display_id = state.selected_display_id
        if display_id is None:
            raise no_display_selected()
        panel, _kind = self._generator.resolve_panel(state.selected_panel_key or GENERIC_PANEL_KEY)
        try:
            correction_state = qualify_uncorrected(display_id)
            measured = self._run_measurement(
                display_id=display_id,
                panel=panel,
                steps=steps,
                window_fraction=window_fraction,
                progress=progress,
            )
        except MeasurementRefused as exc:
            # A run that stopped is a refusal carrying a reason, not a defect.
            # Letting it out as an unexpected error would journal an unplugged
            # sensor and a closed window the way a crash is journaled.
            raise measurement_refused(str(exc)) from exc
        state.record_measurement(measured)
        self._sealed_plan = None
        self._transition(self._controller.invalidate_preview)
        return MeasurementSummary(
            display_id=display_id,
            characterization=measured,
            correction_state=correction_state,
        )

    def _run_measurement(
        self,
        *,
        display_id: str,
        panel: PanelCharacterization,
        steps: int,
        window_fraction: float,
        progress: Callable[[str, float], None] | None,
    ) -> MeasuredCharacterization:
        """Hold both ports open for one run and close them however it ends.

        The instrument opens first and closes last. Opening it runs the device's
        own dark calibration, which the operator waits through, and running that
        behind a fullscreen patch window would black the display out with
        nothing on it to explain the wait and no event loop pumping to notice an
        Escape. Opening it first also puts the common failure first: a
        colorimeter that is not plugged in refuses before anything covers the
        screen.
        """
        instrument = self._open_instrument()
        try:
            patches, settle = self._open_patches(display_id, window_fraction)
            try:
                return measure_characterization(
                    instrument=instrument,
                    patches=patches,
                    base=panel,
                    steps=steps,
                    settle=settle,
                    progress=progress,
                )
            finally:
                patches.close()
        finally:
            instrument.close()

    def _open_instrument(self) -> InstrumentPort:
        """Open the colorimeter, reporting a missing one as a retryable refusal."""
        try:
            return self._instruments.open()
        except InstrumentUnavailable as exc:
            raise measurement_refused(str(exc)) from exc

    def _open_patches(self, display_id: str, fraction: float) -> tuple[PatchPort, Callable[[], None]]:
        """Open a patch window on the display being measured.

        The presenter is imported here rather than at module scope. Importing it
        above would pull Qt into every session that only publishes files, and
        the read-only build's import probe reports on exactly that.

        The settle function comes back with the port because waiting has to pump
        the window's event loop. A plain sleep would leave the requested patch
        unpainted, and the instrument would read whichever colour was on screen
        before it.
        """
        from calibrate_pro.adapters.qt_patch_presenter import PatchWindowUnavailable, open_patch_window

        try:
            presenter = open_patch_window(device_name=display_id, fraction=fraction)
        except PatchWindowUnavailable as exc:
            raise measurement_refused(str(exc)) from exc
        return presenter, lambda: presenter.settle(SETTLE_SECONDS)

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

    def verify_measured(
        self,
        *,
        window_fraction: float = 1.0,
        progress: Callable[[str, float], None] | None = None,
    ) -> ActionOutcome[VerificationResult]:
        """Read the reference chart off the display and report what it measured."""
        return self._runner.run(
            "verification.measured",
            lambda: self._verify_measured(window_fraction=window_fraction, progress=progress),
        )

    def _verify_measured(
        self,
        *,
        window_fraction: float,
        progress: Callable[[str, float], None] | None,
    ) -> VerificationResult:
        state = self._state
        preset_id = state.selected_preset_id
        if preset_id is None:
            raise no_sealed_plan()
        display_id = state.selected_display_id
        if display_id is None:
            raise no_display_selected()
        if not target_is_modelled(preset_id):
            # Answered without opening anything. The reference chart describes
            # one target, so a run against any other one reports no figure, and
            # reaching that answer through the ports would cost the operator a
            # dark calibration and a blacked-out screen to arrive where the
            # preset already arrives.
            result = uncovered_result()
        else:
            try:
                result = self._run_verification(
                    display_id=display_id,
                    preset_id=preset_id,
                    window_fraction=window_fraction,
                    progress=progress,
                )
            except MeasurementRefused as exc:
                raise measurement_refused(str(exc)) from exc
        state.verification_evidence = result.evidence
        self._transition(self._controller.verify_complete)
        return result

    def _run_verification(
        self,
        *,
        display_id: str,
        preset_id: str,
        window_fraction: float,
        progress: Callable[[str, float], None] | None,
    ) -> VerificationResult:
        """Hold both ports open for one chart reading.

        Nothing qualifies the display's correction here, and that is the
        difference between this and a characterization run. A verification is
        supposed to read whatever correction is loaded, because that correction
        is the thing being checked.
        """
        instrument = self._open_instrument()
        try:
            patches, settle = self._open_patches(display_id, window_fraction)
            try:
                return measured_accuracy(
                    instrument=instrument,
                    patches=patches,
                    preset_id=preset_id,
                    settle=settle,
                    progress=progress,
                )
            finally:
                patches.close()
        finally:
            instrument.close()

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
        return self._runner.run(f"export.active.{export_name}", lambda: export_single_format(self._state, export_name))

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
