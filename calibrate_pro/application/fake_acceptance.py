"""A composition that drives an apply end to end without touching a display.

Production performs no physical mutation, so the apply path would otherwise
ship untested. This module supplies the missing half: a service that enters the
apply stage, redeems a real confirmation token through the real actuation
coordinator, and records the adapter calls that resulted.

The adapter is a recorder. It captures nothing from the machine, writes nothing
to it, and returns a snapshot built from the plan it was handed. What the proof
establishes is the ordering and the gating around an apply, not that any
particular display was calibrated. A test that wants the physical path still
needs hardware and an acceptance run.
"""

from __future__ import annotations

from calibrate_pro.actuation import ActuationCoordinator
from calibrate_pro.application.outcomes import ActionOutcome
from calibrate_pro.application.refusals import policy_refusal
from calibrate_pro.application.results import FakeApplyResult, PlanDecision
from calibrate_pro.application.selection import DENIED_CAPABILITIES
from calibrate_pro.application.service import FunctionalRecoveryService
from calibrate_pro.recovery import ApplyReceipt, DisplayStateSnapshot
from calibrate_pro.workflow import ApplyPlan, CapabilityState

APPLY_NOT_AUTHORIZED = "APPLY_NOT_AUTHORIZED"
NO_CONFIRMATION_TOKEN = "NO_CONFIRMATION_TOKEN"


class RecordingFakeAdapter:
    """A display adapter that records what it was asked to do and does none of it."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def capture(self, plan: ApplyPlan, *, authorization: object | None = None) -> DisplayStateSnapshot:
        _ = authorization
        self.calls.append("capture")
        return DisplayStateSnapshot(
            display_id=plan.display_id,
            ddc_values=(),
            icc_profile=None,
            gamma_ramp=None,
            dwm_luts=None,
        )

    def apply(self, plan: ApplyPlan) -> None:
        _ = plan
        self.calls.append("apply")

    def verify(self, plan: ApplyPlan) -> bool:
        _ = plan
        self.calls.append("verify")
        return True

    def commit(self, plan: ApplyPlan) -> None:
        _ = plan
        self.calls.append("commit")

    def restore(self, snapshot: DisplayStateSnapshot) -> None:
        _ = snapshot
        self.calls.append("restore")


class FakeAcceptanceService(FunctionalRecoveryService):
    """The production session, with the one stage production never enters."""

    def __init__(self, *, adapter: RecordingFakeAdapter, **kwargs: object) -> None:
        super().__init__(**kwargs)  # type: ignore[arg-type]
        self._adapter = adapter
        self._coordinator = ActuationCoordinator(adapter, self._capabilities_for)
        self._token: str | None = None

    @property
    def adapter(self) -> RecordingFakeAdapter:
        """Expose the recorder so a proof can read the call order it produced."""
        return self._adapter

    def _capabilities_for(self, display_id: str) -> CapabilityState:
        _ = display_id
        return self._state.capabilities or DENIED_CAPABILITIES

    def _acknowledge(self) -> None:
        """Enter the apply stage and mint the token that apply will redeem.

        Confirmation and redemption are separate calls, which is the whole point
        of the coordinator. Minting here means the proof exercises the token
        binding rather than issuing and consuming a confirmation in one step.
        """
        plan = self._require_sealed_plan()
        self._controller.confirm_apply()
        try:
            self._token = self._coordinator.preview(plan)
        except Exception:
            self._controller.apply_failed()
            raise

    def _discard_token(self) -> None:
        """Drop an outstanding confirmation so a stale token cannot be redeemed."""
        self._token = None
        self._coordinator.invalidate_confirmation()

    def _reset_downstream(self) -> None:
        self._discard_token()
        super()._reset_downstream()

    def _decline_plan(self) -> PlanDecision:
        self._discard_token()
        return super()._decline_plan()

    def apply_confirmed_plan(self) -> ActionOutcome[FakeApplyResult]:
        return self._runner.run("fake_acceptance.apply", self._apply_confirmed)

    def _apply_confirmed(self) -> FakeApplyResult:
        plan = self._require_sealed_plan()
        digest = self._require_digest()
        token = self._token
        if token is None:
            raise policy_refusal(
                NO_CONFIRMATION_TOKEN,
                "This session holds no confirmation to redeem.",
                "Confirm the previewed plan, then apply it.",
            )
        self._token = None
        state = self._state
        # The coordinator consumes the pending confirmation on every rejection
        # path as well as on success, so the token is spent the moment it is
        # handed over. Recording that after redemption would leave a refused
        # apply still claiming a live confirmation, and the resolver would go on
        # offering an apply control that could only refuse again.
        state.confirmation_state = "consumed"
        receipt = self._redeem(plan, token)
        if receipt.success:
            state.fake_applied_plan_sha256 = digest
            self._transition(self._controller.apply_complete)
        else:
            self._transition(self._controller.apply_failed)
        return FakeApplyResult(plan_sha256=digest, receipt=receipt, physical_apply_performed=False)

    def _redeem(self, plan: ApplyPlan, token: str) -> ApplyReceipt:
        """Redeem one token, reporting a rejected confirmation as a refusal.

        The coordinator raises PermissionError for a token that is unknown,
        expired, declined, or bound to another plan. Every one of those is a
        rule working, so it is reported as a policy refusal rather than as an
        unexpected error the journal would record as a defect.
        """
        try:
            return self._coordinator.apply(plan, token, confirmed=True)
        except PermissionError as exc:
            self._controller.apply_failed()
            self._sync_stage()
            raise policy_refusal(
                APPLY_NOT_AUTHORIZED,
                str(exc),
                "Preview the plan again and confirm it before applying.",
            ) from exc


__all__ = [
    "APPLY_NOT_AUTHORIZED",
    "NO_CONFIRMATION_TOKEN",
    "FakeAcceptanceService",
    "RecordingFakeAdapter",
]
