# Calibrate Pro Functional Recovery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Recover one truthful Calibrate Pro sensorless workflow through the active `CalibrateProWindow`, prove it end-to-end with an injected fake adapter, and keep every production physical writer and measured path disabled until separately supervised qualification.

**Architecture:** Introduce an application/session layer between the active PySide6 shell and the existing pure `WorkflowController`/`ActuationCoordinator`. A source-controlled default-deny action manifest governs every menu, page, tray, shortcut, and dialog surface. Read-only detection, deterministic generation, immutable preview, estimated verification, atomic export, typed outcomes, and durable redacted diagnostics are production-capable; Apply is enabled only in a separately constructed fake-acceptance composition. Active pages become presentation-only and lose direct sensor/writer imports.

**Tech Stack:** Python 3.10+, PySide6/QtPy, Build UI, dataclasses and Protocols, canonical JSON/SHA-256, existing ICC/LUT core, pytest/pytest-qt-style offscreen construction, pytest-xdist, Ruff, mypy, PyInstaller allowlists, pinned Windows release scripts.

## Global Constraints

- Implement in `C:/dev/worktrees/calibrate-pro-functional-recovery-design` on branch `design/calibrate-pro-functional-recovery-20260713`.
- Normative design: `docs/superpowers/specs/2026-07-13-calibrate-pro-functional-recovery-design.md` at commit `d876f17111b857d1821951aa53396b72571e9efb` plus its approved-status follow-up.
- Scope is Phase 0 and Phase 1 only. Do not enable Phase 2 physical mutation or Phase 3 measured calibration/verification.
- `calibrate_pro.gui.app.CalibrateProWindow` remains the sole source/frozen shell. Do not substitute the historical `gui.main_window.MainWindow` or similarly named inactive page classes.
- Automated work must not open USB/colorimeter, DDC/CI, DWM LUT, WCS/ICC association, VCGT, startup persistence, registry, GPU-driver, or other physical writer paths.
- Production source and frozen compositions expose no enabled physical Apply action. Only `CompositionMode.FAKE_ACCEPTANCE` constructs the packaged recording fake adapter.
- Sensorless output is `ESTIMATED` or `NOT_MEASURED`; it never reports measured Delta E, measured gamut, instrument provenance, or accuracy.
- Every interactive surface has a stable action ID. Aliases intentionally share action IDs; surface IDs, not action IDs, are globally unique.
- Every enabled action has one canonical handler, typed result, action-level test, required first-party/resource closure, and truthful success evidence.
- Unsupported actions are disabled with an exact reason or hidden. No status-only success, silent fallback page, sensorless fallback for measured selection, or zero-file export may remain.
- Reuse and extend `WorkflowController`, `ApplyPlan`, `CapabilityState`, `ActuationCoordinator`, and `ApplyReceipt`; do not duplicate their authority rules.
- Every changed behavior begins with a focused failing test, then the smallest implementation, focused verification, and a narrow commit.
- Run Qt tests with `QT_API=pyside6`, `QT_QPA_PLATFORM=offscreen`, and services injected before constructing the window.
- Do not publish, tag, release, push, use physical hardware, or rewrite `v1.1.0` history under this plan.

---

## Verified Starting Point

The following was checked against the implementation worktree before writing this plan:

| Item | Verified state |
| --- | --- |
| Active shell | `calibrate_pro.gui.app.CalibrateProWindow` from both `commands/gui.py` and `frozen_main.py` |
| Active pages | `gui/pages/calibrate.py`, `verify.py`, `profiles.py`, `ddc_control.py`, and `settings.py`; the similarly named `*_page.py` files are not the active graph |
| Active unsafe routes | Calibrate/Verify contain direct HID/native workers; DDC active handlers can reach direct controls; these must be removed from the active graph, not merely hidden behind a new service |
| Frozen module schema | `schema_version`, `default`, `first_party_exact`, `optional_first_party_exact`, `distribution_roots`; there are no `modules` or `resources` fields |
| Frozen feature schema | `schema_version`, exact commands `doctor`, `gui`, `hdr`, and `developer_only_commands` |
| Wheel data | `pyproject.toml` includes only `resources/*.ico` and `resources/*.png`; new JSON resources are not currently packaged |
| Canonical executable build | `scripts/build_windows.ps1` and `calibrate-pro.spec` |
| Coverage | All GUI/tray code is omitted; no dedicated active-action branch lane exists |
| Parallel safety | `tests/test_professional_features.py` writes fixed `%TEMP%/test_export.clf`; pytest-xdist is not declared |
| Dependency graph | `index internals --root . --json` reports an active GUI/page import cycle because pages import shared names from `gui.app` |

No physical operation was used to establish this baseline.

---

## File and Interface Map

### New application layer

- `calibrate_pro/application/__init__.py`: stable public application exports.
- `calibrate_pro/application/actions.py`: manifest loader, resolver, handler parity, and default-deny rules.
- `calibrate_pro/application/outcomes.py`: typed success/failure boundary.
- `calibrate_pro/application/contracts.py`: immutable observation, characterization, target, asset, evidence, export, and session values.
- `calibrate_pro/application/journal.py`: allowlisted rotating JSONL, redaction, salt policy, diagnostics bundle.
- `calibrate_pro/application/detection.py`: injected read-only detector and atomic dashboard model.
- `calibrate_pro/application/generation.py`: deterministic sensorless generator and strict asset reparsers.
- `calibrate_pro/application/export.py`: one-file atomic bundle publication and readback.
- `calibrate_pro/application/service.py`: one-session orchestration.
- `calibrate_pro/application/composition.py`: production versus fake-acceptance composition roots.
- `calibrate_pro/application/fake_acceptance.py`: packaged public fixture and recording fake adapter; no external adapter injection.

### New product resources

- `calibrate_pro/resources/action-capabilities.json`: product action truth.
- `calibrate_pro/resources/fake-acceptance-display.json`: synthetic public observation/target fixture.
- `calibrate_pro/resources/fake-acceptance-expected.json`: independently pinned expected asset/export hashes.

### Existing production files modified

- `calibrate_pro/workflow.py`: generated-asset/processing/evidence plan fields and explicit invalidation/apply-failure transitions.
- `calibrate_pro/actuation.py`: explicit confirmation invalidation; physical authority remains unchanged.
- `calibrate_pro/core/icc_profile.py`: caller-supplied deterministic creation date and strict readback validator.
- `calibrate_pro/gui/theme.py`: remains the shared theme source.
- `calibrate_pro/gui/action_binding.py`: new signal-aware binder and action properties.
- `calibrate_pro/gui/plan_dialog.py`: new sealed-plan confirmation view.
- `calibrate_pro/gui/app.py`: injected composition root, atomic dashboard, canonical handlers, truthful state.
- Active `calibrate.py`, `verify.py`, `profiles.py`, `ddc_control.py`, `settings.py`: presentation only; direct workers/writers removed or made inaccessible.
- `calibrate_pro/commands/gui.py`, `calibrate_pro/frozen_main.py`: production construction and exact fake-acceptance smoke grammar.
- `pyproject.toml`, `MANIFEST.in`, `.github/workflows/ci.yml`: package JSON, xdist, and active-action coverage lane.
- `packaging/frozen-modules.json`, `packaging/frozen-features.json`, `packaging/components-win64.json`, `calibrate-pro.spec`: positive closure only.
- `scripts/release_artifacts.py`, `scripts/smoke_frozen.ps1`, `scripts/build_windows.ps1`: stage/audit/action smoke with a pinned verifier interpreter.

### New focused tests

- `tests/recovery_fakes.py`
- `tests/test_action_capabilities.py`
- `tests/test_action_outcomes.py`
- `tests/test_diagnostic_journal.py`
- `tests/test_recovery_detection.py`
- `tests/test_sensorless_generation.py`
- `tests/test_atomic_export.py`
- `tests/test_functional_recovery_service.py`
- `tests/test_active_gui_actions.py`
- `tests/test_frozen_action_closure.py`
- `tests/test_fake_acceptance.py`

### Existing tests modified

- `tests/test_professional_features.py`
- `tests/test_workflow.py`
- `tests/test_gui_preview_mode.py`
- `tests/test_gui_truthfulness.py`
- `tests/test_qt_binding_contract.py`
- `tests/test_actuator_boundary.py`
- `tests/test_frozen_module_allowlist.py`
- `tests/test_packaging_contract.py`
- `tests/test_release_metadata.py`
- `tests/test_release_artifacts.py`
- `tests/test_release_pipeline_contract.py`

