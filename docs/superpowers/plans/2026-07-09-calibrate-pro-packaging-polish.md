# Calibrate Pro 1.1 Packaging and Product Polish Implementation Plan

> **Status: Superseded draft — do not execute.** The revised packaging design
> selects PySide6, adds LGPL/source-provenance and least-privilege gates, and
> adds fail-closed HDR/PQ requirements. Regenerate this plan only after the
> revised packaging design and CP-HDR-1 boundary are reviewed and approved.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox syntax for tracking.

**Goal:** Ship Calibrate Pro 1.1.0 as a truthful, polished Windows application whose installer and portable archive contain every required runtime dependency, including build-color and build-ui.

**Architecture:** Keep calibrate_pro.main:main as the public entry point, make package metadata and the GUI consume one version source, and make the active PyQt shell load only its supported pages. Freeze an explicit PyInstaller onedir graph, wrap it with Inno Setup, and generate every release receipt from the same staged directory. Keep hardware mutation behind deliberate Apply actions; diagnostics and automated packaging checks remain read-only.

**Tech Stack:** Python 3.10+, PyQt6, build-color, build-ui, NumPy, SciPy, PyInstaller, Inno Setup 6, PowerShell, pytest, GitHub Actions Windows runners.

## Global Constraints

- Target release version is exactly 1.1.0.
- The Windows x64 installer must run without Python, pip, Git, or network access after download.
- The desktop artifact must contain build-color, build-ui, PyQt6, NumPy, SciPy, dwm_lut runtime files, and required notices.
- calibrate-pro.spec is the only PyInstaller specification; CalibratePro.spec is removed.
- The primary installed application uses PyInstaller onedir, not onefile.
- Sensorless values are estimates. A value is measured only when an instrument produced the source reading.
- Missing measurements render as “Not measured”; synthetic numbers never appear as observed results.
- The active workflow is Detect → Method → Preview → Apply → Verify → Save/Report.
- Hardware and operating-system failures must remain actionable and must not become successful calibration results.
- calibrate-pro doctor --json and the frozen CLI diagnostic are read-only.
- CalibratePro-1.1.0-Setup.exe and CalibratePro-1.1.0-win64.zip must each be no larger than 350 MB.
- Automated packaging tests do not write DDC/CI, DWM LUT, VCGT, USB, startup, or display-profile state.
- Signing is conditional; unsigned output is labeled unsigned.

## File Responsibility Map

- calibrate_pro/__init__.py — authoritative version and package-level truthful description.
- pyproject.toml — dynamic version metadata and complete optional dependency unions.
- calibrate_pro/runtime.py — source/frozen resource location without side effects.
- calibrate_pro/diagnostics.py — read-only dependency and packaged-resource report.
- calibrate_pro/verification/provenance.py — estimated, measured, and not-measured metric contract.
- calibrate_pro/workflow.py — calibration stage, capability, error, snapshot, and transition model.
- calibrate_pro/recovery.py — DDC state capture and restoration through injected adapters.
- calibrate_pro/gui/__init__.py — lazy compatibility facade.
- calibrate_pro/gui/app.py — active shell version and primary navigation.
- calibrate_pro/gui/pages/calibrate.py — preflight, preview, deliberate apply, and recovery presentation.
- calibrate_pro/gui/pages/verify.py — provenance-aware metrics with no seeded synthetic results.
- calibrate_pro/gui/calibration_wizard.py — removal of synthetic completion claims.
- calibrate-pro.spec — explicit onedir frozen graph.
- packaging/constraints-win64.txt — exact Python 3.12 Windows release dependency resolution.
- installer/CalibratePro.iss — Windows installer definition.
- scripts/build_windows.ps1 — deterministic local/CI build entry point.
- scripts/release_artifacts.py — hashes, inventory, notices, size, and forbidden-module audit.
- tests/test_release_metadata.py — version and dependency contract.
- tests/test_diagnostics.py — diagnostics and resource checks.
- tests/test_truthful_results.py — provenance and public-claim regression.
- tests/test_workflow.py — transition and recovery behavior.
- tests/test_gui_lazy_imports.py — optional GUI import boundary.
- tests/test_packaging_contract.py — PyInstaller, installer, artifact, and notice contract.
- .github/workflows/ci.yml — source and metadata gates.
- .github/workflows/release.yml — clean Windows build and artifact publication.

---

### Task 1: Unify version and dependency metadata

**Files:**
- Modify: pyproject.toml
- Modify: calibrate_pro/__init__.py
- Modify: calibrate_pro/gui/app.py
- Modify: calibrate_pro/gui/theme.py
- Modify: calibrate_pro/gui/pages/settings.py
- Create: tests/test_release_metadata.py

**Interfaces:**
- Consumes: calibrate_pro.__version__.
- Produces: one 1.1.0 version value used by package metadata, GUI, CLI, installer, and release scripts.

- [ ] **Step 1: Write the failing metadata tests**

    from pathlib import Path
    import tomllib

    import calibrate_pro

    ROOT = Path(__file__).resolve().parents[1]


    def _pyproject() -> dict:
        with (ROOT / "pyproject.toml").open("rb") as stream:
            return tomllib.load(stream)


    def test_release_version_is_authoritative():
        data = _pyproject()
        assert calibrate_pro.__version__ == "1.1.0"
        assert "version" not in data["project"]
        assert data["project"]["dynamic"] == ["version"]
        assert data["tool"]["setuptools"]["dynamic"]["version"] == {
            "attr": "calibrate_pro.__version__"
        }


    def test_gui_and_all_extras_include_shared_runtime_dependencies():
        data = _pyproject()
        extras = data["project"]["optional-dependencies"]
        assert "build-ui>=1.0.0" in extras["gui"]
        assert set(extras["gui"] + extras["tray"] + extras["sensor"]).issubset(
            set(extras["all"])
        )


    def test_active_gui_uses_package_version():
        from calibrate_pro.gui.app import APP_VERSION

        assert APP_VERSION == calibrate_pro.__version__

- [ ] **Step 2: Run the tests and confirm the intended failures**

    pytest tests/test_release_metadata.py -q

Expected: failures for version 1.0.1, the literal project version, and the incomplete all extra.

- [ ] **Step 3: Make calibrate_pro.__version__ the only version source**

Replace the project version declaration with:

    [project]
    name = "calibrate-pro"
    dynamic = ["version"]

Add:

    [tool.setuptools.dynamic]
    version = { attr = "calibrate_pro.__version__" }

Set:

    __version__ = "1.1.0"

Make the all extra the literal union:

    all = [
        "PyQt6>=6.5,<7",
        "build-ui>=1.0.0",
        "pystray>=0.19.4",
        "Pillow>=10.0,<11",
        "hidapi>=0.14,<1",
    ]

In the active GUI and compatibility version modules, import rather than duplicate:

    from calibrate_pro import __version__

    APP_VERSION = __version__

- [ ] **Step 4: Run focused and full tests**

    pytest tests/test_release_metadata.py -q
    pytest -q

Expected: the focused file passes and the full suite reports at least the existing 297 tests plus the new tests passing.

- [ ] **Step 5: Commit**

    git add pyproject.toml calibrate_pro/__init__.py calibrate_pro/gui/app.py calibrate_pro/gui/theme.py calibrate_pro/gui/pages/settings.py tests/test_release_metadata.py
    git commit -m "fix: unify Calibrate Pro release metadata"

---

### Task 2: Add read-only runtime diagnostics

