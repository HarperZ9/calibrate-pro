from __future__ import annotations

import copy
import json
from dataclasses import fields, replace

import pytest

from calibrate_pro.application.actions import (
    ActionClassification,
    ActionContext,
    ActionDisposition,
    ActionRegistry,
)
from calibrate_pro.application.contracts import CharacterizationKind, EvidenceKind
from calibrate_pro.workflow import CalibrationMethod, WorkflowStage

# fmt: off
EXPECTED_ACTION_IDS = {
    "application.exit", "window.hide_or_minimize", "window.show", "window.toggle_visibility",
    "navigation.dashboard", "navigation.calibrate", "navigation.verify", "navigation.profiles",
    "navigation.ddc", "navigation.settings", "help.about", "onboarding.complete",
    "diagnostics.folder.open", "diagnostics.bundle.preview", "diagnostics.bundle.create",
    "display.detect", "calibration.open_for_display", "panel_profile.dialog.open",
    "panel_profile.edid.select_display", "panel_profile.edid.create",
    "panel_profile.import.choose", "panel_profile.import",
    "display.restore_defaults", "profile.install", "display.hdr_status",
    "display.characterization.use_generic", "workflow.select_display",
    "calibration.method.sensorless", "calibration.method.measured", "calibration.method.hybrid",
    "calibration.target.gamut", "calibration.target.whitepoint", "calibration.target.custom_cct",
    "calibration.target.gamma", "calibration.target.hdr",
    "calibration.preset.srgb_web", "calibration.preset.rec709", "calibration.preset.dci_p3",
    "calibration.preset.hdr10", "calibration.preset.photography",
    "calibration.generate", "calibration.preview", "calibration.confirm_plan",
    "calibration.decline_plan", "fake_acceptance.apply", "calibration.all",
    "verification.sensorless", "verification.measured", "report.save",
    "export.active.cube", "export.active.3dlut", "export.active.png", "export.active.icc",
    "export.active.mpv", "export.active.obs",
    "profile.list.refresh", "profile.inspect", "profile.rename", "profile.generate_all",
    "profile.activate", "profile.export", "profile.delete", "patterns.open",
    "ddc.stage.brightness", "ddc.stage.contrast", "ddc.stage.red_gain",
    "ddc.stage.green_gain", "ddc.stage.blue_gain", "ddc.stage.red_black_level",
    "ddc.stage.green_black_level", "ddc.stage.blue_black_level",
    "ddc.unsupported.image_mode", "ddc.unsupported.color_preset", "ddc.unsupported.gamma",
    "ddc.unsupported.factory_color_reset", "ddc.read_current", "ddc.restore_defaults",
    "ddc.raw_read", "ddc.raw_write", "ddc.apply",
    "settings.default_target", "settings.lut_size", "settings.output_directory", "settings.hdr",
    "settings.startup", "settings.minimize_to_tray", "settings.oled_automation",
    "settings.per_app.enabled", "settings.per_app.rules", "settings.argyll_path",
    "settings.panel_profiles_path", "tray.switch_profile", "measurement.live.toggle",
}

