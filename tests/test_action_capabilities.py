from __future__ import annotations

import copy
import json
from dataclasses import fields, replace
from importlib import resources

import pytest

from calibrate_pro.application.actions import (
    PRESET_TARGETS,
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
    "calibration.decline_plan", "calibration.apply", "fake_acceptance.apply",
    "calibration.all",
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

EXPECTED_ENABLED_POLICY_IDS = {
    "application.exit",
    "window.hide_or_minimize", "window.show", "window.toggle_visibility",
    "navigation.dashboard", "navigation.calibrate", "navigation.verify", "navigation.profiles",
    "navigation.ddc", "navigation.settings",
    "help.about", "onboarding.complete", "display.detect",
    "panel_profile.dialog.open", "panel_profile.edid.select_display", "panel_profile.import.choose",
    "display.hdr_status", "profile.list.refresh", "profile.inspect",
    "diagnostics.folder.open", "diagnostics.bundle.preview",
}

EXPECTED_CONDITIONAL_POLICY_IDS = {
    "calibration.open_for_display", "display.characterization.use_generic", "workflow.select_display",
    "calibration.method.sensorless",
    "calibration.target.gamut", "calibration.target.whitepoint", "calibration.target.custom_cct",
    "calibration.target.gamma",
    "calibration.preset.srgb_web", "calibration.preset.rec709", "calibration.preset.dci_p3",
    "calibration.preset.photography",
    "calibration.generate", "calibration.preview", "calibration.confirm_plan",
    "calibration.decline_plan", "calibration.apply", "fake_acceptance.apply",
    "verification.sensorless", "report.save",
    "export.active.cube", "export.active.3dlut", "export.active.png", "export.active.icc",
    "export.active.mpv", "export.active.obs", "profile.export",
    "settings.lut_size", "settings.output_directory", "diagnostics.bundle.create",
}

EXPECTED_DISABLED_POLICY_IDS = {
    "calibration.method.measured", "calibration.method.hybrid", "calibration.target.hdr",
    "calibration.preset.hdr10", "verification.measured", "settings.hdr",
    "panel_profile.edid.create", "panel_profile.import", "display.restore_defaults",
    "profile.install", "profile.rename", "profile.generate_all", "profile.activate", "profile.delete",
    "patterns.open",
    "ddc.stage.brightness", "ddc.stage.contrast", "ddc.stage.red_gain", "ddc.stage.green_gain",
    "ddc.stage.blue_gain", "ddc.stage.red_black_level", "ddc.stage.green_black_level",
    "ddc.stage.blue_black_level", "ddc.unsupported.image_mode", "ddc.unsupported.color_preset",
    "ddc.unsupported.gamma", "ddc.unsupported.factory_color_reset", "ddc.read_current",
    "ddc.restore_defaults", "ddc.raw_read", "ddc.raw_write", "ddc.apply", "tray.switch_profile",
}

EXPECTED_HIDDEN_POLICY_IDS = {
    "calibration.all", "measurement.live.toggle", "settings.startup", "settings.minimize_to_tray",
    "settings.oled_automation", "settings.per_app.enabled", "settings.per_app.rules",
    "settings.argyll_path", "settings.panel_profiles_path", "settings.default_target",
}

EXPECTED_SURFACES_BY_ACTION = {
    "application.exit": {"menu.file.exit", "tray.exit"},
    "window.hide_or_minimize": {"shortcut.escape"},
    "window.show": {"tray.show"},
    "window.toggle_visibility": {"tray.icon.activate"},
    "navigation.dashboard": {"sidebar.dashboard", "menu.view.dashboard"},
    "navigation.calibrate": {"sidebar.calibrate", "menu.view.calibrate"},
    "navigation.verify": {"sidebar.verify", "menu.view.verify"},
    "navigation.profiles": {"sidebar.profiles", "menu.view.profiles", "tray.profiles"},
    "navigation.ddc": {"sidebar.ddc", "menu.view.ddc"},
    "navigation.settings": {"sidebar.settings", "menu.view.settings"},
    "help.about": {"menu.help.about"},
    "onboarding.complete": {"dialog.onboarding.get_started"},
    "diagnostics.folder.open": {"settings.diagnostics.open_folder"},
    "diagnostics.bundle.preview": {"settings.diagnostics.preview_bundle"},
    "diagnostics.bundle.create": {"settings.diagnostics.create_bundle"},
    # The add-profile dialog used to carry a scan button of its own. It now
    # lists the displays the session already detected, so detection is offered
    # in three places and none of them is inside a dialog.
    "display.detect": {"dashboard.refresh", "menu.view.refresh", "menu.display.detect"},
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
    "calibration.apply": {"calibrate.apply"},
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
    "tray.switch_profile": {"tray.switch_profile"},
    "measurement.live.toggle": {"dashboard.live_sensor.toggle"},
}
# fmt: on


def test_default_registry_matches_complete_initial_action_census():
    registry = ActionRegistry.load_default()

    assert registry.action_ids == frozenset(EXPECTED_ACTION_IDS)
    assert registry.surfaces_by_action == {
        action_id: frozenset(surfaces) for action_id, surfaces in EXPECTED_SURFACES_BY_ACTION.items()
    }


def test_source_and_frozen_policy_assignments_match_exact_approved_groups():
    registry = ActionRegistry.load_default()
    expected_by_policy = {
        "enabled": EXPECTED_ENABLED_POLICY_IDS,
        "conditional": EXPECTED_CONDITIONAL_POLICY_IDS,
        "disabled": EXPECTED_DISABLED_POLICY_IDS,
        "hidden": EXPECTED_HIDDEN_POLICY_IDS,
    }

    assert {policy: len(action_ids) for policy, action_ids in expected_by_policy.items()} == {
        "enabled": 21,
        "conditional": 30,
        "disabled": 33,
        "hidden": 10,
    }
    assert set().union(*expected_by_policy.values()) == EXPECTED_ACTION_IDS
    assert sum(len(action_ids) for action_ids in expected_by_policy.values()) == len(EXPECTED_ACTION_IDS)

    source_by_policy = {
        policy: {action_id for action_id, spec in registry._specs_by_id.items() if spec.source_policy == policy}
        for policy in ("enabled", "conditional", "disabled", "hidden")
    }
    frozen_by_policy = {
        policy: {action_id for action_id, spec in registry._specs_by_id.items() if spec.frozen_policy == policy}
        for policy in ("enabled", "conditional", "disabled", "hidden")
    }

    assert source_by_policy == expected_by_policy
    assert frozen_by_policy == expected_by_policy
    assert "fake_acceptance.apply" in EXPECTED_CONDITIONAL_POLICY_IDS
    assert {action_id for action_id, surfaces in registry.surfaces_by_action.items() if not surfaces} == {
        "fake_acceptance.apply"
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


def test_manifest_rejects_zero_surfaces_for_every_action_except_fake_apply():
    record = _manifest_record()
    record["surfaces"] = []

    with pytest.raises(ValueError, match="fake_acceptance.apply"):
        ActionRegistry.from_json_bytes(_manifest_bytes(record))


def test_manifest_rejects_any_surface_for_fake_apply():
    record = _manifest_record(action_id="fake_acceptance.apply")
    record["source_policy"] = "conditional"
    record["frozen_policy"] = "conditional"

    with pytest.raises(ValueError, match="fake_acceptance.apply"):
        ActionRegistry.from_json_bytes(_manifest_bytes(record))


def test_manifest_accepts_fake_apply_as_the_sole_zero_surface_action():
    record = _manifest_record(action_id="fake_acceptance.apply")
    record["surfaces"] = []
    record["source_policy"] = "conditional"
    record["frozen_policy"] = "conditional"

    registry = ActionRegistry.from_json_bytes(_manifest_bytes(record))

    assert registry.surfaces_by_action["fake_acceptance.apply"] == frozenset()


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
        ("required_resources", ["C:/private.json"]),
    ],
)
def test_manifest_rejects_wildcards_traversal_and_drive_qualified_resources(field_name: str, invalid_value: object):
    record = _manifest_record()
    record[field_name] = invalid_value

    with pytest.raises(ValueError):
        ActionRegistry.from_json_bytes(_manifest_bytes(record))


