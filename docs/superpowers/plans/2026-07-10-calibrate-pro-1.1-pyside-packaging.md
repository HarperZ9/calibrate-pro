# Calibrate Pro 1.1 PySide Packaging Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship Calibrate Pro 1.1.0 as a truthful, self-contained Windows x64 application whose per-user installer and portable ZIP include Build Color, Build UI 2, PySide6/Qt, NumPy, SciPy, and `dwm_lut` without requiring Python, pip, Git, administrator launch, or network access after download.

**Architecture:** Keep `calibrate_pro.main:main` as the source and frozen entry point, select PySide6 deterministically before QtPy/Build UI imports, and retain one audited PQ implementation behind compatibility delegates. Freeze an explicit PyInstaller `onedir` graph, stage notices and machine-readable receipts into that graph, produce a deterministic portable ZIP, and wrap the same staged directory with Inno Setup 6.7.3. Evidence-bearing result types and a transactional workflow keep simulation, estimation, measurement, and display mutation distinct.

**Tech Stack:** Python 3.12 x64 release runtime; Python 3.10-3.13 developer support; PySide6 6.11.1; QtPy 2.4.3; Build UI 2.0.0; Build Color 1.0.2 or its independently qualified compatible release; NumPy; SciPy; PyInstaller 6.21.0; Inno Setup 6.7.3; PowerShell; pytest; Ruff; Mypy; uv 0.11.25; GitHub Actions Windows runners.

## Global Constraints

- This plan supersedes `docs/superpowers/plans/2026-07-09-calibrate-pro-packaging-polish.md`; that stale draft remains untouched and must never be executed.
- Product implementation is consent-gated. Do not create an implementation worktree or change product code until the operator explicitly approves this plan.
- After approval, every implementation task runs only in `C:\dev\worktrees\calibrate-pro-1.1-pyside`, created from clean commit `10149aa8e96dc2991eae8db134b53512c5afe5b8`. Never execute implementation steps in `C:\dev\public\calibrate-pro`.
- Target version is exactly `1.1.0`, sourced only from `calibrate_pro.__version__`.
- Build UI dependency is exactly `build-ui[pyside6]>=2,<3`; its 2.0 candidate or published wheel must expose the approved QtPy bridge and preserve the current public theme/widget API.
- Calibrate metadata also declares `PySide6>=6.11.1,<7`; release resolution pins PySide6, PySide6_Addons, PySide6_Essentials, and shiboken6 to `6.11.1` unless a repeated compatibility proof approves an update.
- Calibrate source and frozen dependency closure contain no PyQt5 or PyQt6 imports, modules, distributions, or Qt objects. QtPy's unselected adapter source is not itself a PyQt distribution; frozen TOC and installed distribution checks are authoritative.
- `QT_API=pyside6` is set before the first QtPy or Build UI import in source and by a PyInstaller runtime hook when frozen.
- `calibrate-pro.spec` is the only PyInstaller spec. The release is `onedir`, `upx=False`, and both frozen executables use `uac_admin=False`.
- Build Color is collected through the explicit core modules `build_color.adaptation`, `build_color.difference`, `build_color.gamut`, and `build_color.spaces`. `build_color.gui` and recursive Build Color collection are forbidden.
- Sensorless values are estimates. A metric is measured only when a supported instrument produced its source reading. Missing readings render as `Not measured`; simulation and replay are explicit provenance values.
- The active workflow is Detect -> Method -> Preview -> Apply -> Verify -> Save/Report. Only Apply may invoke a privileged actuator, and it does so after explicit confirmation.
- Automated tests do not write DDC/CI, DWM LUT, VCGT, USB, startup, ICC association, or display state.
- `calibrate-pro doctor --json` and `CalibrateProCLI.exe doctor --json` are read-only and return stable JSON.
- Runtime and build dependencies are hash-locked for Python 3.12 Windows x64. Release builds use published dependency artifacts; local wheels are allowed only for the pre-publication integration gate.
- Portable ZIP members are lexicographically sorted with normalized timestamps. Unsigned duplicate builds must have identical ZIP hashes and canonical staged inventories.
- Required public outputs are `CalibratePro-1.1.0-Setup.exe`, `CalibratePro-1.1.0-win64.zip`, `SHA256SUMS.txt`, `dependency-manifest.json`, `qt-module-inventory.json`, and `THIRD_PARTY_LICENSES/`.
- The installer and portable ZIP must each be at most 350 MiB (`367001600` bytes). Failure emits the dependency report and stops the build.
- Signing is optional, but status is derived from Authenticode verification for each EXE and installer, never from an environment flag.
- Qt/PySide libraries remain external and replaceable inside the onedir tree. The release carries LGPL text, Qt notices, corresponding-source provenance, source-offer text, and relinking instructions. These gates are release engineering controls, not legal certification.
- A trusted public signature and final legal review are external release gates; an unsigned build must identify itself truthfully.

---

## Execution Consent and Isolation Gate

The normal checkout is the planning and review surface. Implementation begins only after the operator replies with explicit approval and the executor invokes `superpowers:using-git-worktrees`.

- [ ] **Gate 1: Record normal-checkout state without changing it**

```powershell
git -C C:\dev\public\calibrate-pro status --short --branch
git -C C:\dev\public\calibrate-pro rev-parse 10149aa
```

Expected: commit resolves to `10149aa8e96dc2991eae8db134b53512c5afe5b8`; no product-source modification is present. Planning files may be untracked or committed in the normal checkout.

- [ ] **Gate 2: Stop and obtain explicit operator approval**

Report the plan path, base commit, proposed worktree path, Build UI prerequisite, and release side effects. Do not interpret an earlier product approval as consent to create this implementation worktree.

- [ ] **Gate 3: Create the isolated worktree after approval**

```powershell
git -C C:\dev\public\calibrate-pro worktree add C:\dev\worktrees\calibrate-pro-1.1-pyside 10149aa8e96dc2991eae8db134b53512c5afe5b8
git -C C:\dev\worktrees\calibrate-pro-1.1-pyside rev-parse HEAD
git -C C:\dev\worktrees\calibrate-pro-1.1-pyside status --porcelain
```

Expected: HEAD is exactly `10149aa8e96dc2991eae8db134b53512c5afe5b8` and status output is empty.

- [ ] **Gate 4: Pin every subsequent command to the isolated worktree**

```powershell
$env:CALIBRATE_PRO_WORKTREE = 'C:\dev\worktrees\calibrate-pro-1.1-pyside'
Set-Location -LiteralPath $env:CALIBRATE_PRO_WORKTREE
if ((git rev-parse --show-toplevel).Trim() -ne $env:CALIBRATE_PRO_WORKTREE) { throw 'Refusing to implement outside the approved worktree' }
```

Expected: command completes silently. Keep this guard at the start of every implementation turn.

## File Responsibility Map

- `calibrate_pro/qt_runtime.py` - deterministic PySide6 selection before QtPy/Build UI import.
- `packaging/pyi_rth_qt_api.py` - frozen-process `QT_API=pyside6` runtime hook.
- `calibrate_pro/core/pq.py` - one audited float64 ST 2084 implementation.
- `calibrate_pro/verification/provenance.py` - measured, estimated, simulated, replayed, and absent metric contract.
- `calibrate_pro/workflow.py` - pure Detect/Method/Preview/Apply/Verify/Save state model.
- `calibrate_pro/recovery.py` - injected display-state transaction and restoration boundary.
- `calibrate_pro/runtime.py` - source/frozen resource resolution without hardware access.
- `calibrate_pro/diagnostics.py` - read-only doctor report and dependency/resource/PQ checks.
- `calibrate_pro/gui/__init__.py` - lazy compatibility exports.
- `calibrate_pro/gui/app.py` - active shell, version, primary flow, and opt-in services.
- `calibrate_pro/gui/pages/calibrate.py` - capability preflight, preview, explicit Apply, and recovery state.
- `calibrate_pro/gui/pages/verify.py` - provenance-aware metrics with no seeded observed-looking data.
- `calibrate-pro.spec` - sole allowlisted onedir graph with GUI and console executables.
- `packaging/requirements-win64.in` - human-reviewed release roots.
- `packaging/requirements-win64-py312.lock` - exact Windows wheel resolution with hashes.
- `packaging/qt-components.json` - fail-closed Qt module/plugin license classification.
- `packaging/source-provenance.lock.json` - exact upstream source identifiers and verified hashes.
- `scripts/release_artifacts.py` - stage audit, deterministic ZIP, receipts, hashes, and signature probes.
- `scripts/build_windows.ps1` - only source-to-release orchestration path.
- `installer/CalibratePro.iss` - per-user Inno Setup wrapper over the staged onedir tree.
- `tests/test_qt_binding_contract.py` - source, metadata, Qt selection, signals, widgets, and window closure.
- `tests/test_pq_conformance.py` - shared ST 2084 gold vectors across every compatibility surface.
- `tests/test_hdr_provenance.py` - missing/simulated/replayed/measured HDR behavior.
- `tests/test_workflow.py` - transitions, capability gating, Apply transaction, and restoration.
- `tests/test_diagnostics.py` - JSON shape, dependency/resource status, and mutation prohibition.
- `tests/test_packaging_contract.py` - spec, installer, lock, TOC, manifest, and output contract.
- `tests/test_release_artifacts.py` - deterministic archive and fail-closed staged-tree audits.

---

### Task 1: Prove the Build UI 2 PySide Candidate Before Editing Calibrate

**Files:**
- Test only: candidate `build_ui-2.0.0-py3-none-any.whl`
- Inspect: `C:\dev\public\build-ui\docs\superpowers\specs\2026-07-10-build-ui-2-qt-bridge-design.md`

**Interfaces:**
- Consumes: one Build UI 2.0.0 wheel supplied through `$env:BUILD_UI_2_WHEEL`.
- Produces: a clean-process receipt proving `qtpy.API_NAME == "PySide6"`, the approved public names import, representative widgets construct, and no PyQt distribution is installed.

- [ ] **Step 1: Require an explicit candidate-wheel path**

```powershell
if (-not $env:BUILD_UI_2_WHEEL) { throw 'Set BUILD_UI_2_WHEEL to the reviewed Build UI 2.0.0 wheel' }
$wheel = (Resolve-Path -LiteralPath $env:BUILD_UI_2_WHEEL).Path
if ([IO.Path]::GetFileName($wheel) -notlike 'build_ui-2.0.0-*.whl') { throw "Unexpected Build UI wheel: $wheel" }
```

Expected: a reviewed Build UI 2.0.0 wheel resolves. Stop if it does not.

- [ ] **Step 2: Install the candidate with exactly the PySide binding**

```powershell
$proof = Join-Path $env:TEMP ('calibrate-build-ui-proof-' + [guid]::NewGuid().ToString('N'))
py -3.12 -m venv $proof
$python = Join-Path $proof 'Scripts\python.exe'
& $python -m pip install --upgrade pip
& $python -m pip install 'QtPy==2.4.3' 'PySide6==6.11.1' $wheel
& $python -m pip check
```

Expected: installation and `pip check` succeed without PyQt.

- [ ] **Step 3: Run the binding-isolated behavioral probe**

```powershell
$env:QT_API = 'pyside6'
$env:QT_QPA_PLATFORM = 'offscreen'
@'
from importlib import metadata
from qtpy import API_NAME
from qtpy.QtWidgets import QApplication
from build_ui.theme import C, STYLE, create_stylesheet
from build_ui.widgets import Card, Heading, NavButton, Sidebar, Stat, StatusDot, ToastNotification

app = QApplication.instance() or QApplication([])
card = Card('Proof')
sidebar = Sidebar(['One', 'Two'])
seen = []
sidebar.page_changed.connect(seen.append)
sidebar.page_changed.emit(1)
assert API_NAME == 'PySide6'
assert seen == [1]
assert card.windowTitle() == ''
assert C and STYLE and create_stylesheet
for name in ('PyQt5', 'PyQt6'):
    try:
        metadata.version(name)
    except metadata.PackageNotFoundError:
        continue
    raise AssertionError(f'{name} must not be installed')
print('build-ui-2-pyside-proof=pass')
'@ | & $python -
```