**Files:**
- Create: calibrate_pro/runtime.py
- Create: calibrate_pro/diagnostics.py
- Modify: calibrate_pro/main.py
- Create: tests/test_diagnostics.py

**Interfaces:**
- Produces: application_root() -> Path.
- Produces: dwm_lut_directory() -> Path.
- Produces: missing_dwm_lut_files() -> tuple[str, ...].
- Produces: build_doctor_report() -> dict.
- Produces: calibrate-pro doctor --json.

- [ ] **Step 1: Write failing diagnostic tests**

    import json
    from pathlib import Path

    from calibrate_pro import diagnostics
    from calibrate_pro.runtime import DWM_LUT_FILES, missing_dwm_lut_files


    def test_missing_dwm_files_is_exact(tmp_path: Path):
        (tmp_path / DWM_LUT_FILES[0]).write_bytes(b"x")
        missing = missing_dwm_lut_files(tmp_path)
        assert missing == DWM_LUT_FILES[1:]


    def test_doctor_report_is_json_serializable(monkeypatch, tmp_path: Path):
        for name in DWM_LUT_FILES:
            (tmp_path / name).write_bytes(b"x")
        monkeypatch.setattr(diagnostics, "dwm_lut_directory", lambda: tmp_path)
        report = diagnostics.build_doctor_report()
        assert report["schema_version"] == 1
        assert report["version"] == "1.1.0"
        assert {item["module"] for item in report["dependencies"]} == {
            "build_color",
            "build_ui",
            "PyQt6",
            "numpy",
            "scipy",
            "hid",
        }
        assert report["resources"]["dwm_lut"]["missing"] == []
        json.dumps(report)


    def test_doctor_does_not_import_hardware_modules(monkeypatch):
        imported = []
        real_import = diagnostics.importlib.import_module

        def recording_import(name: str):
            imported.append(name)
            return real_import(name)

        monkeypatch.setattr(diagnostics.importlib, "import_module", recording_import)
        diagnostics.build_doctor_report()
        assert not any(name.startswith("calibrate_pro.hardware") for name in imported)
        assert not any(name.startswith("calibrate_pro.lut_system") for name in imported)

- [ ] **Step 2: Run the tests and confirm missing modules**

    pytest tests/test_diagnostics.py -q

Expected: collection fails because calibrate_pro.runtime and calibrate_pro.diagnostics do not exist.

- [ ] **Step 3: Implement frozen/source resource location**

Create calibrate_pro/runtime.py:

    from __future__ import annotations

    import sys
    from pathlib import Path

    DWM_LUT_FILES = (
        "WindowsDisplayAPI.dll",
        "dwm_lut.dll",
        "DwmLutGUI.exe",
        "LICENSE",
        "LICENSE-THIRD-PARTY",
    )


    def application_root() -> Path:
        if getattr(sys, "frozen", False):
            frozen_root = getattr(sys, "_MEIPASS", None)
            if frozen_root:
                return Path(frozen_root)
            return Path(sys.executable).resolve().parent
        return Path(__file__).resolve().parent.parent


    def dwm_lut_directory() -> Path:
        return application_root() / "dwm_lut"


    def missing_dwm_lut_files(directory: Path | None = None) -> tuple[str, ...]:
        root = directory if directory is not None else dwm_lut_directory()
        return tuple(name for name in DWM_LUT_FILES if not (root / name).is_file())

- [ ] **Step 4: Implement the diagnostic report**

Create calibrate_pro/diagnostics.py:

    from __future__ import annotations

    import importlib
    import importlib.metadata
    import json
    import platform
    from typing import Any

    from calibrate_pro import __version__
    from calibrate_pro.runtime import dwm_lut_directory, missing_dwm_lut_files

    DEPENDENCIES = (
        ("build_color", "build-color"),
        ("build_ui", "build-ui"),
        ("PyQt6", "PyQt6"),
        ("numpy", "numpy"),
        ("scipy", "scipy"),
        ("hid", "hidapi"),
    )


    def _dependency_report(module: str, distribution: str) -> dict[str, Any]:
        try:
            importlib.import_module(module)
            version = importlib.metadata.version(distribution)
            return {"module": module, "distribution": distribution, "ok": True, "version": version}
        except Exception as exc:
            return {
                "module": module,
                "distribution": distribution,
                "ok": False,
                "error": f"{type(exc).__name__}: {exc}",
            }


    def build_doctor_report() -> dict[str, Any]:
        dependencies = [_dependency_report(module, dist) for module, dist in DEPENDENCIES]
        missing = list(missing_dwm_lut_files(dwm_lut_directory()))
        failed = any(not item["ok"] for item in dependencies) or bool(missing)
        windows = platform.system() == "Windows"
        status = "fail" if failed else "ok" if windows else "degraded"
        return {
            "schema_version": 1,
            "product": "Calibrate Pro",
            "version": __version__,
            "status": status,
            "platform": {
                "system": platform.system(),
                "release": platform.release(),
                "supported": windows,
            },
            "dependencies": dependencies,
            "resources": {
                "dwm_lut": {
                    "path": str(dwm_lut_directory()),
                    "missing": missing,
                }
            },
            "mutation_performed": False,
        }


    def render_doctor_json() -> str:
        return json.dumps(build_doctor_report(), indent=2, sort_keys=True)

- [ ] **Step 5: Wire the CLI without touching devices**

Add:

    def cmd_doctor(args):
        from calibrate_pro.diagnostics import build_doctor_report

        report = build_doctor_report()
        if args.json:
            print(json.dumps(report, indent=2, sort_keys=True))
        else:
            print(f"Calibrate Pro {report['version']}: {report['status']}")
            for item in report["dependencies"]:
                state = "ok" if item["ok"] else "missing"
                print(f"  {item['module']}: {state}")
            missing = report["resources"]["dwm_lut"]["missing"]
            print(f"  dwm_lut: {'ok' if not missing else 'missing ' + ', '.join(missing)}")
        return 1 if report["status"] == "fail" else 0

Add the parser:

    doctor_parser = subparsers.add_parser("doctor", help="Check packaged runtime without changing display state")
    doctor_parser.add_argument("--json", action="store_true", help="Emit machine-readable diagnostics")

Add command dispatch before the GUI default:

    if args.command == "doctor":
        return cmd_doctor(args)

Import json at the top of calibrate_pro/main.py.

- [ ] **Step 6: Verify source CLI behavior**

    pytest tests/test_diagnostics.py -q
    python -m calibrate_pro.main doctor --json

Expected: tests pass; JSON reports mutation_performed false and lists all six dependencies.

- [ ] **Step 7: Commit**

    git add calibrate_pro/runtime.py calibrate_pro/diagnostics.py calibrate_pro/main.py tests/test_diagnostics.py
    git commit -m "feat: add read-only runtime diagnostics"

---

### Task 3: Enforce measured, estimated, and not-measured provenance

**Files:**
- Create: calibrate_pro/verification/provenance.py
- Modify: calibrate_pro/gui/pages/verify.py
- Modify: calibrate_pro/gui/calibration_wizard.py
- Modify: calibrate_pro/__init__.py
- Modify: README.md
- Modify: RELEASE_NOTES.md
- Create: tests/test_truthful_results.py

**Interfaces:**
- Produces: EvidenceKind enum.
- Produces: MetricValue(value, unit, evidence, source).
- Produces: MetricValue.display_text() and MetricValue.to_dict().

