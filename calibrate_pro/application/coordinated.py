"""The apply lifecycle a session shares with whatever adapter it was given.

An apply is four separate moments: entering the stage, minting a confirmation,
redeeming it exactly once, and reporting what the receipt says happened. Those
moments are the same whether the adapter records calls or drives a display, so
they live here and each composition supplies only its adapter and the result
type it reports.

Splitting confirmation from redemption is the point of the coordinator. A token
is minted when the operator accepts a previewed plan and spent when the apply
runs, so a plan that changed in between cannot be applied against a
confirmation the operator gave for something else.

This module holds no import of an adapter package. What a session drives is
decided by the composition that constructs it, which is what keeps the shipped
read-only session from acquiring a display adapter through an import.
"""

from __future__ import annotations

from calibrate_pro.actuation import ActuationCoordinator
from calibrate_pro.application.refusals import policy_refusal
from calibrate_pro.application.results import PlanDecision
from calibrate_pro.application.selection import DENIED_CAPABILITIES
from calibrate_pro.application.service import FunctionalRecoveryService
from calibrate_pro.recovery import ApplyReceipt, DisplayStateAdapter
from calibrate_pro.workflow import ApplyPlan, CapabilityState

APPLY_NOT_AUTHORIZED = "APPLY_NOT_AUTHORIZED"
NO_CONFIRMATION_TOKEN = "NO_CONFIRMATION_TOKEN"

__all__ = [
    "APPLY_NOT_AUTHORIZED",
    "NO_CONFIRMATION_TOKEN",
    "CoordinatedApplyService",
]


class CoordinatedApplyService(FunctionalRecoveryService):
    """A session that holds one display adapter and redeems tokens against it."""

    def __init__(self, *, adapter: DisplayStateAdapter, **kwargs: object) -> None:
        super().__init__(**kwargs)  # type: ignore[arg-type]
        self._adapter = adapter
        self._coordinator = ActuationCoordinator(adapter, self._capabilities_for)
        self._token: str | None = None

    def _capabilities_for(self, display_id: str) -> CapabilityState:
        """Answer with what detection found, and deny when nothing was detected.

        The coordinator asks again at redemption rather than trusting the state
        read at confirmation. A session that lost its detection between those
        two moments denies the apply instead of running it against a capability
        set nobody currently holds.
        """
        _ = display_id
        return self._state.capabilities or DENIED_CAPABILITIES

    def _acknowledge(self) -> None:
        """Enter the apply stage and mint the token that apply will redeem."""
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

    def _redeem_confirmation(self) -> tuple[str, ApplyPlan, ApplyReceipt]:
        """Spend this session's one confirmation and report what came back.

        The stage transition happens here because the receipt decides it. A
        subclass turns the three values into whatever result its composition
        reports, and cannot reach the coordinator to redeem a second time.
        """
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
            self._transition(self._controller.apply_complete)
        else:
            self._transition(self._controller.apply_failed)
        return digest, plan, receipt

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
