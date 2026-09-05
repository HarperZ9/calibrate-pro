"""Evidence and actuation boundaries for measured display calibration.

This module deliberately keeps patch presentation and hardware measurement
behind injected callables.  A run may become destructive only after its exact
display identity, complete verification set, LUT digest, and direct-correction
improvement have all been checked.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

REQUIRED_COLORCHECKER_PATCHES = 24
MINIMUM_ABSOLUTE_DELTA_E_IMPROVEMENT = 0.5
MINIMUM_RELATIVE_DELTA_E_IMPROVEMENT = 0.10


@dataclass(frozen=True)
class DisplayTarget:
    device_name: str
    device_id: str
    geometry: tuple[int, int, int, int]
    name: str


@dataclass(frozen=True)
class PatchResult:
    name: str
    requested_rgb: tuple[float, float, float]
    displayed_rgb: tuple[float, float, float]
    xyz: tuple[float, float, float]
    delta_e: float


@dataclass(frozen=True)
class VerificationSummary:
    valid_patches: int
    delta_e_average: float
    delta_e_maximum: float
    patch_results: tuple[PatchResult, ...]


@dataclass(frozen=True)
class MeasuredCalibrationRun:
    target: DisplayTarget
    baseline: VerificationSummary
    direct_correction: VerificationSummary
    lut_path: str
    lut_sha256: str
    receipt_path: str
    evidence_grade: str


@dataclass(frozen=True)
class ApplyDecision:
    target: DisplayTarget
    applied: bool
    verified: bool
    rolled_back: bool
    reason: str
    post_apply: VerificationSummary | None = None


class DwmPort(Protocol):
    def target_for(self, device_name: str) -> DisplayTarget: ...

    def has_active_lut(self, device_name: str) -> bool: ...

    def apply(self, device_name: str, lut_path: str) -> bool: ...

    def unload(self, device_name: str) -> bool: ...


def select_exact_display(
    displays: Iterable[DisplayTarget],
    device_name: str,
    geometry: tuple[int, int, int, int],
) -> DisplayTarget:
    matches = [display for display in displays if display.device_name == device_name]
    if len(matches) != 1:
        raise ValueError(f"expected exactly one display named {device_name!r}; found {len(matches)}")
    selected = matches[0]
    if selected.geometry != geometry:
        raise ValueError(
            f"display geometry changed for {device_name}: expected {geometry}, found {selected.geometry}"
        )
    if not selected.device_id:
        raise ValueError(f"display identity is unavailable for {device_name}")
    return selected


def target_hdr_enabled(states: Iterable[object], device_name: str) -> bool:
    """Return current HDR mode for one exact display, never a global flag."""
    matches = [state for state in states if getattr(state, "device_path", None) == device_name]
    if len(matches) != 1:
        raise ValueError(f"expected exactly one HDR state for {device_name!r}; found {len(matches)}")
    # A state carrying no flag is an unanswered question, and bool() would read
    # it back as the answer no. Raising keeps the two apart, the way the
    # identity check above does.
    hdr_enabled = getattr(matches[0], "hdr_enabled", None)
    if not isinstance(hdr_enabled, bool):
        raise ValueError(f"HDR state for {device_name!r} carries no hdr_enabled flag")
    return hdr_enabled


def require_device_id_token(target: DisplayTarget, token: str) -> None:
    """Bind a generic Windows monitor label to a stable PnP identity token."""
    if not token or token.casefold() not in target.device_id.casefold():
        raise ValueError(
            f"display identity token {token!r} is absent from {target.device_id!r}"
        )


def _validate_summary(summary: VerificationSummary, label: str) -> None:
    if summary.valid_patches != REQUIRED_COLORCHECKER_PATCHES:
        raise ValueError(
            f"{label} requires {REQUIRED_COLORCHECKER_PATCHES} valid patches; "
            f"found {summary.valid_patches}"
        )
    if len(summary.patch_results) != REQUIRED_COLORCHECKER_PATCHES:
        raise ValueError(
            f"{label} requires {REQUIRED_COLORCHECKER_PATCHES} patch receipts; "
            f"found {len(summary.patch_results)}"
        )
    metrics = [summary.delta_e_average, summary.delta_e_maximum]
    metrics.extend(result.delta_e for result in summary.patch_results)
    if not all(math.isfinite(value) and value >= 0.0 for value in metrics):
        raise ValueError(f"{label} contains an invalid Delta E value")
    for result in summary.patch_results:
        values = (*result.requested_rgb, *result.displayed_rgb, *result.xyz)
        if not all(math.isfinite(value) for value in values):
            raise ValueError(f"{label} patch {result.name!r} contains a non-finite reading")


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _meaningfully_improves(
    candidate: VerificationSummary,
    baseline: VerificationSummary,
) -> bool:
    required_average_gain = max(
        MINIMUM_ABSOLUTE_DELTA_E_IMPROVEMENT,
        baseline.delta_e_average * MINIMUM_RELATIVE_DELTA_E_IMPROVEMENT,
    )
    return (
        candidate.delta_e_average <= baseline.delta_e_average - required_average_gain
        and candidate.delta_e_maximum < baseline.delta_e_maximum
    )


def validate_run_evidence(run: MeasuredCalibrationRun) -> None:
    _validate_summary(run.baseline, "baseline")
    _validate_summary(run.direct_correction, "direct correction")
    if run.evidence_grade != "research_fallback_oled_matrix":
        raise ValueError(f"unexpected evidence grade: {run.evidence_grade!r}")

    lut_path = Path(run.lut_path)
    receipt_path = Path(run.receipt_path)
    if not lut_path.is_file() or not receipt_path.is_file():
        raise ValueError("LUT or receipt artifact is missing")
    actual_digest = sha256_file(lut_path)
    if actual_digest != run.lut_sha256:
        raise ValueError("LUT digest does not match the measured run")
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    if receipt.get("lut_sha256") != actual_digest:
        raise ValueError("receipt LUT digest does not match the LUT artifact")


def apply_and_verify(
    run: MeasuredCalibrationRun,
    dwm: DwmPort,
    verifier: Callable[[], VerificationSummary],
) -> ApplyDecision:
    """Apply one run to its exact display and roll back on weak evidence."""

    validate_run_evidence(run)
    current_target = dwm.target_for(run.target.device_name)
    if current_target != run.target:
        raise ValueError("display identity or geometry changed before apply")
    if dwm.has_active_lut(run.target.device_name):
        raise ValueError("target already has an active DWM LUT")
    if not _meaningfully_improves(run.direct_correction, run.baseline):
        raise ValueError("direct correction did not meaningfully improve over baseline")
    if not dwm.apply(run.target.device_name, run.lut_path):
        return ApplyDecision(
            target=run.target,
            applied=False,
            verified=False,
            rolled_back=False,
            reason="DWM LUT apply failed",
        )

    try:
        post_apply = verifier()
        _validate_summary(post_apply, "post-apply")
        improved = _meaningfully_improves(post_apply, run.baseline)
    except Exception as exc:
        dwm.unload(run.target.device_name)
        return ApplyDecision(
            target=run.target,
            applied=True,
            verified=False,
            rolled_back=True,
            reason=f"post-apply verification failed: {exc}",
        )

    if not improved:
        dwm.unload(run.target.device_name)
        return ApplyDecision(
            target=run.target,
            applied=True,
            verified=False,
            rolled_back=True,
            reason="post-apply Delta E did not meaningfully improve over baseline",
            post_apply=post_apply,
        )

    return ApplyDecision(
        target=run.target,
        applied=True,
        verified=True,
        rolled_back=False,
        reason="post-apply measurement meaningfully improved over baseline",
        post_apply=post_apply,
    )
