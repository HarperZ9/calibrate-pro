"""Producing a sealed calibration bundle from a session's choices.

Generation is the step that turns three selections into bytes. It reads the
display, the method, and the target out of the session, asks the generator for
the artifacts, builds the plan those artifacts belong to, and seals the pair
together with the capability generation current at the time.

Sealing here rather than at the call site is deliberate. The digest, the bytes,
and the capability generation are written in one place, so a later step cannot
find a plan whose seal was recorded without the bundle it describes.

What the plan requests is the one decision left to the caller. A session that
only publishes files builds a plan requesting nothing; a session composed to
apply builds one that pins staged assets and names the routes it will use. The
plan builder is passed in so both go through this same sealing step rather than
growing a second one.
"""

from __future__ import annotations

from collections.abc import Callable

from calibrate_pro.application.actions import PRESET_TARGETS
from calibrate_pro.application.assets import AssetGenerator, AssetRequest, GeneratedAssets
from calibrate_pro.application.planning import (
    DEFAULT_ASSET_FORMATS,
    build_apply_plan,
    output_filenames,
    plan_digest,
)
from calibrate_pro.application.refusals import incomplete_setup
from calibrate_pro.application.results import GenerationResult
from calibrate_pro.application.session import SessionState
from calibrate_pro.panels.database import GENERIC_PANEL_KEY
from calibrate_pro.workflow import ApplyPlan, CalibrationMethod

#: Build the plan one generated bundle belongs to. The publishing builder
#: ignores the bundle because it requests nothing; an applying builder reads it
#: to decide which routes would change an output code.
PlanBuilder = Callable[[str, CalibrationMethod, str, tuple[str, ...], GeneratedAssets], ApplyPlan]


def publishing_plan(
    display_id: str,
    method: CalibrationMethod,
    preset_id: str,
    filenames: tuple[str, ...],
    generated: GeneratedAssets,
) -> ApplyPlan:
    """Build the plan that names files and requests no capability."""
    _ = generated
    return build_apply_plan(
        display_id=display_id,
        method=method,
        preset_id=preset_id,
        output_files=filenames,
    )


def generate_bundle(
    state: SessionState,
    generator: AssetGenerator,
    lut_size: int,
    *,
    plan_builder: PlanBuilder | None = None,
) -> tuple[GenerationResult, ApplyPlan]:
    """Generate and seal one bundle, returning what to report and what to hold."""
    display_id = state.selected_display_id
    method = state.selected_method
    preset_id = state.selected_preset_id
    # ``preset_id is None`` is spelled out rather than left to the membership
    # test. None is not a key of PRESET_TARGETS, so the two read the same at
    # runtime, but only the identity test narrows the type for a checker.
    if display_id is None or method is None or preset_id is None:
        raise incomplete_setup()
    if preset_id not in PRESET_TARGETS:
        raise incomplete_setup()
    request = AssetRequest(
        display_id=display_id,
        panel_key=state.selected_panel_key or GENERIC_PANEL_KEY,
        preset_id=preset_id,
        formats=DEFAULT_ASSET_FORMATS,
        lut_size=lut_size,
    )
    generated = generator.generate(request)
    filenames = output_filenames(request)
    build = publishing_plan if plan_builder is None else plan_builder
    plan = build(display_id, method, preset_id, filenames, generated)
    digest = plan_digest(plan)
    state.generated = generated
    state.sealed_plan_sha256 = digest
    state.sealed_capability_generation = state.capability_generation
    state.sealed_plan_actuatable = False
    state.confirmation_state = "none"
    state.fake_applied_plan_sha256 = None
    state.applied_plan_sha256 = None
    state.verification_evidence = None
    result = GenerationResult(
        plan_sha256=digest,
        filenames=filenames,
        panel_name=generated.panel_name,
        characterization_kind=generated.characterization_kind,
        evidence_kind=generated.evidence_kind,
    )
    return result, plan


__all__ = ["PlanBuilder", "generate_bundle", "publishing_plan"]