def test_manifest_accepts_normalized_relative_posix_resource_paths():
    record = _manifest_record()
    record["required_resources"] = ["resources/contracts/action.json"]

    registry = ActionRegistry.from_json_bytes(_manifest_bytes(record))

    assert registry._specs_by_id["test.action"].required_resources == ("resources/contracts/action.json",)


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


def test_action_context_shape_includes_plan_bound_fake_apply_evidence():
    assert tuple(field.name for field in fields(ActionContext)) == (
        "stage",
        "runtime_mode",
        "fake_acceptance",
        "selected_display_id",
        "characterization_kind",
        "selected_method",
        "target_valid",
        "selected_preset_id",
        "target_hdr",
        "generated_asset_kinds",
        "sealed_plan_sha256",
        "sealed_plan_actuatable",
        "confirmation_state",
        "fake_applied_plan_sha256",
        "applied_plan_sha256",
        "capability_generation",
        "sealed_capability_generation",
        "verification_evidence",
        "export_source_ready",
        "configured_export_directory_valid",
        "available_export_formats",
        "selected_profile_reparsed",
        "validated_import_ready",
        "supported_vcp_codes",
        "diagnostic_bundle_preview_live",
        "journal_ready",
        "physical_apply_qualified",
        "measured_qualified",
    )