---

## Core Interfaces Frozen by This Plan

```python
# calibrate_pro/application/outcomes.py
T = TypeVar("T")

@dataclass(frozen=True)
class ActionSuccess(Generic[T]):
    action_id: str
    correlation_id: str
    stage: WorkflowStage
    value: T

@dataclass(frozen=True)
class ActionError:
    action_id: str
    code: str
    summary: str
    retryable: bool
    next_action: str | None
    stage: WorkflowStage
    category: str
    correlation_id: str
    effect_state: Literal["none", "local_write_published", "fake_apply_attempted"]
    published_artifact: tuple[str, str] | None
    apply_phase_flags: tuple[tuple[str, bool], ...]
    recovery_guarantee: str | None

ActionOutcome: TypeAlias = ActionSuccess[T] | ActionError
```

```python
# calibrate_pro/application/actions.py
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
    runtime_mode: Literal["source", "frozen"]
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
    capability_generation: int
    sealed_capability_generation: int | None
    verification_evidence: EvidenceKind | None
    export_source_ready: bool
    configured_export_directory_valid: bool
    available_export_formats: frozenset[Literal["cube", "3dlut", "png", "icc", "mpv", "obs"]]
    selected_profile_reparsed: bool
    validated_import_ready: bool
    supported_vcp_codes: frozenset[int]
    diagnostic_bundle_preview_live: bool
    journal_ready: bool
    physical_apply_qualified: bool
    measured_qualified: bool

@dataclass(frozen=True)
class ActionSpec:
    action_id: str
    surfaces: tuple[str, ...]
    classification: ActionClassification
    required_stages: tuple[WorkflowStage, ...]
    required_capabilities: tuple[str, ...]
    source_policy: Literal["enabled", "conditional", "disabled", "hidden"]
    frozen_policy: Literal["enabled", "conditional", "disabled", "hidden"]
    handler: str
    required_modules: tuple[str, ...]
    required_resources: tuple[str, ...]
    receipt_required: bool
    evidence_modes: tuple[Literal["none", "read_only", "estimated", "measured"], ...]
    unavailable_disposition: ActionDisposition
    unavailable_reason: str

@dataclass(frozen=True)
class ResolvedAction:
    action_id: str
    disposition: ActionDisposition
    reason: str | None
    handler: str

class ActionRegistry:
    @classmethod
    def from_json_bytes(cls, payload: bytes) -> "ActionRegistry": ...
    @classmethod
    def load_default(cls) -> "ActionRegistry": ...
    @property
    def action_ids(self) -> frozenset[str]: ...
    @property
    def surfaces_by_action(self) -> Mapping[str, frozenset[str]]: ...
    def resolve(self, action_id: str, context: ActionContext) -> ResolvedAction: ...
```

Unknown action IDs resolve to `DISABLED` with exactly:

```text
Action is absent from the source-controlled product capability manifest.
```

```python
# calibrate_pro/application/contracts.py
class CharacterizationKind(str, Enum):
    MATCHED = "matched"
    EXPLICIT_GENERIC = "explicit_generic"
    UNKNOWN = "unknown"

@dataclass(frozen=True)
class PanelCharacterization:
    kind: CharacterizationKind
    provenance: str
    red_xy: tuple[str, str] | None
    green_xy: tuple[str, str] | None
    blue_xy: tuple[str, str] | None
    white_xy: tuple[str, str] | None
    nominal_gamma: str | None

@dataclass(frozen=True)
class DisplayObservation:
    platform_display_id: str
    safe_label: str
    width_px: int
    height_px: int
    refresh_millihz: int
    hdr_enabled: bool | None
    characterization: PanelCharacterization
    capabilities: CapabilityState
    evidence: tuple[str, ...]

@dataclass(frozen=True)
class TargetSpec:
    gamut: str
    white_xy: tuple[str, str]
    cct_kelvin: int | None
    transfer: str
    lut_size: int
    hdr: bool

@dataclass(frozen=True)
class GeneratedAsset:
    kind: Literal["ICC", "CUBE"]
    member_path: str
    sha256: str
    byte_length: int
    format_version: str

@dataclass(frozen=True)
class AssetLocation:
    member_path: str
    private_path: Path

@dataclass(frozen=True)
class GenerationResult:
    assets: tuple[GeneratedAsset, ...]
    locations: tuple[AssetLocation, ...]  # runtime lookup only; never canonicalized
    algorithm_version: str
    dependency_versions: tuple[tuple[str, str], ...]
    evidence_kind: EvidenceKind
    characterization_provenance: str
    canonical_input_sha256: str

@dataclass(frozen=True)
class ExportReceipt:
    published_path: Path
    bundle_sha256: str
    byte_length: int
    member_hashes: tuple[tuple[str, str], ...]
    manifest_sha256: str
    readback_verified: bool
```

`GeneratedAsset.member_path` is a normalized relative POSIX member such as
`assets/display.icc`; it is the only path-like value admitted to a canonical
plan. `AssetLocation.private_path` is held by the service-owned asset store,
must resolve below that store, and is excluded from equality, serialization,
plan hashing, receipts, and UI. An exporter resolves a descriptor through the
store and rechecks its digest before use.

The remaining owners and values are also exact:

```python
# calibrate_pro/application/contracts.py
class EvidenceKind(str, Enum):
    NOT_MEASURED = "not_measured"
    ESTIMATED = "estimated"
    MEASURED = "measured"

@dataclass(frozen=True)
class DashboardModel:
    displays: tuple[DisplayObservation, ...]
    selected_display_id: str | None
    refreshed_utc: str

@dataclass(frozen=True)
class PlanConfirmationReceipt:
    plan_sha256: str
    accepted: bool
    confirmation_consumed: bool
    physical_apply_performed: bool

@dataclass(frozen=True)
class VerificationSnapshot:
    plan_sha256: str
    evidence_kind: EvidenceKind
    describes: Literal["generated_plan", "fake_applied_plan"]
    metrics: tuple[tuple[str, str], ...]
    provenance: str

@dataclass(frozen=True)
class SessionSnapshot:
    dashboard: DashboardModel
    stage: WorkflowStage
    target: TargetSpec | None
    generation: GenerationResult | None
    sealed_plan_sha256: str | None
    confirmation: PlanConfirmationReceipt | None
    apply_receipt: ApplyReceipt | None
    verification: VerificationSnapshot | None

# calibrate_pro/application/journal.py
@dataclass(frozen=True)
class BundleMemberPreview:
    basename: str
    byte_length: int
    sha256: str

@dataclass(frozen=True)
class BundlePreview:
    token: str
    members: tuple[BundleMemberPreview, ...]
    expires_utc: str

class JournalSink(Protocol):
    def preflight(self, action_id: str, correlation_id: str) -> ActionOutcome[None]: ...
    def append_and_sync(self, record: JournalRecord) -> ActionOutcome[None]: ...

# calibrate_pro/application/service.py
class FunctionalRecoveryService:
    def detect(self) -> ActionOutcome[DashboardModel]: ...
    def select_display(self, display_id: str) -> ActionOutcome[SessionSnapshot]: ...
    def use_generic_characterization(self, display_id: str) -> ActionOutcome[SessionSnapshot]: ...
    def select_method(self, method: CalibrationMethod) -> ActionOutcome[SessionSnapshot]: ...
    def set_target(self, target: TargetSpec) -> ActionOutcome[SessionSnapshot]: ...
    def generate(self) -> ActionOutcome[GenerationResult]: ...
    def preview(self) -> ActionOutcome[ApplyPlan]: ...
    def confirm_plan(self, accepted: bool) -> ActionOutcome[PlanConfirmationReceipt]: ...
    def verify(self) -> ActionOutcome[VerificationSnapshot]: ...
    def export(self, bundle_path: Path) -> ActionOutcome[ExportReceipt]: ...
    def preview_diagnostic_bundle(self) -> ActionOutcome[BundlePreview]: ...
    def create_diagnostic_bundle(self, token: str, bundle_path: Path) -> ActionOutcome[ExportReceipt]: ...
    def snapshot(self) -> SessionSnapshot: ...

class FakeAcceptanceService(FunctionalRecoveryService):
    def apply_confirmed_plan(self) -> ActionOutcome[ApplyReceipt]: ...
```