EXPECTED_SURFACES_BY_ACTION = {
    "application.exit": {"menu.file.exit", "tray.exit"},
    "window.hide_or_minimize": {"shortcut.escape"},
    "window.show": {"tray.show"},
    "window.toggle_visibility": {"tray.icon.activate"},
    "navigation.dashboard": {"sidebar.dashboard", "menu.view.dashboard"},
    "navigation.calibrate": {"sidebar.calibrate", "menu.view.calibrate"},
    "navigation.verify": {"sidebar.verify", "menu.view.verify"},
    "navigation.profiles": {"sidebar.profiles", "menu.view.profiles"},
    "navigation.ddc": {"sidebar.ddc", "menu.view.ddc"},
    "navigation.settings": {"sidebar.settings", "menu.view.settings"},
    "help.about": {"menu.help.about"},
    "onboarding.complete": {"dialog.onboarding.get_started"},
    "diagnostics.folder.open": {"settings.diagnostics.open_folder"},
    "diagnostics.bundle.preview": {"settings.diagnostics.preview_bundle"},
    "diagnostics.bundle.create": {"settings.diagnostics.create_bundle"},
    "display.detect": {
        "dashboard.refresh", "menu.view.refresh", "menu.display.detect", "dialog.add_display.scan"
    },
    "calibration.open_for_display": {"dashboard.display_card.calibrate"},
    "panel_profile.dialog.open": {"dashboard.add_display"},
    "panel_profile.edid.select_display": {"dialog.add_display.edid.display"},
    "panel_profile.edid.create": {"dialog.add_display.edid.create"},
    "panel_profile.import.choose": {"dialog.add_display.import.choose"},
    "panel_profile.import": {"dialog.add_display.import.commit"},
    "display.restore_defaults": {"menu.display.restore_defaults", "tray.restore_defaults"},
    "profile.install": {"menu.display.install_profile"},
    "display.hdr_status": {"menu.tools.hdr_status"},
    "display.characterization.use_generic": {"dashboard.characterization.use_generic"},
    "workflow.select_display": {"calibrate.display", "verify.display", "ddc.display"},
    "calibration.method.sensorless": {"calibrate.method.sensorless"},
    "calibration.method.measured": {"calibrate.method.measured"},
    "calibration.method.hybrid": {"calibrate.method.hybrid"},
    "calibration.target.gamut": {"calibrate.target.gamut"},
    "calibration.target.whitepoint": {"calibrate.target.whitepoint"},
    "calibration.target.custom_cct": {"calibrate.target.custom_cct"},
    "calibration.target.gamma": {"calibrate.target.gamma"},
    "calibration.target.hdr": {"calibrate.target.hdr"},
    "calibration.preset.srgb_web": {"calibrate.preset.srgb_web"},
    "calibration.preset.rec709": {"calibrate.preset.rec709"},
    "calibration.preset.dci_p3": {"calibrate.preset.dci_p3"},
    "calibration.preset.hdr10": {"calibrate.preset.hdr10"},
    "calibration.preset.photography": {"calibrate.preset.photography"},
    "calibration.generate": {"calibrate.generate"},
    "calibration.preview": {"calibrate.preview"},
    "calibration.confirm_plan": {"dialog.plan.accept"},
    "calibration.decline_plan": {"dialog.plan.decline"},
    "fake_acceptance.apply": set(),
    "calibration.all": {"dashboard.calibrate_all", "menu.file.calibrate_all", "tray.calibrate_all"},
    "verification.sensorless": {"verify.run_sensorless"},
    "verification.measured": {"verify.run_measured"},
    "report.save": {"verify.export_report"},
    "export.active.cube": {"menu.export.cube"},
    "export.active.3dlut": {"menu.export.3dlut"},
    "export.active.png": {"menu.export.png"},
    "export.active.icc": {"menu.export.icc"},
    "export.active.mpv": {"menu.export.mpv"},
    "export.active.obs": {"menu.export.obs"},
    "profile.list.refresh": {"profiles.refresh"},
    "profile.inspect": {"profiles.card.inspect"},
    "profile.rename": {"profiles.rename"},
    "profile.generate_all": {"profiles.generate_all"},
    "profile.activate": {"profiles.card.activate"},
    "profile.export": {"profiles.card.export"},
    "profile.delete": {"profiles.card.delete"},
    "patterns.open": {"menu.tools.patterns"},
    "ddc.stage.brightness": {"ddc.brightness"},
    "ddc.stage.contrast": {"ddc.contrast"},
    "ddc.stage.red_gain": {"ddc.red_gain"},
    "ddc.stage.green_gain": {"ddc.green_gain"},
    "ddc.stage.blue_gain": {"ddc.blue_gain"},
    "ddc.stage.red_black_level": {"ddc.red_black_level"},
    "ddc.stage.green_black_level": {"ddc.green_black_level"},
    "ddc.stage.blue_black_level": {"ddc.blue_black_level"},
    "ddc.unsupported.image_mode": {"ddc.image_mode"},
    "ddc.unsupported.color_preset": {"ddc.color_preset"},
    "ddc.unsupported.gamma": {"ddc.gamma"},
    "ddc.unsupported.factory_color_reset": {"ddc.factory_color_reset"},
    "ddc.read_current": {"ddc.read_current"},
    "ddc.restore_defaults": {"ddc.restore_defaults"},
    "ddc.raw_read": {"ddc.raw_read"},
    "ddc.raw_write": {"ddc.raw_write"},
    "ddc.apply": {"ddc.apply"},
    "settings.default_target": {"settings.default_target"},
    "settings.lut_size": {"settings.lut_size"},
    "settings.output_directory": {"settings.output_directory", "settings.output_directory.browse"},
    "settings.hdr": {"settings.hdr"},
    "settings.startup": {"settings.startup"},
    "settings.minimize_to_tray": {"settings.minimize_to_tray"},
    "settings.oled_automation": {"settings.oled_automation"},
    "settings.per_app.enabled": {"settings.per_app.enabled"},
    "settings.per_app.rules": {
        "settings.per_app.table", "settings.per_app.add", "settings.per_app.remove",
        "settings.per_app.profile", "settings.per_app.action"
    },
    "settings.argyll_path": {"settings.argyll_path", "settings.argyll_path.browse"},
    "settings.panel_profiles_path": {"settings.panel_profiles_path", "settings.panel_profiles_path.browse"},
    "tray.switch_profile": {"tray.profile.dynamic"},
    "measurement.live.toggle": {"dashboard.live_sensor.toggle"},
}
# fmt: on


