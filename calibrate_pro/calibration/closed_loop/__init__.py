"""One-click closed-loop calibration: display intent, simulated hardware, controller.

See project-docs/specs/SPEC-one-click-closed-loop-2026-11-04.md. Everything a
simulated panel or instrument produces is labelled SIMULATED in the result.
"""

from calibrate_pro.calibration.closed_loop.controller import LoopResult, run_closed_loop
from calibrate_pro.calibration.closed_loop.intent import (
    AchievableTarget,
    Clip,
    DisplayIntent,
    PanelCapability,
    Tolerances,
    resolve_intent,
)
from calibrate_pro.calibration.closed_loop.plan import ClosedLoopPlan, PlanApproval, PlanRefused, StopRules, build_plan
from calibrate_pro.calibration.closed_loop.sim_instrument import SimulatedInstrument
from calibrate_pro.calibration.closed_loop.sim_panel import PanelTruth, SimulatedPanel

__all__ = [
    "AchievableTarget",
    "Clip",
    "ClosedLoopPlan",
    "DisplayIntent",
    "LoopResult",
    "PanelCapability",
    "PanelTruth",
    "PlanApproval",
    "PlanRefused",
    "SimulatedInstrument",
    "SimulatedPanel",
    "StopRules",
    "Tolerances",
    "build_plan",
    "resolve_intent",
    "run_closed_loop",
]