Production composition returns only `FunctionalRecoveryService` and therefore
has no Apply method. `FakeAcceptanceService` is constructed only by the sealed
fake composition. Confirmation is a truthful, non-mutating acknowledgement in
both compositions; the fake runner invokes the separately typed fake-only Apply
after a successful confirmation.

---

## Task 1: Freeze the Baseline, Isolate Tests, and Establish the Action Census

**Files:**
- Modify: `tests/test_professional_features.py`
- Modify: `pyproject.toml`
- Modify: `.github/workflows/ci.yml`
- Create: `tests/test_action_capabilities.py`

- [ ] **Step 1: Write a test that proves the fixed temp path is gone**

Change `TestCLFFormat.test_clf_export` to accept `tmp_path` and write exactly:

```python
output = tmp_path / "test_export.clf"
lut.save_clf(output)
assert output.is_file()
```

Add a static regression assertion that the test module contains neither `tempfile.gettempdir()` nor the literal `test_export.clf` outside the `tmp_path` expression.

- [ ] **Step 2: Declare and prove the supported parallel lane**

Add `pytest-xdist>=3.6,<4` to both `test` and `dev` extras, then run:

```powershell
python -m pytest -n 2 -p no:cacheprovider tests/test_professional_features.py tests/test_lut_engine.py tests/test_pdf_export.py -q
```

Expected: exit 0 with no shared-temp collision. Add this exact lane to the Python 3.12 Windows CI job; do not parallelize the Qt action lane in this task.

- [ ] **Step 3: Freeze the complete initial action ID census RED**

Create `EXPECTED_ACTION_IDS` in `test_action_capabilities.py` with exactly:

```python
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
```

Freeze the source-level surface map in the same test. A surface ID identifies one declared Qt construction site; dynamically repeated display/profile rows reuse that declared site with a data payload, so they do not create undeclared action types:

```python
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
```

The RED test imports `ActionRegistry.load_default()`, which does not exist yet, and verifies exact action and surface equality rather than subsets. Export formats and page destinations are distinct actions because their availability and outputs can differ; only true aliases such as the four Detect surfaces share an ID. `fake_acceptance.apply` is the sole zero-surface internal action; schema validation rejects an empty surface list for every other action.

- [ ] **Step 4: Run RED and preserve the failure**

```powershell
python -m pytest -p no:cacheprovider tests/test_action_capabilities.py -q
```

Expected: import failure for the absent application action registry.

- [ ] **Step 5: Commit only baseline safety and RED census**

```powershell
git add tests/test_professional_features.py tests/test_action_capabilities.py pyproject.toml .github/workflows/ci.yml
git diff --cached --check
git commit -m "test(functional-recovery): freeze action and parallel-safety baseline"
```

---

## Task 2: Implement the Default-Deny Manifest and Typed Action Boundary

**Files:**
- Create: `calibrate_pro/application/__init__.py`
- Create: `calibrate_pro/application/actions.py`
- Create: `calibrate_pro/application/outcomes.py`
- Create: `calibrate_pro/resources/action-capabilities.json`
- Create: `tests/test_action_outcomes.py`
- Modify: `tests/test_action_capabilities.py`

- [ ] **Step 1: Write manifest schema, resolver, and outcome RED tests**

The manifest root is exact:

```json
{"schema_version":1,"default":"disabled","actions":[]}
```

Every action record requires these fields and rejects extras:

```json
{
  "action_id": "display.detect",
  "surfaces": ["dashboard.refresh", "menu.view.refresh", "menu.display.detect"],
  "classification": "read_only",
  "required_stages": ["detect", "method", "preview", "apply", "verify", "save_report"],
  "required_capabilities": [],
  "source_policy": "conditional",
  "frozen_policy": "conditional",
  "handler": "detect_displays",
  "required_modules": ["calibrate_pro.application.service", "calibrate_pro.application.detection"],
  "required_resources": [],
  "receipt_required": true,
  "evidence_modes": ["read_only"],
  "unavailable_disposition": "disabled",
  "unavailable_reason": "Display detection is unavailable in this composition."
}
```

Tests reject duplicate action IDs, duplicate surface IDs, unknown enum values, missing/extra keys, wildcard module names, paths containing `..`, enabled actions with no handler, receipt-required actions with no typed success contract, and any GUI surface absent from the manifest.

Outcome tests require `ActionBoundary.invoke(action_id, stage, operation)` to:

- preserve a returned typed success;
- convert known application exceptions to stable `ActionError` values;
- convert unexpected exceptions to code `UNEXPECTED_ACTION_FAILURE`;
- create one correlation ID and pass it to the journal;
- never report success after an exception;
- preflight diagnostics before any receipt-required local write or fake Apply;
- preserve exact post-effect evidence if final journal sync fails.

- [ ] **Step 2: Encode the exact Phase 0/1 state table**

Use these grouped policies; the manifest contains one full record for every ID from Task 1:

| Policy | Action IDs |
| --- | --- |
| Enabled UI/read-only | `application.exit`, the three `window.*` actions, six `navigation.*` actions, `help.about`, `onboarding.complete`, `display.detect`, `panel_profile.dialog.open`, `panel_profile.edid.select_display`, `panel_profile.import.choose`, `display.hdr_status`, `profile.list.refresh`, `profile.inspect`, `diagnostics.folder.open`, `diagnostics.bundle.preview` |
| Conditional sensorless/local file | `calibration.open_for_display`, `display.characterization.use_generic`, `workflow.select_display`, `calibration.method.sensorless`, the four non-HDR `calibration.target.*` actions, exactly `calibration.preset.srgb_web`, `calibration.preset.rec709`, `calibration.preset.dci_p3`, and `calibration.preset.photography`, `calibration.generate`, `calibration.preview`, `calibration.confirm_plan`, `calibration.decline_plan`, `verification.sensorless`, `report.save`, six `export.active.*` actions, `profile.export`, `settings.default_target`, `settings.lut_size`, `settings.output_directory`, `diagnostics.bundle.create` |
| Fake-acceptance only | zero-surface internal action `fake_acceptance.apply` |
| Hidden | `calibration.all`, `measurement.live.toggle`, `settings.startup`, `settings.minimize_to_tray`, `settings.oled_automation`, `settings.per_app.enabled`, `settings.per_app.rules`, `settings.argyll_path`, `settings.panel_profiles_path` |
| Disabled pending distinct measured/HDR contract | `calibration.method.measured`, `calibration.method.hybrid`, `calibration.target.hdr`, `calibration.preset.hdr10`, `verification.measured`, `settings.hdr` |
| Disabled pending Phase 2 plan/qualification | `panel_profile.edid.create`, `panel_profile.import`, `display.restore_defaults`, `profile.install`, `profile.rename`, `profile.generate_all`, `profile.activate`, `profile.delete`, `patterns.open`, all 17 `ddc.*` actions, `tray.switch_profile` |

Reasons name the missing contract or qualification. No reason says merely “unavailable” when a more specific condition is known.

Freeze resolver predicates in tests instead of letting handlers reinterpret
`conditional`:

- `calibration.generate` requires a selected display, `MATCHED` or
  `EXPLICIT_GENERIC` characterization, sensorless method, valid non-HDR target,
  no live sealed plan, and a ready journal.
- The four enabled preset IDs expand to their current literal tuples:
  `sRGB Web=(sRGB,D65,2.2,false)`,
  `Rec.709=(Rec.709,D65,BT.1886,false)`,
  `DCI-P3=(DCI-P3,D65,2.4,false)`, and
  `Photography=(sRGB,D50,2.2,false)`. `HDR10` is disabled.
- `calibration.preview` requires both ICC and CUBE descriptors whose private
  bytes reparse and match their digests. `calibration.confirm_plan` and
  `calibration.decline_plan` require a live sealed plan, matching capability
  generations, and a live one-use token. Only the former records acceptance.
- `fake_acceptance.apply` additionally requires fake composition, a confirmed
  current plan, matching capability generations, and a ready journal;
  production always resolves it disabled.
- `verification.sensorless` requires a generated plan and either a production
  confirmation (describes `generated_plan`) or a successful fake Apply receipt
  (describes `fake_applied_plan`). It never accepts measured evidence.
- Each `export.active.<format>` requires that exact format in
  `available_export_formats`, verified matching source assets, and a current
  verification snapshot. `report.save` requires the same snapshot and
  `configured_export_directory_valid=True`. `profile.export` requires
  `selected_profile_reparsed=True`.
