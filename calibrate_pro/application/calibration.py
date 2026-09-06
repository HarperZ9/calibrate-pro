"""The session that stages a bundle, seals an actuating plan, and applies it.

This is the calibrating half of the product. It differs from the shipped
read-only session in two places and nowhere else: generation stages the bundle
to disk and seals a plan that pins those files, and the confirmed apply is
redeemed against a display adapter rather than refused.

Both differences are load-bearing together. What the operator previews has to
be the plan the adapter receives, so the actuating plan is built during
generation and sealed there, not assembled later from the same inputs. A plan
built after confirmation would carry the same digest only by luck, and the
coordinator would reject it, which is a refusal the operator could do nothing
about.

The adapter is constructed by the composition, never imported here. Keeping the
import out of this module is what lets the shipped read-only build load the
application layer without pulling a writer into the process.

Not every bundle this session generates can be applied. A characterization
that already matches its target changes no output code, and a machine may
report no route this build can capture and put back. Neither is a generation
failure: the bundle is real and an operator can export it for a colour-managed
application. So generation falls back to the plan that requests nothing, keeps
the reason, and lowers the flag the apply control reads.
"""

from __future__ import annotations

from dataclasses import replace

from calibrate_pro.application.coordinated import CoordinatedApplyService
from calibrate_pro.application.generation import generate_bundle, publishing_plan
from calibrate_pro.application.outcomes import ActionOutcome
from calibrate_pro.application.planning import PlanNotActuatable, build_actuating_plan
from calibrate_pro.application.results import AppliedPlanResult, GenerationResult
from calibrate_pro.application.staging import stage_bundle
from calibrate_pro.workflow import ApplyPlan, CalibrationMethod

#: Action id the runner records for a confirmed physical apply. It is separate
#: from the fake composition's id so the journal, the registry, and the boundary
#: all distinguish a display that was written from one that was recorded.
CALIBRATION_APPLY_ACTION = "calibration.apply"

__all__ = ["CALIBRATION_APPLY_ACTION", "CalibrationApplyService"]


class CalibrationApplyService(CoordinatedApplyService):
    """The session that can change a display, given a plan that would change one."""

    #: Why the plan built during the last generation requests no route, or
    #: None when it requests one. Generation sets it and reads it back in the
    #: same call, so a reason from one bundle never describes another.
    _plan_refusal: str | None = None

    def _generate(self) -> GenerationResult:
        self._plan_refusal = None
        result, plan = generate_bundle(
            self._state,
            self._generator,
            self._lut_size,
            plan_builder=self._actuating_plan,
        )
        self._sealed_plan = plan
        self._state.sealed_plan_actuatable = self._plan_refusal is None
        return replace(result, apply_note=self._plan_refusal)

    def _actuating_plan(
        self,
        display_id: str,
        method: CalibrationMethod,
        preset_id: str,
        filenames: tuple[str, ...],
        generated: object,
    ) -> ApplyPlan:
        """Stage the bundle, then build the plan that pins what was written.

        Staging comes first because a plan names files by digest and nothing can
        be digested before it exists. The capability state is read here rather
        than at apply time so a route the machine cannot take is reported while
        the operator is still looking at a preview.

        A refused plan falls back to the one that requests nothing. The bundle
        is still sealed and still exportable, and the reason is kept so the
        apply control can carry it instead of leaving the operator to guess
        why a bundle that generated cleanly cannot be sent to the display.
        """
        from calibrate_pro.application.assets import GeneratedAssets

        assert isinstance(generated, GeneratedAssets)
        staged = stage_bundle(generated)
        try:
            return build_actuating_plan(
                display_id=display_id,
                method=method,
                preset_id=preset_id,
                output_files=filenames,
                generated=generated,
                staged=staged,
                capabilities=self._capabilities_for(display_id),
            )
        except PlanNotActuatable as reason:
            self._plan_refusal = str(reason)
            return publishing_plan(display_id, method, preset_id, filenames, generated)

    def apply_confirmed_plan(self) -> ActionOutcome[AppliedPlanResult]:
        return self._runner.run(CALIBRATION_APPLY_ACTION, self._apply_confirmed)

    def _apply_confirmed(self) -> AppliedPlanResult:
        digest, plan, receipt = self._redeem_confirmation()
        if receipt.success:
            self._state.applied_plan_sha256 = digest
        return AppliedPlanResult(plan_sha256=digest, receipt=receipt, routes=_routes(plan))


def _routes(plan: ApplyPlan) -> tuple[str, ...]:
    """Name each route the plan requested, in the order the adapter takes them."""
    routes = []
    if plan.icc_profile_path is not None:
        routes.append("icc")
    if plan.vcgt_path is not None:
        routes.append("vcgt")
    if plan.dwm_lut_path is not None:
        routes.append("dwm_lut")
    if plan.ddc_changes:
        routes.append("ddc")
    return tuple(routes)
