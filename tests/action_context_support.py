"""The session state a resolver test starts from, with every gate open.

Each lane's tests close one predicate at a time and assert the action they are
about goes with it. That only means something if the baseline had every other
predicate open, so the baseline is written once here rather than per lane. A
field added to `ActionContext` and not added here fails construction, which is
what keeps a new predicate from arriving with nothing exercising it.

Nothing in this baseline describes a real machine. It describes the most
qualified session the resolver can be handed, which is the only starting point
from which a single closed predicate is the reason an action closed.
"""

from __future__ import annotations

from dataclasses import replace

from calibrate_pro.application.actions import ActionContext
from calibrate_pro.application.contracts import CharacterizationKind, EvidenceKind
from calibrate_pro.workflow import CalibrationMethod, WorkflowStage


def action_context(**changes: object) -> ActionContext:
    """A fully qualified session, with the named fields replaced."""
    context = ActionContext(
        stage=WorkflowStage.PREVIEW,
        runtime_mode="source",
        fake_acceptance=False,
        selected_display_id="display-1",
        characterization_kind=CharacterizationKind.MATCHED,
        selected_method=CalibrationMethod.SENSORLESS,
        target_valid=True,
        selected_preset_id="calibration.preset.srgb_web",
        target_hdr=False,
        generated_asset_kinds=frozenset({"ICC", "CUBE"}),
        sealed_plan_sha256="a" * 64,
        sealed_plan_actuatable=True,
        confirmation_state="live",
        fake_applied_plan_sha256=None,
        applied_plan_sha256=None,
        capability_generation=7,
        sealed_capability_generation=7,
        verification_evidence=EvidenceKind.ESTIMATED,
        export_source_ready=True,
        configured_export_directory_valid=True,
        available_export_formats=frozenset({"cube", "3dlut", "png", "icc", "mpv", "obs"}),
        selected_profile_reparsed=True,
        validated_import_ready=True,
        supported_vcp_codes=frozenset({0x10, 0x12}),
        staged_vcp_codes=frozenset({0x10}),
        diagnostic_bundle_preview_live=True,
        journal_ready=True,
        physical_apply_qualified=True,
        measured_qualified=True,
        monitor_controls_qualified=True,
        monitor_writes_qualified=True,
        system_profiles_qualified=True,
        system_profile_writes_qualified=True,
        selected_profile_installed=True,
        restorable_system_profiles=True,
        switchable_system_profiles=True,
    )
    return replace(context, **changes)


__all__ = ["action_context"]