- `diagnostics.bundle.create` requires a live unconsumed bundle-preview token
  represented by `diagnostic_bundle_preview_live=True`; preview expiry or any
  journal change disables it until a new preview is created.
- `panel_profile.import` requires `validated_import_ready=True` but remains
  Phase-2 disabled; each `ddc.*` action also remains Phase-2 disabled regardless
  of `supported_vcp_codes`. A capability-generation mismatch disables every
  plan-dependent action before its handler can run.

- [ ] **Step 3: Implement the typed loader/resolver and boundary**

Load the manifest with `importlib.resources.files("calibrate_pro").joinpath("resources", "action-capabilities.json")`; decode UTF-8 strictly; reject duplicate JSON object keys with `object_pairs_hook`; validate exact types (`bool` is never accepted as `int`); freeze lists to tuples; and default unknown/invalid actions to disabled.

`ActionBoundary` accepts injected `CorrelationIdFactory` and `JournalSink`. It never catches `KeyboardInterrupt` or `SystemExit`; all `Exception` subclasses become typed failures. The manifest resolver consumes every `ActionContext` field above, and tests mutate each predicate independently to prove a handler cannot broaden policy.

- [ ] **Step 4: Run GREEN and static checks**

```powershell
python -m pytest -p no:cacheprovider tests/test_action_capabilities.py tests/test_action_outcomes.py -q
python -m ruff check calibrate_pro/application tests/test_action_capabilities.py tests/test_action_outcomes.py
python -m mypy calibrate_pro/application
```

Expected: exact action inventory, manifest closure, default deny, and typed outcomes pass.

- [ ] **Step 5: Commit**

```powershell
git add calibrate_pro/application calibrate_pro/resources/action-capabilities.json tests/test_action_capabilities.py tests/test_action_outcomes.py
git diff --cached --check
git commit -m "feat(functional-recovery): add action truth and typed outcomes"
```

---

## Task 3: Add Durable Redacted Diagnostics and User-Controlled Bundles

**Files:**
- Create: `calibrate_pro/application/journal.py`
- Create: `tests/test_diagnostic_journal.py`
- Modify: `calibrate_pro/application/outcomes.py`

- [ ] **Step 1: Write RED tests for the complete allowlisted schema**

Freeze `JournalRecord` with these fields only:

```python
@dataclass(frozen=True)
class JournalRecord:
    timestamp_utc: str
    correlation_id: str
    product_version: str
    runtime_mode: Literal["source", "frozen", "fake_acceptance"]
    platform_version: str
    action_id: str
    workflow_stage: str
    capability_flags: tuple[tuple[str, bool], ...]
    outcome: Literal["success", "failure"]
    exception_type: str | None
    error_code: str | None
    technical_category: str | None
    redacted_message: str | None
    display_pseudonym: str | None
    plan_sha256: str | None
    asset_sha256: tuple[str, ...]
    apply_phase_flags: tuple[tuple[str, bool], ...]
    recovery_guarantee: str | None
    export_basename: str | None
    export_sha256: str | None
```

Tests prove:

- exact schema/ordering and strict UTF-8 JSON Lines;
- 1 MiB rotation with five retained files;
- `flush()` plus `os.fsync()` before a success outcome is returned;
- append/readback after process restart;
- token, password, private key, home path, username, raw EDID, serial, PnP path, confirmation token, and environment-value redaction;
- a private salt store yields stable HMAC-SHA-256 pseudonyms but never writes the salt into logs/bundles;
- salt-store verification failure yields `display_pseudonym=None` rather than a raw/weak identifier;
- bundle preview shows exact basenames, sizes, and hashes; bundle creation requires that preview token, performs a second redaction pass, and atomically publishes one ZIP;
- injected folder opener is called only for `diagnostics.folder.open`.

The failure ordering is exact. Before a receipt-required local write or
`fake_acceptance.apply`, `ActionBoundary` calls `JournalSink.preflight()` to
open, permission-check, rotate if needed, and reserve one bounded record. A
preflight failure returns `DIAGNOSTIC_JOURNAL_UNAVAILABLE` with
`effect_state="none"` and does not invoke the operation. After an operation,
`append_and_sync()` writes the final success/failure record, flushes, and
fsyncs. If this final sync fails, the boundary returns
`ACTION_COMPLETED_DIAGNOSTICS_FAILED`, never success. It preserves an actual
published export as `(basename, sha256)` with
`effect_state="local_write_published"`; for fake Apply it preserves the exact
phase flags and recovery guarantee with
`effect_state="fake_apply_attempted"`. Read-only/UI failures use `none`.
Production physical mutation remains prohibited; a later Phase 2 plan must
define crash-safe transactional diagnostics before enabling it.

- [ ] **Step 2: Run RED**

```powershell
python -m pytest -p no:cacheprovider tests/test_diagnostic_journal.py -q
```

Expected: import failure for the absent journal.

- [ ] **Step 3: Implement fail-closed local storage**

Resolve the production directory as `%LOCALAPPDATA%/Build Universe/Calibrate Pro/Diagnostics`; reject an absent/non-absolute `LOCALAPPDATA` rather than falling back to the working directory. Use sibling temporary files and `os.replace` for rotation/bundles.

`WindowsPrivateSaltStore` creates a random 32-byte salt separately from logs and verifies that the salt file is owned by the current user and not readable by broad principals before returning it. If ctypes security-descriptor checks are unavailable or inconclusive, return no salt. Non-Windows implementations return no stable pseudonym unless an equivalently verified store is injected.

Central redaction operates on scalar values before JSON encoding and again on bundle bytes. It keeps basenames but removes full paths. Unknown fields are rejected rather than persisted.

- [ ] **Step 4: Run GREEN and restart/fault subsets**

```powershell
python -m pytest -p no:cacheprovider tests/test_diagnostic_journal.py -q
python -m pytest -p no:cacheprovider tests/test_diagnostic_journal.py -k "restart or rotation or fsync or redaction or bundle" -q
python -m ruff check calibrate_pro/application/journal.py tests/test_diagnostic_journal.py
python -m mypy calibrate_pro/application/journal.py
```

- [ ] **Step 5: Commit**

```powershell
git add calibrate_pro/application/journal.py calibrate_pro/application/outcomes.py tests/test_diagnostic_journal.py
git diff --cached --check
git commit -m "feat(functional-recovery): add durable redacted diagnostics"
```

---

## Task 4: Define Immutable Observations and Atomic Read-Only Detection

**Files:**
- Create: `calibrate_pro/application/contracts.py`
- Create: `calibrate_pro/application/detection.py`
- Create: `tests/recovery_fakes.py`
- Create: `tests/test_recovery_detection.py`
- Modify: `calibrate_pro/gui/app.py`

- [ ] **Step 1: Write immutable contract and detector RED tests**

Tests cover exact type/range checks, defensive copies, stable platform IDs, safe labels, matched/generic/unknown characterization, explicit provenance, HDR unknown versus false, and capability evidence.

The detector Protocol is:

```python
class DisplayDetector(Protocol):
    def detect(self) -> tuple[DisplayObservation, ...]: ...
```

`DetectionService.refresh(previous)` returns `ActionOutcome[DashboardModel]`; it builds a complete candidate tuple before replacing the prior model. On any required detector failure it returns a typed error and the caller retains the complete previous model.

Add GUI-level tests for:

- detector success with two displays;
- detector exception before the first display;
- exception while enriching the second display;
- matched, explicit generic, and unknown panel cards;
- no reference to an uninitialized `StartupManager` or partial card list;
- EDID Create disabled when validated chromaticity evidence is absent.

- [ ] **Step 2: Run RED without constructing production hardware services**

```powershell
$env:QT_API='pyside6'
$env:QT_QPA_PLATFORM='offscreen'
python -m pytest -p no:cacheprovider tests/test_recovery_detection.py -q
```

- [ ] **Step 3: Implement read-only production observation**

Move Qt screen enumeration out of `gui.app` into `detection.py`. Use `QScreen.name()` as the in-session platform display ID and `QScreen.manufacturer()/model()` only for safe matching; never journal serials or raw EDID. Convert refresh Hz to a rounded integer millihertz and dimensions to positive integers.

Panel matching returns:

- `MATCHED` only with a real database record and its primaries/provenance;
- `EXPLICIT_GENERIC` only after the user invokes `display.characterization.use_generic`;
- `UNKNOWN` with null primaries and a disabled sensorless-method reason.

