"""Turn a session's choices into the exact plan it will show and seal.

A plan built here proposes a calibration target and names the files a publish
would create. It carries no ICC association, no gamma ramp, and no DWM LUT,
because this phase writes nothing to a display. That is what makes the plan
valid against any capability state: it requests no capability at all.

The digest is the seal. It is computed from the plan alone, so a plan the
operator saw and a plan a later step acts on are the same object or they are
visibly different.
"""

from __future__ import annotations

from dataclasses import replace

from calibrate_pro.actuation import canonical_plan_sha256
from calibrate_pro.application.actions import PRESET_TARGETS
from calibrate_pro.application.assets import AssetFormat, AssetRequest, GeneratedAssets
from calibrate_pro.workflow import ApplyPlan, CalibrationMethod

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
    "build_apply_plan",
    "output_filenames",
    "plan_digest",
    "restrict_assets",
    "target_for",
]