def test_default_registry_matches_complete_initial_action_census():
    registry = ActionRegistry.load_default()

    assert registry.action_ids == frozenset(EXPECTED_ACTION_IDS)
    assert registry.surfaces_by_action == {
        action_id: frozenset(surfaces) for action_id, surfaces in EXPECTED_SURFACES_BY_ACTION.items()
    }


def _manifest_record(action_id: str = "test.action", surface: str = "test.surface") -> dict[str, object]:
    return {
        "action_id": action_id,
        "surfaces": [surface],
        "classification": "read_only",
        "required_stages": [stage.value for stage in WorkflowStage],
        "required_capabilities": [],
        "source_policy": "enabled",
        "frozen_policy": "enabled",
        "handler": "test_handler",
        "required_modules": ["calibrate_pro.application.actions"],
        "required_resources": ["resources/action-capabilities.json"],
        "receipt_required": True,
        "evidence_modes": ["read_only"],
        "unavailable_disposition": "disabled",
        "unavailable_reason": "The test action is unavailable.",
    }


def _manifest_bytes(*records: dict[str, object]) -> bytes:
    return json.dumps(
        {"schema_version": 1, "default": "disabled", "actions": list(records)},
        separators=(",", ":"),
    ).encode("utf-8")


def _context(**changes: object) -> ActionContext:
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
        confirmation_state="live",
        capability_generation=7,
        sealed_capability_generation=7,
        verification_evidence=EvidenceKind.ESTIMATED,
        export_source_ready=True,
        configured_export_directory_valid=True,
        available_export_formats=frozenset({"cube", "3dlut", "png", "icc", "mpv", "obs"}),
        selected_profile_reparsed=True,
        validated_import_ready=True,
        supported_vcp_codes=frozenset({0x10, 0x12}),
        diagnostic_bundle_preview_live=True,
        journal_ready=True,
        physical_apply_qualified=True,
        measured_qualified=True,
    )
    return replace(context, **changes)


def test_manifest_root_and_action_schema_are_exact_and_sequences_are_frozen():
    registry = ActionRegistry.from_json_bytes(_manifest_bytes(_manifest_record()))
    spec = registry._specs_by_id["test.action"]

    assert tuple(field.name for field in fields(spec)) == (
        "action_id",
        "surfaces",
        "classification",
        "required_stages",
        "required_capabilities",
        "source_policy",
        "frozen_policy",
        "handler",
        "required_modules",
        "required_resources",
        "receipt_required",
        "evidence_modes",
        "unavailable_disposition",
        "unavailable_reason",
    )
    assert spec.surfaces == ("test.surface",)
    assert spec.required_stages == tuple(WorkflowStage)
    assert spec.required_modules == ("calibrate_pro.application.actions",)
    assert spec.required_resources == ("resources/action-capabilities.json",)
    assert spec.classification is ActionClassification.READ_ONLY


@pytest.mark.parametrize(
    "payload",
    [
        b'{"schema_version":1,"default":"disabled","default":"disabled","actions":[]}',
        b'{"schema_version":true,"default":"disabled","actions":[]}',
        b'{"schema_version":1,"default":"disabled","actions":[],"extra":null}',
        b'{"schema_version":1,"default":"enabled","actions":[]}',
        b'{"schema_version":1,"default":"disabled","actions":{}}',
        b"\xff",
    ],
)
def test_manifest_rejects_duplicate_keys_wrong_exact_types_and_root_drift(payload: bytes):
    with pytest.raises((UnicodeDecodeError, ValueError)):
        ActionRegistry.from_json_bytes(payload)