Read-only HDR and stored-calibration status readers are injected enrichers. A nonessential status-reader failure yields explicit unknown status; it cannot leave a local variable unbound or invalidate already proven display identity.

- [ ] **Step 4: Make Dashboard consume one atomic model**

`DashboardPage` receives a `DashboardModel` and replaces its card container only after every new card is constructed. Remove its direct `StartupManager`, panel database, and hard-coded `panel=None`/`edid_chromaticity=None` paths. The Add Display dialog may scan read-only displays but keeps EDID creation and profile import commit disabled by registry state.

- [ ] **Step 5: Run GREEN and prove no mutation import**

```powershell
python -m pytest -p no:cacheprovider tests/test_recovery_detection.py tests/test_gui_truthfulness.py -q
python -m ruff check calibrate_pro/application/contracts.py calibrate_pro/application/detection.py calibrate_pro/gui/app.py
python -m mypy calibrate_pro/application/contracts.py calibrate_pro/application/detection.py
```

Extend `test_actuator_boundary.py` so the detection module fails if it imports hardware, startup writers, DDC, LUT writers, profile installers, or `adapters.windows_display_state`.

- [ ] **Step 6: Commit**

```powershell
git add calibrate_pro/application/contracts.py calibrate_pro/application/detection.py calibrate_pro/gui/app.py tests/recovery_fakes.py tests/test_recovery_detection.py tests/test_actuator_boundary.py
git diff --cached --check
git commit -m "feat(functional-recovery): add atomic read-only detection"
```

---

## Task 5: Generate Deterministic Assets and Publish One Atomic Export Bundle

**Files:**
- Create: `calibrate_pro/application/generation.py`
- Create: `calibrate_pro/application/export.py`
- Modify: `calibrate_pro/core/icc_profile.py`
- Modify: `calibrate_pro/workflow.py`
- Create: `tests/test_sensorless_generation.py`
- Create: `tests/test_atomic_export.py`
- Modify: `tests/test_workflow.py`

- [ ] **Step 1: Write generation RED tests with non-empty assertions**

Use one fixed matched characterization and one explicit generic characterization. Tests require:

```python
first = generator.generate(observation, target, staging_a)
second = generator.generate(observation, target, staging_b)
assert len(first.assets) == 2
assert [asset.kind for asset in first.assets] == ["ICC", "CUBE"]
assert [asset.sha256 for asset in first.assets] == [asset.sha256 for asset in second.assets]
assert [asset.member_path for asset in first.assets] == ["assets/display.icc", "assets/display.cube"]
assert all(asset.byte_length > 128 for asset in first.assets)
assert writer.calls == []
```

Also reject unknown characterization, HDR target, invalid custom white point, unsupported LUT size, nonempty staging directory, path escape, oversized output, malformed ICC, malformed CUBE, declared-size mismatch, non-finite LUT samples, and changed dependency/algorithm identity.

- [ ] **Step 2: Make ICC bytes deterministic without changing legacy defaults silently**

Add `creation_date: datetime | None` to `create_display_profile()` and pass it to `ICCHeader`. Existing callers that omit it retain existing behavior; the recovery generator always supplies the algorithm constant:

```python
ICC_PROFILE_EPOCH = datetime(2026, 1, 1, 0, 0, 0)
SENSORLESS_ALGORITHM_VERSION = "calibrate-pro-sensorless-v1"
```

Add `validate_icc_profile_bytes(payload)` to check declared size equals actual length, `acsp` signature, supported class/color space/version, tag-count/table bounds, aligned nonoverlapping tag extents, and bounded size. Reparse CUBE through `LUT3D.load_cube`, then compare dimensions and finite samples with the generated in-memory LUT.

- [ ] **Step 3: Extend `ApplyPlan` for generated assets without implying installation**

Add immutable `GeneratedAssetRef(kind, member_path, sha256, byte_length)`, `generated_assets`, `processing_domain`, `evidence_kind`, and `characterization_provenance`. `member_path` is the stable logical member from the descriptor; absolute/private staging paths remain only in the service-owned `AssetLocation` map. Keep `icc_profile_path`, `vcgt_path`, and `dwm_lut_path` exclusively for proposed physical application. A generated ICC appears in `generated_assets`; it does not set `icc_profile_path` in production Phase 1.

Canonical plan hashing includes only the new stable descriptor fields, never `AssetLocation.private_path`. Two generations under distinct private roots must produce byte-identical canonical plan bodies and plan digests. Capability validation continues to gate only requested mutations. Tests reject duplicate asset kinds/member paths, absolute or non-normalized member paths, digest mismatch shape, empty generated set for a sensorless preview, and measured evidence on a sensorless plan.

- [ ] **Step 4: Write export RED tests for operation-level atomicity**

The exporter creates one ZIP bundle, not a sequence of independently published destination files. Tests require:

- at least one verified asset;
- canonical `manifest.json`, human-readable `report.html`, and exact asset members;
- manifest asset hashes, plan digest, apply receipt phase flags or explicit `not_applied`, verification evidence/source, algorithm/dependency versions, recovery guarantee;
- absence of tokens, raw IDs, serials, usernames, full source paths, and raw measurement payloads;
- sibling temporary ZIP, close/fsync, reopen, member reparse/hash, whole-file hash, then one `os.replace`;
- injected write/close/readback/replace failures leave no destination and no success receipt;
- existing destination is refused rather than partially overwritten;
- zero-file export fails.

- [ ] **Step 5: Implement deterministic generation and atomic exporter**

Generation writes only into a service-owned private staging directory. The asset store maps stable member paths to confined private paths and rechecks the mapping/digest on every read. Run metadata time/correlation IDs and private roots stay outside the asset/plan hash domains. Dependency versions are sorted exact package/version pairs; characterization provenance participates in the canonical input digest.

Export member order and ZIP timestamps are fixed. `ExportReceipt.readback_verified` can be true only after both archive-member and whole-file digest verification.

- [ ] **Step 6: Run focused GREEN and writer-import guards**

```powershell
python -m pytest -p no:cacheprovider tests/test_sensorless_generation.py tests/test_atomic_export.py tests/test_workflow.py -q
python -m ruff check calibrate_pro/application/generation.py calibrate_pro/application/export.py calibrate_pro/core/icc_profile.py calibrate_pro/workflow.py
python -m mypy calibrate_pro/application/generation.py calibrate_pro/application/export.py calibrate_pro/workflow.py
```

Extend `test_actuator_boundary.py` so generation/export cannot import physical adapters, hardware, startup, `lut_system`, profile installer, or platform writer modules.

- [ ] **Step 7: Commit**

```powershell
git add calibrate_pro/application/generation.py calibrate_pro/application/export.py calibrate_pro/core/icc_profile.py calibrate_pro/workflow.py tests/test_sensorless_generation.py tests/test_atomic_export.py tests/test_workflow.py tests/test_actuator_boundary.py
git diff --cached --check
git commit -m "feat(functional-recovery): generate and export verified sensorless assets"
```

---

## Task 6: Build the One-Session Service and Fake-Only Apply Proof

**Files:**
- Create: `calibrate_pro/application/service.py`
- Create: `calibrate_pro/application/composition.py`
- Create: `calibrate_pro/application/fake_acceptance.py`
- Create: `calibrate_pro/resources/fake-acceptance-display.json`
- Modify: `calibrate_pro/workflow.py`
- Modify: `calibrate_pro/actuation.py`
- Create: `tests/test_functional_recovery_service.py`
- Create: `tests/test_fake_acceptance.py`

- [ ] **Step 1: Write the full vertical-slice RED test**

The fake-composed service must complete:

```python
detected = service.detect()
selected = service.select_method(CalibrationMethod.SENSORLESS)
targeted = service.set_target(valid_target)
generated = service.generate()
previewed = service.preview()
confirmed = service.confirm_plan(accepted=True)
applied = service.apply_confirmed_plan()
verified = service.verify()
exported = service.export(bundle_path)
```

This test uses `FakeAcceptanceService`. Assert every value is `ActionSuccess`, confirmation reports `physical_apply_performed=False`, the plan contains two generated assets, the fake adapter call order is `capture, apply, verify`, the receipt flags are reproduced exactly, verification is `EvidenceKind.ESTIMATED`, export exists/readbacks, and journal records share each action’s correlation ID.