Expected: `build-ui-2-pyside-proof=pass`.

- [ ] **Step 4: Preserve the proof output in the task log, not the repository**

Record the wheel path, SHA-256, Python version, QtPy version, PySide6 version, and probe output in the agent task handoff. Do not commit the candidate wheel or temporary environment.

---

### Task 2: Migrate Calibrate Source and Metadata to PySide6

**Files:**
- Create: `calibrate_pro/qt_runtime.py`
- Create: `packaging/pyi_rth_qt_api.py`
- Create: `tests/test_qt_binding_contract.py`
- Modify: `tests/conftest.py`
- Modify: `pyproject.toml:35-43,60-65`
- Modify all files returned by `rg -l "PyQt6|PyQt5|pyqtSignal|pyqtSlot|pyqtProperty" calibrate_pro -g "*.py"`

**Interfaces:**
- Consumes: Build UI 2 public API proven in Task 1.
- Produces: `configure_qt_api() -> str`, a PySide6-only Calibrate source graph, and a frozen runtime hook that selects the same binding.

- [ ] **Step 1: Write the failing static and metadata tests**

Create `tests/test_qt_binding_contract.py` with:

```python
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
BANNED = ("PyQt5", "PyQt6", "pyqtSignal", "pyqtSlot", "pyqtProperty")


def test_calibrate_source_contains_no_pyqt_binding_tokens() -> None:
    offenders: list[str] = []
    for path in sorted((ROOT / "calibrate_pro").rglob("*.py")):
        text = path.read_text(encoding="utf-8")
        if any(token in text for token in BANNED):
            offenders.append(str(path.relative_to(ROOT)))
    assert offenders == []


def test_gui_extra_selects_build_ui_2_pyside() -> None:
    text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert '"build-ui[pyside6]>=2,<3"' in text
    assert '"PySide6>=6.11.1,<7"' in text
    assert "PyQt5" not in text
    assert "PyQt6" not in text


def test_qt_api_is_forced_before_build_ui_import() -> None:
    code = """
import os
os.environ['QT_API'] = 'pyqt6'
from calibrate_pro.qt_runtime import configure_qt_api
assert configure_qt_api() == 'pyside6'
from build_ui.widgets import Card
from qtpy import API_NAME
assert API_NAME == 'PySide6'
print(Card.__name__)
"""
    env = {**os.environ, "QT_QPA_PLATFORM": "offscreen"}
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "Card"


def test_active_window_constructs_with_pyside(qapp, monkeypatch: pytest.MonkeyPatch) -> None:
    from calibrate_pro.gui.app import CalibrateProWindow

    monkeypatch.setattr(CalibrateProWindow, "_start_services", lambda self: setattr(self, "_guard", None))
    monkeypatch.setattr(CalibrateProWindow, "_check_first_run", lambda self: None)
    window = CalibrateProWindow()
    assert type(window).__module__.startswith("calibrate_pro")
    window.close()
```

Add this session fixture at the top of `tests/conftest.py`, before any Qt import:

```python
import os

os.environ["QT_API"] = "pyside6"
os.environ["QT_QPA_PLATFORM"] = "offscreen"


@pytest.fixture(scope="session")
def qapp():
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    yield app
```

- [ ] **Step 2: Run the test and verify the expected failure**

```powershell
$env:QT_API = 'pyside6'
$env:QT_QPA_PLATFORM = 'offscreen'
python -m pytest tests/test_qt_binding_contract.py -q
```

Expected: source-token and metadata tests fail against the PyQt6 starting state; `calibrate_pro.qt_runtime` is absent.

- [ ] **Step 3: Add deterministic source and frozen binding selection**

Create `calibrate_pro/qt_runtime.py`:

```python
"""Deterministic Qt binding selection for Calibrate Pro."""

from __future__ import annotations

import os

QT_API = "pyside6"


def configure_qt_api() -> str:
    """Select PySide6 before QtPy or Build UI imports."""
    os.environ["QT_API"] = QT_API
    return QT_API
```

Create `packaging/pyi_rth_qt_api.py`:

```python
"""PyInstaller runtime hook selecting Calibrate Pro's sole Qt binding."""

import os

os.environ["QT_API"] = "pyside6"
```

At the beginning of `calibrate_pro/gui/app.py`, before `build_ui` imports, add:

```python
from calibrate_pro.qt_runtime import configure_qt_api

configure_qt_api()
```

Call the same function inside `cmd_gui` and `cmd_hdr` before importing PySide6 or a GUI module.

- [ ] **Step 4: Apply the exact binding substitutions with `apply_patch`**

Across the complete file list produced by the Step 1 scan, apply these substitutions and remove both legacy PyQt5 fallback branches rather than retaining a second binding path:

```text
from PyQt6.            -> from PySide6.
from PyQt5.            -> from PySide6.
pyqtSignal             -> Signal
pyqtSlot               -> Slot
pyqtProperty           -> Property
Professional GUI (PyQt6) -> Professional GUI (PySide6)
```

Every file using `Signal`, `Slot`, or `Property` imports it from `PySide6.QtCore`. Update PDF-export messages to name PySide6. Do not introduce a binding compatibility shim inside Calibrate; Build UI owns the QtPy bridge.

- [ ] **Step 5: Update developer dependency metadata**

Replace the GUI and all extras with:

```toml
[project.optional-dependencies]
gui = ["PySide6>=6.11.1,<7", "build-ui[pyside6]>=2,<3"]
tray = ["pystray>=0.19.4", "Pillow>=10.0,<11"]
sensor = ["hidapi>=0.14,<1"]
macos = ["pyobjc-framework-Quartz>=9.0,<11", "pyobjc-framework-CoreFoundation>=9.0,<11"]
test = ["pytest>=8.0", "pytest-cov>=5"]
dev = ["pytest>=8.0", "pytest-cov>=5", "ruff>=0.6", "mypy>=1.10", "build>=1.2"]
all = [
    "PySide6>=6.11.1,<7",
    "build-ui[pyside6]>=2,<3",
    "pystray>=0.19.4",
    "Pillow>=10.0,<11",
    "hidapi>=0.14,<1",
]
```

Update Mypy comments from PyQt6 to PySide6.

- [ ] **Step 6: Run focused and complete verification**

```powershell
$env:QT_API = 'pyside6'
$env:QT_QPA_PLATFORM = 'offscreen'
python -m pytest tests/test_qt_binding_contract.py -q
ruff check .
mypy calibrate_pro
python -m pytest -q
```

Expected: binding contract passes, Ruff and Mypy succeed, and all existing tests remain green.

- [ ] **Step 7: Commit the binding cutover**

```powershell
git add pyproject.toml packaging/pyi_rth_qt_api.py calibrate_pro tests/conftest.py tests/test_qt_binding_contract.py
git commit -m "refactor: migrate Calibrate Pro to PySide6"
```

---

### Task 3: Unify Version and Wheel Metadata

**Files:**
- Modify: `pyproject.toml:1-19`
- Modify: `calibrate_pro/__init__.py:1-16`
- Modify: `calibrate_pro/app.py:29`
- Modify: `calibrate_pro/advanced/__init__.py:270`
- Modify: `calibrate_pro/sensorless/__init__.py:117`
- Modify: `calibrate_pro/gui/app.py:47-49`
- Modify: `calibrate_pro/gui/theme.py:9-12`
- Modify: `calibrate_pro/gui/pages/settings.py:35-40`
- Modify: `calibrate_pro/gui/report_viewer.py:90-105`
- Create: `tests/test_release_metadata.py`

**Interfaces:**
- Consumes: `calibrate_pro.__version__` as the only release version source.
- Produces: package, GUI, report, CLI, installer, and release-script version `1.1.0`.

- [ ] **Step 1: Write failing version and extras tests**

Create `tests/test_release_metadata.py`:

```python
from __future__ import annotations

import ast
from pathlib import Path

from calibrate_pro import __version__

ROOT = Path(__file__).resolve().parents[1]


def test_release_version_is_1_1_0() -> None:
    assert __version__ == "1.1.0"


def test_pyproject_reads_version_dynamically() -> None:
    text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert 'dynamic = ["version"]' in text
    assert 'version = {attr = "calibrate_pro.__version__"}' in text
    assert '\nversion = "1.1.0"' not in text


def test_no_independent_application_version_assignment() -> None:
    offenders: list[str] = []
    for path in sorted((ROOT / "calibrate_pro").rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, (ast.Assign, ast.AnnAssign)):
                continue
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for target in targets:
                if isinstance(target, ast.Name) and target.id in {"APP_VERSION", "__version__"}:
                    if path != ROOT / "calibrate_pro" / "__init__.py":
                        offenders.append(f"{path.relative_to(ROOT)}:{node.lineno}")
    assert offenders == []


def test_all_extra_is_gui_tray_sensor_union() -> None:
    text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    for requirement in (
        '"PySide6>=6.11.1,<7"',
        '"build-ui[pyside6]>=2,<3"',
        '"pystray>=0.19.4"',
        '"Pillow>=10.0,<11"',
        '"hidapi>=0.14,<1"',
    ):
        assert text.count(requirement) >= 2
```

- [ ] **Step 2: Verify RED**

```powershell
python -m pytest tests/test_release_metadata.py -q
```

Expected: version, dynamic metadata, and duplicate assignment tests fail.

- [ ] **Step 3: Make the root package authoritative**

Set in `calibrate_pro/__init__.py`:

```python
__version__ = "1.1.0"
__author__ = "Zain Dana Harper"
```

Remove other assignments and import the root version where compatibility exports remain:

```python
from calibrate_pro import __version__

APP_VERSION = __version__
```

For the report dataclass default, use:

```python
from calibrate_pro import __version__

software_version: str = __version__
```

- [ ] **Step 4: Make setuptools dynamic and remove the license warning**

Use this project metadata shape:

```toml
[build-system]
requires = ["setuptools>=77.0"]
build-backend = "setuptools.build_meta"

[project]
name = "calibrate-pro"
dynamic = ["version"]
description = "Windows display calibration toolkit with evidence-labeled sensorless and measured workflows, DDC/CI, ICC/LUT output, and reports"
readme = "README.md"
license = "LicenseRef-FSL-1.1-MIT"
license-files = ["LICENSE"]

[tool.setuptools.dynamic]
version = {attr = "calibrate_pro.__version__"}
```

Retain the existing authors, Python floor, dependencies, classifiers, URLs, scripts, and package discovery.

- [ ] **Step 5: Verify source and built-wheel metadata**

```powershell
python -m pytest tests/test_release_metadata.py -q
python -m build
python -c "import glob, zipfile; p=glob.glob('dist/calibrate_pro-1.1.0-*.whl')[0]; z=zipfile.ZipFile(p); m=[n for n in z.namelist() if n.endswith('.dist-info/METADATA')][0]; t=z.read(m).decode(); assert 'Version: 1.1.0' in t; assert 'build-ui[pyside6]>=2,<3' in t; print(p)"
```

Expected: metadata tests pass and the built wheel reports version 1.1.0 plus the Build UI PySide extra.

- [ ] **Step 6: Commit metadata unification**

```powershell
git add pyproject.toml calibrate_pro tests/test_release_metadata.py
git commit -m "build: unify Calibrate Pro 1.1 metadata"
```

---

### Task 4: Make ST 2084 One Audited Float64 Primitive

**Files:**
- Create: `calibrate_pro/core/pq.py`
- Create: `tests/data/st2084-gold-vectors.json`
- Create: `tests/test_pq_conformance.py`
- Modify: `calibrate_pro/core/color_math.py:559-581,775-816`
- Modify: `calibrate_pro/core/color_models.py:49-101`
- Modify: `calibrate_pro/targets/gamma.py:167-223`
- Modify: `calibrate_pro/hdr/pq_st2084.py:17-94`
- Modify: `calibrate_pro/lut_system/dwm_lut.py:44-49,122-156`
- Modify: `calibrate_pro/display/scrgb_pipeline.py:51-117`
- Modify: `calibrate_pro/core/__init__.py`, `calibrate_pro/targets/__init__.py`, `calibrate_pro/hdr/__init__.py`

