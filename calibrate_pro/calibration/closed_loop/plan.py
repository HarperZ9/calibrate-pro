"""The previewed plan, its single approval, and the writer that enforces it.

One click means one confirmation of a plan the user has seen: which controls
may change, the hard range of each, the largest step per write, the write
budget, and the stop rules. The approval is bound to the plan digest and is
consumed once. The writer refuses any write the plan does not cover.
"""

from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass

from calibrate_pro.calibration.closed_loop.controls import LOOP_WRITABLE, PanelControls
from calibrate_pro.calibration.closed_loop.intent import DisplayIntent
from calibrate_pro.calibration.closed_loop.ledger import Ledger, canonical


class PlanRefused(RuntimeError):
    """A write or a run was refused because the plan does not cover it."""


@dataclass(frozen=True)
class StopRules:
    """When the loop stops, besides reaching tolerance."""

    max_iterations: int = 12
    min_improvement: float = 0.05
    patience: int = 2
    repeat_reads: int = 3
    noise_probe_reads: int = 6
    noise_floor_k: float = 2.0
    warmup_interval_s: float = 60.0
    warmup_max_s: float = 1800.0
    warmup_threshold_pct_per_min: float = 0.1
    warmup_stable_count: int = 3


@dataclass(frozen=True)
class ControlBound:
    name: str
    minimum: int
    maximum: int
    max_step: int


@dataclass(frozen=True)
class ClosedLoopPlan:
    display: str
    intent: DisplayIntent
    bounds: tuple[ControlBound, ...]
    max_writes: int
    stop: StopRules
    initial: tuple[tuple[str, int], ...]

    def digest(self) -> str:
        return hashlib.sha256(canonical(asdict(self)).encode("utf-8")).hexdigest()

    def bound(self, name: str) -> ControlBound | None:
        return next((b for b in self.bounds if b.name == name), None)


def build_plan(
    display: str,
    intent: DisplayIntent,
    panel: PanelControls,
    *,
    stop: StopRules | None = None,
    max_step: int = 10,
    max_writes: int = 80,
) -> ClosedLoopPlan:
    """Build a plan over the loop-writable controls this panel advertises."""
    bounds = tuple(
        ControlBound(spec.name, spec.minimum, spec.maximum, max_step)
        for spec in panel.controls()
        if spec.name in LOOP_WRITABLE
    )
    initial = tuple((b.name, panel.read_control(b.name)) for b in bounds)
    return ClosedLoopPlan(display, intent, bounds, max_writes, stop or StopRules(), initial)


class PlanApproval:
    """The user's one confirmation of one plan. Consumed by the first run."""

    def __init__(self, plan: ClosedLoopPlan) -> None:
        self.digest = plan.digest()
        self._consumed = False

    def consume(self, plan: ClosedLoopPlan) -> None:
        if self._consumed:
            raise PlanRefused("this approval has already been used")
        if plan.digest() != self.digest:
            raise PlanRefused("this approval was given for a different plan")
        self._consumed = True


class BoundedWriter:
    """Write panel controls only inside the approved plan's hard bounds."""

    def __init__(self, plan: ClosedLoopPlan, panel: PanelControls, ledger: Ledger) -> None:
        self._plan = plan
        self._panel = panel
        self._ledger = ledger
        self.writes = 0

    def write(self, name: str, value: int) -> bool:
        """Write one control. Returns False when the value is already set."""
        bound = self._plan.bound(name)
        if bound is None:
            raise PlanRefused(f"the plan does not cover writing {name}")
        if not bound.minimum <= value <= bound.maximum:
            raise PlanRefused(f"{name}={value} is outside the approved {bound.minimum}..{bound.maximum}")
        current = self._panel.read_control(name)
        if value == current:
            return False
        if abs(value - current) > bound.max_step:
            raise PlanRefused(f"{name} step {value - current} exceeds the approved {bound.max_step}")
        if self.writes >= self._plan.max_writes:
            raise PlanRefused("the approved write budget is spent")
        self._panel.write_control(name, value)
        self.writes += 1
        self._ledger.append("write", {"control": name, "from": current, "to": value})
        return True


__all__ = ["BoundedWriter", "ClosedLoopPlan", "ControlBound", "PlanApproval", "PlanRefused", "StopRules", "build_plan"]