@pytest.mark.parametrize("digest", ["not-a-digest", "A" * 64])
def test_action_context_rejects_noncanonical_fake_applied_plan_digest(digest: str):
    with pytest.raises(ValueError, match="fake_applied_plan_sha256"):
        _context(fake_applied_plan_sha256=digest)


def test_preset_targets_are_exact_literals_and_hdr10_stays_disabled():
    expected = {
        "calibration.preset.srgb_web": ("sRGB", "D65", "2.2", False),
        "calibration.preset.rec709": ("Rec.709", "D65", "BT.1886", False),
        "calibration.preset.dci_p3": ("DCI-P3", "D65", "2.4", False),
        "calibration.preset.photography": ("sRGB", "D50", "2.2", False),
    }
    registry = ActionRegistry.load_default()
    context = _context()

    assert dict(PRESET_TARGETS) == expected
    for action_id in expected:
        assert registry.resolve(action_id, context).disposition is ActionDisposition.ENABLED
    assert registry.resolve("calibration.preset.hdr10", context).disposition is ActionDisposition.DISABLED


def test_every_declared_preset_is_selectable_or_says_why_it_is_not():
    """A declared preset is in the table, or the resolver names its own reason.

    The four selectable presets share a manifest fallback naming what a session
    needs before they open. A fifth preset declared without an entry in
    PRESET_TARGETS would inherit that sentence and stay closed to a session that
    already meets every condition it names, so an operator would read it as a
    fault in their session rather than as a preset nobody wired up. hdr10 is the
    shape this holds: declared, closed, and refused in words of its own.
    """
    payload = resources.files("calibrate_pro").joinpath("resources", "action-capabilities.json").read_bytes()
    declared = {
        record["action_id"]: record["unavailable_reason"]
        for record in json.loads(payload)["actions"]
        if record["action_id"].startswith("calibration.preset.")
    }
    registry = ActionRegistry.load_default()
    context = _context()

    assert set(PRESET_TARGETS) <= set(declared)
    for action_id, fallback in sorted(declared.items()):
        resolved = registry.resolve(action_id, context)
        if action_id in PRESET_TARGETS:
            assert resolved.disposition is ActionDisposition.ENABLED
            continue
        assert resolved.disposition is not ActionDisposition.ENABLED
        assert resolved.reason != fallback


