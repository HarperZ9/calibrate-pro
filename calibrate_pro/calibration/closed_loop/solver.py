"""One correction step: from a white reading to new gain and brightness values.

The solver works in the panel's own primaries. A characterization gives the
XYZ of each primary, so a white reading decomposes into three channel amounts,
and the target white does too. Their ratio is the change each channel needs in
linear light. Gains carry the ratio between channels; brightness carries the
common factor, with the top gain held at its maximum to keep headroom.

The solver assumes gain and brightness act linearly. They do not on a real
panel, nor on the simulated one, so the loop iterates. Brightness response is
learned by a secant estimate from the previous step.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

from calibrate_pro.calibration.closed_loop.controls import GAIN_NAMES
from calibrate_pro.calibration.closed_loop.plan import ClosedLoopPlan

SLOPE_RANGE = (0.2, 3.0)


@dataclass
class SolverMemory:
    """What the solver carries between steps."""

    slope: float = 1.0
    last_brightness: int | None = None
    last_luminance: float | None = None
    last_gain_effect: float = 1.0
    history: list[float] = field(default_factory=list)


def _clamp_step(plan: ClosedLoopPlan, name: str, current: int, wanted: float) -> int:
    bound = plan.bound(name)
    if bound is None:
        return current
    value = int(round(wanted))
    value = max(current - bound.max_step, min(current + bound.max_step, value))
    return max(bound.minimum, min(bound.maximum, value))


def _gain_maximum(plan: ClosedLoopPlan, name: str) -> int:
    bound = plan.bound(name)
    return bound.maximum if bound is not None else 100


def _learn_slope(memory: SolverMemory, brightness: int, luminance: float) -> None:
    """Update the brightness response exponent from the last move."""
    last_b, last_y = memory.last_brightness, memory.last_luminance
    if last_b is None or last_y is None or last_b == brightness or min(last_b, brightness) <= 0:
        return
    observed = luminance / last_y / memory.last_gain_effect
    if observed <= 0.0:
        return
    slope = math.log(observed) / math.log(brightness / last_b)
    if math.isfinite(slope):
        memory.slope = max(SLOPE_RANGE[0], min(SLOPE_RANGE[1], slope))


def _gain_effect(primaries: np.ndarray, amounts: np.ndarray, old: np.ndarray, new: np.ndarray) -> float:
    """Predicted luminance ratio from gain changes alone, gains taken as linear."""
    weights = primaries[1, :] * amounts
    before = float(np.sum(weights))
    after = float(np.sum(weights * new / np.maximum(old, 1e-9)))
    return after / before if before > 0.0 else 1.0


def solve_step(
    plan: ClosedLoopPlan,
    state: dict[str, int],
    primaries_xyz: np.ndarray,
    measured_white: np.ndarray,
    target_white: np.ndarray,
    memory: SolverMemory,
) -> dict[str, int]:
    """Return the next control values. Controls the plan omits stay put."""
    _learn_slope(memory, state.get("brightness", 0), float(measured_white[1]))
    current = np.linalg.solve(primaries_xyz, measured_white)
    wanted = np.linalg.solve(primaries_xyz, target_white)
    ratio = wanted / np.maximum(current, 1e-9)
    gain_max = [_gain_maximum(plan, name) for name in GAIN_NAMES]
    old = np.array([state.get(n, m) / m for n, m in zip(GAIN_NAMES, gain_max)])
    desired = old * ratio
    common = float(np.max(desired))
    proposal = dict(state)
    brightness = state.get("brightness")
    if plan.bound("brightness") is not None and brightness:
        target_b = brightness * common ** (1.0 / memory.slope)
        proposal["brightness"] = _clamp_step(plan, "brightness", brightness, target_b)
        achieved = (proposal["brightness"] / brightness) ** memory.slope
        desired = desired / achieved
    top = float(np.max(desired))
    if top > 1.0:
        desired = desired / top
    for index, name in enumerate(GAIN_NAMES):
        if name in state:
            wanted_value = desired[index] * gain_max[index]
            proposal[name] = _clamp_step(plan, name, state[name], wanted_value)
    new = np.array([proposal.get(n, m) / m for n, m in zip(GAIN_NAMES, gain_max)])
    memory.last_gain_effect = _gain_effect(primaries_xyz, current, old, new)
    memory.last_brightness = brightness
    memory.last_luminance = float(measured_white[1])
    return proposal


__all__ = ["SolverMemory", "solve_step"]
