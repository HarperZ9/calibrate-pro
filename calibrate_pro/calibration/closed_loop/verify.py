"""Held-out verification after the hardware loop.

The loop tunes on full white and characterizes on full primaries and black.
Verification uses none of those patches: grays and colours at other levels, so
a controller that overfits the white it tuned on is caught here. Patches whose
target colour lies outside the panel's measured primaries are listed and not
graded, because no control can reach them.
"""

from __future__ import annotations

from dataclasses import dataclass

from calibrate_pro.calibration.closed_loop import gamut
from calibrate_pro.calibration.closed_loop.controls import RGB
from calibrate_pro.calibration.closed_loop.intent import AchievableTarget
from calibrate_pro.calibration.closed_loop.measure import Probe, read_patch
from calibrate_pro.calibration.closed_loop.metrics import delta_e_relative, target_patch_xy, target_patch_xyz
from calibrate_pro.verification.provenance import EvidenceKind, MetricValue

#: Slack, in xy cross-product units, for a target colour on the edge of the
#: measured panel triangle. A noisy characterization pulls the measured
#: vertices inward, and a patch on a vertex is still reachable.
GAMUT_MARGIN = 0.002

HELD_OUT: tuple[tuple[str, str, RGB], ...] = (
    ("gray 25", "gray", (0.25, 0.25, 0.25)),
    ("gray 50", "gray", (0.5, 0.5, 0.5)),
    ("gray 75", "gray", (0.75, 0.75, 0.75)),
    ("red 75", "color", (0.75, 0.0, 0.0)),
    ("green 75", "color", (0.0, 0.75, 0.0)),
    ("blue 75", "color", (0.0, 0.0, 0.75)),
    ("cyan 75", "color", (0.0, 0.75, 0.75)),
    ("magenta 75", "color", (0.75, 0.0, 0.75)),
    ("yellow 75", "color", (0.75, 0.75, 0.0)),
    ("skin", "color", (0.8, 0.6, 0.5)),
)


@dataclass(frozen=True)
class PatchResult:
    name: str
    patch_class: str
    delta_e: MetricValue
    tolerance: float
    graded: bool
    passed: bool


@dataclass(frozen=True)
class Verification:
    patches: tuple[PatchResult, ...]
    passed: bool
    residual_lut: str = "not built in this slice"

    def worst(self, patch_class: str) -> float:
        values = [p.delta_e.value or 0.0 for p in self.patches if p.patch_class == patch_class and p.graded]
        return max(values) if values else 0.0


def _tolerance(target: AchievableTarget, patch_class: str) -> float:
    tolerances = target.intent.tolerances
    return tolerances.gray_de2000 if patch_class == "gray" else tolerances.color_de2000


def verify_held_out(
    probe: Probe,
    target: AchievableTarget,
    panel_primaries_xy: gamut.Triangle,
    repeats: int,
    evidence: EvidenceKind,
) -> Verification:
    """Measure the held-out set and grade each patch against its class bound."""
    source = probe.port.identity()
    results = []
    for name, patch_class, rgb in HELD_OUT:
        graded = patch_class == "gray" or gamut.contains(panel_primaries_xy, target_patch_xy(target, rgb), GAMUT_MARGIN)
        measured = read_patch(probe, rgb, repeats)
        value = delta_e_relative(target, measured, target_patch_xyz(target, rgb))
        tolerance = _tolerance(target, patch_class)
        metric = MetricValue(value, "dE2000", evidence, source)
        results.append(PatchResult(name, patch_class, metric, tolerance, graded, (not graded) or value <= tolerance))
    return Verification(tuple(results), all(r.passed for r in results))


__all__ = ["HELD_OUT", "PatchResult", "Verification", "verify_held_out"]