@pytest.mark.parametrize(
    ("action_id", "baseline_changes", "field_name", "invalid_value"),
    [
        pytest.param("calibration.open_for_display", {}, "selected_display_id", None, id="open-display"),
        pytest.param(
            "display.characterization.use_generic",
            {"characterization_kind": CharacterizationKind.UNKNOWN},
            "selected_display_id",
            None,
            id="generic-display",
        ),
        pytest.param(
            "display.characterization.use_generic",
            {"characterization_kind": CharacterizationKind.UNKNOWN},
            "characterization_kind",
            CharacterizationKind.MATCHED,
            id="generic-characterization",
        ),
        pytest.param("workflow.select_display", {}, "selected_display_id", None, id="workflow-display"),
        pytest.param(
            "calibration.method.sensorless",
            {"stage": WorkflowStage.METHOD},
            "selected_display_id",
            None,
            id="method-display",
        ),
        pytest.param(
            "calibration.method.sensorless",
            {"stage": WorkflowStage.METHOD},
            "characterization_kind",
            CharacterizationKind.UNKNOWN,
            id="method-characterization",
        ),
        pytest.param("settings.lut_size", {}, "journal_ready", False, id="lut-size-journal"),
        pytest.param("settings.output_directory", {}, "journal_ready", False, id="output-directory-journal"),
    ],
)
def test_remaining_individual_conditional_predicates_are_default_deny(
    action_id: str,
    baseline_changes: dict[str, object],
    field_name: str,
    invalid_value: object,
):
    registry = ActionRegistry.load_default()
    baseline = _context(**baseline_changes)

    assert registry.resolve(action_id, baseline).disposition is ActionDisposition.ENABLED
    denied = replace(baseline, **{field_name: invalid_value})
    assert registry.resolve(action_id, denied).disposition is ActionDisposition.DISABLED


@pytest.mark.parametrize(
    "action_id",
    (
        "calibration.target.gamut",
        "calibration.target.whitepoint",
        "calibration.target.custom_cct",
        "calibration.target.gamma",
        "calibration.preset.srgb_web",
        "calibration.preset.rec709",
        "calibration.preset.dci_p3",
        "calibration.preset.photography",
    ),
)
@pytest.mark.parametrize(
    ("field_name", "invalid_value"),
    (
        ("selected_display_id", None),
        ("characterization_kind", CharacterizationKind.UNKNOWN),
        ("selected_method", CalibrationMethod.MEASURED),
        ("target_hdr", True),
    ),
)
def test_target_and_preset_sensorless_predicates_are_independently_default_deny(
    action_id: str,
    field_name: str,
    invalid_value: object,
):
    registry = ActionRegistry.load_default()
    baseline = _context()

    assert registry.resolve(action_id, baseline).disposition is ActionDisposition.ENABLED
    denied = replace(baseline, **{field_name: invalid_value})
    assert registry.resolve(action_id, denied).disposition is ActionDisposition.DISABLED


@pytest.mark.parametrize(
    "action_id",
    (
        "calibration.target.gamut",
        "calibration.target.whitepoint",
        "calibration.target.custom_cct",
        "calibration.target.gamma",
        "calibration.preset.srgb_web",
        "calibration.preset.rec709",
        "calibration.preset.dci_p3",
        "calibration.preset.photography",
    ),
)
@pytest.mark.parametrize(
    "characterization_kind",
    (CharacterizationKind.MATCHED, CharacterizationKind.EXPLICIT_GENERIC),
)
def test_sensorless_conditional_actions_accept_each_qualified_characterization(
    action_id: str,
    characterization_kind: CharacterizationKind,
):
    registry = ActionRegistry.load_default()

    resolved = registry.resolve(action_id, _context(characterization_kind=characterization_kind))

    assert resolved.disposition is ActionDisposition.ENABLED