- [ ] **Step 1: Write failing provenance and claim tests**

    from pathlib import Path

    from calibrate_pro.verification.provenance import EvidenceKind, MetricValue

    ROOT = Path(__file__).resolve().parents[1]
    PUBLIC_COPY = (
        ROOT / "calibrate_pro" / "__init__.py",
        ROOT / "calibrate_pro" / "gui" / "calibration_wizard.py",
        ROOT / "calibrate_pro" / "gui" / "pages" / "verify.py",
        ROOT / "README.md",
        ROOT / "RELEASE_NOTES.md",
    )


    def test_missing_metric_is_not_rendered_as_zero():
        metric = MetricValue(None, "dE2000", EvidenceKind.NOT_MEASURED, None)
        assert metric.display_text() == "Not measured"
        assert metric.to_dict()["value"] is None


    def test_estimate_is_labeled():
        metric = MetricValue(1.25, "dE2000", EvidenceKind.ESTIMATED, "panel model")
        assert metric.display_text() == "1.25 dE2000 (estimated)"


    def test_public_copy_has_no_fabricated_release_values():
        combined = "\n".join(path.read_text(encoding="utf-8") for path in PUBLIC_COPY)
        banned = (
            "Predicted dE < 1.0",
            "Sensorless Calibration (Delta E < 1.0)",
            "Average Delta E: 0.42",
            "Maximum Delta E: 0.89",
            "95th Percentile: 0.71",
        )
        for phrase in banned:
            assert phrase not in combined

- [ ] **Step 2: Confirm the failures**

    pytest tests/test_truthful_results.py -q

Expected: import failure for provenance.py and public-copy failures.

- [ ] **Step 3: Implement the provenance contract**

Create calibrate_pro/verification/provenance.py:

    from __future__ import annotations

    from dataclasses import asdict, dataclass
    from enum import Enum
    from typing import Any


    class EvidenceKind(str, Enum):
        NOT_MEASURED = "not_measured"
        ESTIMATED = "estimated"
        MEASURED = "measured"


    @dataclass(frozen=True)
    class MetricValue:
        value: float | None
        unit: str
        evidence: EvidenceKind
        source: str | None

        def __post_init__(self) -> None:
            if self.evidence is EvidenceKind.NOT_MEASURED and self.value is not None:
                raise ValueError("not-measured metrics cannot carry a numeric value")
            if self.evidence is EvidenceKind.MEASURED and not self.source:
                raise ValueError("measured metrics require an instrument or measurement source")

        def display_text(self, decimals: int = 2) -> str:
            if self.value is None:
                return "Not measured"
            suffix = " (estimated)" if self.evidence is EvidenceKind.ESTIMATED else ""
            return f"{self.value:.{decimals}f} {self.unit}{suffix}"

        def to_dict(self) -> dict[str, Any]:
            data = asdict(self)
            data["evidence"] = self.evidence.value
            return data

- [ ] **Step 4: Remove seeded observed-looking GUI values**

Change ColorPatchWidget.delta_e to float | None. Use a neutral border and an em dash when delta_e is None:

    self._de = delta_e
    de_text = "Not measured" if delta_e is None else f"dE: {delta_e:.2f}"

In paintEvent:

    if self._de is None:
        border_color = QColor(C.BORDER)
        overlay = "—"
    elif self._de < 2.0:
        border_color = QColor(C.GREEN_HI)
        overlay = f"{self._de:.1f}"
    elif self._de < 3.0:
        border_color = QColor(C.YELLOW)
        overlay = f"{self._de:.1f}"
    else:
        border_color = QColor(C.RED)
        overlay = f"{self._de:.1f}"

Pass None from ColorCheckerGrid when delta_e is absent. In _seed_default_grid, omit delta_e entirely. Replace _seed_grayscale_chart with:

    def _show_grayscale_not_measured(self):
        self._gs_chart.set_data([], 2.2, [], delta_es=[])
        self._gs_avg_label.setText("Avg grayscale dE: Not measured")
        self._gs_max_label.setText("Max grayscale dE: Not measured")

Call this method at initialization and whenever results do not contain actual or explicitly estimated grayscale data. Do not synthesize grayscale values from ColorChecker patches.

Set result evidence explicitly:

    results["evidence_kind"] = "estimated"
    results["evidence_source"] = "panel characterization model"

For instrument-produced patch measurements:

    results["evidence_kind"] = "measured"
    results["evidence_source"] = sensor_name

If only white luminance was measured, leave Delta E summary values absent.

- [ ] **Step 5: Make the wizard report capability state rather than fake completion**

Remove the timer-driven _simulate_calibration completion path. When a selected method has no executable worker, disable Apply and show:

    "This method is not available with the detected hardware. You can still export the proposed ICC/LUT files."

Use “Not measured” for absent average, maximum, and percentile metrics. A saved or installed profile is reported only after the corresponding function returns success.

- [ ] **Step 6: Correct public copy**

Describe sensorless mode as a panel-characterization estimate. Describe the native i1Display3 path as hardware-measured only for readings it actually takes. Remove the fixed 0.42, 0.89, 0.71, less-than-one, and unqualified compliance claims.

- [ ] **Step 7: Run focused and full verification**

    pytest tests/test_truthful_results.py tests/test_verification.py -q
    pytest -q

Expected: all tests pass and no seeded GUI metric is presented as observed.

- [ ] **Step 8: Commit**

    git add calibrate_pro/verification/provenance.py calibrate_pro/gui/pages/verify.py calibrate_pro/gui/calibration_wizard.py calibrate_pro/__init__.py README.md RELEASE_NOTES.md tests/test_truthful_results.py
    git commit -m "fix: make calibration evidence explicit"

---

### Task 4: Add workflow stages, preflight, and restoration

**Files:**
- Create: calibrate_pro/workflow.py
- Create: calibrate_pro/recovery.py
- Create: tests/test_workflow.py

**Interfaces:**
- Produces: WorkflowStage, Capability, WorkflowFailure, CalibrationPlan, WorkflowSession.
- Produces: capture_ddc_state(controller, monitor) -> DdcSnapshot.
- Produces: restore_ddc_state(controller, monitor, snapshot) -> tuple[bool, tuple[str, ...]].

- [ ] **Step 1: Write failing transition and recovery tests**

    import pytest

    from calibrate_pro.recovery import capture_ddc_state, restore_ddc_state
    from calibrate_pro.workflow import WorkflowSession, WorkflowStage


    class FakeDdc:
        def __init__(self):
            self.values = {0x10: 45, 0x12: 70, 0x16: 98, 0x18: 100, 0x1A: 97}
            self.writes = []

        def get_vcp(self, monitor, code):
            if int(code) not in self.values:
                raise RuntimeError("unsupported")
            value = self.values[int(code)]
            return value, 100

        def set_vcp(self, monitor, code, value):
            self.writes.append((int(code), value))
            self.values[int(code)] = value
            return True


    def test_workflow_requires_preview_before_apply():
        session = WorkflowSession()
        session.advance(WorkflowStage.METHOD)
        with pytest.raises(ValueError):
            session.advance(WorkflowStage.APPLY)
        session.advance(WorkflowStage.PREVIEW)
        session.advance(WorkflowStage.APPLY)
        assert session.stage is WorkflowStage.APPLY


    def test_ddc_snapshot_round_trips():
        ddc = FakeDdc()
        snapshot = capture_ddc_state(ddc, object())
        ddc.values[0x10] = 80
        ok, errors = restore_ddc_state(ddc, object(), snapshot)
        assert ok is True
        assert errors == ()
        assert ddc.values[0x10] == 45


    def test_failure_records_recovery_without_becoming_success():
        session = WorkflowSession()
        session.advance(WorkflowStage.METHOD)
        session.advance(WorkflowStage.PREVIEW)
        session.advance(WorkflowStage.APPLY)
        session.fail("profile_apply_failed", "Windows rejected the profile", "Run as administrator")
        assert session.stage is WorkflowStage.FAILED
        assert session.failure.category == "profile_apply_failed"
        assert session.success is False