def test_manifest_rejects_duplicate_action_and_surface_ids():
    duplicate_action = _manifest_record()
    duplicate_surface = _manifest_record("test.other")

    with pytest.raises(ValueError, match="duplicate action_id"):
        ActionRegistry.from_json_bytes(_manifest_bytes(duplicate_action, copy.deepcopy(duplicate_action)))
    with pytest.raises(ValueError, match="duplicate surface"):
        ActionRegistry.from_json_bytes(_manifest_bytes(duplicate_action, duplicate_surface))


@pytest.mark.parametrize(
    ("field_name", "invalid_value"),
    [
        ("classification", "network_write"),
        ("required_stages", ["unknown"]),
        ("source_policy", "maybe"),
        ("frozen_policy", "maybe"),
        ("evidence_modes", ["simulated"]),
        ("unavailable_disposition", "conditional"),
    ],
)
def test_manifest_rejects_unknown_enum_values(field_name: str, invalid_value: object):
    record = _manifest_record()
    record[field_name] = invalid_value

    with pytest.raises(ValueError):
        ActionRegistry.from_json_bytes(_manifest_bytes(record))


def test_manifest_rejects_missing_and_extra_action_keys():
    missing = _manifest_record()
    missing.pop("handler")
    extra = _manifest_record()
    extra["success_contract"] = "invented"

    with pytest.raises(ValueError, match="exact keys"):
        ActionRegistry.from_json_bytes(_manifest_bytes(missing))
    with pytest.raises(ValueError, match="exact keys"):
        ActionRegistry.from_json_bytes(_manifest_bytes(extra))


@pytest.mark.parametrize(
    ("field_name", "invalid_value"),
    [
        ("required_modules", ["calibrate_pro.*"]),
        ("required_modules", ["calibrate_pro..actions"]),
        ("required_resources", ["../private.json"]),
    ],
)
def test_manifest_rejects_wildcards_and_parent_traversal(field_name: str, invalid_value: object):
    record = _manifest_record()
    record[field_name] = invalid_value

    with pytest.raises(ValueError):
        ActionRegistry.from_json_bytes(_manifest_bytes(record))


def test_manifest_rejects_enabled_action_without_handler_and_receipt_without_contract():
    missing_handler = _manifest_record()
    missing_handler["handler"] = ""
    missing_contract = _manifest_record()
    missing_contract["evidence_modes"] = []

    with pytest.raises(ValueError, match="handler"):
        ActionRegistry.from_json_bytes(_manifest_bytes(missing_handler))
    with pytest.raises(ValueError, match="typed success contract"):
        ActionRegistry.from_json_bytes(_manifest_bytes(missing_contract))


def test_manifest_never_allows_an_unavailable_path_to_resolve_enabled():
    record = _manifest_record()
    record["unavailable_disposition"] = "enabled"

    with pytest.raises(ValueError, match="unavailable_disposition"):
        ActionRegistry.from_json_bytes(_manifest_bytes(record))


def test_unknown_action_is_default_denied_with_exact_reason():
    resolved = ActionRegistry.load_default().resolve("absent.action", _context())

    assert resolved.disposition is ActionDisposition.DISABLED
    assert resolved.reason == "Action is absent from the source-controlled product capability manifest."
    assert resolved.handler == ""


def test_phase_one_context_rejects_simulated_and_replayed_evidence():
    for evidence in (EvidenceKind.SIMULATED, EvidenceKind.REPLAYED):
        with pytest.raises(ValueError, match="Phase 0/1"):
            _context(verification_evidence=evidence)


@pytest.mark.parametrize(
    ("field_name", "invalid_value"),
    [
        ("selected_display_id", None),
        ("characterization_kind", CharacterizationKind.UNKNOWN),
        ("selected_method", CalibrationMethod.MEASURED),
        ("target_valid", False),
        ("selected_preset_id", "calibration.preset.hdr10"),
        ("target_hdr", True),
        ("sealed_plan_sha256", "a" * 64),
        ("journal_ready", False),
    ],
)
def test_calibration_generate_predicates_are_independently_default_deny(field_name: str, invalid_value: object):
    registry = ActionRegistry.load_default()
    baseline = _context(
        sealed_plan_sha256=None,
        sealed_capability_generation=None,
        confirmation_state="none",
        verification_evidence=None,
    )

    assert registry.resolve("calibration.generate", baseline).disposition is ActionDisposition.ENABLED
    denied = registry.resolve("calibration.generate", replace(baseline, **{field_name: invalid_value}))
    assert denied.disposition is ActionDisposition.DISABLED


