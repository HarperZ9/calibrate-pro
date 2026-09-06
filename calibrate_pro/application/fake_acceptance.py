"""A composition that drives an apply end to end without touching a display.

This composition exists so the apply lifecycle can be proven without hardware.
It enters the apply stage, redeems a real confirmation token through the real
actuation coordinator, and records the adapter calls that resulted.

The adapter is a recorder. It captures nothing from the machine, writes nothing
to it, and returns a snapshot built from the plan it was handed. What the proof
establishes is the ordering and the gating around an apply, not that any
particular display was calibrated. A test that wants the physical path still
needs hardware and an acceptance run.

The lifecycle itself lives in :mod:`calibrate_pro.application.coordinated` and
is shared with the calibration composition, so what this proof exercises is the
same code a real apply runs and not a parallel implementation of it.
"""

from __future__ import annotations

from calibrate_pro.application.coordinated import (
    APPLY_NOT_AUTHORIZED,
    NO_CONFIRMATION_TOKEN,
    CoordinatedApplyService,
)
from calibrate_pro.application.outcomes import ActionOutcome
from calibrate_pro.application.results import FakeApplyResult
from calibrate_pro.recovery import DisplayStateSnapshot
from calibrate_pro.workflow import ApplyPlan


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


class FakeAcceptanceService(CoordinatedApplyService):
    """The apply lifecycle, driven against a recorder instead of a display."""

    def __init__(self, *, adapter: RecordingFakeAdapter, **kwargs: object) -> None:
        super().__init__(adapter=adapter, **kwargs)

    @property
    def adapter(self) -> RecordingFakeAdapter:
        """Expose the recorder so a proof can read the call order it produced."""
        adapter = self._adapter
        assert isinstance(adapter, RecordingFakeAdapter)
        return adapter

    def apply_confirmed_plan(self) -> ActionOutcome[FakeApplyResult]:
        return self._runner.run("fake_acceptance.apply", self._apply_confirmed)

    def _apply_confirmed(self) -> FakeApplyResult:
        digest, _plan, receipt = self._redeem_confirmation()
        if receipt.success:
            self._state.fake_applied_plan_sha256 = digest
        return FakeApplyResult(plan_sha256=digest, receipt=receipt, physical_apply_performed=False)


__all__ = [
    "APPLY_NOT_AUTHORIZED",
    "NO_CONFIRMATION_TOKEN",
    "FakeAcceptanceService",
    "RecordingFakeAdapter",
]