@pytest.mark.parametrize(
    "characterization_kind",
    (CharacterizationKind.MATCHED, CharacterizationKind.EXPLICIT_GENERIC),
)
def test_sensorless_method_accepts_each_qualified_characterization(
    characterization_kind: CharacterizationKind,
):
    registry = ActionRegistry.load_default()

    resolved = registry.resolve(
        "calibration.method.sensorless",
        _context(stage=WorkflowStage.METHOD, characterization_kind=characterization_kind),
    )

    assert resolved.disposition is ActionDisposition.ENABLED


@pytest.mark.parametrize("characterization_kind", (None, CharacterizationKind.UNKNOWN))
def test_generic_characterization_action_accepts_only_uncharacterized_displays(
    characterization_kind: CharacterizationKind | None,
):
    registry = ActionRegistry.load_default()

    resolved = registry.resolve(
        "display.characterization.use_generic",
        _context(characterization_kind=characterization_kind),
    )

    assert resolved.disposition is ActionDisposition.ENABLED


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


@pytest.mark.parametrize(
    ("field_name", "invalid_value"),
    [
        ("generated_asset_kinds", frozenset()),
        ("generated_asset_kinds", frozenset({"ICC"})),
        ("generated_asset_kinds", frozenset({"CUBE"})),
        ("sealed_plan_sha256", None),
        ("export_source_ready", False),
        ("journal_ready", False),
    ],
)
def test_preview_predicates_are_independently_default_deny(field_name: str, invalid_value: object):
    registry = ActionRegistry.load_default()
    baseline = _context()

    assert registry.resolve("calibration.preview", baseline).disposition is ActionDisposition.ENABLED
    assert (
        registry.resolve("calibration.preview", replace(baseline, **{field_name: invalid_value})).disposition
        is ActionDisposition.DISABLED
    )


@pytest.mark.parametrize("action_id", ["calibration.confirm_plan", "calibration.decline_plan"])
@pytest.mark.parametrize(
    ("field_name", "invalid_value"),
    [
        ("sealed_plan_sha256", None),
        ("confirmation_state", "none"),
        ("confirmation_state", "confirmed"),
        ("confirmation_state", "consumed"),
        ("confirmation_state", "expired"),
        ("journal_ready", False),
    ],
)
def test_confirmation_predicates_are_independently_default_deny(action_id: str, field_name: str, invalid_value: object):
    registry = ActionRegistry.load_default()
    baseline = _context()

    assert registry.resolve(action_id, baseline).disposition is ActionDisposition.ENABLED
    assert (
        registry.resolve(action_id, replace(baseline, **{field_name: invalid_value})).disposition
        is ActionDisposition.DISABLED
    )


@pytest.mark.parametrize(
    ("field_name", "invalid_value"),
    [
        ("fake_acceptance", False),
        ("sealed_plan_sha256", None),
        ("confirmation_state", "none"),
        ("confirmation_state", "live"),
        ("confirmation_state", "consumed"),
        ("confirmation_state", "expired"),
        ("journal_ready", False),
    ],
)
def test_fake_apply_predicates_are_independently_default_deny(field_name: str, invalid_value: object):
    registry = ActionRegistry.load_default()
    baseline = _context(fake_acceptance=True, confirmation_state="confirmed")

    assert registry.surfaces_by_action["fake_acceptance.apply"] == frozenset()
    assert registry.resolve("fake_acceptance.apply", baseline).disposition is ActionDisposition.ENABLED
    assert (
        registry.resolve("fake_acceptance.apply", replace(baseline, **{field_name: invalid_value})).disposition
        is ActionDisposition.DISABLED
    )


