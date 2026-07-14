"""Source-controlled action capability manifest and default-deny resolver."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum
from importlib import resources
from types import MappingProxyType
from typing import Any, Literal, cast

from calibrate_pro.application.contracts import (
    PHASE_ONE_EVIDENCE_KINDS,
    CharacterizationKind,
    EvidenceKind,
)
from calibrate_pro.workflow import CalibrationMethod, WorkflowStage

Policy = Literal["enabled", "conditional", "disabled", "hidden"]
EvidenceMode = Literal["none", "read_only", "estimated", "measured"]
RuntimeMode = Literal["source", "frozen"]
ExportFormat = Literal["cube", "3dlut", "png", "icc", "mpv", "obs"]

UNKNOWN_ACTION_REASON = "Action is absent from the source-controlled product capability manifest."
_POLICIES = frozenset({"enabled", "conditional", "disabled", "hidden"})
_EVIDENCE_MODES = frozenset({"none", "read_only", "estimated", "measured"})
_ASSET_KINDS = frozenset({"ICC", "CUBE"})
_EXPORT_FORMATS = frozenset({"cube", "3dlut", "png", "icc", "mpv", "obs"})
_SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")


class ActionDisposition(str, Enum):
    ENABLED = "enabled"
    DISABLED = "disabled"
    HIDDEN = "hidden"


class ActionClassification(str, Enum):
    UI_ONLY = "ui_only"
    READ_ONLY = "read_only"
    LOCAL_FILE_WRITE = "local_file_write"
    PHYSICAL_MUTATION = "physical_mutation"


@dataclass(frozen=True)
class ActionContext:
    stage: WorkflowStage
    runtime_mode: RuntimeMode
    fake_acceptance: bool
    selected_display_id: str | None
    characterization_kind: CharacterizationKind | None
    selected_method: CalibrationMethod | None
    target_valid: bool
    selected_preset_id: str | None
    target_hdr: bool
    generated_asset_kinds: frozenset[Literal["ICC", "CUBE"]]
    sealed_plan_sha256: str | None
    confirmation_state: Literal["none", "live", "confirmed", "consumed", "expired"]
    fake_applied_plan_sha256: str | None
    capability_generation: int
    sealed_capability_generation: int | None
    verification_evidence: EvidenceKind | None
    export_source_ready: bool
    configured_export_directory_valid: bool
    available_export_formats: frozenset[ExportFormat]
    selected_profile_reparsed: bool
    validated_import_ready: bool
    supported_vcp_codes: frozenset[int]
    diagnostic_bundle_preview_live: bool
    journal_ready: bool
    physical_apply_qualified: bool
    measured_qualified: bool

    def __post_init__(self) -> None:
        if not isinstance(self.stage, WorkflowStage):
            raise TypeError("stage must be a WorkflowStage")
        if type(self.runtime_mode) is not str or self.runtime_mode not in {"source", "frozen"}:
            raise ValueError("runtime_mode must be source or frozen")
        for name in (
            "fake_acceptance",
            "target_valid",
            "target_hdr",
            "export_source_ready",
            "configured_export_directory_valid",
            "selected_profile_reparsed",
            "validated_import_ready",
            "diagnostic_bundle_preview_live",
            "journal_ready",
            "physical_apply_qualified",
            "measured_qualified",
        ):
            if type(getattr(self, name)) is not bool:
                raise TypeError(f"{name} must be an exact boolean")
        _validate_optional_nonempty_string(self.selected_display_id, "selected_display_id")
        _validate_optional_nonempty_string(self.selected_preset_id, "selected_preset_id")
        if self.characterization_kind is not None and not isinstance(self.characterization_kind, CharacterizationKind):
            raise TypeError("characterization_kind must be CharacterizationKind or None")
        if self.selected_method is not None and not isinstance(self.selected_method, CalibrationMethod):
            raise TypeError("selected_method must be CalibrationMethod or None")
        _validate_exact_frozenset(self.generated_asset_kinds, _ASSET_KINDS, "generated_asset_kinds")
        _validate_optional_sha256(self.sealed_plan_sha256, "sealed_plan_sha256")
        if type(self.confirmation_state) is not str or self.confirmation_state not in {
            "none",
            "live",
            "confirmed",
            "consumed",
            "expired",
        }:
            raise ValueError("confirmation_state is invalid")
        _validate_optional_sha256(self.fake_applied_plan_sha256, "fake_applied_plan_sha256")
        _validate_generation(self.capability_generation, "capability_generation")
        if self.sealed_capability_generation is not None:
            _validate_generation(self.sealed_capability_generation, "sealed_capability_generation")
        if self.verification_evidence is not None:
            if not isinstance(self.verification_evidence, EvidenceKind):
                raise TypeError("verification_evidence must be the canonical EvidenceKind")
            if self.verification_evidence not in PHASE_ONE_EVIDENCE_KINDS:
                raise ValueError("Phase 0/1 does not admit simulated or replayed evidence")
        _validate_exact_frozenset(self.available_export_formats, _EXPORT_FORMATS, "available_export_formats")
        if type(self.supported_vcp_codes) is not frozenset:
            raise TypeError("supported_vcp_codes must be an exact frozenset")
        for code in self.supported_vcp_codes:
            if type(code) is not int or not 0 <= code <= 0xFF:
                raise ValueError("supported_vcp_codes must contain exact integers from 0 through 255")


@dataclass(frozen=True)
class ActionSpec:
    action_id: str
    surfaces: tuple[str, ...]
    classification: ActionClassification
    required_stages: tuple[WorkflowStage, ...]
    required_capabilities: tuple[str, ...]
    source_policy: Policy
    frozen_policy: Policy
    handler: str
    required_modules: tuple[str, ...]
    required_resources: tuple[str, ...]
    receipt_required: bool
    evidence_modes: tuple[EvidenceMode, ...]
    unavailable_disposition: ActionDisposition
    unavailable_reason: str


@dataclass(frozen=True)
class ResolvedAction:
    action_id: str
    disposition: ActionDisposition
    reason: str | None
    handler: str


PRESET_TARGETS: Mapping[str, tuple[str, str, str, bool]] = MappingProxyType(
    {
        "calibration.preset.srgb_web": ("sRGB", "D65", "2.2", False),
        "calibration.preset.rec709": ("Rec.709", "D65", "BT.1886", False),
        "calibration.preset.dci_p3": ("DCI-P3", "D65", "2.4", False),
        "calibration.preset.photography": ("sRGB", "D50", "2.2", False),
    }
)


_ACTION_KEYS = frozenset(
    {
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
    }
)


class ActionRegistry:
    """Validated immutable view of the source-controlled action manifest."""

    def __init__(self, specs: tuple[ActionSpec, ...]) -> None:
        self._specs_by_id: Mapping[str, ActionSpec] = MappingProxyType({spec.action_id: spec for spec in specs})
        self._surfaces_by_action: Mapping[str, frozenset[str]] = MappingProxyType(
            {spec.action_id: frozenset(spec.surfaces) for spec in specs}
        )

    @classmethod
    def from_json_bytes(cls, payload: bytes) -> ActionRegistry:
        if type(payload) is not bytes:
            raise TypeError("manifest payload must be exact bytes")
        text = payload.decode("utf-8", errors="strict")
        decoded = json.loads(text, object_pairs_hook=_object_from_pairs)
        if type(decoded) is not dict:
            raise ValueError("manifest root must be an object")
        root = cast(dict[str, object], decoded)
        _require_exact_keys(root, frozenset({"schema_version", "default", "actions"}), "manifest root")
        if type(root["schema_version"]) is not int or root["schema_version"] != 1:
            raise ValueError("manifest schema_version must be exact integer 1")
        if type(root["default"]) is not str or root["default"] != "disabled":
            raise ValueError("manifest default must be disabled")
        raw_actions = root["actions"]
        if type(raw_actions) is not list:
            raise ValueError("manifest actions must be an exact list")

        specs: list[ActionSpec] = []
        action_ids: set[str] = set()
        surface_ids: set[str] = set()
        for index, raw_action in enumerate(cast(list[object], raw_actions)):
            spec = _parse_action_spec(raw_action, index)
            if spec.action_id in action_ids:
                raise ValueError(f"duplicate action_id: {spec.action_id}")
            action_ids.add(spec.action_id)
            for surface in spec.surfaces:
                if surface in surface_ids:
                    raise ValueError(f"duplicate surface: {surface}")
                surface_ids.add(surface)
            specs.append(spec)
        return cls(tuple(specs))

    @classmethod
    def load_default(cls) -> ActionRegistry:
        package_files = cast(Any, resources.files("calibrate_pro"))
        payload = package_files.joinpath("resources", "action-capabilities.json").read_bytes()
        return cls.from_json_bytes(payload)

    @property
    def action_ids(self) -> frozenset[str]:
        return frozenset(self._specs_by_id)

    @property
    def surfaces_by_action(self) -> Mapping[str, frozenset[str]]:
        return self._surfaces_by_action

    def resolve(self, action_id: str, context: ActionContext) -> ResolvedAction:
        if type(action_id) is not str or not isinstance(context, ActionContext):
            return ResolvedAction(
                action_id=action_id if type(action_id) is str else "",
                disposition=ActionDisposition.DISABLED,
                reason=UNKNOWN_ACTION_REASON,
                handler="",
            )
        spec = self._specs_by_id.get(action_id)
        if spec is None:
            return ResolvedAction(
                action_id=action_id,
                disposition=ActionDisposition.DISABLED,
                reason=UNKNOWN_ACTION_REASON,
                handler="",
            )

        policy = spec.source_policy if context.runtime_mode == "source" else spec.frozen_policy
        if policy == "hidden":
            return ResolvedAction(action_id, ActionDisposition.HIDDEN, spec.unavailable_reason, spec.handler)
        if policy == "disabled":
            return ResolvedAction(action_id, ActionDisposition.DISABLED, _disabled_reason(spec, context), spec.handler)
        if context.stage not in spec.required_stages:
            return ResolvedAction(
                action_id,
                spec.unavailable_disposition,
                f"Action is unavailable during the {context.stage.value} stage.",
                spec.handler,
            )
        if policy == "conditional" and not _conditional_allowed(spec.action_id, context):
            return ResolvedAction(
                action_id,
                spec.unavailable_disposition,
                spec.unavailable_reason,
                spec.handler,
            )
        return ResolvedAction(action_id, ActionDisposition.ENABLED, None, spec.handler)

    def _spec_for(self, action_id: str) -> ActionSpec | None:
        return self._specs_by_id.get(action_id)


def _object_from_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON object key: {key}")
        result[key] = value
    return result


def _require_exact_keys(value: Mapping[str, object], expected: frozenset[str], label: str) -> None:
    actual = frozenset(value)
    if actual != expected:
        missing = sorted(expected - actual)
        extra = sorted(actual - expected)
        raise ValueError(f"{label} must contain exact keys; missing={missing}, extra={extra}")


def _parse_action_spec(raw_action: object, index: int) -> ActionSpec:
    if type(raw_action) is not dict:
        raise ValueError(f"action {index} must be an object")
    action = cast(dict[str, object], raw_action)
    _require_exact_keys(action, _ACTION_KEYS, f"action {index}")
    action_id = _exact_nonempty_string(action["action_id"], f"action {index} action_id")
    _validate_dotted_identifier(action_id, "action_id")
    surfaces = _string_tuple(action["surfaces"], "surfaces", dotted=True)
    if action_id == "fake_acceptance.apply":
        if surfaces:
            raise ValueError("fake_acceptance.apply must be the sole zero-surface action")
    elif not surfaces:
        raise ValueError("only fake_acceptance.apply may have zero surfaces")
    classification = _enum_value(ActionClassification, action["classification"], "classification")
    stage_values = _string_tuple(action["required_stages"], "required_stages")
    try:
        required_stages = tuple(WorkflowStage(stage) for stage in stage_values)
    except ValueError as exc:
        raise ValueError("required_stages contains an unknown workflow stage") from exc
    _reject_duplicates(required_stages, "required_stages")
    required_capabilities = _string_tuple(action["required_capabilities"], "required_capabilities")
    for capability in required_capabilities:
        _validate_safe_token(capability, "required_capabilities")
    source_policy = _policy(action["source_policy"], "source_policy")
    frozen_policy = _policy(action["frozen_policy"], "frozen_policy")
    handler = _exact_string(action["handler"], "handler")
    if handler and not handler.isidentifier():
        raise ValueError("handler must be empty or a Python identifier")
    if (source_policy in {"enabled", "conditional"} or frozen_policy in {"enabled", "conditional"}) and not handler:
        raise ValueError("an enabled or conditional action requires a handler")
    required_modules = _string_tuple(action["required_modules"], "required_modules")
    for module in required_modules:
        _validate_module_name(module)
    required_resources = _string_tuple(action["required_resources"], "required_resources")
    for resource in required_resources:
        _validate_resource_path(resource)
    if type(action["receipt_required"]) is not bool:
        raise ValueError("receipt_required must be an exact boolean")
    receipt_required = cast(bool, action["receipt_required"])
    evidence_values = _string_tuple(action["evidence_modes"], "evidence_modes")
    if any(value not in _EVIDENCE_MODES for value in evidence_values):
        raise ValueError("evidence_modes contains an unknown value")
    if receipt_required and not evidence_values:
        raise ValueError("receipt-required action has no typed success contract")
    unavailable_disposition = _enum_value(
        ActionDisposition,
        action["unavailable_disposition"],
        "unavailable_disposition",
    )
    if unavailable_disposition is ActionDisposition.ENABLED:
        raise ValueError("unavailable_disposition must be disabled or hidden")
    unavailable_reason = _exact_nonempty_string(action["unavailable_reason"], "unavailable_reason")
    return ActionSpec(
        action_id=action_id,
        surfaces=surfaces,
        classification=classification,
        required_stages=required_stages,
        required_capabilities=required_capabilities,
        source_policy=source_policy,
        frozen_policy=frozen_policy,
        handler=handler,
        required_modules=required_modules,
        required_resources=required_resources,
        receipt_required=receipt_required,
        evidence_modes=cast(tuple[EvidenceMode, ...], evidence_values),
        unavailable_disposition=unavailable_disposition,
        unavailable_reason=unavailable_reason,
    )


def _enum_value(enum_type: type[Enum], value: object, field_name: str) -> Any:
    if type(value) is not str:
        raise ValueError(f"{field_name} must be an exact string")
    try:
        return enum_type(value)
    except ValueError as exc:
        raise ValueError(f"{field_name} contains an unknown value") from exc


def _policy(value: object, field_name: str) -> Policy:
    text = _exact_string(value, field_name)
    if text not in _POLICIES:
        raise ValueError(f"{field_name} contains an unknown policy")
    return cast(Policy, text)


def _string_tuple(value: object, field_name: str, *, dotted: bool = False) -> tuple[str, ...]:
    if type(value) is not list:
        raise ValueError(f"{field_name} must be an exact list")
    result = tuple(_exact_nonempty_string(item, field_name) for item in cast(list[object], value))
    _reject_duplicates(result, field_name)
    if dotted:
        for item in result:
            _validate_dotted_identifier(item, field_name)
    return result


def _reject_duplicates(values: tuple[object, ...], field_name: str) -> None:
    if len(values) != len(set(values)):
        raise ValueError(f"{field_name} contains a duplicate value")


def _exact_string(value: object, field_name: str) -> str:
    if type(value) is not str:
        raise ValueError(f"{field_name} must be an exact string")
    return cast(str, value)


def _exact_nonempty_string(value: object, field_name: str) -> str:
    text = _exact_string(value, field_name)
    if not text or text != text.strip():
        raise ValueError(f"{field_name} must be non-empty without surrounding whitespace")
    return text


def _validate_dotted_identifier(value: str, field_name: str) -> None:
    if (
        "*" in value
        or ".." in value
        or any(
            not part or not all(character.isalnum() or character == "_" for character in part)
            for part in value.split(".")
        )
    ):
        raise ValueError(f"{field_name} must be a dotted identifier without wildcards or traversal")


def _validate_safe_token(value: str, field_name: str) -> None:
    if "*" in value or ".." in value or not all(character.isalnum() or character in "_.-" for character in value):
        raise ValueError(f"{field_name} contains an unsafe token")


def _validate_module_name(value: str) -> None:
    if "*" in value or ".." in value or any(not part.isidentifier() for part in value.split(".")):
        raise ValueError("required_modules must contain Python module names without wildcards or traversal")


def _validate_resource_path(value: str) -> None:
    if (
        "*" in value
        or ".." in value
        or "\\" in value
        or value.startswith("/")
        or re.match(r"^[A-Za-z]:", value) is not None
    ):
        raise ValueError("required_resources must be normalized relative paths without traversal or wildcards")
    parts = value.split("/")
    if any(not part or part == "." for part in parts):
        raise ValueError("required_resources must be normalized relative paths")


def _validate_optional_nonempty_string(value: str | None, field_name: str) -> None:
    if value is not None and (type(value) is not str or not value.strip()):
        raise TypeError(f"{field_name} must be None or a non-empty exact string")


def _validate_optional_sha256(value: str | None, field_name: str) -> None:
    if value is not None and (type(value) is not str or _SHA256_RE.fullmatch(value) is None):
        raise ValueError(f"{field_name} must be None or a canonical lowercase SHA-256 digest")


def _validate_generation(value: int, field_name: str) -> None:
    if type(value) is not int or value < 0:
        raise ValueError(f"{field_name} must be a non-negative exact integer")


def _validate_exact_frozenset(value: object, allowed: frozenset[str], field_name: str) -> None:
    if type(value) is not frozenset:
        raise TypeError(f"{field_name} must be an exact frozenset")
    if not cast(frozenset[object], value).issubset(allowed):
        raise ValueError(f"{field_name} contains an unknown value")


def _generation_matches(context: ActionContext) -> bool:
    return (
        context.sealed_capability_generation is not None
        and context.capability_generation == context.sealed_capability_generation
    )


def _sensorless_ready(context: ActionContext) -> bool:
    return (
        context.selected_display_id is not None
        and context.characterization_kind in {CharacterizationKind.MATCHED, CharacterizationKind.EXPLICIT_GENERIC}
        and context.selected_method is CalibrationMethod.SENSORLESS
        and not context.target_hdr
    )


def _verified_export_source(context: ActionContext) -> bool:
    return (
        context.sealed_plan_sha256 is not None
        and _generation_matches(context)
        and context.export_source_ready
        and context.verification_evidence in PHASE_ONE_EVIDENCE_KINDS
    )


def _conditional_allowed(action_id: str, context: ActionContext) -> bool:
    if action_id == "calibration.open_for_display":
        return context.selected_display_id is not None
    if action_id == "display.characterization.use_generic":
        return context.selected_display_id is not None and context.characterization_kind in {
            None,
            CharacterizationKind.UNKNOWN,
        }
    if action_id == "workflow.select_display":
        return context.selected_display_id is not None
    if action_id == "calibration.method.sensorless":
        return context.selected_display_id is not None and context.characterization_kind in {
            CharacterizationKind.MATCHED,
            CharacterizationKind.EXPLICIT_GENERIC,
        }
    if action_id in {
        "calibration.target.gamut",
        "calibration.target.whitepoint",
        "calibration.target.custom_cct",
        "calibration.target.gamma",
    }:
        return _sensorless_ready(context)
    if action_id in PRESET_TARGETS:
        return _sensorless_ready(context)
    if action_id == "calibration.generate":
        return (
            _sensorless_ready(context)
            and context.target_valid
            and (context.selected_preset_id is None or context.selected_preset_id in PRESET_TARGETS)
            and context.sealed_plan_sha256 is None
            and context.journal_ready
        )
    if action_id == "calibration.preview":
        return (
            context.generated_asset_kinds == _ASSET_KINDS
            and context.sealed_plan_sha256 is not None
            and _generation_matches(context)
            and context.export_source_ready
            and context.journal_ready
        )
    if action_id in {"calibration.confirm_plan", "calibration.decline_plan"}:
        return (
            context.sealed_plan_sha256 is not None
            and _generation_matches(context)
            and context.confirmation_state == "live"
            and context.journal_ready
        )
    if action_id == "fake_acceptance.apply":
        return (
            context.fake_acceptance
            and context.sealed_plan_sha256 is not None
            and _generation_matches(context)
            and context.confirmation_state == "confirmed"
            and context.journal_ready
        )
    if action_id == "verification.sensorless":
        production_confirmed = not context.fake_acceptance and context.confirmation_state == "confirmed"
        fake_applied = (
            context.fake_acceptance
            and context.confirmation_state == "consumed"
            and context.fake_applied_plan_sha256 == context.sealed_plan_sha256
        )
        return (
            _sensorless_ready(context)
            and context.sealed_plan_sha256 is not None
            and _generation_matches(context)
            and (production_confirmed or fake_applied)
            and context.verification_evidence is not EvidenceKind.MEASURED
        )
    if action_id == "report.save":
        return _verified_export_source(context) and context.configured_export_directory_valid and context.journal_ready
    if action_id.startswith("export.active."):
        export_format = action_id.removeprefix("export.active.")
        return (
            export_format in context.available_export_formats
            and _verified_export_source(context)
            and context.journal_ready
        )
    if action_id == "profile.export":
        return context.selected_profile_reparsed and context.journal_ready
    if action_id == "settings.default_target":
        return context.target_valid and not context.target_hdr and context.journal_ready
    if action_id in {"settings.lut_size", "settings.output_directory"}:
        return context.journal_ready
    if action_id == "diagnostics.bundle.create":
        return context.diagnostic_bundle_preview_live and context.journal_ready
    return False


def _disabled_reason(spec: ActionSpec, context: ActionContext) -> str:
    action_id = spec.action_id
    if action_id == "panel_profile.import":
        if not context.validated_import_ready:
            return "Panel import requires a validated source before Phase 2 qualification."
        return "Panel import remains disabled pending the Phase 2 import contract."
    if action_id.startswith("ddc."):
        if not context.supported_vcp_codes:
            return "DDC/CI action requires detected VCP support and Phase 2 qualification."
        if not context.physical_apply_qualified:
            return "DDC/CI physical mutation is not qualified."
        return "DDC/CI action remains disabled pending the Phase 2 transactional plan."
    if action_id in {
        "display.restore_defaults",
        "profile.install",
        "profile.activate",
        "profile.delete",
        "tray.switch_profile",
    }:
        if not context.physical_apply_qualified:
            return "Physical mutation is not qualified."
        return "Physical mutation remains disabled pending the Phase 2 transactional contract."
    if action_id in {
        "calibration.method.measured",
        "calibration.method.hybrid",
        "verification.measured",
    }:
        if not context.measured_qualified:
            return "Measured calibration requires a distinct qualified measurement contract."
        return "Measured calibration remains disabled pending its distinct evidence contract."
    if action_id in {"calibration.target.hdr", "calibration.preset.hdr10", "settings.hdr"}:
        if not context.target_hdr:
            return "HDR requires an explicitly selected HDR target and distinct evidence contract."
        return "HDR remains disabled pending its distinct qualified workflow contract."
    return spec.unavailable_reason


__all__ = [
    "ActionClassification",
    "ActionContext",
    "ActionDisposition",
    "ActionRegistry",
    "ActionSpec",
    "PRESET_TARGETS",
    "ResolvedAction",
]