- [ ] **Step 2: Confirm the missing-module failures**

    pytest tests/test_workflow.py -q

- [ ] **Step 3: Implement the pure workflow model**

Create calibrate_pro/workflow.py:

    from __future__ import annotations

    from dataclasses import dataclass, field
    from enum import Enum


    class WorkflowStage(str, Enum):
        DETECT = "detect"
        METHOD = "method"
        PREVIEW = "preview"
        APPLY = "apply"
        VERIFY = "verify"
        SAVE_REPORT = "save_report"
        COMPLETE = "complete"
        FAILED = "failed"


    ALLOWED_TRANSITIONS = {
        WorkflowStage.DETECT: {WorkflowStage.METHOD},
        WorkflowStage.METHOD: {WorkflowStage.PREVIEW},
        WorkflowStage.PREVIEW: {WorkflowStage.APPLY, WorkflowStage.METHOD},
        WorkflowStage.APPLY: {WorkflowStage.VERIFY, WorkflowStage.FAILED},
        WorkflowStage.VERIFY: {WorkflowStage.SAVE_REPORT, WorkflowStage.FAILED},
        WorkflowStage.SAVE_REPORT: {WorkflowStage.COMPLETE, WorkflowStage.FAILED},
        WorkflowStage.COMPLETE: set(),
        WorkflowStage.FAILED: set(),
    }


    @dataclass(frozen=True)
    class Capability:
        available: bool
        reason: str
        next_action: str


    @dataclass(frozen=True)
    class WorkflowFailure:
        category: str
        summary: str
        next_action: str


    @dataclass(frozen=True)
    class CalibrationPlan:
        display_index: int
        method: str
        target_gamut: str
        whitepoint: str
        gamma: str
        proposed_changes: tuple[str, ...] = ()
        output_files: tuple[str, ...] = ()


    @dataclass
    class WorkflowSession:
        stage: WorkflowStage = WorkflowStage.DETECT
        plan: CalibrationPlan | None = None
        failure: WorkflowFailure | None = None
        recovery_messages: list[str] = field(default_factory=list)
        success: bool = False

        def advance(self, target: WorkflowStage) -> None:
            if target not in ALLOWED_TRANSITIONS[self.stage]:
                raise ValueError(f"invalid workflow transition: {self.stage.value} -> {target.value}")
            self.stage = target

        def fail(self, category: str, summary: str, next_action: str) -> None:
            self.failure = WorkflowFailure(category, summary, next_action)
            self.success = False
            self.stage = WorkflowStage.FAILED

        def complete(self) -> None:
            self.advance(WorkflowStage.COMPLETE)
            self.success = True

- [ ] **Step 4: Implement injected DDC snapshot and restoration**

Create calibrate_pro/recovery.py:

    from __future__ import annotations

    from dataclasses import dataclass

    from calibrate_pro.hardware.ddc_ci import VCPCode

    SNAPSHOT_CODES = (
        VCPCode.BRIGHTNESS,
        VCPCode.CONTRAST,
        VCPCode.RED_GAIN,
        VCPCode.GREEN_GAIN,
        VCPCode.BLUE_GAIN,
        VCPCode.RED_BLACK_LEVEL,
        VCPCode.GREEN_BLACK_LEVEL,
        VCPCode.BLUE_BLACK_LEVEL,
        VCPCode.COLOR_PRESET,
        VCPCode.GAMMA,
    )


    @dataclass(frozen=True)
    class DdcValue:
        code: int
        current: int
        maximum: int


    @dataclass(frozen=True)
    class DdcSnapshot:
        values: tuple[DdcValue, ...]


    def capture_ddc_state(controller, monitor) -> DdcSnapshot:
        values = []
        for code in SNAPSHOT_CODES:
            try:
                current, maximum = controller.get_vcp(monitor, code)
                values.append(DdcValue(int(code), int(current), int(maximum)))
            except RuntimeError:
                continue
        return DdcSnapshot(tuple(values))


    def restore_ddc_state(controller, monitor, snapshot: DdcSnapshot) -> tuple[bool, tuple[str, ...]]:
        errors = []
        for value in snapshot.values:
            try:
                if not controller.set_vcp(monitor, VCPCode(value.code), value.current):
                    errors.append(f"VCP 0x{value.code:02X} rejected {value.current}")
            except Exception as exc:
                errors.append(f"VCP 0x{value.code:02X}: {exc}")
        return not errors, tuple(errors)

- [ ] **Step 5: Run the pure tests**

    pytest tests/test_workflow.py -q

Expected: transition ordering and round-trip restoration pass without physical hardware.

- [ ] **Step 6: Commit**

    git add calibrate_pro/workflow.py calibrate_pro/recovery.py tests/test_workflow.py
    git commit -m "feat: model safe calibration workflow"

---

### Task 5: Integrate preview, deliberate apply, and actionable failure UI

**Files:**
- Modify: calibrate_pro/gui/pages/calibrate.py
- Modify: calibrate_pro/gui/app.py
- Modify: tests/test_workflow.py
- Modify: pyproject.toml

**Interfaces:**
- Consumes: WorkflowSession, CalibrationPlan, Capability, capture_ddc_state, restore_ddc_state.
- Produces: one active Detect → Method → Preview → Apply → Verify → Save/Report flow.

- [ ] **Step 1: Add an offscreen GUI test for the preview gate**

Append:

    def test_calibrate_page_does_not_start_worker_before_apply(qtbot, monkeypatch):
        pytest.importorskip("PyQt6")
        from calibrate_pro.gui.pages.calibrate import CalibratePage

        started = []
        monkeypatch.setattr(CalibratePage, "_launch_worker", lambda self: started.append(True))
        page = CalibratePage()
        qtbot.addWidget(page)
        page._prepare_preview()
        assert started == []
        assert page._apply_btn.isEnabled()
        page._apply_calibration()
        assert started == [True]

Add pytest-qt to the test and dev extras:

    "pytest-qt>=4.4,<5"

- [ ] **Step 2: Run the offscreen test and confirm failure**

    $env:QT_QPA_PLATFORM = "offscreen"
    pytest tests/test_workflow.py::test_calibrate_page_does_not_start_worker_before_apply -q

Expected: failure because the preview/apply methods do not exist.

- [ ] **Step 3: Split preparation from mutation**

In CalibratePage:

    self._session = WorkflowSession()
    self._preview_card.setVisible(False)
    self._apply_btn.setEnabled(False)
    self._apply_btn.clicked.connect(self._apply_calibration)

Replace the existing start button handler with _prepare_preview. It creates a CalibrationPlan from the selected display, method, gamut, whitepoint, gamma, planned DDC actions, ICC output, and LUT output. It advances METHOD then PREVIEW, renders every proposed change, and enables Apply. It does not instantiate or start a worker.

Use:

    def _apply_calibration(self):
        if self._session.stage is not WorkflowStage.PREVIEW:
            self._show_error("Preview the proposed changes before applying them.")
            return
        self._session.advance(WorkflowStage.APPLY)
        self._apply_btn.setEnabled(False)
        self._launch_worker()

Move the existing worker-selection logic into _launch_worker.

- [ ] **Step 4: Capture and restore state around mutations**