Production composition tests assert `calibration.confirm_plan` succeeds as a non-mutating acknowledgement, the returned `FunctionalRecoveryService` has no `apply_confirmed_plan` attribute, `fake_acceptance.apply` resolves disabled, no physical adapter module is imported or constructed, generation/preview/estimated verification/export still work, verification describes `generated_plan`, and no mutation call occurs.

- [ ] **Step 2: Write invalidation and recovery RED tests**

Cover display, method, target, characterization, capability, and generated-asset changes. Each invalidates the sealed plan and consumes/clears confirmation. Cover decline, expiry, token replay, plan mismatch, capability drift, capture failure, apply failure, readback failure, restore success, restore failure, and serialized concurrent Apply.

For every unsuccessful apply attempt assert:

- zero or exact expected fake calls;
- `WorkflowController` returns to `PREVIEW` with no live token;
- partial `ApplyReceipt` flags are preserved when a receipt exists;
- the GUI-facing outcome is failure, never success;
- a new deliberate preview is required before retry.

- [ ] **Step 3: Add explicit controller/coordinator invalidation**

Add:

```python
class WorkflowController:
    def invalidate_preview(self) -> None: ...
    def apply_failed(self) -> None: ...

class ActuationCoordinator:
    def invalidate_confirmation(self) -> None: ...
```

`invalidate_preview()` clears preview and returns a pre-apply session to `PREVIEW`; `apply_failed()` is legal only from `APPLY` and returns to `PREVIEW`. The application service calls both on every plan-affecting change. Only `FakeAcceptanceService.apply_confirmed_plan()` enters `APPLY`, and it calls `apply_failed()` in a `finally`-safe failure path after coordinator Apply begins.

- [ ] **Step 4: Implement composition with no adapter injection ambiguity**

```python
class CompositionMode(str, Enum):
    PRODUCTION = "production"
    FAKE_ACCEPTANCE = "fake_acceptance"

def build_production_service() -> FunctionalRecoveryService: ...
def build_fake_acceptance_service(output_root: Path) -> FakeAcceptanceService: ...
```

`build_production_service()` does not import `adapters.windows_display_state` and has no constructor parameter for an adapter. `build_fake_acceptance_service()` accepts only an empty output root, constructs its own `RecordingFakeAdapter`, consumes only the bundled synthetic resource, and rejects nonempty/out-of-root paths. It cannot be switched to a production adapter by environment variable, plugin, or command argument.

- [ ] **Step 5: Implement method-bound verification and export**

The service chooses verifier from `sealed_plan.method`. Sensorless verification receives characterization plus confirmation/apply state and emits only `ESTIMATED`/`NOT_MEASURED`. A production confirmation marks the generated plan acknowledged but not applied; fake Apply is a distinct state transition and journal action. Measured and hybrid selections return their manifest reason before constructing a worker. Export consumes the immutable service snapshot, not current widgets.

- [ ] **Step 6: Run GREEN and authority gates**

```powershell
python -m pytest -p no:cacheprovider tests/test_functional_recovery_service.py tests/test_fake_acceptance.py tests/test_workflow.py tests/test_actuator_boundary.py -q
python -m ruff check calibrate_pro/application/service.py calibrate_pro/application/composition.py calibrate_pro/application/fake_acceptance.py calibrate_pro/workflow.py calibrate_pro/actuation.py
python -m mypy calibrate_pro/application/service.py calibrate_pro/application/composition.py calibrate_pro/application/fake_acceptance.py calibrate_pro/workflow.py calibrate_pro/actuation.py
```

- [ ] **Step 7: Commit**

```powershell
git add calibrate_pro/application calibrate_pro/resources/fake-acceptance-display.json calibrate_pro/workflow.py calibrate_pro/actuation.py tests/test_functional_recovery_service.py tests/test_fake_acceptance.py tests/test_workflow.py tests/test_actuator_boundary.py
git diff --cached --check
git commit -m "feat(functional-recovery): close fake-adapter sensorless workflow"
```

---

## Task 7: Bind Every Active GUI Surface to One Dynamic Action Graph

**Files:**
- Create: `calibrate_pro/gui/action_binding.py`
- Create: `calibrate_pro/gui/plan_dialog.py`
- Modify: `calibrate_pro/gui/app.py`
- Modify: active page files `calibrate.py`, `verify.py`, `profiles.py`, `ddc_control.py`, `settings.py`
- Modify: `calibrate_pro/gui/theme.py` imports only if needed to break the page/app cycle
- Create: `tests/test_active_gui_actions.py`
- Modify: `tests/test_gui_preview_mode.py`
- Modify: `tests/test_gui_truthfulness.py`
- Modify: `tests/test_qt_binding_contract.py`
- Modify: `pyproject.toml`
- Modify: `.github/workflows/ci.yml`

- [ ] **Step 1: Write signal-aware binding RED tests**

Freeze these binder interfaces:

```python
@dataclass(frozen=True)
class SurfaceBinding:
    surface_id: str
    action_id: str
    signal_name: Literal[
        "triggered", "clicked", "activated", "currentIndexChanged",
        "currentTextChanged", "valueChanged", "toggled", "editingFinished",
        "itemChanged", "page_changed", "calibrate_clicked"
    ]

class ActionBinder:
    def bind(self, widget: QObject, binding: SurfaceBinding, payload: Callable[..., object]) -> None: ...
    def refresh_all(self) -> None: ...
```

The binder sets `calibrateActionId` and `calibrateSurfaceId` Qt properties, connects the named signal once, resolves the action against current session context on every emission, and invokes one handler from the canonical handler table. It must support `QAction`, `QPushButton`, mode/display/profile cards, `QComboBox`, `QSlider`, `QCheckBox`, `QLineEdit`, `QTableWidget`, sidebar navigation, `QSystemTrayIcon`, and `QShortcut`.

Tests assert:

```python
surface_ids = [binding.surface_id for binding in bindings]
assert len(surface_ids) == len(set(surface_ids))
assert registry.surfaces_by_action == EXPECTED_SURFACES_BY_ACTION
expected_bound = {
    surface_id
    for action_id, declared in EXPECTED_SURFACES_BY_ACTION.items()
    if registry.resolve(action_id, context).disposition is not ActionDisposition.HIDDEN
    for surface_id in declared
}
assert set(surface_ids) == expected_bound
assert alias_groups["display.detect"] == {
    "dashboard.refresh", "menu.view.refresh", "menu.display.detect", "dialog.add_display.scan"
}
```

Do not assert action IDs are unique across surfaces.

- [ ] **Step 2: Write active-window RED tests with services injected before construction**

Instantiate `CalibrateProWindow(service=fake_service, registry=registry)` offscreen. Exercise every public UI signal and verify enabled/disabled/hidden state, exact reason text, handler parity, dynamic reevaluation, and alias behavior.

Required cases include:

- complete surface census across menu, dashboard, active pages, tray, shortcuts, and confirmation dialog;
- atomic detector success/failures and matched/generic/unknown states;
- Detect → Method → Target → Generate → Preview → Confirm; then, only in fake composition, the zero-surface fake Apply → estimated Verify → Save/Report;
- preview dialog exact display/method/targets/assets/hashes/mutations/evidence/verification/recovery guarantee;
- decline/expiry/replay/drift/capability-loss zero-write behavior;
- partial apply/recovery receipts and correlation IDs;
- export success/readback and injected disk failure;
- measured/hybrid/HDR disabled reasons and no worker construction;
- profile/DDC/tray/status-only paths cannot report success;
- only consumed default-target, LUT-size, and export-directory settings visible;
- no success toast/status/dialog without an `ActionSuccess` value.

- [ ] **Step 3: Remove direct worker and writer routes from active pages**

Delete active `NativeCalibrationWorker`, `HardwareFirstWorker`, and `NativeVerifyWorker` paths and their HID/native imports from the active page graph. `CalibratePage` and `VerifyPage` submit action payloads to the injected service. `DDCControlPage` does not instantiate a controller or call VCP methods; Phase 1 controls resolve disabled. Remove Profiles → Generate All’s nonexistent engine import and route all profile buttons through the manifest.

Move shared theme/widget imports so active pages no longer import `gui.app`; use `gui.theme` and `build_ui.widgets` directly. Re-run `index internals --root . --json` and require that the `gui.app`/active-page cycle disappears.

- [ ] **Step 4: Make the active shell an injected composition root**

`CalibrateProWindow.__init__` accepts service/registry with production defaults supplied by `commands.gui`, not hidden inside page constructors. Pages receive the service/binder explicitly. UI state renders from immutable service snapshots; target edits invalidate preview before widgets display the new state.