**Interfaces:**
- Produces: `pq_eotf(signal, peak_luminance=10000.0) -> np.ndarray` and `pq_oetf(luminance, peak_luminance=10000.0) -> np.ndarray`.
- Preserves: existing compatibility signatures such as `normalize` and `normalize_input` through delegates.

- [ ] **Step 1: Add independent gold vectors**

Create `tests/data/st2084-gold-vectors.json`:

```json
{
  "float64_encode_abs_tolerance": 1e-12,
  "float64_decode_abs_tolerance_nits": 1e-8,
  "vectors": [
    {"nits": 0.0001, "pq": 0.001667188217860},
    {"nits": 0.005, "pq": 0.015076399042368},
    {"nits": 0.1, "pq": 0.062336865662696},
    {"nits": 1.0, "pq": 0.149945732100180},
    {"nits": 100.0, "pq": 0.508078421517399},
    {"nits": 203.0, "pq": 0.580688881041611},
    {"nits": 1000.0, "pq": 0.751827096247041},
    {"nits": 4000.0, "pq": 0.902572393310937},
    {"nits": 10000.0, "pq": 1.0}
  ]
}
```

- [ ] **Step 2: Write the failing cross-surface test**

Create `tests/test_pq_conformance.py` with a table covering:

```python
SURFACES = (
    ("core", "calibrate_pro.core.pq", "pq_oetf", "pq_eotf"),
    ("color_math", "calibrate_pro.core.color_math", "pq_oetf", "pq_eotf"),
    ("color_models", "calibrate_pro.core.color_models", "pq_oetf", "pq_eotf"),
    ("targets", "calibrate_pro.targets.gamma", "pq_oetf", "pq_eotf"),
    ("hdr", "calibrate_pro.hdr.pq_st2084", "pq_oetf", "pq_eotf"),
    ("dwm", "calibrate_pro.lut_system.dwm_lut", "pq_oetf", "pq_eotf"),
    ("scrgb", "calibrate_pro.display.scrgb_pipeline", "_pq_oetf", "_pq_eotf"),
)
```

The test loads the JSON, imports each module with `importlib.import_module`, encodes the nits array, decodes the expected PQ array, and uses `np.testing.assert_allclose` with the declared absolute tolerances. Add:

```python
def test_st2084_m2_is_exact() -> None:
    from calibrate_pro.core.pq import ST2084_M2

    assert ST2084_M2 == 78.84375
```

- [ ] **Step 3: Verify RED catches the current defect**

```powershell
python -m pytest tests/test_pq_conformance.py -q
```

Expected: missing canonical module plus failures where 100 nits encodes near zero instead of `0.508078421517399`.

- [ ] **Step 4: Add the canonical implementation**

Create `calibrate_pro/core/pq.py`:

```python
"""SMPTE ST 2084 perceptual quantizer in absolute luminance units."""

from __future__ import annotations

from typing import Any

import numpy as np

ST2084_M1 = 2610.0 / 16384.0
ST2084_M2 = 2523.0 / 4096.0 * 128.0
ST2084_C1 = 3424.0 / 4096.0
ST2084_C2 = 2413.0 / 4096.0 * 32.0
ST2084_C3 = 2392.0 / 4096.0 * 32.0
ST2084_PEAK_NITS = 10000.0


def pq_eotf(signal: Any, peak_luminance: float = ST2084_PEAK_NITS) -> np.ndarray:
    if peak_luminance <= 0:
        raise ValueError("peak_luminance must be positive")
    value = np.clip(np.asarray(signal, dtype=np.float64), 0.0, 1.0)
    power = np.power(value, 1.0 / ST2084_M2)
    numerator = np.maximum(power - ST2084_C1, 0.0)
    denominator = ST2084_C2 - ST2084_C3 * power
    denominator = np.where(np.abs(denominator) < 1e-30, 1e-30, denominator)
    normalized = np.power(np.maximum(numerator / denominator, 0.0), 1.0 / ST2084_M1)
    return normalized * peak_luminance


def pq_oetf(luminance: Any, peak_luminance: float = ST2084_PEAK_NITS) -> np.ndarray:
    if peak_luminance <= 0:
        raise ValueError("peak_luminance must be positive")
    value = np.clip(np.asarray(luminance, dtype=np.float64), 0.0, peak_luminance)
    power = np.power(value / peak_luminance, ST2084_M1)
    numerator = ST2084_C1 + ST2084_C2 * power
    denominator = 1.0 + ST2084_C3 * power
    return np.power(numerator / denominator, ST2084_M2)
```

- [ ] **Step 5: Replace duplicate math with compatibility delegates**

Import the canonical functions under private names and preserve public signatures. For example, `hdr/pq_st2084.py` becomes:

```python
from calibrate_pro.core.pq import (
    ST2084_C1 as PQ_C1,
    ST2084_C2 as PQ_C2,
    ST2084_C3 as PQ_C3,
    ST2084_M1 as PQ_M1,
    ST2084_M2 as PQ_M2,
    ST2084_PEAK_NITS as PQ_REFERENCE_WHITE,
    pq_eotf as _canonical_pq_eotf,
    pq_oetf as _canonical_pq_oetf,
)


def pq_eotf(signal: np.ndarray, normalize: bool = False) -> np.ndarray:
    result = _canonical_pq_eotf(signal)
    return result / PQ_REFERENCE_WHITE if normalize else result


def pq_oetf(luminance: np.ndarray, normalize_input: bool = False) -> np.ndarray:
    values = np.asarray(luminance, dtype=np.float64)
    if normalize_input:
        values = values * PQ_REFERENCE_WHITE
    return _canonical_pq_oetf(values)
```

Use direct delegates in the other modules and remove all duplicate ST 2084 constants except public aliases needed for compatibility.

- [ ] **Step 6: Run focused and complete numerical verification**

```powershell
python -m pytest tests/test_pq_conformance.py tests/test_color_math.py tests/test_hdr_workflow.py -q
python -m pytest -q
```

Expected: every surface passes the same vectors and the complete suite remains green.

- [ ] **Step 7: Commit the fail-closed PQ boundary**

```powershell
git add calibrate_pro/core/pq.py calibrate_pro/core calibrate_pro/targets calibrate_pro/hdr calibrate_pro/lut_system/dwm_lut.py calibrate_pro/display/scrgb_pipeline.py tests/data/st2084-gold-vectors.json tests/test_pq_conformance.py
git commit -m "fix: make ST 2084 fail closed across PQ surfaces"
```

---

### Task 5: Make HDR Metrics Carry Evidence Provenance

**Files:**
- Create: `calibrate_pro/verification/provenance.py`
- Create: `tests/test_hdr_provenance.py`
- Modify: `calibrate_pro/hdr/workflow.py:78-93,312-360`
- Modify: `calibrate_pro/hdr/__init__.py`
- Modify: `tests/test_hdr_workflow.py:371-425`

**Interfaces:**
- Produces: `EvidenceKind`, `MetricValue`, and provenance-bearing `HDRCalibrationResult`.
- Produces: `HDRWorkflow.run(measured_luminances=None, lut_size=17, evidence=EvidenceKind.NOT_MEASURED, evidence_source=None)`.

- [ ] **Step 1: Write failing provenance tests**

Create `tests/test_hdr_provenance.py`:

```python
from __future__ import annotations

import numpy as np
import pytest

from calibrate_pro.hdr.workflow import HDRTarget, HDRWorkflow
from calibrate_pro.verification.provenance import EvidenceKind


def test_default_hdr_run_reports_no_measurements() -> None:
    result = HDRWorkflow(HDRTarget.hdr10_1000()).run(lut_size=5)
    assert result.eotf_error.value is None
    assert result.peak_luminance.value is None
    assert result.gamut_coverage_bt2020.value is None
    assert result.eotf_error.evidence is EvidenceKind.NOT_MEASURED


def test_simulation_requires_explicit_evidence() -> None:
    result = HDRWorkflow(HDRTarget.hdr10_1000()).run(
        lut_size=5,
        evidence=EvidenceKind.SIMULATED,
        evidence_source="ST 2084 reference replay",
    )
    assert result.eotf_error.value == pytest.approx(0.0)
    assert result.peak_luminance.value == pytest.approx(10000.0)
    assert result.eotf_error.evidence is EvidenceKind.SIMULATED
    assert result.gamut_coverage_bt2020.value is None


def test_numeric_readings_require_explicit_source() -> None:
    readings = np.linspace(0.0, 1000.0, 21)
    with pytest.raises(ValueError, match="evidence_source"):
        HDRWorkflow(HDRTarget.hdr10_1000()).run(
            measured_luminances=readings,
            evidence=EvidenceKind.MEASURED,
            lut_size=5,
        )


def test_measured_readings_serialize_source() -> None:
    workflow = HDRWorkflow(HDRTarget.hdr10_1000())
    expected = workflow.generate_eotf_patches(steps=21)[:, 1]
    result = workflow.run(
        measured_luminances=expected,
        evidence=EvidenceKind.MEASURED,
        evidence_source="i1Display3 serial-redacted receipt 42",
        lut_size=5,
    )
    payload = result.to_dict()
    assert payload["peak_luminance"]["evidence"] == "measured"
    assert payload["peak_luminance"]["source"] == "i1Display3 serial-redacted receipt 42"
    assert payload["gamut_coverage_bt2020"]["value"] is None
```

- [ ] **Step 2: Verify RED**

```powershell
python -m pytest tests/test_hdr_provenance.py tests/test_hdr_workflow.py -q
```

Expected: provenance module is missing and current default run fabricates perfect measurements and gamut coverage.

- [ ] **Step 3: Add the evidence contract**

Create `calibrate_pro/verification/provenance.py`:

```python
"""Evidence labels for calibration metrics."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any


class EvidenceKind(str, Enum):
    NOT_MEASURED = "not_measured"
    ESTIMATED = "estimated"
    MEASURED = "measured"
    SIMULATED = "simulated"
    REPLAYED = "replayed"


@dataclass(frozen=True)
class MetricValue:
    value: float | None
    unit: str
    evidence: EvidenceKind
    source: str | None = None

    def __post_init__(self) -> None:
        if self.evidence is EvidenceKind.NOT_MEASURED and self.value is not None:
            raise ValueError("not-measured metrics cannot carry a value")
        if self.evidence in {EvidenceKind.MEASURED, EvidenceKind.SIMULATED, EvidenceKind.REPLAYED} and not self.source:
            raise ValueError(f"{self.evidence.value} metrics require an evidence source")

    def display_text(self, decimals: int = 2) -> str:
        if self.value is None:
            return "Not measured"
        label = {
            EvidenceKind.ESTIMATED: "estimated",
            EvidenceKind.SIMULATED: "simulated",
            EvidenceKind.REPLAYED: "replayed",
        }.get(self.evidence)
        suffix = f" ({label})" if label else ""
        return f"{self.value:.{decimals}f} {self.unit}{suffix}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "value": self.value,
            "unit": self.unit,
            "evidence": self.evidence.value,
            "source": self.source,
        }
```

- [ ] **Step 4: Make the HDR result and run path explicit**

Replace numeric metric fields in `HDRCalibrationResult` with:

```python
@dataclass
class HDRCalibrationResult:
    target: HDRTarget
    eotf_error: MetricValue
    peak_luminance: MetricValue
    gamut_coverage_bt2020: MetricValue
    tone_map_curve: np.ndarray
    lut_data: np.ndarray | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "target": self.target.standard.value,
            "eotf_error": self.eotf_error.to_dict(),
            "peak_luminance": self.peak_luminance.to_dict(),
            "gamut_coverage_bt2020": self.gamut_coverage_bt2020.to_dict(),
        }
```

Change `run` to this signature and branch contract:

```python
def run(
    self,
    measured_luminances: np.ndarray | None = None,
    lut_size: int = 17,
    *,
    evidence: EvidenceKind = EvidenceKind.NOT_MEASURED,
    evidence_source: str | None = None,
) -> HDRCalibrationResult:
```

If readings are absent and evidence is `NOT_MEASURED`, create `MetricValue(None, "percent", EvidenceKind.NOT_MEASURED)` and `MetricValue(None, "nits", EvidenceKind.NOT_MEASURED)` values. If evidence is `SIMULATED`, use expected luminance and label the derived error/peak with that source. If readings exist, require `MEASURED` or `REPLAYED` plus a source. Gamut always remains `NOT_MEASURED` in this 1.1 lane because luminance-only arrays cannot prove color volume.

- [ ] **Step 5: Update existing tests to call simulation explicitly**

Tests that intentionally exercise the perfect reference path call:

```python
result = hdr10_wf.run(
    lut_size=5,
    evidence=EvidenceKind.SIMULATED,
    evidence_source="test ST 2084 reference",
)
```

Measured-array tests pass `EvidenceKind.REPLAYED` and `evidence_source="test fixture"` unless they exercise an instrument adapter.

- [ ] **Step 6: Run focused and complete verification**

```powershell
python -m pytest tests/test_hdr_provenance.py tests/test_hdr_workflow.py -q
python -m pytest -q
```

Expected: default metrics are absent, explicit simulation/replay remains testable, and no gamut percentage is synthesized.

- [ ] **Step 7: Commit provenance**

```powershell
git add calibrate_pro/verification/provenance.py calibrate_pro/hdr tests/test_hdr_provenance.py tests/test_hdr_workflow.py
git commit -m "fix: require explicit provenance for HDR results"
```

---

### Task 6: Add the Pure Workflow and Transactional Recovery Boundary

**Files:**
- Create: `calibrate_pro/workflow.py`
- Create: `calibrate_pro/recovery.py`
- Create: `tests/test_workflow.py`

**Interfaces:**
- Consumes: `EvidenceKind` from Task 5.
- Produces: `WorkflowStage`, `CalibrationMethod`, `CapabilityState`, `ApplyPlan`, `WorkflowError`, `WorkflowController`, `DisplayStateAdapter`, and `apply_transactionally()`.

- [ ] **Step 1: Write failing state-machine tests**

Create `tests/test_workflow.py`:

```python
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

import pytest

from calibrate_pro.recovery import ApplyReceipt, DisplayStateAdapter, apply_transactionally
from calibrate_pro.workflow import (
    ApplyPlan,
    CalibrationMethod,
    CapabilityState,
    WorkflowController,
    WorkflowStage,
)


def test_detect_method_preview_apply_sequence() -> None:
    controller = WorkflowController(CapabilityState(sensor_available=True, ddc_available=True, dwm_lut_available=True))
    controller.detect_complete()
    controller.select_method(CalibrationMethod.MEASURED)
    plan = ApplyPlan(
        display_id="display-1",
        method=CalibrationMethod.MEASURED,
        target_whitepoint="D65",
        target_gamma="2.2",
        target_gamut="sRGB",
        ddc_changes=(("brightness", 42),),
        output_files=("display-1.icc", "display-1.cube"),
    )
    controller.set_preview(plan)
    controller.confirm_apply()
    assert controller.stage is WorkflowStage.APPLY


def test_measured_method_is_disabled_without_sensor() -> None:
    controller = WorkflowController(CapabilityState(sensor_available=False, ddc_available=True, dwm_lut_available=True))
    controller.detect_complete()
    with pytest.raises(ValueError, match="supported colorimeter"):
        controller.select_method(CalibrationMethod.MEASURED)


def test_apply_requires_preview_confirmation() -> None:
    controller = WorkflowController(CapabilityState(sensor_available=False, ddc_available=False, dwm_lut_available=False))
    controller.detect_complete()
    controller.select_method(CalibrationMethod.SENSORLESS)
    with pytest.raises(ValueError, match="preview"):
        controller.confirm_apply()


@dataclass
class FakeAdapter(DisplayStateAdapter):
    verify_result: bool = True
    raise_during_apply: bool = False
    restored: bool = False

    def capture(self, display_id: str) -> dict[str, object]:
        return {"display_id": display_id, "brightness": 50}

    def apply(self, plan: ApplyPlan) -> None:
        if self.raise_during_apply:
            raise RuntimeError("apply failed")

    def verify(self, plan: ApplyPlan) -> bool:
        return self.verify_result

    def restore(self, snapshot: dict[str, object]) -> None:
        self.restored = True


@pytest.mark.parametrize(
    ("adapter", "message"),
    (
        (FakeAdapter(raise_during_apply=True), "apply failed"),
        (FakeAdapter(verify_result=False), "verification failed"),
    ),
)
def test_failed_apply_restores_snapshot(adapter: FakeAdapter, message: str) -> None:
    plan = ApplyPlan("display-1", CalibrationMethod.SENSORLESS, "D65", "2.2", "sRGB", (), ("display-1.icc",))
    receipt = apply_transactionally(adapter, plan)
    assert receipt == ApplyReceipt(success=False, restored=True, error=message)
    assert adapter.restored is True
```

- [ ] **Step 2: Verify RED**

```powershell
python -m pytest tests/test_workflow.py -q
```

Expected: workflow and recovery modules are absent.

- [ ] **Step 3: Add the pure workflow model**

Create `calibrate_pro/workflow.py`:

```python
"""Pure calibration workflow state and capability gating."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class WorkflowStage(str, Enum):
    DETECT = "detect"
    METHOD = "method"
    PREVIEW = "preview"
    APPLY = "apply"
    VERIFY = "verify"
    SAVE_REPORT = "save_report"


class CalibrationMethod(str, Enum):
    SENSORLESS = "sensorless"
    MEASURED = "measured"


@dataclass(frozen=True)
class CapabilityState:
    sensor_available: bool
    ddc_available: bool
    dwm_lut_available: bool

    def disabled_reason(self, method: CalibrationMethod) -> str | None:
        if method is CalibrationMethod.MEASURED and not self.sensor_available:
            return "Measured calibration requires a supported colorimeter."
        return None


@dataclass(frozen=True)
class ApplyPlan:
    display_id: str
    method: CalibrationMethod
    target_whitepoint: str
    target_gamma: str
    target_gamut: str
    ddc_changes: Sequence[tuple[str, int]]
    output_files: Sequence[str]


@dataclass(frozen=True)
class WorkflowError:
    category: str
    summary: str
    detail: str
    next_action: str


class WorkflowController:
    def __init__(self, capabilities: CapabilityState):
        self.capabilities = capabilities
        self.stage = WorkflowStage.DETECT
        self.method: CalibrationMethod | None = None
        self.preview: ApplyPlan | None = None
        self.error: WorkflowError | None = None

    def detect_complete(self) -> None:
        if self.stage is not WorkflowStage.DETECT:
            raise ValueError("detect can complete only from the detect stage")
        self.stage = WorkflowStage.METHOD

    def select_method(self, method: CalibrationMethod) -> None:
        if self.stage is not WorkflowStage.METHOD:
            raise ValueError("method selection requires the method stage")
        reason = self.capabilities.disabled_reason(method)
        if reason:
            raise ValueError(reason)
        self.method = method
        self.stage = WorkflowStage.PREVIEW

    def set_preview(self, plan: ApplyPlan) -> None:
        if self.stage is not WorkflowStage.PREVIEW:
            raise ValueError("preview data requires the preview stage")
        if plan.method is not self.method:
            raise ValueError("preview method does not match the selected method")
        self.preview = plan

    def confirm_apply(self) -> None:
        if self.stage is not WorkflowStage.PREVIEW or self.preview is None:
            raise ValueError("apply requires a completed preview")
        self.stage = WorkflowStage.APPLY

    def apply_complete(self) -> None:
        if self.stage is not WorkflowStage.APPLY:
            raise ValueError("apply completion requires the apply stage")
        self.stage = WorkflowStage.VERIFY

    def verify_complete(self) -> None:
        if self.stage is not WorkflowStage.VERIFY:
            raise ValueError("verification completion requires the verify stage")
        self.stage = WorkflowStage.SAVE_REPORT

    def fail(self, error: WorkflowError) -> None:
        self.error = error
```

- [ ] **Step 4: Add the injected transaction boundary**

Create `calibrate_pro/recovery.py`:

```python
"""Transactional display application through an injected adapter."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from calibrate_pro.workflow import ApplyPlan


class DisplayStateAdapter(Protocol):
    def capture(self, display_id: str) -> dict[str, object]:
        raise NotImplementedError

    def apply(self, plan: ApplyPlan) -> None:
        raise NotImplementedError

    def verify(self, plan: ApplyPlan) -> bool:
        raise NotImplementedError

    def restore(self, snapshot: dict[str, object]) -> None:
        raise NotImplementedError


@dataclass(frozen=True)
class ApplyReceipt:
    success: bool
    restored: bool
    error: str | None


def apply_transactionally(adapter: DisplayStateAdapter, plan: ApplyPlan) -> ApplyReceipt:
    snapshot = adapter.capture(plan.display_id)
    try:
        adapter.apply(plan)
        if not adapter.verify(plan):
            raise RuntimeError("verification failed")
    except Exception as exc:
        adapter.restore(snapshot)
        return ApplyReceipt(success=False, restored=True, error=str(exc))
    return ApplyReceipt(success=True, restored=False, error=None)
```

- [ ] **Step 5: Run focused and full tests**

```powershell
python -m pytest tests/test_workflow.py -q
python -m pytest -q
```

Expected: pure transition and recovery tests pass without importing hardware modules.

- [ ] **Step 6: Commit the workflow boundary**

```powershell
git add calibrate_pro/workflow.py calibrate_pro/recovery.py tests/test_workflow.py
git commit -m "feat: add transactional calibration workflow"
```

---

### Task 7: Add Read-Only Runtime Diagnostics and Resource Resolution

**Files:**
- Create: `calibrate_pro/runtime.py`
- Create: `calibrate_pro/diagnostics.py`
- Create: `tests/test_diagnostics.py`
- Modify: `calibrate_pro/main.py:39-47,1904-1914,2112-2174`
- Modify: `calibrate_pro/lut_system/dwm_lut.py:632-663`

**Interfaces:**
- Produces: `application_root() -> Path`, `resource_path(*parts: str) -> Path`, `build_doctor_report(root: Path | None = None) -> dict[str, object]`, and `doctor_exit_code(report) -> int`.
- Produces: CLI command `calibrate-pro doctor --json`.

- [ ] **Step 1: Write failing diagnostic and mutation tests**

Create `tests/test_diagnostics.py`:

```python
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from calibrate_pro import __version__


def test_doctor_report_is_stable_json(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / "dwm_lut").mkdir()
    for name in ("DwmLutGUI.exe", "dwm_lut.dll", "WindowsDisplayAPI.dll", "LICENSE", "LICENSE-THIRD-PARTY"):
        (tmp_path / "dwm_lut" / name).write_bytes(b"proof")
    notices = tmp_path / "THIRD_PARTY_LICENSES"
    notices.mkdir()
    for name in ("LGPL-3.0-only.txt", "QT_SOURCE_OFFER.txt", "LGPL_RELINKING.md", "source-provenance.json"):
        (notices / name).write_text("proof", encoding="utf-8")

    from calibrate_pro.diagnostics import build_doctor_report

    report = build_doctor_report(root=tmp_path)
    encoded = json.dumps(report, sort_keys=True)
    assert json.loads(encoded)["application"]["version"] == __version__
    assert report["qt"]["api_name"] == "PySide6"
    assert report["pq"]["passed"] is True
    assert report["resources"]["dwm_lut"]["available"] is True


def test_doctor_never_imports_hardware_or_mutation_modules(tmp_path: Path) -> None:
    before = set(sys.modules)
    from calibrate_pro.diagnostics import build_doctor_report

    build_doctor_report(root=tmp_path)
    added = set(sys.modules) - before
    forbidden = (
        "calibrate_pro.hardware",
        "calibrate_pro.services.calibration_guard",
        "calibrate_pro.utils.startup_manager",
    )
    assert not any(name == prefix or name.startswith(prefix + ".") for name in added for prefix in forbidden)


def test_frozen_resource_root_uses_meipass(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)
    from calibrate_pro.runtime import application_root, resource_path

    assert application_root() == tmp_path
    assert resource_path("dwm_lut", "DwmLutGUI.exe") == tmp_path / "dwm_lut" / "DwmLutGUI.exe"
```