Before DDC auto-setup, enumerate the selected monitor and capture a DdcSnapshot. Store it on the worker. If calibration, profile installation, or LUT application fails, call restore_ddc_state and include each recovery message in the worker log. Emit success only after the requested apply operation returns success.

Use failure categories and actions:

    elevation_missing -> "Restart the Apply step as administrator."
    ddc_unavailable -> "Export ICC/LUT files or enable DDC/CI in the monitor menu."
    colorimeter_missing -> "Connect a supported meter or select Sensorless estimate."
    dwm_lut_missing -> "Repair the installation or export the LUT for manual use."
    profile_apply_failed -> "Retry as administrator or install the ICC profile from Profiles."
    display_detection_failed -> "Reconnect the display and run Detect again."

- [ ] **Step 5: Make capability absence visible and non-fatal**

Measured mode remains disabled when no supported instrument is detected, with the exact reason shown in the card. DDC and DWM absence disable their specific actions but leave ICC/LUT export available. The window remains usable without elevation.

- [ ] **Step 6: Run GUI and workflow tests**

    $env:QT_QPA_PLATFORM = "offscreen"
    pytest tests/test_workflow.py tests/test_truthful_results.py -q
    pytest -q

Expected: preview gating and pure recovery tests pass; no hardware is touched.

- [ ] **Step 7: Commit**

    git add calibrate_pro/gui/pages/calibrate.py calibrate_pro/gui/app.py tests/test_workflow.py pyproject.toml
    git commit -m "feat: gate display changes behind preview"

---

### Task 6: Replace eager GUI imports and define the compact frozen graph

**Files:**
- Modify: calibrate_pro/gui/__init__.py
- Modify: calibrate-pro.spec
- Delete: CalibratePro.spec
- Create: tests/test_gui_lazy_imports.py
- Create: tests/test_packaging_contract.py

**Interfaces:**
- Produces: lazy compatibility attributes through calibrate_pro.gui.__getattr__.
- Produces: dist/CalibratePro/CalibratePro.exe and dist/CalibratePro/CalibrateProCLI.exe.

- [ ] **Step 1: Write lazy-import and spec-contract tests**

    import importlib
    import sys
    from pathlib import Path

    ROOT = Path(__file__).resolve().parents[1]


    def test_importing_gui_does_not_import_historical_pages():
        for name in list(sys.modules):
            if name == "calibrate_pro.gui" or name.startswith("calibrate_pro.gui."):
                sys.modules.pop(name)
        gui = importlib.import_module("calibrate_pro.gui")
        assert gui.__name__ == "calibrate_pro.gui"
        assert "calibrate_pro.gui.main_window" not in sys.modules
        assert "calibrate_pro.gui.calibration_wizard" not in sys.modules


    def test_only_canonical_pyinstaller_spec_exists():
        assert (ROOT / "calibrate-pro.spec").is_file()
        assert not (ROOT / "CalibratePro.spec").exists()


    def test_spec_is_onedir_and_bundles_shared_dependencies():
        text = (ROOT / "calibrate-pro.spec").read_text(encoding="utf-8")
        assert "COLLECT(" in text
        assert "build_color" in text
        assert "build_ui" in text
        assert "dwm_lut" in text
        assert "collect_submodules('calibrate_pro')" not in text

- [ ] **Step 2: Confirm current failures**

    pytest tests/test_gui_lazy_imports.py tests/test_packaging_contract.py -q

Expected: eager modules are loaded, duplicate spec exists, and canonical spec has no COLLECT stage.

- [ ] **Step 3: Replace calibrate_pro.gui with a lazy facade**

Use importlib.import_module and a literal mapping:

    from importlib import import_module

    _EXPORTS = {
        "CalibrateProWindow": ("calibrate_pro.gui.app", "CalibrateProWindow"),
        "MainWindow": ("calibrate_pro.gui.main_window", "MainWindow"),
        "run_application": ("calibrate_pro.gui.main_window", "run_application"),
        "CalibrationWizard": ("calibrate_pro.gui.calibration_wizard", "CalibrationWizard"),
        "CalibrationConfig": ("calibrate_pro.gui.calibration_wizard", "CalibrationConfig"),
        "DisplaySelector": ("calibrate_pro.gui.display_selector", "DisplaySelector"),
        "PatternWindow": ("calibrate_pro.gui.pattern_window", "PatternWindow"),
        "ReportViewer": ("calibrate_pro.gui.report_viewer", "ReportViewer"),
    }

    __all__ = sorted(_EXPORTS)


    def __getattr__(name: str):
        try:
            module_name, attribute = _EXPORTS[name]
        except KeyError as exc:
            raise AttributeError(f"module {__name__!r} has no attribute {name!r}") from exc
        value = getattr(import_module(module_name), attribute)
        globals()[name] = value
        return value

- [ ] **Step 4: Replace the PyInstaller spec**

Use one Analysis, one PYZ, two EXE objects, and one COLLECT. The GUI executable is windowed; the CLI executable owns stdout for doctor --json.

    # -*- mode: python ; coding: utf-8 -*-
    from PyInstaller.utils.hooks import collect_data_files, collect_submodules

    active_modules = [
        "calibrate_pro.gui.app",
        "calibrate_pro.gui.pages.calibrate",
        "calibrate_pro.gui.pages.verify",
        "calibrate_pro.gui.pages.profiles",
        "calibrate_pro.gui.pages.ddc_control",
        "calibrate_pro.gui.pages.settings",
        "calibrate_pro.gui.widgets.cie_diagram",
        "calibrate_pro.core.color_math",
        "calibrate_pro.core.calibration_engine",
        "calibrate_pro.core.lut_engine",
        "calibrate_pro.panels.builtin_panels",
        "calibrate_pro.panels.database",
        "calibrate_pro.panels.detection",
        "calibrate_pro.profiles.icc_v4",
        "calibrate_pro.verification.provenance",
        "calibrate_pro.diagnostics",
        "calibrate_pro.runtime",
        "hid",
    ]
    shared_modules = collect_submodules("build_color") + collect_submodules("build_ui")
    shared_data = collect_data_files("build_color") + collect_data_files("build_ui")
    runtime_data = [
        ("dwm_lut/WindowsDisplayAPI.dll", "dwm_lut"),
        ("dwm_lut/dwm_lut.dll", "dwm_lut"),
        ("dwm_lut/DwmLutGUI.exe", "dwm_lut"),
        ("dwm_lut/LICENSE", "dwm_lut"),
        ("dwm_lut/LICENSE-THIRD-PARTY", "dwm_lut"),
    ]

    a = Analysis(
        ["calibrate_pro/main.py"],
        pathex=[],
        binaries=[],
        datas=runtime_data + shared_data,
        hiddenimports=active_modules + shared_modules,
        hookspath=[],
        hooksconfig={},
        runtime_hooks=[],
        excludes=[
            "torch", "torchvision", "torchaudio", "transformers", "diffusers",
            "pandas", "sklearn", "matplotlib", "IPython", "jupyter", "notebook",
            "cv2", "wx", "pytest", "hypothesis",
        ],
        noarchive=False,
        optimize=1,
    )
    pyz = PYZ(a.pure)
    gui = EXE(
        pyz,
        a.scripts,
        [],
        exclude_binaries=True,
        name="CalibratePro",
        console=False,
        uac_admin=False,
        debug=False,
        strip=False,
        upx=True,
    )
    cli = EXE(
        pyz,
        a.scripts,
        [],
        exclude_binaries=True,
        name="CalibrateProCLI",
        console=True,
        uac_admin=False,
        debug=False,
        strip=False,
        upx=True,
    )
    coll = COLLECT(
        gui,
        cli,
        a.binaries,
        a.datas,
        name="CalibratePro",
        strip=False,
        upx=True,
    )

