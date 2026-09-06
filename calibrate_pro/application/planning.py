"""Turn a session's choices into the exact plan it will show and seal.

Two plans are built here. A publishing plan proposes a calibration target and
names the files a publish would create, requests no capability, and is valid
against any capability state because it writes nothing. An actuating plan pins
staged files by path and digest and requests the specific routes that will
change the display.

An actuating plan is built only when the bundle moves a visible output code. A
gamut clamp that leaves neutral grey alone yields a gamma table that changes
nothing, and a characterization already sitting on its target yields a cube that
changes nothing. Requesting a route for either would let the session report an
applied calibration the panel never received, so the refusal is raised here
where the operator can still be told why.

The digest is the seal. It is computed from the plan alone, so a plan the
operator saw and a plan a later step acts on are the same object or they are
visibly different.
"""

from __future__ import annotations

from dataclasses import replace

from calibrate_pro.actuation import canonical_plan_sha256
from calibrate_pro.application.actions import PRESET_TARGETS
from calibrate_pro.application.assets import AssetFormat, AssetRequest, GeneratedAssets
from calibrate_pro.application.staging import StagedBundle
from calibrate_pro.workflow import ApplyPlan, CalibrationMethod, CapabilityState, DwmLutKind

#: What a session generates unless a surface asks for more. Both anchor
#: artifacts are required downstream, and generating only what is required
#: keeps the sealed bundle small enough to hold in memory without question.
DEFAULT_ASSET_FORMATS: tuple[AssetFormat, ...] = (AssetFormat.ICC, AssetFormat.CUBE)


def target_for(preset_id: str) -> tuple[str, str, str]:
    """Read a preset's gamut, white point, and tone response."""
    target = PRESET_TARGETS.get(preset_id)
    if target is None:
        raise ValueError(f"unknown calibration preset: {preset_id!r}")
    return (target[0], target[1], target[2])


def output_filenames(request: AssetRequest) -> tuple[str, ...]:
    """Name every file the request would publish, in request order."""
    return tuple(request.filename_for(fmt) for fmt in request.formats)


def build_apply_plan(
    *,
    display_id: str,
    method: CalibrationMethod,
    preset_id: str,
    output_files: tuple[str, ...],
) -> ApplyPlan:
    """Build the proposal for one generated bundle."""
    gamut, white_point, tone_response = target_for(preset_id)
    return ApplyPlan(
        display_id=display_id,
        method=method,
        target_whitepoint=white_point,
        target_gamma=tone_response,
        target_gamut=gamut,
        output_files=output_files,
    )


class PlanNotActuatable(ValueError):
    """A bundle cannot be applied, and the message says which reason it is."""


def build_actuating_plan(
    *,
    display_id: str,
    method: CalibrationMethod,
    preset_id: str,
    output_files: tuple[str, ...],
    generated: GeneratedAssets,
    staged: StagedBundle,
    capabilities: CapabilityState,
) -> ApplyPlan:
    """Build the proposal that will change the display, or refuse and say why.

    A route is requested when the bundle moves an output code through it and the
    machine was detected to support it. The ICC rides along whenever a visible
    route is requested and profile writing is available, because a colour-managed
    application reads the profile and would otherwise disagree with the LUT the
    compositor is running.
    """
    if not isinstance(capabilities, CapabilityState):
        raise TypeError("capabilities must be a CapabilityState")
    if not isinstance(staged, StagedBundle):
        raise TypeError("staged must be a StagedBundle")
    if not isinstance(generated, GeneratedAssets):
        raise TypeError("generated must be a GeneratedAssets")

    wants_cube = generated.cube_changes_output
    wants_curve = generated.gamma_table_changes_output
    if not wants_cube and not wants_curve:
        raise PlanNotActuatable(
            "This calibration would not change a single output code. The characterization "
            f"for {generated.panel_name} already matches the selected target, so there is "
            "nothing to apply. The bundle can still be exported for a colour-managed "
            "application."
        )

    dwm_available = capabilities.dwm_lut_available and capabilities.dwm_state_capture_available
    use_cube = wants_cube and dwm_available
    use_curve = wants_curve and capabilities.vcgt_available
    if not use_cube and not use_curve:
        raise PlanNotActuatable(_unavailable_reason(wants_cube, wants_curve, capabilities))

    gamut, white_point, tone_response = target_for(preset_id)
    use_icc = capabilities.profile_write_available
    return ApplyPlan(
        display_id=display_id,
        method=method,
        target_whitepoint=white_point,
        target_gamma=tone_response,
        target_gamut=gamut,
        icc_profile_path=staged.icc_profile_path if use_icc else None,
        icc_profile_sha256=staged.icc_profile_sha256 if use_icc else None,
        vcgt_path=staged.vcgt_path if use_curve else None,
        vcgt_sha256=staged.vcgt_sha256 if use_curve else None,
        dwm_lut_path=staged.dwm_lut_path if use_cube else None,
        dwm_lut_kind=DwmLutKind.SDR if use_cube else None,
        dwm_lut_sha256=staged.dwm_lut_sha256 if use_cube else None,
        output_files=output_files,
    )


def _unavailable_reason(wants_cube: bool, wants_curve: bool, capabilities: CapabilityState) -> str:
    """Name the route this bundle needs and the reason it is not available.

    Reporting only that an apply is unavailable leaves the operator guessing
    between a driver that refuses the compositor and a display that refuses the
    gamma ramp, which are different problems with different repairs.
    """
    if wants_cube and not capabilities.dwm_lut_available:
        return "This calibration needs a compositor LUT, and none is available for this display."
    if wants_cube and not capabilities.dwm_state_capture_available:
        return (
            "This calibration needs a compositor LUT, and the prior LUT state cannot be "
            "captured, so applying it could not be undone."
        )
    if wants_curve and not capabilities.vcgt_available:
        return "This calibration needs a display gamma ramp, and this display does not accept one."
    return "No route that would change this display was detected."


def plan_digest(plan: ApplyPlan) -> str:
    """Seal a plan by content, using the same digest the actuator checks."""
    return canonical_plan_sha256(plan)


def restrict_assets(generated: GeneratedAssets, fmt: AssetFormat) -> GeneratedAssets:
    """Narrow a generated bundle to one format without regenerating anything.

    The narrowed value keeps the bytes that were already sealed, so a
    single-format export publishes the same artifact the full bundle would have
    published rather than a freshly computed one that might differ.
    """
    if fmt not in generated.assets:
        raise ValueError(f"bundle holds no {fmt.value} asset")
    request = replace(generated.request, formats=(fmt,))
    return replace(generated, request=request, assets={fmt: generated.assets[fmt]})


__all__ = [
    "DEFAULT_ASSET_FORMATS",
    "PlanNotActuatable",
    "build_actuating_plan",
    "build_apply_plan",
    "output_filenames",
    "plan_digest",
    "restrict_assets",
    "target_for",
]