@pytest.mark.parametrize(
    ("field_name", "invalid_value"),
    [
        ("selected_display_id", None),
        ("characterization_kind", CharacterizationKind.UNKNOWN),
        ("selected_method", CalibrationMethod.MEASURED),
        ("target_hdr", True),
        ("sealed_plan_sha256", None),
        ("confirmation_state", "live"),
        ("verification_evidence", EvidenceKind.MEASURED),
    ],
)
def test_production_sensorless_verification_predicates_are_independently_default_deny(
    field_name: str, invalid_value: object
):
    registry = ActionRegistry.load_default()
    baseline = _context(
        stage=WorkflowStage.VERIFY,
        confirmation_state="confirmed",
        verification_evidence=None,
    )

    assert registry.resolve("verification.sensorless", baseline).disposition is ActionDisposition.ENABLED
    assert (
        registry.resolve("verification.sensorless", replace(baseline, **{field_name: invalid_value})).disposition
        is ActionDisposition.DISABLED
    )


def test_fake_sensorless_verification_requires_current_successful_apply_digest():
    registry = ActionRegistry.load_default()
    sealed_digest = "a" * 64
    baseline = _context(
        stage=WorkflowStage.VERIFY,
        fake_acceptance=True,
        confirmation_state="consumed",
        sealed_plan_sha256=sealed_digest,
        fake_applied_plan_sha256=None,
        verification_evidence=None,
    )

    # No/failed receipt and token consumption alone carry no applied-plan digest.
    assert registry.resolve("verification.sensorless", baseline).disposition is ActionDisposition.DISABLED
    assert (
        registry.resolve(
            "verification.sensorless",
            replace(baseline, fake_applied_plan_sha256="b" * 64),
        ).disposition
        is ActionDisposition.DISABLED
    )
    current = replace(baseline, fake_applied_plan_sha256=sealed_digest)
    assert registry.resolve("verification.sensorless", current).disposition is ActionDisposition.ENABLED
    assert (
        registry.resolve(
            "verification.sensorless",
            replace(current, confirmation_state="confirmed"),
        ).disposition
        is ActionDisposition.DISABLED
    )
    assert (
        registry.resolve(
            "verification.sensorless",
            replace(current, verification_evidence=EvidenceKind.MEASURED),
        ).disposition
        is ActionDisposition.DISABLED
    )