Delete CalibratePro.spec.

- [ ] **Step 5: Run source contract tests**

    pytest tests/test_gui_lazy_imports.py tests/test_packaging_contract.py -q

Expected: all pass.

- [ ] **Step 6: Build the onedir application**

    python -m PyInstaller --clean --noconfirm calibrate-pro.spec
    .\dist\CalibratePro\CalibrateProCLI.exe doctor --json

Expected: the build succeeds and frozen diagnostics report all dependencies and dwm_lut files present.

- [ ] **Step 7: Commit**

    git add calibrate_pro/gui/__init__.py calibrate-pro.spec tests/test_gui_lazy_imports.py tests/test_packaging_contract.py
    git rm CalibratePro.spec
    git commit -m "build: define compact onedir application"

---

### Task 7: Build installer, portable archive, receipts, and license inventory

**Files:**
- Create: packaging/constraints-win64.txt
- Create: installer/CalibratePro.iss
- Create: scripts/build_windows.ps1
- Create: scripts/release_artifacts.py
- Modify: tests/test_packaging_contract.py

**Interfaces:**
- Produces: CalibratePro-1.1.0-Setup.exe.
- Produces: CalibratePro-1.1.0-win64.zip.
- Produces: SHA256SUMS.txt, dependency-manifest.json, THIRD_PARTY_LICENSES.

- [ ] **Step 1: Add failing release-script contract tests**

Append:

    def test_installer_and_release_scripts_exist():
        assert (ROOT / "installer" / "CalibratePro.iss").is_file()
        assert (ROOT / "scripts" / "build_windows.ps1").is_file()
        assert (ROOT / "scripts" / "release_artifacts.py").is_file()


    def test_installer_uses_onedir_and_does_not_enable_startup():
        text = (ROOT / "installer" / "CalibratePro.iss").read_text(encoding="utf-8")
        assert r"dist\CalibratePro\*" in text
        assert "runatstartup" not in text.lower()
        assert "PrivilegesRequired=lowest" in text


    def test_windows_release_constraints_pin_required_dependencies():
        lines = set(
            (ROOT / "packaging" / "constraints-win64.txt")
            .read_text(encoding="utf-8")
            .splitlines()
        )
        assert "build-color==1.0.2" in lines
        assert "build-ui==1.0.1" in lines
        assert "hidapi==0.15.0" in lines
        assert "PyQt6==6.11.0" in lines

- [ ] **Step 2: Confirm the files are absent**

    pytest tests/test_packaging_contract.py -q

- [ ] **Step 3: Pin the clean Windows build environment**

Create packaging/constraints-win64.txt from the versions resolved from PyPI on 2026-07-10:

    altgraph==0.17.5
    build-color==1.0.2
    build-ui==1.0.1
    hidapi==0.15.0
    numpy==2.5.1
    packaging==26.2
    pefile==2024.8.26
    PyQt6==6.11.0
    PyQt6-Qt6==6.11.1
    PyQt6-sip==13.11.1
    pyinstaller==6.21.0
    pyinstaller-hooks-contrib==2026.6
    pywin32-ctypes==0.2.3
    scipy==1.18.0
    setuptools==83.0.0

The release build uses Python 3.12 x64 and installs the project with gui and sensor extras under this constraints file. The normal developer package retains its broader supported ranges.

- [ ] **Step 4: Create the Inno Setup definition**