`PlanConfirmationDialog` renders from the sealed plan only. It never receives or displays the confirmation token. Accept dispatches `calibration.confirm_plan`; closing or declining dispatches `calibration.decline_plan` and consumes the current token. Production acceptance never invokes Apply. The fake-smoke runner may invoke the separate zero-surface `fake_acceptance.apply` action only after the dialog acceptance succeeds.

- [ ] **Step 5: Hide/disable every unsupported surface**

- Hide Calibrate All in menu/dashboard/tray.
- Hide live sensor/read buttons and inert startup/tray/OLED/app-rule settings.
- Disable measured/hybrid/HDR, profile activation/deletion/generation/rename, DDC operations, restore defaults, profile install/import commit, test patterns, and tray switching with manifest reasons.
- Keep profile export conditional on an existing reparsed source file and menu/report export conditional on active verified assets.
- Do not construct `CalibrationGuard` or another startup service from the active Phase 1 shell.

- [ ] **Step 6: Run the complete offscreen action lane GREEN**

```powershell
$env:QT_API='pyside6'
$env:QT_QPA_PLATFORM='offscreen'
python -m pytest -p no:cacheprovider tests/test_active_gui_actions.py tests/test_gui_preview_mode.py tests/test_gui_truthfulness.py tests/test_qt_binding_contract.py -q
python -m pytest -p no:cacheprovider tests/test_active_gui_actions.py --cov=calibrate_pro.gui.app --cov=calibrate_pro.gui.action_binding --cov=calibrate_pro.application --cov-branch --cov-report=term-missing --cov-fail-under=85 -q
index internals --root . --json
```

Expected: all tests and 85% active-action branch coverage pass; no active GUI/page cycle. Update `[tool.coverage.run]` to stop omitting all GUI/tray code. Omit only named paint-only widgets that contain no action orchestration, and add this exact coverage lane to Python 3.12 Windows CI.

- [ ] **Step 7: Commit**

```powershell
git add calibrate_pro/gui calibrate_pro/application pyproject.toml .github/workflows/ci.yml tests/test_active_gui_actions.py tests/test_gui_preview_mode.py tests/test_gui_truthfulness.py tests/test_qt_binding_contract.py tests/test_actuator_boundary.py
git diff --cached --check
git commit -m "feat(functional-recovery): bind active GUI to truthful actions"
```

---

## Task 8: Close Wheel, Frozen, Staged, and Packaged Fake-Acceptance Graphs

**Files:**
- Create: `calibrate_pro/resources/fake-acceptance-expected.json`
- Modify: `pyproject.toml`, `MANIFEST.in`
- Modify: `packaging/frozen-modules.json`, `packaging/components-win64.json`
- Modify: `calibrate-pro.spec`
- Modify: `calibrate_pro/commands/gui.py`, `calibrate_pro/frozen_main.py`
- Modify: `scripts/release_artifacts.py`, `scripts/smoke_frozen.ps1`, `scripts/build_windows.ps1`
- Create: `scripts/verify_fake_acceptance_receipt.py`
- Create: `tests/test_frozen_action_closure.py`
- Modify packaging/release tests named in the file map

- [ ] **Step 1: Write installed-resource and exact-closure RED tests**

Tests build a wheel, install it with `--no-deps --target` into an empty temporary directory, prepend that directory to a fresh current-interpreter process (whose declared test dependencies are already installed), and use `importlib.resources.files("calibrate_pro")` to read all three JSON resources. They also inspect wheel `RECORD`. Source-tree success is insufficient; the canonical Windows builder later proves the fully isolated hash-locked dependency installation.

For each action enabled in frozen mode, derive its handler’s transitive first-party imports with an AST walk and compare them with the action record’s `required_modules`. Then require every derived/listed module to appear in `first_party_exact` or `optional_first_party_exact`. Require each action resource in wheel RECORD, PyInstaller `datas`, staged inventory, and a matching `components-win64.json` artifact/component record.

Exercise optional imports in available and unavailable states. Reject wildcard modules, unlisted distributions, unexpected staged files, missing license/source records, and `calibrate_pro.calibration.native_loop` or `calibrate_pro.patterns.display` reachability from enabled actions.

- [ ] **Step 2: Package the source-controlled resources explicitly**

Change package data to:

```toml
[tool.setuptools.package-data]
calibrate_pro = ["resources/*.ico", "resources/*.png", "resources/*.json"]
```

Add matching sdist, metadata, wheel, PyInstaller data, staging, and component-policy assertions. Do not add fictitious `modules` or `resources` fields to `frozen-modules.json`; preserve its existing schema.

- [ ] **Step 3: Compute the positive action closure and update the real manifests**

Add only the new Phase 0/1 modules actually reachable by the three frozen commands and enabled actions to `first_party_exact`. Keep truly optional platform modules in `optional_first_party_exact`. Remove a legacy module only when the installed-wheel/frozen analysis proves it unreachable from all approved commands; do not broaden to the full package.

Keep frozen commands exactly `doctor`, `gui`, `hdr`. Fake acceptance is an option to `gui`, not a fourth command, so `frozen-features.json` command inventory does not change.

- [ ] **Step 4: Define the exact packaged smoke grammar and refusal boundary**

`commands.gui.run()` parses only:

```text
gui
gui --fake-acceptance-smoke --output ABSOLUTE_EMPTY_DIRECTORY
```

Unknown flags, missing output, relative/nonempty output, and any adapter/provider/plugin flag exit 2 before window construction. Fake mode forces its own composition before creating `CalibrateProWindow`, runs the active UI action path offscreen, closes cleanly, writes `fake-acceptance-receipt.json`, and returns 0. It never enters the indefinite event loop and never imports a physical adapter.

The bundled fake display resource also contains one fixed
`failure_after_success` detector record with the literal message
`fixture-token=CALIBRATE_FAKE_SECRET_123 path=C:\Users\FixtureUser\sensitive.icc`.
After the successful vertical slice, fake smoke invokes `display.detect` once
more; the sealed fake detector raises that record, the boundary returns the
expected typed error, and receipt verification proves neither the sentinel
token nor the full path survives the persisted journal or diagnostics bundle.
This behavior is intrinsic to the bundled fake composition: no CLI flag,
environment variable, or external failure payload can select it.

Pin expected ICC, CUBE, export-bundle, manifest, and plan hashes in `fake-acceptance-expected.json` only after two independent clean runs produce the same bytes and strict reparsers pass. The test reads pinned literals; it does not compute expected values with the production generator.

- [ ] **Step 5: Extend frozen smoke and staged audit**

Add this sequence to `scripts/smoke_frozen.ps1`:

```powershell
$receiptRoot = Join-Path $env:TEMP ("calibrate-pro-fake-smoke-" + [guid]::NewGuid())
New-Item -ItemType Directory -Path $receiptRoot | Out-Null
& $cli gui --fake-acceptance-smoke --output $receiptRoot
if ($LASTEXITCODE -ne 0) { throw 'Frozen fake-acceptance smoke failed' }
& $VerifierPython (Join-Path $PSScriptRoot 'verify_fake_acceptance_receipt.py') `
    --root $receiptRoot `
    --expected (Join-Path (Split-Path $PSScriptRoot -Parent) 'calibrate_pro\resources\fake-acceptance-expected.json')
if ($LASTEXITCODE -ne 0) { throw 'Frozen fake-acceptance receipt verification failed' }
```

Add mandatory `[string]$VerifierPython` to `smoke_frozen.ps1`; resolve it to an existing file before any probe. Modify `build_windows.ps1` to pass its hash-locked `$releasePython` in the existing smoke call. Every repository script/resource path resolves from `$PSScriptRoot`, never the caller's working directory. Create `scripts/verify_fake_acceptance_receipt.py` and tests for exact schema, hashes, disabled-reason inventory, estimated evidence, fake apply receipt flags, the intrinsic detector failure/redaction, production-adapter absence, and orderly exit. Keep existing help/version/doctor/GUI/HDR probes.

- [ ] **Step 6: Run source/wheel/frozen-contract GREEN**

```powershell
python -m pytest -p no:cacheprovider tests/test_frozen_action_closure.py tests/test_frozen_module_allowlist.py tests/test_packaging_contract.py tests/test_release_metadata.py tests/test_release_artifacts.py tests/test_release_pipeline_contract.py tests/test_fake_acceptance.py -q
$pythonDist = Join-Path $env:TEMP ("calibrate-pro-python-dist-" + [guid]::NewGuid())
New-Item -ItemType Directory -Path $pythonDist | Out-Null
python -m build --wheel --sdist --no-isolation --outdir $pythonDist
```