def test_export_source_ready_is_an_independent_service_owned_proof(monkeypatch: pytest.MonkeyPatch):
    registry = ActionRegistry.load_default()
    baseline = _context(export_source_ready=True)

    def deny_filesystem_access(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("pure resolver must not read private asset bytes")

    monkeypatch.setattr("builtins.open", deny_filesystem_access)

    assert registry.resolve("calibration.preview", baseline).disposition is ActionDisposition.ENABLED
    assert (
        registry.resolve("calibration.preview", replace(baseline, export_source_ready=False)).disposition
        is ActionDisposition.DISABLED
    )


def test_exports_and_report_require_each_independent_source_and_journal_predicate():
    registry = ActionRegistry.load_default()
    export_actions = (
        ("export.active.cube", "cube"),
        ("export.active.3dlut", "3dlut"),
        ("export.active.png", "png"),
        ("export.active.icc", "icc"),
        ("export.active.mpv", "mpv"),
        ("export.active.obs", "obs"),
    )
    baseline = _context(stage=WorkflowStage.SAVE_REPORT, confirmation_state="confirmed")

    for action_id, export_format in export_actions:
        assert registry.resolve(action_id, baseline).disposition is ActionDisposition.ENABLED
        for denied in (
            replace(baseline, available_export_formats=baseline.available_export_formats - {export_format}),
            replace(baseline, sealed_plan_sha256=None),
            replace(baseline, verification_evidence=None),
            replace(baseline, export_source_ready=False),
            replace(baseline, journal_ready=False),
        ):
            assert registry.resolve(action_id, denied).disposition is ActionDisposition.DISABLED

    assert registry.resolve("report.save", baseline).disposition is ActionDisposition.ENABLED
    for denied in (
        replace(baseline, sealed_plan_sha256=None),
        replace(baseline, verification_evidence=None),
        replace(baseline, export_source_ready=False),
        replace(baseline, configured_export_directory_valid=False),
        replace(baseline, journal_ready=False),
    ):
        assert registry.resolve("report.save", denied).disposition is ActionDisposition.DISABLED


def test_profile_export_and_bundle_create_predicates_are_independently_default_deny():
    registry = ActionRegistry.load_default()
    baseline = _context()

    assert registry.resolve("profile.export", baseline).disposition is ActionDisposition.ENABLED
    for denied in (
        replace(baseline, selected_profile_reparsed=False),
        replace(baseline, journal_ready=False),
    ):
        assert registry.resolve("profile.export", denied).disposition is ActionDisposition.DISABLED

    assert registry.resolve("diagnostics.bundle.create", baseline).disposition is ActionDisposition.ENABLED
    for denied in (
        replace(baseline, diagnostic_bundle_preview_live=False),
        replace(baseline, journal_ready=False),
    ):
        assert registry.resolve("diagnostics.bundle.create", denied).disposition is ActionDisposition.DISABLED


def test_generation_mismatch_disables_every_plan_dependent_action():
    registry = ActionRegistry.load_default()
    preview = _context()
    fake_apply = _context(fake_acceptance=True, confirmation_state="confirmed")
    verify = _context(
        stage=WorkflowStage.VERIFY,
        confirmation_state="confirmed",
        verification_evidence=None,
    )
    save = _context(stage=WorkflowStage.SAVE_REPORT, confirmation_state="confirmed")
    cases = (
        ("calibration.preview", preview),
        ("calibration.confirm_plan", preview),
        ("calibration.decline_plan", preview),
        ("fake_acceptance.apply", fake_apply),
        ("verification.sensorless", verify),
        ("report.save", save),
        ("export.active.cube", save),
        ("export.active.3dlut", save),
        ("export.active.png", save),
        ("export.active.icc", save),
        ("export.active.mpv", save),
        ("export.active.obs", save),
    )

    for action_id, baseline in cases:
        assert registry.resolve(action_id, baseline).disposition is ActionDisposition.ENABLED
        mismatch = replace(baseline, sealed_capability_generation=baseline.capability_generation + 1)
        assert registry.resolve(action_id, mismatch).disposition is ActionDisposition.DISABLED


def test_all_seventeen_ddc_actions_remain_phase_two_disabled_when_qualified():
    registry = ActionRegistry.load_default()
    ddc_action_ids = (
        "ddc.stage.brightness",
        "ddc.stage.contrast",
        "ddc.stage.red_gain",
        "ddc.stage.green_gain",
        "ddc.stage.blue_gain",
        "ddc.stage.red_black_level",
        "ddc.stage.green_black_level",
        "ddc.stage.blue_black_level",
        "ddc.unsupported.image_mode",
        "ddc.unsupported.color_preset",
        "ddc.unsupported.gamma",
        "ddc.unsupported.factory_color_reset",
        "ddc.read_current",
        "ddc.restore_defaults",
        "ddc.raw_read",
        "ddc.raw_write",
        "ddc.apply",
    )
    context = _context(
        supported_vcp_codes=frozenset(range(256)),
        physical_apply_qualified=True,
    )

    assert len(ddc_action_ids) == 17
    for action_id in ddc_action_ids:
        assert registry.resolve(action_id, context).disposition is ActionDisposition.DISABLED


def test_phase_two_import_measured_and_physical_actions_remain_disabled_when_qualified():
    registry = ActionRegistry.load_default()
    context = _context(validated_import_ready=True, physical_apply_qualified=True, measured_qualified=True)

    for action_id in (
        "panel_profile.import",
        "display.restore_defaults",
        "calibration.method.measured",
        "verification.measured",
    ):
        assert registry.resolve(action_id, context).disposition is ActionDisposition.DISABLED
