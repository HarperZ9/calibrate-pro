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

from calibrate_pro.application.assets import AssetGenerator, AssetRequest, GeneratedAssets
from calibrate_pro.application.declaration import DeclaredCharacterization
from calibrate_pro.application.measurement import MeasuredCharacterization
from calibrate_pro.application.planning import (
    DEFAULT_ASSET_FORMATS,
    build_apply_plan,
    output_filenames,
    plan_digest,
)
from calibrate_pro.application.refusals import incomplete_setup, no_measurement
from calibrate_pro.application.results import GenerationResult
from calibrate_pro.application.session import SessionState
from calibrate_pro.application.target_selection import is_target_id
from calibrate_pro.panels.database import GENERIC_PANEL_KEY
from calibrate_pro.panels.panel_types import PanelCharacterization
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


def _measurement_for(state: SessionState, method: CalibrationMethod) -> MeasuredCharacterization | None:
    """Decide which characterization this bundle is allowed to be built from.

    The measured method must hand the generator a run of the display that is
    selected right now, and it refuses rather than falling back. A fallback is
    what would make the failure invisible: the session would keep the word
    measured on the button it was asked from and publish an estimate.

    The sensorless method passes None even when a run is held, so choosing it
    after measuring produces a sensorless bundle labeled as one.
    """
    if method is not CalibrationMethod.MEASURED:
        return None
    if not state.measurement_matches_selection:
        raise no_measurement()
    return state.measured_characterization


def _declaration_for(state: SessionState, method: CalibrationMethod) -> DeclaredCharacterization | None:
    """Decide whether this bundle is built from what the display declared.

    Only the sensorless method reads a declaration, and only while the session
    holds one for the display selected right now. The measured method passes
    None because a reading of the unit answers the question a descriptor only
    claims to, and handing the generator both would ask it to build from two
    descriptions of the same panel.

    Absence is not a refusal here. A sensorless session with no declaration
    builds from the panel record the way it always did, which is the path a
    matched display and an accepted generic record both take.
    """
    if method is not CalibrationMethod.SENSORLESS:
        return None
    if not state.declaration_matches_selection:
        return None
    return state.declared_characterization


def verification_panel(state: SessionState, generator: AssetGenerator) -> PanelCharacterization:
    """The panel record a bundle from this session was built from.

    Verification reads this rather than resolving the panel key. The key names
    the record the session started from, and two of the three build paths
    replace that record before the generator sees it, so a session that
    accepted a declaration and then verified against its key would report
    figures for a panel no correction was generated for.

    Those figures would look correct, which is what makes reading the key the
    dangerous version of this rather than the merely wrong one. The generic
    record is exact sRGB, so it scores zero against an sRGB reference whatever
    the display in front of the operator actually does, and a report built that
    way says the calibration is perfect on every display it is run against.

    The precedence is the generator's own and it is written here beside the two
    functions that feed the generator, so a fourth build path cannot be added
    without this seeing it.
    """
    if state.measurement_matches_selection and state.measured_characterization is not None:
        return state.measured_characterization.panel
    if state.declaration_matches_selection and state.declared_characterization is not None:
        return state.declared_characterization.panel
    panel, _kind = generator.resolve_panel(state.selected_panel_key or GENERIC_PANEL_KEY)
    return panel


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
    # ``preset_id is None`` is spelled out rather than left to the target
    # test. ``is_target_id(None)`` is False, so the two read the same at
    # runtime, but only the identity test narrows the type for a checker.
    if display_id is None or method is None or preset_id is None:
        raise incomplete_setup()
    if not is_target_id(preset_id):
        raise incomplete_setup()
    request = AssetRequest(
        display_id=display_id,
        panel_key=state.selected_panel_key or GENERIC_PANEL_KEY,
        preset_id=preset_id,
        formats=DEFAULT_ASSET_FORMATS,
        lut_size=lut_size,
    )
    generated = generator.generate(
        request,
        measured=_measurement_for(state, method),
        declared=_declaration_for(state, method),
    )
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
        gamut_reach=generated.gamut_reach,
    )
    return result, plan


__all__ = ["PlanBuilder", "generate_bundle", "publishing_plan"]