Expected: exact resource/module/component closure and fake smoke contracts pass; wheel and sdist build. The canonical Windows builder performs the pinned `twine check` in Step 7.

- [ ] **Step 7: Build one unsigned installer-free candidate with the canonical script**

```powershell
$out = Join-Path $env:TEMP ("calibrate-pro-recovery-" + [guid]::NewGuid())
New-Item -ItemType Directory -Path $out | Out-Null
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/build_windows.ps1 -Unsigned -SkipInstaller -SkipSourceProvenance -OutputRoot $out
```

Expected: canonical build, staged audits, read-only doctor, normal liveness probes, pinned-interpreter receipt verification, and fake vertical slice all exit 0. `build_windows.ps1` already invokes `smoke_frozen.ps1` against `$out\dist\CalibratePro`; do not run a redundant second smoke after its temporary locked environment is removed. Executable manifests remain unelevated.

- [ ] **Step 8: Commit packaging closure**

```powershell
git add calibrate_pro/resources/action-capabilities.json calibrate_pro/resources/fake-acceptance-display.json calibrate_pro/resources/fake-acceptance-expected.json calibrate_pro/commands/gui.py calibrate_pro/frozen_main.py pyproject.toml MANIFEST.in packaging/frozen-modules.json packaging/frozen-features.json packaging/components-win64.json calibrate-pro.spec scripts/release_artifacts.py scripts/smoke_frozen.ps1 scripts/build_windows.ps1 scripts/verify_fake_acceptance_receipt.py tests/test_frozen_action_closure.py tests/test_frozen_module_allowlist.py tests/test_packaging_contract.py tests/test_release_metadata.py tests/test_release_artifacts.py tests/test_release_pipeline_contract.py tests/test_fake_acceptance.py
git diff --cached --check
git commit -m "build(functional-recovery): close packaged fake acceptance"
```

---

## Task 9: Verify, Document Evidence, Review, and Stop Before Hardware

**Files:**
- Modify: `README.md`, `docs/TECHNICAL.md`, `docs/ENTERPRISE-READINESS.md`
- Create: `docs/release-evidence/functional-recovery/README.md`
- Create: `docs/release-evidence/functional-recovery/disabled-actions.json`
- Create: `docs/release-evidence/functional-recovery/source-gates.json`
- Create only after an actual packaged run: `docs/release-evidence/functional-recovery/packaged-candidate.json`

- [ ] **Step 1: Document exact support and limitations**

Call the work functional recovery, not a regression. Document production support for read-only detection, matched/explicit-generic sensorless generation, immutable preview, estimated verification, atomic export, diagnostics, and disabled reasons. State that physical Apply and measured paths remain unqualified/disabled and recovery is `IN_PROCESS_BEST_EFFORT`, not crash-safe.

- [ ] **Step 2: Run focused safety and action gates**

```powershell
$env:QT_API='pyside6'
$env:QT_QPA_PLATFORM='offscreen'
python -m pytest -p no:cacheprovider tests/test_action_capabilities.py tests/test_action_outcomes.py tests/test_diagnostic_journal.py tests/test_recovery_detection.py tests/test_sensorless_generation.py tests/test_atomic_export.py tests/test_functional_recovery_service.py tests/test_active_gui_actions.py tests/test_fake_acceptance.py tests/test_frozen_action_closure.py tests/test_actuator_boundary.py -q
```

Expected: exit 0 and no physical writer import/call.

- [ ] **Step 3: Run the complete supported source gates sequentially**

```powershell
python -m pytest -p no:cacheprovider tests -q
python -m ruff check .
python -m ruff format --check .
python -m mypy --platform win32
python -m pip check
git diff --check 8ed017577b34c7a6d2bfe04a17a254f377ad7b7c...HEAD
```

Record exact commands, commit, platform, counts, duration, and exit codes in `source-gates.json`. Do not translate a legacy failure into a pass; separate pre-existing failures from branch regressions.

- [ ] **Step 4: Re-run supported parallel and active-action coverage lanes**

```powershell
python -m pytest -n 2 -p no:cacheprovider tests/test_professional_features.py tests/test_lut_engine.py tests/test_pdf_export.py -q
python -m pytest -p no:cacheprovider tests/test_active_gui_actions.py --cov=calibrate_pro.gui.app --cov=calibrate_pro.gui.action_binding --cov=calibrate_pro.application --cov-branch --cov-report=term-missing --cov-fail-under=85 -q
```

- [ ] **Step 5: Run the pinned Windows candidate and disposable-VM checklist**

Use the exact Task 8 build output. In an unelevated Windows VM with networking disabled and no separate Python installation:

```powershell
& '.\CalibratePro\CalibrateProCLI.exe' doctor --json
$smoke = Join-Path $env:TEMP 'calibrate-pro-functional-recovery-smoke'
New-Item -ItemType Directory -Path $smoke | Out-Null
& '.\CalibratePro\CalibrateProCLI.exe' gui --fake-acceptance-smoke --output $smoke
Get-Content "$smoke\fake-acceptance-receipt.json"
```

Also launch/exit the GUI normally, verify measured mode fails closed, verify the intrinsic bundled fake-detector failure and persisted redaction after restart, compare deterministic hashes, verify staged/license inventories, and record installer/portable hashes and PE manifests if the installer lane is run. Do not connect hardware or enable network.

Write `packaged-candidate.json` only from observed outputs; otherwise record the gate as not run.

- [ ] **Step 6: Request two independent reviews**

Use `superpowers:requesting-code-review` for:

1. action truth, workflow state, deterministic generation/export, diagnostics, GUI behavior;
2. no-hardware boundary, frozen transitive closure, package resources, staged evidence, and claims.

Address only in-scope findings, then repeat every invalidated gate and candidate hash.

- [ ] **Step 7: Commit documentation/evidence and stop**

```powershell
git add README.md docs/TECHNICAL.md docs/ENTERPRISE-READINESS.md docs/release-evidence/functional-recovery
git diff --cached --check
git commit -m "docs(functional-recovery): record verified recovery evidence"
git status --short
```

Stop with a clean worktree. Do not enable real DDC/ICC/VCGT/DWM, measured/HDR/hybrid paths, profile mutation, startup automation, Calibrate All, Test Patterns, publish, tag, push, or begin Phase 2 without a new explicit workflow decision.

---

## Completion Definition

- Source and frozen modes use only `CalibrateProWindow` and one injected application service.
- Every active surface has one manifest record and unique surface ID; aliases share a canonical action ID/handler.
- Unsupported controls are disabled with an exact reason or hidden, and no false-success path remains.
- Detection is atomic and yields matched, explicit-generic, or unknown characterization with provenance.
- Generation emits nonempty, deterministic, strictly reparsed ICC/CUBE assets and performs no display write.
- Preview is immutable and plan-affecting edits invalidate one-use confirmation.
- Fake acceptance proves Apply through `ActuationCoordinator`; production physical Apply remains disabled and uncomposed.
- Verification is method-bound and sensorless evidence remains estimated/not measured.
- Save/Report atomically publishes one verified bundle and returns a truthful receipt.
- Diagnostics rotate, survive restart, redact required secret/device/user data, and use no weak display identifier.
- Parallel-safe, active-action coverage, installed-wheel, frozen, staged, and packaged-candidate gates have durable observed results.
- No automated or packaged-candidate step touches physical hardware.
- Physical and measured capabilities remain pending separate supervised acceptance.

## Required Self-Review Before Execution

- Every file path and manifest field matches the actual repository (`calibrate-pro.spec`, `first_party_exact`, `optional_first_party_exact`).
- Every fixture/helper named by a test has a defining file/task.
- Every new type has one owning module; `GeneratedAsset` is defined only in `application/contracts.py`.
- Alias tests require unique surface IDs, not unique action IDs.
- Deterministic tests require a nonempty asset set and strictly reparse complete outputs.
- Export atomicity covers the complete operation through a single published bundle.
- Typed outcomes carry every approved field through service, GUI, journal, and packaged smoke.
- Direct HID/DDC/native workers are removed from the active page graph before any action is claimed safe.
- Exact build, smoke, coverage, parallel, and VM commands are present.
- No unresolved planning markers or vague implementation steps remain.