- [ ] **Step 2: Verify RED**

```powershell
python -m pytest tests/test_diagnostics.py -q
```

Expected: runtime and diagnostics modules are absent.

- [ ] **Step 3: Add source/frozen resource resolution**

Create `calibrate_pro/runtime.py`:

```python
"""Read-only source and frozen resource locations."""

from __future__ import annotations

import sys
from pathlib import Path


def application_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS")).resolve()
    return Path(__file__).resolve().parents[1]


def resource_path(*parts: str) -> Path:
    return application_root().joinpath(*parts)
```

Use `resource_path("dwm_lut")` as the first candidate in `DwmLutController._find_dwm_lut()`; do not instantiate the controller from doctor because its constructor creates directories and enumerates monitors.

- [ ] **Step 4: Add the doctor report**

Create `calibrate_pro/diagnostics.py` with these exact report sections and dependency imports:

```python
"""Read-only packaged-runtime diagnostics."""

from __future__ import annotations

import importlib
import importlib.metadata
import json
import os
import sys
from pathlib import Path
from typing import Any

import numpy as np

from calibrate_pro import __version__
from calibrate_pro.core.pq import pq_eotf, pq_oetf
from calibrate_pro.qt_runtime import configure_qt_api
from calibrate_pro.runtime import application_root

DEPENDENCIES = (
    ("build-color", "build_color"),
    ("build-ui", "build_ui"),
    ("QtPy", "qtpy"),
    ("PySide6", "PySide6"),
    ("PySide6-Addons", "PySide6.QtWebEngineWidgets"),
    ("PySide6-Essentials", "PySide6.QtWidgets"),
    ("shiboken6", "shiboken6"),
    ("numpy", "numpy"),
    ("scipy", "scipy"),
)


def _dependency_status(distribution: str, module: str) -> dict[str, object]:
    try:
        version = importlib.metadata.version(distribution)
        importlib.import_module(module)
    except Exception as exc:
        return {"version": None, "importable": False, "error": str(exc)}
    return {"version": version, "importable": True, "error": None}


def build_doctor_report(root: Path | None = None) -> dict[str, Any]:
    configure_qt_api()
    from qtpy import API_NAME

    base = (root or application_root()).resolve()
    dwm_names = ("DwmLutGUI.exe", "dwm_lut.dll", "WindowsDisplayAPI.dll", "LICENSE", "LICENSE-THIRD-PARTY")
    notice_names = ("LGPL-3.0-only.txt", "QT_SOURCE_OFFER.txt", "LGPL_RELINKING.md", "source-provenance.json")
    dependencies = {name: _dependency_status(name, module) for name, module in DEPENDENCIES}
    encoded = float(pq_oetf(np.array([100.0], dtype=np.float64))[0])
    decoded = float(pq_eotf(np.array([encoded], dtype=np.float64))[0])
    dwm_missing = [name for name in dwm_names if not (base / "dwm_lut" / name).is_file()]
    notice_missing = [name for name in notice_names if not (base / "THIRD_PARTY_LICENSES" / name).is_file()]
    passed_pq = abs(encoded - 0.508078421517399) <= 1e-12 and abs(decoded - 100.0) <= 1e-8
    ok = all(item["importable"] for item in dependencies.values()) and not dwm_missing and not notice_missing and passed_pq
    return {
        "schema_version": 1,
        "application": {"name": "Calibrate Pro", "version": __version__, "frozen": bool(getattr(sys, "frozen", False))},
        "qt": {"qt_api": os.environ.get("QT_API"), "api_name": API_NAME},
        "dependencies": dependencies,
        "resources": {
            "dwm_lut": {"available": not dwm_missing, "missing": dwm_missing},
            "third_party_licenses": {"available": not notice_missing, "missing": notice_missing},
        },
        "pq": {"encoded_100_nits": encoded, "decoded_nits": decoded, "passed": passed_pq},
        "capabilities": {"display_mutation": "not_probed", "usb": "not_probed", "startup": "not_probed"},
        "ok": ok,
    }


def doctor_exit_code(report: dict[str, Any]) -> int:
    return 0 if report.get("ok") is True else 1


def render_doctor_json(root: Path | None = None) -> str:
    return json.dumps(build_doctor_report(root=root), indent=2, sort_keys=True)
```

- [ ] **Step 5: Wire the CLI without importing hardware**

Add:

```python
def cmd_doctor(args) -> int:
    from calibrate_pro.diagnostics import build_doctor_report, doctor_exit_code

    report = build_doctor_report()
    print(json.dumps(report, indent=2, sort_keys=True))
    return doctor_exit_code(report)
```

Import `json`, add a `doctor` parser with `--json`, and dispatch it before the default GUI branch. Plain `doctor` may print the same JSON in 1.1; this keeps one stable diagnostic representation.

- [ ] **Step 6: Verify focused behavior**

```powershell
python -m pytest tests/test_diagnostics.py -q
python -m calibrate_pro.main doctor --json
```

Expected: tests pass. Source doctor may return status 1 until Task 11 adds the checked-in notice tree; its JSON must still be valid and must name the missing notices without touching hardware.

- [ ] **Step 7: Commit diagnostics**

```powershell
git add calibrate_pro/runtime.py calibrate_pro/diagnostics.py calibrate_pro/main.py calibrate_pro/lut_system/dwm_lut.py tests/test_diagnostics.py
git commit -m "feat: add read-only packaged diagnostics"
```

---

### Task 8: Remove Automatic Elevation and Launch-Time Actuators

**Files:**
- Create: `tests/test_least_privilege.py`
- Modify: `calibrate_pro/main.py:35-69,869-893,1875-1901,2023-2027`
- Modify: `calibrate_pro/gui/hdr_calibration.py:19-54,230-232,617-668`
- Modify: `calibrate_pro/gui/app.py:1383-1450`

**Interfaces:**
- Consumes: explicit `WorkflowStage.APPLY` boundary from Task 6.
- Produces: unelevated `cmd_gui`, `cmd_hdr`, and opt-in CalibrationGuard startup.

- [ ] **Step 1: Write failing launch-boundary tests**

Create `tests/test_least_privilege.py`:

```python
from __future__ import annotations

import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def test_gui_entry_points_do_not_request_elevation() -> None:
    main_text = (ROOT / "calibrate_pro" / "main.py").read_text(encoding="utf-8")
    hdr_text = (ROOT / "calibrate_pro" / "gui" / "hdr_calibration.py").read_text(encoding="utf-8")
    assert '"runas"' not in main_text
    assert "run_as_admin" not in main_text
    assert '"runas"' not in hdr_text
    assert "run_as_admin" not in hdr_text


def test_hdr_window_does_not_schedule_dwm_start(monkeypatch: pytest.MonkeyPatch, qapp) -> None:
    from calibrate_pro.gui.hdr_calibration import HDRCalibrationWindow
    from calibrate_pro.lut_system.dwm_lut import DwmLutController

    calls: list[str] = []
    monkeypatch.setattr(DwmLutController, "start_dwm_lut_gui", lambda self: calls.append("start") or True)
    window = HDRCalibrationWindow()
    qapp.processEvents()
    assert calls == []
    window.close()


def test_main_window_guard_is_opt_in(monkeypatch: pytest.MonkeyPatch, qapp) -> None:
    from calibrate_pro.gui.app import CalibrateProWindow

    calls: list[str] = []
    monkeypatch.setattr(CalibrateProWindow, "_start_services", lambda self: calls.append("start"))
    monkeypatch.setattr(CalibrateProWindow, "_check_first_run", lambda self: None)
    window = CalibrateProWindow()
    assert calls == []
    window.close()
```

- [ ] **Step 2: Verify RED**

```powershell
$env:QT_QPA_PLATFORM = 'offscreen'
python -m pytest tests/test_least_privilege.py -q
```

Expected: source contains automatic elevation and both launch-time actuator tests fail.

- [ ] **Step 3: Remove GUI-wide elevation paths**

Delete `is_admin()` and `run_as_admin()` from `main.py` and the HDR GUI module. `cmd_hdr` follows the same pattern as `cmd_gui`: configure Qt, import PySide6/window, construct, show, and enter the event loop. Update command help to remove `runs as admin`.

Keep elevation only inside the explicit `DwmLutController.start_dwm_lut_gui()` actuator called after Apply confirmation; no launch path calls it.

- [ ] **Step 4: Make CalibrationGuard an explicit persisted opt-in**

Replace unconditional service startup in `CalibrateProWindow.__init__` with:

```python
self._guard = None
guard_enabled = self.settings.value("services/calibration_guard_enabled", False, type=bool)
if guard_enabled:
    self._start_services()
```

The settings page owns changing this value. Enabling it explains that it monitors and may reapply a previously saved calibration. A fresh install defaults to disabled.

- [ ] **Step 5: Verify least privilege and regressions**

```powershell
$env:QT_QPA_PLATFORM = 'offscreen'
python -m pytest tests/test_least_privilege.py -q
python -m pytest -q
```

Expected: GUI/HDR launch tests invoke no elevation or automatic actuator.

- [ ] **Step 6: Commit the least-privilege boundary**

```powershell
git add calibrate_pro/main.py calibrate_pro/gui/hdr_calibration.py calibrate_pro/gui/app.py tests/test_least_privilege.py
git commit -m "fix: keep desktop launch unelevated"
```

---

### Task 9: Present the Active Workflow and Truthful Result States

**Files:**
- Create: `tests/test_truthful_results.py`
- Modify: `calibrate_pro/__init__.py:1-10`
- Modify: `calibrate_pro/gui/app.py:1114-1170,1383-1410,1661-1725`
- Modify: `calibrate_pro/gui/calibration_wizard.py:563-580,854-910,1069-1081`
- Modify: `calibrate_pro/gui/pages/calibrate.py`
- Modify: `calibrate_pro/gui/pages/calibration_page.py:199,222-243,341-360`
- Modify: `calibrate_pro/gui/pages/verify.py:965-1014,1161-1192,1223-1237`
- Modify: `calibrate_pro/gui/dialogs.py:80-105`
- Modify: `calibrate_pro/gui/hdr_calibration.py`

**Interfaces:**
- Consumes: `WorkflowController`, `ApplyPlan`, `apply_transactionally`, `MetricValue`, and `EvidenceKind`.
- Produces: visible Detect -> Method -> Preview -> Apply -> Verify -> Save/Report navigation and actionable disabled states.

- [ ] **Step 1: Write failing copy and state tests**

Create `tests/test_truthful_results.py`:

```python
from __future__ import annotations

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
CLAIM_FILES = (
    ROOT / "calibrate_pro" / "__init__.py",
    ROOT / "calibrate_pro" / "gui" / "calibration_wizard.py",
    ROOT / "calibrate_pro" / "gui" / "pages" / "calibration_page.py",
    ROOT / "calibrate_pro" / "gui" / "pages" / "verify.py",
    ROOT / "calibrate_pro" / "gui" / "dialogs.py",
)


def test_no_observed_looking_seed_values_or_threshold_promises() -> None:
    text = "\n".join(path.read_text(encoding="utf-8") for path in CLAIM_FILES)
    for phrase in (
        "Average Delta E: 0.42",
        "Max Delta E: 0.89",
        "99.2% DCI-P3",
        "87.3% BT.2020",
        "100% coverage",
        "Achieves Delta E < 1.0",
        "Delta E < 0.5 typical",
    ):
        assert phrase not in text


def test_missing_metric_renders_not_measured() -> None:
    from calibrate_pro.verification.provenance import EvidenceKind, MetricValue

    assert MetricValue(None, "dE2000", EvidenceKind.NOT_MEASURED).display_text() == "Not measured"


def test_measured_method_is_visibly_disabled_without_sensor(monkeypatch: pytest.MonkeyPatch, qapp) -> None:
    from calibrate_pro.gui.pages.calibrate import CalibratePage

    monkeypatch.setattr(CalibratePage, "_detect_sensor", lambda self: False, raising=False)
    page = CalibratePage()
    assert page.measured_method_enabled is False
    assert "supported colorimeter" in page.measured_disabled_reason.lower()
    page.close()
```