Create installer/CalibratePro.iss:

    #define AppName "Calibrate Pro"
    #define AppVersion "1.1.0"
    #define AppPublisher "Zain Dana Harper"
    #define AppExeName "CalibratePro.exe"

    [Setup]
    AppId={{A8A22043-566C-4DF6-9AC8-7C8F5A8B4157}
    AppName={#AppName}
    AppVersion={#AppVersion}
    AppPublisher={#AppPublisher}
    DefaultDirName={localappdata}\Programs\Calibrate Pro
    DefaultGroupName=Calibrate Pro
    OutputDir=..\release
    OutputBaseFilename=CalibratePro-1.1.0-Setup
    Compression=lzma2/ultra64
    SolidCompression=yes
    ArchitecturesAllowed=x64compatible
    ArchitecturesInstallIn64BitMode=x64compatible
    PrivilegesRequired=lowest
    UninstallDisplayIcon={app}\CalibratePro.exe
    WizardStyle=modern

    [Files]
    Source: "..\dist\CalibratePro\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

    [Icons]
    Name: "{group}\Calibrate Pro"; Filename: "{app}\CalibratePro.exe"
    Name: "{autodesktop}\Calibrate Pro"; Filename: "{app}\CalibratePro.exe"; Tasks: desktopicon

    [Tasks]
    Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Additional shortcuts:"

    [Run]
    Filename: "{app}\CalibratePro.exe"; Description: "Launch Calibrate Pro"; Flags: nowait postinstall skipifsilent

- [ ] **Step 5: Implement release receipts**

Create scripts/release_artifacts.py:

    from __future__ import annotations

    import argparse
    import hashlib
    import importlib.metadata
    import json
    import os
    import shutil
    from pathlib import Path

    from calibrate_pro import __version__

    DISTRIBUTIONS = (
        "calibrate-pro",
        "build-color",
        "build-ui",
        "PyQt6",
        "PyQt6-Qt6",
        "PyQt6-sip",
        "numpy",
        "scipy",
        "hidapi",
        "pyinstaller",
    )
    FORBIDDEN = (
        "torch",
        "transformers",
        "pandas",
        "jupyter",
        "notebook",
        "cv2",
        "sklearn",
    )
    MAXIMUM_BYTES = 350 * 1024 * 1024


    def build_dependency_manifest(distributions: tuple[str, ...]) -> dict:
        resolved = []
        for name in sorted(distributions, key=str.lower):
            try:
                version = importlib.metadata.version(name)
                resolved.append({"distribution": name, "version": version, "resolved": True})
            except importlib.metadata.PackageNotFoundError:
                resolved.append({"distribution": name, "resolved": False})
        return {
            "schema_version": 1,
            "product": "Calibrate Pro",
            "version": __version__,
            "platform": "windows-x64",
            "signed": os.environ.get("CALIBRATE_PRO_SIGNED", "false").lower() == "true",
            "dependencies": resolved,
        }


    def audit_staged_tree(root: Path, forbidden: tuple[str, ...]) -> list[str]:
        offenders = []
        for path in sorted(item for item in root.rglob("*") if item.is_file()):
            relative = path.relative_to(root).as_posix().lower()
            if any(token in relative for token in forbidden):
                offenders.append(relative)
        return offenders


    def enforce_size(path: Path, maximum_bytes: int) -> None:
        size = path.stat().st_size
        if size > maximum_bytes:
            raise RuntimeError(f"{path.name} is {size} bytes; limit is {maximum_bytes}")


    def _sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(block)
        return digest.hexdigest()


    def write_sha256s(paths: list[Path], output: Path) -> None:
        lines = [f"{_sha256(path)}  {path.as_posix()}" for path in sorted(paths)]
        output.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")


    def copy_licenses(
        source_root: Path,
        release_dir: Path,
        distributions: tuple[str, ...],
    ) -> Path:
        destination = release_dir / "THIRD_PARTY_LICENSES"
        destination.mkdir(parents=True, exist_ok=True)
        copies = (
            (source_root / "LICENSE", destination / "calibrate-pro.txt"),
            (source_root / "dwm_lut" / "LICENSE", destination / "dwm_lut.txt"),
            (
                source_root / "dwm_lut" / "LICENSE-THIRD-PARTY",
                destination / "dwm_lut-third-party.txt",
            ),
        )
        for source, target in copies:
            if not source.is_file():
                raise FileNotFoundError(source)
            shutil.copyfile(source, target)

        for name in distributions:
            if name == "calibrate-pro":
                continue
            dist = importlib.metadata.distribution(name)
            package_dir = destination / name.lower().replace("-", "_")
            package_dir.mkdir(parents=True, exist_ok=True)
            candidates = []
            for entry in dist.files or ():
                normalized = str(entry).replace("\\", "/")
                lower = normalized.lower()
                basename = lower.rsplit("/", 1)[-1]
                in_dist_info = ".dist-info/" in lower
                license_name = basename.startswith(("license", "copying", "notice", "authors"))
                if in_dist_info and license_name:
                    candidates.append(entry)

            if not candidates:
                license_text = dist.metadata.get("License")
                if not license_text:
                    raise RuntimeError(f"{name} has no redistributable license payload")
                (package_dir / "LICENSE-METADATA.txt").write_text(
                    license_text + "\n",
                    encoding="utf-8",
                    newline="\n",
                )
                continue

            for entry in sorted(candidates, key=lambda item: str(item).lower()):
                source = Path(dist.locate_file(entry))
                if not source.is_file():
                    raise FileNotFoundError(source)
                flattened = str(entry).replace("\\", "__").replace("/", "__")
                shutil.copyfile(source, package_dir / flattened)
        return destination


    def main() -> int:
        parser = argparse.ArgumentParser()
        parser.add_argument("--release-dir", type=Path)
        parser.add_argument("--staged-dir", type=Path, required=True)
        parser.add_argument("--require-installer", action="store_true")
        parser.add_argument("--prepare-staged", action="store_true")
        args = parser.parse_args()

        source_root = Path(__file__).resolve().parents[1]
        staged_dir = args.staged_dir.resolve()
        if args.prepare_staged:
            copy_licenses(source_root, staged_dir, DISTRIBUTIONS)
            return 0
        if args.release_dir is None:
            parser.error("--release-dir is required unless --prepare-staged is used")
        release_dir = args.release_dir.resolve()
        release_dir.mkdir(parents=True, exist_ok=True)

        offenders = audit_staged_tree(staged_dir, FORBIDDEN)
        if offenders:
            raise RuntimeError("forbidden frozen modules: " + ", ".join(offenders))

        manifest = build_dependency_manifest(DISTRIBUTIONS)
        unresolved = [
            item["distribution"]
            for item in manifest["dependencies"]
            if not item["resolved"]
        ]
        if unresolved:
            raise RuntimeError("unresolved release dependencies: " + ", ".join(unresolved))

        manifest_path = release_dir / "dependency-manifest.json"
        manifest_path.write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        staged_licenses = staged_dir / "THIRD_PARTY_LICENSES"
        if not staged_licenses.is_dir():
            raise FileNotFoundError(staged_licenses)
        shutil.copytree(
            staged_licenses,
            release_dir / "THIRD_PARTY_LICENSES",
            dirs_exist_ok=True,
        )

        portable = release_dir / f"CalibratePro-{__version__}-win64.zip"
        installer = release_dir / f"CalibratePro-{__version__}-Setup.exe"
        if not portable.is_file():
            raise FileNotFoundError(portable)
        enforce_size(portable, MAXIMUM_BYTES)
        if args.require_installer:
            if not installer.is_file():
                raise FileNotFoundError(installer)
            enforce_size(installer, MAXIMUM_BYTES)

        sums_path = release_dir / "SHA256SUMS.txt"
        published = [
            path.relative_to(release_dir)
            for path in release_dir.rglob("*")
            if path.is_file() and path != sums_path
        ]
        current = Path.cwd()
        try:
            os.chdir(release_dir)
            write_sha256s(published, Path("SHA256SUMS.txt"))
        finally:
            os.chdir(current)
        return 0


    if __name__ == "__main__":
        raise SystemExit(main())

- [ ] **Step 6: Create the deterministic PowerShell entry point**

scripts/build_windows.ps1 accepts -SkipInstaller and performs:

    param([switch]$SkipInstaller)

    $ErrorActionPreference = "Stop"
    $root = Split-Path -Parent $PSScriptRoot
    Set-Location $root
    $bootstrapPython = (Get-Command python -ErrorAction Stop).Source
    $tempRoot = [IO.Path]::GetFullPath([IO.Path]::GetTempPath())
    $venv = Join-Path $tempRoot ("calibrate-pro-release-" + [guid]::NewGuid().ToString("N"))
    & $bootstrapPython -m venv $venv
    $releasePython = Join-Path $venv "Scripts\python.exe"

    try {
        & $releasePython -m pip install --upgrade pip
        & $releasePython -m pip install --constraint ".\packaging\constraints-win64.txt" ".[gui,sensor]" "pyinstaller==6.21.0"
        $version = & $releasePython -c "from calibrate_pro import __version__; print(__version__)"
        & $releasePython -m PyInstaller --clean --noconfirm calibrate-pro.spec
        & ".\dist\CalibratePro\CalibrateProCLI.exe" doctor --json
        & $releasePython ".\scripts\release_artifacts.py" --staged-dir ".\dist\CalibratePro" --prepare-staged

        $signed = $false
        if ($env:SIGNTOOL_PATH -and $env:SIGN_CERT_SHA1 -and $env:SIGN_TIMESTAMP_URL) {
            foreach ($binary in @(
                ".\dist\CalibratePro\CalibratePro.exe",
                ".\dist\CalibratePro\CalibrateProCLI.exe"
            )) {
                & $env:SIGNTOOL_PATH sign /sha1 $env:SIGN_CERT_SHA1 /fd SHA256 /tr $env:SIGN_TIMESTAMP_URL /td SHA256 $binary
            }
            $signed = $true
        }

        New-Item -ItemType Directory -Force release | Out-Null
        $portable = ".\release\CalibratePro-$version-win64.zip"
        if (Test-Path $portable) { Remove-Item -LiteralPath $portable -Force }
        Compress-Archive -Path ".\dist\CalibratePro\*" -DestinationPath $portable

        if (-not $SkipInstaller) {
            $iscc = "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe"
            if (-not (Test-Path $iscc)) { throw "Inno Setup 6 is required" }
            & $iscc ".\installer\CalibratePro.iss"
            if ($signed) {
                & $env:SIGNTOOL_PATH sign /sha1 $env:SIGN_CERT_SHA1 /fd SHA256 /tr $env:SIGN_TIMESTAMP_URL /td SHA256 ".\release\CalibratePro-$version-Setup.exe"
            }
        }

        $env:CALIBRATE_PRO_SIGNED = $signed.ToString().ToLowerInvariant()
        $artifactArgs = @("--release-dir", ".\release", "--staged-dir", ".\dist\CalibratePro")
        if (-not $SkipInstaller) { $artifactArgs += "--require-installer" }
        & $releasePython ".\scripts\release_artifacts.py" @artifactArgs
    }
    finally {
        $resolvedVenv = [IO.Path]::GetFullPath($venv)
        if (-not $resolvedVenv.StartsWith($tempRoot, [StringComparison]::OrdinalIgnoreCase)) {
            throw "Refusing to remove release environment outside the temporary directory"
        }
        if (-not (Split-Path $resolvedVenv -Leaf).StartsWith("calibrate-pro-release-")) {
            throw "Refusing to remove an unexpected temporary directory"
        }
        if (Test-Path $resolvedVenv) {
            Remove-Item -LiteralPath $resolvedVenv -Recurse -Force
        }
    }

- [ ] **Step 7: Build and audit local artifacts**

    powershell -NoProfile -ExecutionPolicy Bypass -File scripts/build_windows.ps1

Expected release directory:

    CalibratePro-1.1.0-Setup.exe
    CalibratePro-1.1.0-win64.zip
    SHA256SUMS.txt
    dependency-manifest.json
    THIRD_PARTY_LICENSES

- [ ] **Step 8: Commit**

    git add packaging/constraints-win64.txt installer/CalibratePro.iss scripts/build_windows.ps1 scripts/release_artifacts.py tests/test_packaging_contract.py
    git commit -m "build: add reproducible Windows release artifacts"

---

### Task 8: Add clean Windows CI and release gates

**Files:**
- Modify: .github/workflows/ci.yml
- Modify: .github/workflows/release.yml
- Modify: tests/test_packaging_contract.py

**Interfaces:**
- Consumes: scripts/build_windows.ps1 and release receipts.
- Produces: verified Windows build artifacts from a clean hosted runner.

- [ ] **Step 1: Add workflow-source assertions**

Append:

    def test_release_workflow_runs_frozen_doctor_and_artifact_audit():
        text = (ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
        assert "scripts/build_windows.ps1" in text
        assert "CalibrateProCLI.exe doctor --json" in text
        assert "SHA256SUMS.txt" in text
        assert "dependency-manifest.json" in text

- [ ] **Step 2: Confirm the release workflow test fails**

    pytest tests/test_packaging_contract.py -q

- [ ] **Step 3: Add source gates to CI**

The Windows CI job installs the project from published-style dependency declarations:

    python -m pip install --upgrade pip
    python -m pip install ".[all,test]"
    python -m pytest -q
    python -m calibrate_pro.main doctor --json

Keep the existing supported Python matrix for pure source tests. Add one Python 3.12 Windows packaging-contract job to avoid rebuilding PyInstaller for every interpreter.

- [ ] **Step 4: Replace release assembly with the canonical build script**

The release job runs on windows-latest, installs Inno Setup 6 with Chocolatey, installs build and PyInstaller tooling, invokes scripts/build_windows.ps1, reruns the frozen doctor with its output captured, verifies SHA256SUMS.txt, and uploads the complete release directory.

Use:

    choco install innosetup --no-progress -y
    python -m pip install --upgrade pip
    python -m pip install ".[all,test]" pyinstaller
    powershell -NoProfile -ExecutionPolicy Bypass -File scripts/build_windows.ps1
    .\dist\CalibratePro\CalibrateProCLI.exe doctor --json
    Get-Content .\release\SHA256SUMS.txt
    Get-Content .\release\dependency-manifest.json

Artifact upload includes:

    release/CalibratePro-1.1.0-Setup.exe
    release/CalibratePro-1.1.0-win64.zip
    release/SHA256SUMS.txt
    release/dependency-manifest.json
    release/THIRD_PARTY_LICENSES/**

- [ ] **Step 5: Run workflow and source tests locally**

    pytest tests/test_packaging_contract.py -q
    python -m build
    pytest -q

Expected: workflow assertions, wheel build, and full suite pass.

- [ ] **Step 6: Commit**

    git add .github/workflows/ci.yml .github/workflows/release.yml tests/test_packaging_contract.py
    git commit -m "ci: verify self-contained Windows releases"

---

### Task 9: Align documentation and perform the release acceptance audit

**Files:**
- Modify: README.md
- Modify: RELEASE_NOTES.md
- Modify: CHANGELOG.md
- Modify: ARCHITECTURE.md
- Modify: docs/ENTERPRISE-READINESS.md
- Modify: docs/superpowers/specs/2026-07-09-calibrate-pro-packaging-polish-design.md

**Interfaces:**
- Consumes: verified release artifacts and test output.
- Produces: truthful install, capability, limitation, and verification documentation.

- [ ] **Step 1: Document the two supported installation paths**

README must lead with:

- Windows installer for ordinary users;
- portable ZIP for restricted machines;
- developer wheel/source installation as a separate path;
- no Python or separate build-color/build-ui installation required for installer/ZIP users;
- measured and sensorless evidence distinction;
- administrator rights required only for privileged Apply operations.

- [ ] **Step 2: Document exact artifact and diagnostic commands**

Include:

    CalibrateProCLI.exe doctor --json
    calibrate-pro doctor --json

Describe each release receipt and state that an absent signing identity yields an unsigned artifact.

- [ ] **Step 3: Correct capability and limitation copy**

State hardware validation by named, tested device only. Mark native-driver code without a physical validation receipt as experimental. State that sensorless verification is an estimate. State that HDR workflows with generated measurements are demonstrations, not display measurements. Do not claim DisplayCAL, ColourSpace, or Calman replacement parity in 1.1.

- [ ] **Step 4: Run the complete acceptance sequence**

    ruff check .
    mypy calibrate_pro
    pytest -q
    python -m build
    powershell -NoProfile -ExecutionPolicy Bypass -File scripts/build_windows.ps1
    .\dist\CalibratePro\CalibrateProCLI.exe doctor --json
    Get-FileHash .\release\CalibratePro-1.1.0-Setup.exe -Algorithm SHA256
    Get-FileHash .\release\CalibratePro-1.1.0-win64.zip -Algorithm SHA256

Verify on a disposable Windows environment:

1. Uninstall any prior Calibrate Pro build.
2. Confirm python.exe is not available on PATH.
3. Install CalibratePro-1.1.0-Setup.exe.
4. Launch Calibrate Pro and open Dashboard, Calibrate, Verify, Profiles, DDC Control, and Settings.
5. Run the installed CalibrateProCLI.exe doctor --json.
6. Confirm missing colorimeter and unavailable DDC actions show reasons without reporting success.
7. Uninstall and verify the application directory and shortcuts are removed.
8. Extract the portable ZIP and repeat launch plus diagnostics without installation.

- [ ] **Step 5: Record evidence in the approved spec**

For each R1–R13 and each success criterion, add:

- the command or disposable-machine observation proving it;
- the exact artifact path;
- the result;
- any limitation that remains.

Mark a checkbox complete only when its cited evidence covers the full requirement. Set the spec status to Implemented only when every requirement is proven.

- [ ] **Step 6: Commit**

    git add README.md RELEASE_NOTES.md CHANGELOG.md ARCHITECTURE.md docs/ENTERPRISE-READINESS.md docs/superpowers/specs/2026-07-09-calibrate-pro-packaging-polish-design.md
    git commit -m "docs: publish Calibrate Pro 1.1 release evidence"

---

## Plan Self-Review

- R1, R2, R4, R5, R11, and R12 map to Tasks 6–9.
- R3 and R6 map to Task 1.
- R7 and R8 map to Task 3.
- R9 and R10 map to Tasks 4–5.
- R13 maps to Task 2 and the frozen smoke checks in Tasks 6–9.
- The clean-machine installer and uninstall check remains a required human or disposable-VM acceptance gate; source tests cannot substitute for it.
- Physical display accuracy, DDC writes, USB behavior, and DWM application remain unclaimed unless a named hardware receipt exists.
- HDR grading and the unified DisplayCAL/ColourSpace/Calman parity program are separate specifications because the approved 1.1 design excludes new calibration algorithms and new hardware drivers.
