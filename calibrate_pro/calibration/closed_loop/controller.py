"""The closed loop: measure, solve, write, re-measure, stop, verify, seal.

Order of a run, under one approved plan:

1. consume the approval, or refuse;
2. estimate the instrument noise floor and wait out warm-up (reads only);
3. characterize the panel as it stands; if it already meets the target, stop
   with zero writes;
4. probe capability at full brightness and gains, clip the intent, report
   every clip;
5. iterate solve and write until a stop rule fires;
6. verify on held-out patches and seal the step record.

The SDR transfer functions are built. An HDR intent is resolved and clipped,
and the run refuses it before any write, because the HDR loop is specified and
not built in this slice.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np

from calibrate_pro.application.instruments import InstrumentPort
from calibrate_pro.calibration.closed_loop.controls import GAIN_NAMES, Clock, PanelControls, PatchPresenter
from calibrate_pro.calibration.closed_loop.intent import AchievableTarget, PanelCapability, resolve_intent
from calibrate_pro.calibration.closed_loop.ledger import Ledger
from calibrate_pro.calibration.closed_loop.measure import (
    WHITE,
    Characterization,
    NoiseEstimate,
    Probe,
    WarmupResult,
    characterize,
    noise_floor,
    read_patch,
    warmup_gate,
)
from calibrate_pro.calibration.closed_loop.metrics import delta_e_relative, luminance_error, target_white_xyz, xy_to_xyz
from calibrate_pro.calibration.closed_loop.plan import BoundedWriter, ClosedLoopPlan, PlanApproval, PlanRefused
from calibrate_pro.calibration.closed_loop.sim_instrument import evidence_kind_of
from calibrate_pro.calibration.closed_loop.solver import SolverMemory, solve_step
from calibrate_pro.calibration.closed_loop.verify import Verification, verify_held_out
from calibrate_pro.verification.provenance import EvidenceKind, MetricValue


@dataclass(frozen=True)
class LoopResult:
    stop_reason: str
    iterations: int
    writes: int
    target: AchievableTarget
    white_de: MetricValue
    white_luminance: MetricValue
    noise_floor_de: MetricValue
    warmup: WarmupResult | None
    capability: PanelCapability | None
    verification: Verification | None
    final_controls: dict[str, int]
    ledger: tuple[dict[str, Any], ...]
    seal: str


def _peak_at_white(char: Characterization, white_xy: tuple[float, float]) -> float:
    """Highest white luminance at a chromaticity with every gain at most full."""
    full = np.linalg.solve(char.primaries_xyz, char.white_xyz - char.black_xyz)
    unit = np.linalg.solve(char.primaries_xyz, xy_to_xyz(white_xy, 1.0))
    return float(np.min(full / np.maximum(unit, 1e-12)))


class _LoopRun:
    """State of one run. Each method is one stage of the module docstring."""

    def __init__(self, plan: ClosedLoopPlan, panel: PanelControls, probe: Probe, evidence: EvidenceKind) -> None:
        self.plan, self.panel, self.probe, self.evidence = plan, panel, probe, evidence
        self.ledger = Ledger()
        self.writer = BoundedWriter(plan, panel, self.ledger)
        self.target = resolve_intent(plan.intent, None)
        self.noise = NoiseEstimate(0.0, 0.0)
        self.capability: PanelCapability | None = None
        self.white = np.zeros(3)
        self.iterations = 0

    def error(self, white: np.ndarray) -> tuple[float, float]:
        return delta_e_relative(self.target, white, target_white_xyz(self.target)), luminance_error(self.target, white)

    def within(self, white: np.ndarray) -> bool:
        de, lum = self.error(white)
        tolerances = self.plan.intent.tolerances
        return de <= tolerances.white_de2000 and lum <= tolerances.luminance_relative

    def ramp(self, name: str, value: int) -> None:
        bound = self.plan.bound(name)
        if bound is None:
            return
        current = self.panel.read_control(name)
        while current != value:
            step = max(-bound.max_step, min(bound.max_step, value - current))
            current += step
            self.writer.write(name, current)

    def probe_capability(self) -> Characterization:
        for bound in self.plan.bounds:
            if bound.name == "brightness" or bound.name in GAIN_NAMES:
                self.ramp(bound.name, bound.maximum)
        char = characterize(self.probe, self.plan.stop.repeat_reads)
        intent = self.plan.intent
        white_y = float(char.white_xyz[1])
        primaries = char.primaries_xy()
        native = (float(char.white_xyz[0] / np.sum(char.white_xyz)), float(char.white_xyz[1] / np.sum(char.white_xyz)))
        self.capability = PanelCapability(
            peak_luminance=_peak_at_white(char, intent.white_xy),
            contrast_ratio=white_y / max(float(char.black_xyz[1]), 1e-6),
            primaries_xy=(primaries[0], primaries[1], primaries[2]),
            native_white_xy=native,
            evidence=self.evidence,
            source=self.probe.port.identity(),
        )
        self.target = resolve_intent(intent, self.capability)
        clips = [{"field": c.field, "requested": c.requested, "achievable": c.achievable} for c in self.target.clips]
        self.ledger.append("capability", {"peak": self.capability.peak_luminance, "clips": clips})
        return char

    def confirm_at_floor(self) -> bool:
        """Re-read white with four times the averaging before stopping at the floor.

        One noisy reading can land under the floor by chance. The confirmation
        halves the noise, so a stop here is a property of the panel state.
        """
        confirm = read_patch(self.probe, WHITE, 4 * self.plan.stop.repeat_reads)
        de, _ = self.error(confirm)
        self.ledger.append("floor_check", {"white_de": de, "floor": self.noise.floor_de})
        if de <= self.noise.floor_de:
            self.white = confirm
            return True
        return False

    def step(self, memory: SolverMemory, char: Characterization) -> bool:
        state = {b.name: self.panel.read_control(b.name) for b in self.plan.bounds}
        proposal = solve_step(self.plan, state, char.primaries_xyz, self.white, target_white_xyz(self.target), memory)
        return any([self.writer.write(name, value) for name, value in proposal.items() if value != state[name]])

    def iterate(self, char: Characterization) -> str:
        stop, memory, best, stale = self.plan.stop, SolverMemory(), float("inf"), 0
        for iteration in range(1, stop.max_iterations + 1):
            self.iterations = iteration
            self.white = read_patch(self.probe, WHITE, stop.repeat_reads)
            de, lum = self.error(self.white)
            self.ledger.append("iteration", {"n": iteration, "white_de": de, "luminance_error": lum})
            if self.within(self.white):
                return "converged"
            if de <= self.noise.floor_de and self.confirm_at_floor():
                return "noise_floor"
            if de < best * (1.0 - stop.min_improvement):
                best, stale = de, 0
            else:
                stale += 1
                if stale >= stop.patience:
                    # Stalled inside the noise band means the instrument, not
                    # the panel, is the limit.
                    return "noise_floor" if de <= 2.0 * self.noise.floor_de else "no_improvement"
            try:
                if not self.step(memory, char):
                    return "control_resolution"
            except PlanRefused:
                return "write_budget"
        self.white = read_patch(self.probe, WHITE, stop.repeat_reads)
        return "max_iterations"


def _finish(run: _LoopRun, reason: str, warmup: WarmupResult | None, verification: Verification | None) -> LoopResult:
    source = run.probe.port.identity()
    de, _ = run.error(run.white) if run.white.any() else (float("nan"), 0.0)
    de_metric = MetricValue(de, "dE2000", run.evidence, source) if np.isfinite(de) else _not_measured("dE2000")
    lum = MetricValue(float(run.white[1]), "cd/m2", run.evidence, source) if run.white.any() else _not_measured("cd/m2")
    floor = MetricValue(run.noise.floor_de, "dE2000", run.evidence, source)
    run.ledger.append("stop", {"reason": reason, "iterations": run.iterations, "writes": run.writer.writes})
    controls = {b.name: run.panel.read_control(b.name) for b in run.plan.bounds}
    entries = run.ledger.entries()
    return LoopResult(
        reason, run.iterations, run.writer.writes, run.target, de_metric, lum, floor, warmup,
        run.capability, verification, controls, entries, run.ledger.seal,
    )  # fmt: skip


def _not_measured(unit: str) -> MetricValue:
    return MetricValue(None, unit, EvidenceKind.NOT_MEASURED)


def _verify(run: _LoopRun, primaries: tuple[tuple[float, float], ...]) -> Verification:
    triangle = (primaries[0], primaries[1], primaries[2])
    result = verify_held_out(run.probe, run.target, triangle, run.plan.stop.repeat_reads, run.evidence)
    run.ledger.append("verify", {"passed": result.passed, "gray_worst": result.worst("gray")})
    return result


def run_closed_loop(
    plan: ClosedLoopPlan,
    approval: PlanApproval,
    panel: PanelControls,
    presenter: PatchPresenter,
    port: InstrumentPort,
    clock: Clock,
) -> LoopResult:
    """Run one approved plan to a stop rule and return the sealed result."""
    approval.consume(plan)
    run = _LoopRun(plan, panel, Probe(presenter, port, clock), evidence_kind_of(port))
    run.ledger.append("plan", {"digest": plan.digest(), "evidence": run.evidence.value})
    if plan.intent.is_hdr:
        return _finish(run, "hdr_not_built", None, None)
    run.noise = noise_floor(run.probe, run.target, plan.stop)
    warmup = warmup_gate(run.probe, plan.stop, run.noise.luminance_sigma_rel)
    run.ledger.append("warmup", {"stable": warmup.stable, "elapsed_s": warmup.elapsed_s})
    if not warmup.stable:
        return _finish(run, "warmup_unstable", warmup, None)
    char = characterize(run.probe, plan.stop.repeat_reads)
    run.white = char.white_xyz
    if run.within(run.white):
        return _finish(run, "converged", warmup, _verify(run, char.primaries_xy()))
    try:
        char = run.probe_capability()
    except PlanRefused:
        return _finish(run, "write_budget", warmup, None)
    reason = run.iterate(char)
    return _finish(run, reason, warmup, _verify(run, char.primaries_xy()))


__all__ = ["LoopResult", "run_closed_loop"]