- [ ] **Step 2: Verify RED**

```powershell
$env:QT_QPA_PLATFORM = 'offscreen'
python -m pytest tests/test_truthful_results.py -q
```

Expected: current fixed metrics and promises fail the scan; active page does not expose the required capability-state properties.

- [ ] **Step 3: Replace synthetic metric presentation**

In verification widgets, absent Delta E is `None`, draws a neutral border, and renders `Not measured`. Remove `_seed_grayscale_chart` and random/noise-derived readings. Explicit demonstration data uses `EvidenceKind.SIMULATED` and displays `(simulated)` beside every metric.

The wizard no longer calls `_simulate_calibration()` as a completion path. An unavailable worker disables Apply and displays:

```text
This method is unavailable with the detected hardware. You can still export the proposed ICC and LUT files.
```

HDR GUI title and description use `HDR target transform` until an instrument-backed CP-HDR-1 workflow supplies measurements.

- [ ] **Step 4: Bind the active Calibrate page to the pure workflow**

Expose these read-only properties on `CalibratePage`:

```python
@property
def measured_method_enabled(self) -> bool:
    return self._workflow.capabilities.sensor_available


@property
def measured_disabled_reason(self) -> str:
    return self._workflow.capabilities.disabled_reason(CalibrationMethod.MEASURED) or ""
```

Preview lists target white point, gamma, gamut, each proposed DDC change, and each output path. Apply remains disabled until `WorkflowController.preview` is populated and the user confirms. Call `apply_transactionally()` from the Apply worker; on failure show `ApplyReceipt.error`, state whether restoration succeeded, and do not advance to Verify.

- [ ] **Step 5: Make the shell navigation and dashboard primary action explicit**

The main dashboard primary button text is `Calibrate a display`. Active navigation labels are exactly:

```python
CAL_PAGES = ["Detect", "Method", "Preview", "Apply", "Verify", "Save/Report"]
```

If the current shell keeps page-internal stages rather than six top-level widgets, show the same ordered stage indicator within Calibrate and keep Dashboard/Profiles/DDC/Settings as secondary navigation. The test asserts the exact ordered label sequence from the chosen active component.

- [ ] **Step 6: Verify GUI truthfulness and complete suite**

```powershell
$env:QT_QPA_PLATFORM = 'offscreen'
python -m pytest tests/test_truthful_results.py tests/test_workflow.py tests/test_verification.py -q
python -m pytest -q
```

Expected: no fabricated observed result remains and unsupported actions are disabled with reasons.

- [ ] **Step 7: Commit active product states**

```powershell
git add calibrate_pro tests/test_truthful_results.py
git commit -m "feat: present an evidence-bound calibration flow"
```

---

### Task 10: Make GUI Imports Lazy and Freeze One Explicit Onedir Graph

**Files:**
- Modify: `calibrate_pro/gui/__init__.py`
- Replace: `calibrate-pro.spec`
- Delete: `CalibratePro.spec`
- Create: `tests/test_gui_lazy_imports.py`
- Create: `tests/test_packaging_contract.py`

**Interfaces:**
- Consumes: PySide runtime hook, doctor, active GUI modules, and Build Color core boundary.
- Produces: `dist/CalibratePro/CalibratePro.exe` and `dist/CalibratePro/CalibrateProCLI.exe` sharing one onedir `_internal` tree.

- [ ] **Step 1: Write failing lazy-import and spec tests**

Create `tests/test_gui_lazy_imports.py`:

```python
from __future__ import annotations

import importlib
import sys


def test_importing_gui_does_not_eagerly_load_historical_pages() -> None:
    for name in list(sys.modules):
        if name == "calibrate_pro.gui" or name.startswith("calibrate_pro.gui."):
            sys.modules.pop(name)
    gui = importlib.import_module("calibrate_pro.gui")
    assert gui.__name__ == "calibrate_pro.gui"
    assert "calibrate_pro.gui.main_window" not in sys.modules
    assert "calibrate_pro.gui.calibration_wizard" not in sys.modules
    assert "calibrate_pro.gui.professional_calibration" not in sys.modules
```

Create the first contract tests in `tests/test_packaging_contract.py`:

```python
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_only_canonical_spec_exists() -> None:
    assert sorted(path.name for path in ROOT.glob("*.spec")) == ["calibrate-pro.spec"]


def test_spec_is_pyside_onedir_least_privilege_and_no_upx() -> None:
    text = (ROOT / "calibrate-pro.spec").read_text(encoding="utf-8")
    assert "COLLECT(" in text
    assert 'name="CalibratePro"' in text
    assert 'name="CalibrateProCLI"' in text
    assert text.count("uac_admin=False") == 2
    assert "uac_admin=True" not in text
    assert "upx=True" not in text
    assert "collect_submodules" not in text
    assert '"build_color.gui"' in text
    assert '"PyQt5"' in text and '"PyQt6"' in text
    assert "packaging/pyi_rth_qt_api.py" in text
```

- [ ] **Step 2: Verify RED**

```powershell
python -m pytest tests/test_gui_lazy_imports.py tests/test_packaging_contract.py -q
```

Expected: eager imports, duplicate spec, onefile layout, UPX, and elevation fail.

- [ ] **Step 3: Replace the GUI package initializer with a lazy facade**

Use an exact literal mapping and cached `__getattr__`:

```python
"""Lazy compatibility facade for Calibrate Pro GUI surfaces."""

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
        module_name, attribute_name = _EXPORTS[name]
    except KeyError as exc:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}") from exc
    value = getattr(import_module(module_name), attribute_name)
    globals()[name] = value
    return value
```

- [ ] **Step 4: Replace the spec with the explicit shared onedir graph**

Use one `Analysis`, one `PYZ`, two `EXE` objects with `exclude_binaries=True`, and one `COLLECT`. The explicit hidden imports are:

```python
ACTIVE_MODULES = [
    "calibrate_pro.diagnostics",
    "calibrate_pro.runtime",
    "calibrate_pro.qt_runtime",
    "calibrate_pro.gui.app",
    "calibrate_pro.gui.pages.calibrate",
    "calibrate_pro.gui.pages.verify",
    "calibrate_pro.gui.pages.profiles",
    "calibrate_pro.gui.pages.ddc_control",
    "calibrate_pro.gui.pages.settings",
    "calibrate_pro.gui.widgets.cie_diagram",
    "calibrate_pro.core.pq",
    "calibrate_pro.core.color_math",
    "calibrate_pro.core.calibration_engine",
    "calibrate_pro.core.lut_engine",
    "calibrate_pro.panels.builtin_panels",
    "calibrate_pro.panels.database",
    "calibrate_pro.panels.detection",
    "calibrate_pro.profiles.icc_v4",
    "calibrate_pro.verification.provenance",
    "build_color.adaptation",
    "build_color.difference",
    "build_color.gamut",
    "build_color.spaces",
    "build_ui.theme",
    "build_ui.widgets",
    "qtpy",
    "PySide6.QtCore",
    "PySide6.QtGui",
    "PySide6.QtWidgets",
    "PySide6.QtPrintSupport",
    "PySide6.QtWebEngineWidgets",
]
```

Use `copy_metadata` for `calibrate-pro`, `build-color`, `build-ui`, `QtPy`, `PySide6`, `PySide6-Addons`, `PySide6-Essentials`, `shiboken6`, `numpy`, and `scipy`. Include the five `dwm_lut` files as data. Set:

```python
runtime_hooks=["packaging/pyi_rth_qt_api.py"]
excludes=[
    "PyQt5",
    "PyQt6",
    "build_color.gui",
    "torch",
    "torchvision",
    "torchaudio",
    "transformers",
    "diffusers",
    "pandas",
    "sklearn",
    "matplotlib",
    "IPython",
    "jupyter",
    "notebook",
    "cv2",
    "wx",
    "pytest",
    "hypothesis",
]
```

Set `upx=False`, `strip=False`, and `uac_admin=False` on both EXEs and `upx=False` on `COLLECT`. Delete `CalibratePro.spec` with `git rm`.

- [ ] **Step 5: Verify source contract and build**

```powershell
python -m pytest tests/test_gui_lazy_imports.py tests/test_packaging_contract.py -q
$env:QT_API = 'pyside6'
python -m PyInstaller --clean --noconfirm calibrate-pro.spec
```

Expected: `dist\CalibratePro\CalibratePro.exe`, `CalibrateProCLI.exe`, and `_internal` exist.

- [ ] **Step 6: Audit the initial frozen graph**

```powershell
rg -n "PyQt5|PyQt6|build_color\.gui" build\CalibratePro\Analysis-00.toc
Get-ChildItem -Recurse -LiteralPath dist\CalibratePro | Where-Object { $_.Name -match '^PyQt|PyQt.*dist-info' }
```

Expected: both commands produce no matches. The final release audit is added in Task 12.

- [ ] **Step 7: Commit the onedir graph**

```powershell
git add calibrate_pro/gui/__init__.py calibrate-pro.spec tests/test_gui_lazy_imports.py tests/test_packaging_contract.py
git rm CalibratePro.spec
git commit -m "build: define the PySide-only onedir application"
```

---

### Task 11: Lock the Windows Release and Curate Qt Redistribution Inputs

**Files:**
- Create: `packaging/requirements-win64.in`
- Create: `packaging/requirements-win64-py312.lock`
- Create: `packaging/toolchain-win64.json`
- Create: `packaging/qt-components.json`
- Create: `packaging/source-provenance.lock.json`
- Create: `THIRD_PARTY_LICENSES/README.md`
- Create: `THIRD_PARTY_LICENSES/LGPL-3.0-only.txt`
- Create: `THIRD_PARTY_LICENSES/Qt-for-Python-NOTICE.txt`
- Create: `THIRD_PARTY_LICENSES/QT_SOURCE_OFFER.txt`
- Create: `THIRD_PARTY_LICENSES/LGPL_RELINKING.md`
- Create: `tests/test_release_lock.py`
- Create: `tests/test_qt_redistribution.py`
- Delete: `requirements.txt`
- Delete: `build_installer.bat`

**Interfaces:**
- Consumes: published Build UI 2.0.0 and the proven PySide6 6.11.1 stack.
- Produces: hash-locked Python 3.12 Windows inputs plus a fail-closed license/source classification for every staged Qt component.

- [ ] **Step 1: Write failing lock and redistribution tests**

Create `tests/test_release_lock.py`:

```python
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_release_lock_is_hashed_and_pyside_only() -> None:
    lock = (ROOT / "packaging" / "requirements-win64-py312.lock").read_text(encoding="utf-8")
    for name in ("build-color", "build-ui", "qtpy", "pyside6", "shiboken6", "numpy", "scipy", "pyinstaller"):
        assert name in lock.lower()
    assert "pyqt5" not in lock.lower()
    assert "pyqt6" not in lock.lower()
    requirement_blocks = [block for block in lock.split("\n\n") if "==" in block]
    assert requirement_blocks
    assert all("--hash=sha256:" in block for block in requirement_blocks)


def test_legacy_release_paths_are_removed() -> None:
    assert not (ROOT / "requirements.txt").exists()
    assert not (ROOT / "build_installer.bat").exists()
```

Create `tests/test_qt_redistribution.py`:

```python
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_required_qt_notice_files_are_committed() -> None:
    directory = ROOT / "THIRD_PARTY_LICENSES"
    required = {
        "README.md",
        "LGPL-3.0-only.txt",
        "Qt-for-Python-NOTICE.txt",
        "QT_SOURCE_OFFER.txt",
        "LGPL_RELINKING.md",
    }
    assert required <= {path.name for path in directory.iterdir() if path.is_file()}
    assert "GNU LESSER GENERAL PUBLIC LICENSE" in (directory / "LGPL-3.0-only.txt").read_text(encoding="utf-8")


def test_source_provenance_is_complete_and_verified() -> None:
    data = json.loads((ROOT / "packaging" / "source-provenance.lock.json").read_text(encoding="utf-8"))
    assert data["schema_version"] == 1
    assert data["modifications"] == []
    for component in data["components"]:
        assert component["name"]
        assert component["version"]
        assert component["source_url"].startswith("https://")
        assert len(component["sha256"]) == 64


def test_qt_policy_has_no_unclassified_component() -> None:
    data = json.loads((ROOT / "packaging" / "qt-components.json").read_text(encoding="utf-8"))
    assert data["schema_version"] == 1
    assert data["default"] == "reject"
    assert all(entry["pattern"] and entry["license"] and entry["source_component"] for entry in data["components"])
```

- [ ] **Step 2: Verify RED**

```powershell
python -m pytest tests/test_release_lock.py tests/test_qt_redistribution.py -q
```

Expected: lock, notice, policy, and provenance files are absent; legacy paths remain.

- [ ] **Step 3: Define and compile the release roots**

Create `packaging/requirements-win64.in`:

```text
build-color==1.0.2
build-ui[pyside6]==2.0.0
QtPy==2.4.3
PySide6==6.11.1
numpy==2.5.1
scipy==1.18.0
hidapi==0.15.0
pyinstaller==6.21.0
build==1.3.0
```

Create `packaging/toolchain-win64.json`:

```json
{
  "schema_version": 1,
  "python": "3.12.10",
  "architecture": "x86_64-pc-windows-msvc",
  "uv": "0.11.25",
  "pyinstaller": "6.21.0",
  "inno_setup": "6.7.3"
}
```

Compile only after Build UI 2.0.0 is published to the release index:

```powershell
uv pip compile packaging/requirements-win64.in --python-version 3.12 --python-platform x86_64-pc-windows-msvc --only-binary :all: --generate-hashes --no-sources --output-file packaging/requirements-win64-py312.lock
```

Expected: the lock contains hashes for every resolved wheel and no direct URL, Git, local path, or PyQt requirement.

- [ ] **Step 4: Curate, do not infer, Qt license and source mappings**

Run the Task 10 onedir build once. Enumerate every staged `PySide6*.pyd`, `Qt6*.dll`, Qt plugin, resource helper, and QtWebEngine binary. For each distinct component, verify its upstream module/license and add a literal entry to `packaging/qt-components.json` with this schema:

```json
{
  "schema_version": 1,
  "default": "reject",
  "components": [
    {
      "pattern": "_internal/PySide6/QtCore.pyd",
      "license": "LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only",
      "source_component": "pyside-setup-6.11.1"
    },
    {
      "pattern": "_internal/PySide6/Qt6Core.dll",
      "license": "LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only",
      "source_component": "qtbase-6.11.1"
    }
  ]
}
```

Add all observed components as separate literal entries. Do not use a catch-all pattern for Qt plugins or WebEngine helpers. The release audit rejects the next unknown file and prints its relative path for deliberate classification.

Download the exact corresponding source archives from the upstream Qt/PySide source locations, compute SHA-256, and record one `components` entry per source archive in `packaging/source-provenance.lock.json`. The record includes `name`, `version`, `source_url`, `sha256`, and `license`; top-level `modifications` is the empty list because 1.1 redistributes unmodified libraries.

- [ ] **Step 5: Commit the complete notice set**

Use the verbatim GNU LGPL v3 text from `https://www.gnu.org/licenses/lgpl-3.0.txt`. `Qt-for-Python-NOTICE.txt` names PySide6, shiboken6, Qt 6.11.1, the selected license family, and upstream project links. `QT_SOURCE_OFFER.txt` identifies each exact source archive and checksum from the provenance lock and states how the distributor will provide corresponding source. `LGPL_RELINKING.md` explains the external onedir DLL layout and how a recipient can replace compatible Qt/PySide libraries. `README.md` states that Calibrate's FSL terms do not replace third-party licenses and preserves reverse-engineering/relinking rights needed to debug modified LGPL components.

Copy `dwm_lut/LICENSE` and `dwm_lut/LICENSE-THIRD-PARTY` during staging; retain their originals beside the bundled runtime too.

- [ ] **Step 6: Remove competing dependency/build declarations**

```powershell
git rm requirements.txt build_installer.bat
```

- [ ] **Step 7: Verify the release inputs**

```powershell
python -m pytest tests/test_release_lock.py tests/test_qt_redistribution.py -q
python -m pip install --require-hashes -r packaging/requirements-win64-py312.lock
python -m pip check
```

Expected: all tests pass and the locked environment is consistent.

- [ ] **Step 8: Commit lock and redistribution inputs**

```powershell
git add packaging THIRD_PARTY_LICENSES tests/test_release_lock.py tests/test_qt_redistribution.py
git commit -m "build: lock Windows and Qt redistribution inputs"
```

---

### Task 12: Generate Deterministic Artifacts and Fail-Closed Receipts

**Files:**
- Create: `scripts/release_artifacts.py`
- Create: `tests/test_release_artifacts.py`
- Modify: `tests/test_packaging_contract.py`
- Modify: `tests/test_qt_redistribution.py`

**Interfaces:**
- Produces: `audit_analysis_toc`, `audit_staged_tree`, `write_reproducible_zip`, `probe_authenticode`, `write_dependency_manifest`, `write_qt_inventory`, and `write_sha256s`.

- [ ] **Step 1: Write failing deterministic-archive and audit tests**

Create `tests/test_release_artifacts.py` with synthetic staged trees that assert:

```python
def test_reproducible_zip_is_byte_identical(tmp_path: Path) -> None:
    staged = tmp_path / "staged"
    staged.mkdir()
    (staged / "z.txt").write_text("z", encoding="utf-8")
    (staged / "a.txt").write_text("a", encoding="utf-8")
    first = tmp_path / "first.zip"
    second = tmp_path / "second.zip"
    assert write_reproducible_zip(staged, first, 315532800) == write_reproducible_zip(staged, second, 315532800)
    assert first.read_bytes() == second.read_bytes()


def test_stage_audit_rejects_pyqt_and_build_color_gui(tmp_path: Path) -> None:
    for relative in ("_internal/PyQt6/QtCore.pyd", "_internal/build_color/gui/app.py"):
        staged = tmp_path / relative.replace("/", "_")
        staged.mkdir()
        path = staged / relative
        path.parent.mkdir(parents=True)
        path.write_bytes(b"forbidden")
        with pytest.raises(RuntimeError, match="forbidden"):
            audit_staged_tree(staged, qt_policy={"schema_version": 1, "default": "reject", "components": []})


def test_unknown_qt_component_fails_closed(tmp_path: Path) -> None:
    staged = tmp_path / "staged"
    path = staged / "_internal" / "PySide6" / "Qt6Unknown.dll"
    path.parent.mkdir(parents=True)
    path.write_bytes(b"qt")
    with pytest.raises(RuntimeError, match="Qt6Unknown.dll"):
        audit_staged_tree(staged, qt_policy={"schema_version": 1, "default": "reject", "components": []})
```

Also test the 350 MiB constant, sorted `SHA256SUMS.txt`, required receipts, `UPX!` rejection in Qt binaries, and injectable Authenticode probe output.

- [ ] **Step 2: Verify RED**

```powershell
python -m pytest tests/test_release_artifacts.py -q
```

Expected: release module is absent.

- [ ] **Step 3: Implement deterministic ZIP writing**

Use this exact function in `scripts/release_artifacts.py`:

```python
def write_reproducible_zip(source: Path, output: Path, epoch: int) -> str:
    timestamp = time.gmtime(max(epoch, 315532800))[:6]
    members = sorted(path for path in source.rglob("*") if path.is_file())
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path in members:
            relative = path.relative_to(source).as_posix()
            info = zipfile.ZipInfo(relative, date_time=timestamp)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.create_system = 0
            info.external_attr = 0o100644 << 16
            archive.writestr(info, path.read_bytes(), compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)
    return hashlib.sha256(output.read_bytes()).hexdigest()
```

Imports are `hashlib`, `json`, `subprocess`, `time`, `zipfile`, `dataclasses`, `importlib.metadata`, and `pathlib.Path`. `MAXIMUM_BYTES = 350 * 1024 * 1024`.

- [ ] **Step 4: Implement staged-tree and TOC audits**

`audit_staged_tree()` walks sorted relative paths and rejects path components beginning with `PyQt5` or `PyQt6`, any `build_color/gui` subtree, forbidden framework names, missing required `dwm_lut` files, missing notice files, unknown Qt policy entries, and `UPX!` bytes in a Qt/PySide binary. `audit_analysis_toc()` parses the PyInstaller TOC with `ast.literal_eval` and rejects module names starting with `PyQt5`, `PyQt6`, or `build_color.gui`.

The Qt inventory records for each matched binary: relative path, SHA-256, byte size, policy license, and source component. The dependency manifest records installed distribution name/version and all included distribution-metadata hashes. The canonical staged inventory records every relative path, size, and SHA-256.

- [ ] **Step 5: Implement real signature status probing**

`probe_authenticode(path)` invokes:

```powershell
Get-AuthenticodeSignature -LiteralPath '<absolute path>' | Select-Object Status,StatusMessage,SignerCertificate,TimeStamperCertificate | ConvertTo-Json -Depth 4 -Compress
```

The Python function parses JSON and records `Valid`, `NotSigned`, or the reported failure. It never reads `CALIBRATE_PRO_SIGNED` or another claimed status variable.

- [ ] **Step 6: Generate all receipts from the staged tree**

The command interface is:

```text
python scripts/release_artifacts.py prepare --staged-dir dist/CalibratePro --analysis-toc build/CalibratePro/Analysis-00.toc --release-dir release --source-date-epoch <integer>
python scripts/release_artifacts.py finalize --staged-dir dist/CalibratePro --release-dir release --require-installer
```

`prepare` copies notices, emits dependency/source/Qt/staged inventories, audits, and creates the portable ZIP. `finalize` probes signatures, enforces both size gates, and writes sorted hashes after every other output exists.

- [ ] **Step 7: Verify unit and integration behavior**

```powershell
python -m pytest tests/test_release_artifacts.py tests/test_qt_redistribution.py tests/test_packaging_contract.py -q
python scripts/release_artifacts.py prepare --staged-dir dist/CalibratePro --analysis-toc build/CalibratePro/Analysis-00.toc --release-dir release --source-date-epoch 315532800
.\dist\CalibratePro\CalibrateProCLI.exe doctor --json
```

Expected: audits pass only after notices/receipts are staged; frozen doctor returns `ok: true`.

- [ ] **Step 8: Commit artifact tooling**

```powershell
git add scripts/release_artifacts.py tests/test_release_artifacts.py tests/test_packaging_contract.py tests/test_qt_redistribution.py
git commit -m "build: add deterministic release audits"
```

---

### Task 13: Build the Per-User Installer and Canonical Release Pipeline

**Files:**
- Create: `installer/CalibratePro.iss`
- Create: `scripts/build_windows.ps1`
- Create: `scripts/smoke_frozen.ps1`
- Create: `scripts/verify_reproducibility.ps1`
- Modify: `tests/test_packaging_contract.py`

**Interfaces:**
- Consumes: locked environment, canonical spec, staged audits, and version `1.1.0`.
- Produces: installer, portable ZIP, receipts, smoke evidence, and two-build reproducibility evidence.

- [ ] **Step 1: Add failing installer and orchestration tests**

Extend `tests/test_packaging_contract.py` to assert:

```python
def test_inno_is_per_user_and_version_is_injected() -> None:
    text = (ROOT / "installer" / "CalibratePro.iss").read_text(encoding="utf-8")
    assert "PrivilegesRequired=lowest" in text
    assert r"DefaultDirName={localappdata}\Programs\Calibrate Pro" in text
    assert "#ifndef AppVersion" in text
    assert '#define AppVersion "1.1.0"' not in text
    assert "runatstartup" not in text.lower()


def test_build_script_uses_hash_lock_and_canonical_spec() -> None:
    text = (ROOT / "scripts" / "build_windows.ps1").read_text(encoding="utf-8")
    assert "--require-hashes" in text
    assert "requirements-win64-py312.lock" in text
    assert "calibrate-pro.spec" in text
    assert "Compress-Archive" not in text
    assert "release_artifacts.py" in text
```

- [ ] **Step 2: Verify RED**

```powershell
python -m pytest tests/test_packaging_contract.py -q
```

Expected: installer and scripts are absent.

- [ ] **Step 3: Create the Inno Setup definition**

Create `installer/CalibratePro.iss`:

```text
#ifndef AppVersion
  #error AppVersion must be supplied with /DAppVersion
#endif
#define AppName "Calibrate Pro"
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
OutputBaseFilename=CalibratePro-{#AppVersion}-Setup
Compression=lzma2/ultra64
SolidCompression=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
PrivilegesRequired=lowest
UninstallDisplayIcon={app}\{#AppExeName}
WizardStyle=modern

[Files]
Source: "..\dist\CalibratePro\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\Calibrate Pro"; Filename: "{app}\{#AppExeName}"
Name: "{autodesktop}\Calibrate Pro"; Filename: "{app}\{#AppExeName}"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Additional shortcuts:"; Flags: unchecked

[Run]
Filename: "{app}\{#AppExeName}"; Description: "Launch Calibrate Pro"; Flags: nowait postinstall skipifsilent
```

- [ ] **Step 4: Create the canonical PowerShell build**

`scripts/build_windows.ps1` accepts `-Unsigned` and `-SkipInstaller`, verifies Windows x64 and Python 3.12.10, creates a uniquely named temporary venv, installs the hash lock with `python -m pip install --require-hashes -r`, builds the Calibrate wheel, installs it with `--no-deps`, runs tests, builds PyInstaller, runs `release_artifacts.py prepare`, runs frozen doctor, conditionally signs both EXEs, compiles Inno with:

```powershell
& $iscc "/DAppVersion=$version" '.\installer\CalibratePro.iss'
```

It then conditionally signs the installer and runs `release_artifacts.py finalize`. It validates the temporary directory is below `[IO.Path]::GetTempPath()` and begins with `calibrate-pro-release-` before recursive removal.

Pin Inno Setup 6.7.3 in CI and receipt its `ISCC.exe` file version. The build refuses another version unless `packaging/toolchain-win64.json` changes in a reviewed commit.

- [ ] **Step 5: Add safe frozen smoke and reproducibility scripts**

`smoke_frozen.ps1` runs CLI help, version, doctor, and starts each unelevated GUI executable long enough to verify it remains running, then stops it. It first sets `QT_QPA_PLATFORM=offscreen`; automatic actuators were removed in Tasks 8-9.

`verify_reproducibility.ps1` runs two unsigned `-SkipInstaller` builds in separate temporary roots, compares the two portable ZIP SHA-256 values and canonical staged-inventory JSON bytes, and exits nonzero on any difference. Signing and Inno timestamps are outside this unsigned identity comparison and are recorded separately.

- [ ] **Step 6: Run the complete local Windows release**

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/build_windows.ps1 -Unsigned
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/smoke_frozen.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/verify_reproducibility.ps1
```

Expected release files:

```text
release/CalibratePro-1.1.0-Setup.exe
release/CalibratePro-1.1.0-win64.zip
release/SHA256SUMS.txt
release/dependency-manifest.json
release/qt-module-inventory.json
release/build-receipt.json
release/signature-status.json
release/THIRD_PARTY_LICENSES/
```

- [ ] **Step 7: Commit the release pipeline**

```powershell
git add installer scripts/build_windows.ps1 scripts/smoke_frozen.ps1 scripts/verify_reproducibility.ps1 tests/test_packaging_contract.py
git commit -m "build: produce Calibrate Pro Windows artifacts"
```

---

### Task 14: Add Clean Windows CI, Documentation, and Release Acceptance

**Files:**
- Modify: `.github/workflows/ci.yml`
- Modify: `.github/workflows/release.yml`
- Create: `tests/test_release_workflow_contract.py`
- Modify: `README.md`
- Modify: `RELEASE_NOTES.md`
- Modify: `CHANGELOG.md`
- Modify: `ARCHITECTURE.md`
- Modify: `SECURITY.md`
- Modify: `docs/ENTERPRISE-READINESS.md`
- Modify after evidence exists: `docs/superpowers/specs/2026-07-09-calibrate-pro-packaging-polish-design.md`

**Interfaces:**
- Consumes: canonical Windows build and its receipts.
- Produces: clean-runner artifacts, truthful operator documentation, and R1-R20 acceptance evidence.

- [ ] **Step 1: Write failing workflow-source tests**

Create `tests/test_release_workflow_contract.py`:

```python
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_ci_selects_pyside_and_uses_published_dependencies() -> None:
    text = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    assert "QT_API: pyside6" in text
    assert "git+https://" not in text
    assert '.[all,test]' in text


def test_release_runs_the_canonical_windows_pipeline() -> None:
    text = (ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
    for token in (
        "windows-latest",
        "scripts/build_windows.ps1",
        "scripts/smoke_frozen.ps1",
        "scripts/verify_reproducibility.ps1",
        "SHA256SUMS.txt",
        "dependency-manifest.json",
        "qt-module-inventory.json",
    ):
        assert token in text
```

- [ ] **Step 2: Verify RED**

```powershell
python -m pytest tests/test_release_workflow_contract.py -q
```

Expected: current CI uses Git Build Color and current release is Ubuntu wheel-only.

- [ ] **Step 3: Update CI and release jobs**

Set `QT_API: pyside6` and `QT_QPA_PLATFORM: offscreen`. Source tests install `.[all,test]` from published declarations. Keep Python 3.10-3.13 source coverage. Add one Windows Python 3.12 packaging job that installs exactly Inno Setup 6.7.3, verifies its Authenticode signature and version, invokes the canonical build/smoke/reproducibility scripts, and uploads the complete `release/` directory.

The release workflow retains trusted PyPI publishing for the wheel and adds a dependent Windows artifact job. Signing secrets are consumed only by the release environment; the same scripts produce a truthful unsigned release when secrets are absent.

- [ ] **Step 4: Verify workflow and source gates**

```powershell
python -m pytest tests/test_release_workflow_contract.py -q
ruff check .
ruff format --check .
mypy calibrate_pro
python -m pytest -q
python -m build
```

Expected: all checks pass without warnings attributable to Calibrate metadata.

- [ ] **Step 5: Align public documentation to verified behavior**

README leads with installer, portable ZIP, then developer wheel. It states no Python or separate Build Color/Build UI install is needed for binary users; developer GUI installs use `pip install "calibrate-pro[gui]"`. Replace PyQt references with PySide6/Build UI 2/QtPy. Document both doctor commands and each receipt.

Release notes distinguish sensorless estimates, supported instrument measurements, explicit HDR simulation/replay, and CP-HDR-1 as future measured HDR work. Do not claim DisplayCAL, ColourSpace, or Calman replacement parity in 1.1. State that unsigned artifacts are unsigned and that physical hardware validation is limited to named receipts.

Architecture documents the pure workflow, actuator boundary, Build Color core imports, Build UI 2 bridge, PySide-only freeze, onedir layout, and source/frozen diagnostics. Security documents protected signing secrets, no telemetry assumption, and third-party source/relinking rights.

- [ ] **Step 6: Run disposable-machine acceptance**

In a clean Windows 10/11 x64 VM or Windows Sandbox with Python absent and networking disabled after artifact transfer:

1. Verify both published hashes.
2. Install `CalibratePro-1.1.0-Setup.exe` per user and confirm no installer elevation prompt.
3. Launch GUI, HDR target-transform GUI, Dashboard, Calibrate, Verify, Profiles, DDC, Settings, and report export.
4. Run installed `CalibrateProCLI.exe doctor --json` and retain the JSON receipt.
5. Confirm missing sensor and DDC capabilities are disabled with reasons and never report success.
6. Uninstall silently and verify application files and shortcuts are removed.
7. Extract `CalibratePro-1.1.0-win64.zip`, repeat GUI and doctor without installation, and confirm no external Python is used.
8. Confirm installer and ZIP are each at most `367001600` bytes.

- [ ] **Step 7: Record R1-R20 evidence in the approved spec**

For every requirement, append the exact command or VM observation, artifact path, SHA-256, result, and limitation. Do not change the spec status to Implemented unless all twenty requirements have direct evidence. A missing signing certificate remains a truthful unsigned limitation, not a failed build.

- [ ] **Step 8: Commit CI and release evidence documentation**

```powershell
git add .github README.md RELEASE_NOTES.md CHANGELOG.md ARCHITECTURE.md SECURITY.md docs/ENTERPRISE-READINESS.md docs/superpowers/specs/2026-07-09-calibrate-pro-packaging-polish-design.md tests/test_release_workflow_contract.py
git commit -m "docs: publish Calibrate Pro 1.1 release evidence"
```

---

## Final Acceptance Sequence

Run from the isolated worktree only:

```powershell
if ((git rev-parse --show-toplevel).Trim() -ne 'C:\dev\worktrees\calibrate-pro-1.1-pyside') { throw 'Wrong worktree' }
$env:QT_API = 'pyside6'
$env:QT_QPA_PLATFORM = 'offscreen'
ruff check .
ruff format --check .
mypy calibrate_pro
python -m pytest -q
python -m build
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/build_windows.ps1 -Unsigned
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/smoke_frozen.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/verify_reproducibility.ps1
.\dist\CalibratePro\CalibrateProCLI.exe doctor --json
Get-FileHash .\release\CalibratePro-1.1.0-Setup.exe -Algorithm SHA256
Get-FileHash .\release\CalibratePro-1.1.0-win64.zip -Algorithm SHA256
git diff --check
git status --short
```

Expected: all automated gates pass, doctor reports `ok: true`, both hashes exist, and status contains only intentional implementation changes or is clean after the final commit.

## Plan Self-Review

- R1 is implemented by Tasks 10-14 and proven only by Task 14's offline clean-machine check.
- R2, R3, and R18 map to Tasks 1-3, 10-13.
- R4 and R5 map to Task 10.
- R6 maps to Task 3.
- R7, R8, R9, and R10 map to Tasks 5, 6, 8, and 9.
- R11, R12, R14, and R20 map to Tasks 11-14.
- R13 maps to Task 7 and frozen checks in Tasks 12-14.
- R15 and R19 map to Tasks 8, 10, 13, and 14.
- R16 maps to Tasks 5 and 9.
- R17 maps to Task 4 and doctor/release checks in Tasks 7 and 12.
- Type names and signatures are consistent: `EvidenceKind`, `MetricValue`, `ApplyPlan`, `WorkflowController`, `DisplayStateAdapter`, `ApplyReceipt`, `application_root`, `resource_path`, `build_doctor_report`, and `write_reproducible_zip` retain the same spelling at every consumer.
- CP-HDR-1 measurement expansion, generalized grading, rendering-engine integration, and competitive parity remain outside this packaging plan.
- A trusted signing certificate and legal approval remain explicit external release gates; all unsigned and engineering-audit results stay truthful.

## Execution Handoff

Plan implementation may begin only after explicit operator approval of this document and consent to create the isolated worktree from `10149aa8e96dc2991eae8db134b53512c5afe5b8`.

After approval, use **Subagent-Driven Development** with a fresh implementation agent and two-stage review per task. Inline execution is permitted only if the operator explicitly selects it; it still runs exclusively in `C:\dev\worktrees\calibrate-pro-1.1-pyside`.