def test_plan_actions_require_matching_capability_generation_and_live_confirmation():
    registry = ActionRegistry.load_default()
    baseline = _context()

    assert registry.resolve("calibration.preview", baseline).disposition is ActionDisposition.ENABLED
    assert (
        registry.resolve("calibration.preview", replace(baseline, generated_asset_kinds=frozenset({"ICC"}))).disposition
        is ActionDisposition.DISABLED
    )
    assert (
        registry.resolve("calibration.preview", replace(baseline, export_source_ready=False)).disposition
        is ActionDisposition.DISABLED
    )
    for action_id in ("calibration.preview", "calibration.confirm_plan", "calibration.decline_plan"):
        assert (
            registry.resolve(action_id, replace(baseline, sealed_capability_generation=6)).disposition
            is ActionDisposition.DISABLED
        )
    for action_id in ("calibration.confirm_plan", "calibration.decline_plan"):
        assert (
            registry.resolve(action_id, replace(baseline, confirmation_state="expired")).disposition
            is ActionDisposition.DISABLED
        )


def test_fake_apply_is_zero_surface_fake_only_and_production_default_denied():
    registry = ActionRegistry.load_default()
    production = _context(confirmation_state="confirmed")
    fake = replace(production, fake_acceptance=True)

    assert registry.surfaces_by_action["fake_acceptance.apply"] == frozenset()
    assert registry.resolve("fake_acceptance.apply", production).disposition is ActionDisposition.DISABLED
    assert registry.resolve("fake_acceptance.apply", fake).disposition is ActionDisposition.ENABLED
    for field_name, invalid_value in (
        ("confirmation_state", "live"),
        ("sealed_capability_generation", 6),
        ("journal_ready", False),
    ):
        assert (
            registry.resolve("fake_acceptance.apply", replace(fake, **{field_name: invalid_value})).disposition
            is ActionDisposition.DISABLED
        )


def test_exports_reports_profile_and_bundle_require_their_exact_capabilities():
    registry = ActionRegistry.load_default()
    baseline = _context(confirmation_state="confirmed")
    save_report = replace(baseline, stage=WorkflowStage.SAVE_REPORT)

    for export_format in save_report.available_export_formats:
        action_id = f"export.active.{export_format}"
        assert registry.resolve(action_id, save_report).disposition is ActionDisposition.ENABLED
        assert (
            registry.resolve(
                action_id,
                replace(
                    save_report,
                    available_export_formats=save_report.available_export_formats - {export_format},
                ),
            ).disposition
            is ActionDisposition.DISABLED
        )
    assert registry.resolve("report.save", save_report).disposition is ActionDisposition.ENABLED
    assert (
        registry.resolve("report.save", replace(save_report, configured_export_directory_valid=False)).disposition
        is ActionDisposition.DISABLED
    )
    assert registry.resolve("profile.export", baseline).disposition is ActionDisposition.ENABLED
    assert (
        registry.resolve("profile.export", replace(baseline, selected_profile_reparsed=False)).disposition
        is ActionDisposition.DISABLED
    )
    assert registry.resolve("diagnostics.bundle.create", baseline).disposition is ActionDisposition.ENABLED
    assert (
        registry.resolve(
            "diagnostics.bundle.create", replace(baseline, diagnostic_bundle_preview_live=False)
        ).disposition
        is ActionDisposition.DISABLED
    )


def test_phase_two_import_ddc_measured_and_physical_actions_remain_disabled_when_qualified():
    registry = ActionRegistry.load_default()
    context = _context(validated_import_ready=True, physical_apply_qualified=True, measured_qualified=True)

    for action_id in (
        "panel_profile.import",
        "ddc.apply",
        "display.restore_defaults",
        "calibration.method.measured",
        "verification.measured",
    ):
        assert registry.resolve(action_id, context).disposition is ActionDisposition.DISABLED
