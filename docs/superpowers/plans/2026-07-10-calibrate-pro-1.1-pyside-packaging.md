# Calibrate Pro 1.1 PySide Packaging Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship Calibrate Pro 1.1.0 as a truthful, self-contained Windows x64 application whose per-user installer and portable ZIP include Build Color, Build UI 2, PySide6/Qt, NumPy, SciPy, and `dwm_lut` without requiring Python, pip, Git, administrator launch, or network access after download.

**Architecture:** Keep `calibrate_pro.main:main` as the developer-wheel entry point and share its supported desktop commands with a minimal `calibrate_pro.frozen_main:main` entry point whose command and module closure are positive-allowlisted. Select PySide6 deterministically before QtPy/Build UI imports and retain one audited PQ implementation behind compatibility delegates. Every display write crosses one injected, confirmation-bound Windows adapter; release assembly freezes an explicit `onedir` graph, signs the staged executables, regenerates inventories from those final bytes, creates the deterministic portable ZIP, wraps that same signed tree with Inno Setup 6.7.3, and only then writes signatures and hashes.

**Tech Stack:** Python 3.12 x64 release runtime; Python 3.10-3.13 developer support; PySide6 6.11.1; QtPy 2.4.3; Build UI 2.0.0; Build Color 1.0.2 or its independently qualified compatible release; NumPy; SciPy; PyInstaller 6.21.0; Inno Setup 6.7.3; PowerShell; pytest; Ruff; Mypy; uv 0.11.28; GitHub Actions Windows runners.

## Global Constraints

- This plan supersedes `docs/superpowers/plans/2026-07-09-calibrate-pro-packaging-polish.md`; that stale draft remains untouched and must never be executed.
- Product implementation is consent-gated. Do not create an implementation worktree or change product code until the operator explicitly approves this plan.
- After approval, every implementation task runs only on branch `feat/calibrate-pro-1.1-pyside` in `C:\dev\worktrees\calibrate-pro-1.1-pyside`, created from the exact plan tip stored in `C:\dev\worktrees\calibrate-pro-1.1-pyside-handoff.json` before the consent pause. That tip must be a descendant of `10149aa8e96dc2991eae8db134b53512c5afe5b8`, must contain this approved plan, and must still equal the normal checkout's HEAD when the worktree is created. Never execute implementation steps in `C:\dev\public\calibrate-pro` or on a detached HEAD.
- Target version is exactly `1.1.0`, sourced only from `calibrate_pro.__version__`.
- Build UI dependency is exactly `build-ui[pyside6]>=2,<3`; its 2.0 candidate or published wheel must expose the approved QtPy bridge and preserve the current public theme/widget API.
- Calibrate metadata also declares `PySide6>=6.11.1,<7`; release resolution pins PySide6, PySide6_Addons, PySide6_Essentials, and shiboken6 to `6.11.1` unless a repeated compatibility proof approves an update.
- Calibrate source and frozen dependency closure contain no PyQt5 or PyQt6 imports, modules, distributions, or Qt objects. QtPy's unselected adapter source is not itself a PyQt distribution; frozen TOC and installed distribution checks are authoritative.
- `QT_API=pyside6` is set before the first QtPy or Build UI import in source and by a PyInstaller runtime hook when frozen.
- `configure_qt_api()` fails closed if PyQt5, PyQt6, or a non-PySide QtPy API is already loaded; it never reports PySide6 merely because it rewrote an environment variable.
- `calibrate-pro.spec` is the only PyInstaller spec. The release is `onedir`, `upx=False`, and both frozen executables use `uac_admin=False`.
- Frozen binaries use `calibrate_pro.frozen_main:main`, expose only `doctor`, `gui`, and `hdr`, and reject every developer-only CLI command with exit status 2 and an install-the-wheel message. `packaging/frozen-features.json` and `packaging/frozen-modules.json` are positive allowlists; PyInstaller hidden imports may add only names present in those files.
- Build Color is collected through the explicit core modules `build_color.adaptation`, `build_color.difference`, `build_color.gamut`, and `build_color.spaces`. `build_color.gui` and recursive Build Color collection are forbidden.
- Sensorless values are estimates. A metric is measured only when a supported instrument produced its source reading. Missing readings render as `Not measured`; simulation and replay are explicit provenance values.
- The active workflow is Detect -> Method -> Preview -> Apply -> Verify -> Save/Report. Only a confirmed Apply may invoke a display actuator. DDC sliders, profile actions, HDR live update, DWM launch, tray profile actions, restore-default actions, and CalibrationGuard never call low-level writers directly; in 1.1 the guard is monitor-and-notify only.
- Automated tests do not write DDC/CI, DWM LUT, VCGT, USB, startup, ICC association, or display state.
- `calibrate-pro doctor --json` and `CalibrateProCLI.exe doctor --json` are read-only and return stable JSON.
- Runtime and build dependencies are hash-locked for Python 3.12 Windows x64. Release builds use published dependency artifacts; local wheels are allowed only for the pre-publication integration gate.
- Release wheel construction uses the locked setuptools and wheel versions with `python -m build --wheel --no-isolation`; the canonical release build performs no dependency resolution outside the hash lock.
- Portable ZIP members are lexicographically sorted with normalized timestamps. Unsigned duplicate builds must have identical ZIP hashes and canonical staged inventories.
- `SOURCE_DATE_EPOCH`, `PYTHONHASHSEED=0`, locale, timezone, clean build roots, and the complete Python/PyInstaller environment are fixed before wheel or frozen-byte generation. Signing is excluded from the unsigned identity comparison.
- Required public outputs are `CalibratePro-1.1.0-Setup.exe`, `CalibratePro-1.1.0-win64.zip`, `SHA256SUMS.txt`, `dependency-manifest.json`, `qt-module-inventory.json`, and `THIRD_PARTY_LICENSES/`.
- The installer and portable ZIP must each be at most 350 MiB (`367001600` bytes). Failure emits the dependency report and stops the build.
- Signing is optional, but status is derived from Authenticode verification for each EXE and installer, never from an environment flag.
- Qt/PySide libraries remain external and replaceable inside the onedir tree. The release carries LGPL text, Qt notices, corresponding-source provenance, source-offer text, and relinking instructions. These gates are release engineering controls, not legal certification.
- Every redistributed distribution, Python runtime/native library, PyInstaller bootloader, Build package, Qt component, and `dwm_lut` component is mapped by `packaging/components-win64.json` to a committed notice and source record. Unknown staged distributions or native binaries fail closed.
- A trusted public signature and final legal review are external release gates; an unsigned build must identify itself truthfully.

---

## Execution Consent and Isolation Gate

The normal checkout is the planning and review surface. Implementation begins only after the operator replies with explicit approval and the executor invokes `superpowers:using-git-worktrees`.

- [ ] **Gate 1: Verify the plan-bearing tip and persist a cross-turn handoff without changing the repository**

```powershell
$approvedAncestor = '10149aa8e96dc2991eae8db134b53512c5afe5b8'
$planPath = 'docs/superpowers/plans/2026-07-10-calibrate-pro-1.1-pyside-packaging.md'
$planTip = (git -C C:\dev\public\calibrate-pro rev-parse HEAD).Trim()
git -C C:\dev\public\calibrate-pro merge-base --is-ancestor $approvedAncestor $planTip
if ($LASTEXITCODE -ne 0) { throw "$planTip is not a descendant of the approved packaging specification" }
git -C C:\dev\public\calibrate-pro cat-file -e "${planTip}:$planPath"
if ($LASTEXITCODE -ne 0) { throw "$planTip does not contain the approved implementation plan" }
git -C C:\dev\public\calibrate-pro status --short --branch
$handoffPath = 'C:\dev\worktrees\calibrate-pro-1.1-pyside-handoff.json'
$handoff = [ordered]@{
    schema_version = 1
    plan_tip = $planTip
    approved_ancestor = $approvedAncestor
    plan_path = $planPath
    source_checkout = 'C:\dev\public\calibrate-pro'
    worktree_path = 'C:\dev\worktrees\calibrate-pro-1.1-pyside'
    branch = 'feat/calibrate-pro-1.1-pyside'
}
$handoff | ConvertTo-Json | Set-Content -LiteralPath $handoffPath -Encoding utf8
Get-Content -Raw -LiteralPath $handoffPath
```

Expected: the ancestry and plan-object checks succeed and the printed JSON contains the exact tip to approve. The only write is the out-of-repository handoff JSON; no repository file changes. A separately preserved stale untracked plan does not change the commit snapshot.

- [ ] **Gate 2: Stop and obtain explicit operator approval**

Report the complete handoff JSON, Build UI prerequisite, and release side effects. The operator's approval must quote or otherwise unambiguously identify `plan_tip`. Do not interpret an earlier product approval as consent to create this implementation worktree.

- [ ] **Gate 3: Create the isolated worktree after approval**

```powershell
$handoffPath = 'C:\dev\worktrees\calibrate-pro-1.1-pyside-handoff.json'
$handoff = Get-Content -Raw -LiteralPath $handoffPath | ConvertFrom-Json
$currentTip = (git -C $handoff.source_checkout rev-parse HEAD).Trim()
if ($currentTip -ne $handoff.plan_tip) { throw "Source HEAD changed after consent handoff: $currentTip" }
git -C $handoff.source_checkout merge-base --is-ancestor $handoff.approved_ancestor $handoff.plan_tip
if ($LASTEXITCODE -ne 0) { throw 'Persisted plan tip is not an approved descendant' }
git -C $handoff.source_checkout cat-file -e "$($handoff.plan_tip):$($handoff.plan_path)"
if ($LASTEXITCODE -ne 0) { throw 'Persisted plan tip does not contain this plan' }
if (Test-Path -LiteralPath $handoff.worktree_path) { throw 'Target worktree path already exists' }
git -C $handoff.source_checkout show-ref --verify --quiet "refs/heads/$($handoff.branch)"
if ($LASTEXITCODE -eq 0) { throw 'Implementation branch already exists; inspect it instead of resetting it' }
git -C $handoff.source_checkout worktree add -b $handoff.branch $handoff.worktree_path $handoff.plan_tip
$actualTip = (git -C $handoff.worktree_path rev-parse HEAD).Trim()
$actualBranch = (git -C $handoff.worktree_path symbolic-ref --short HEAD).Trim()
if ($actualTip -ne $handoff.plan_tip) { throw 'Worktree tip mismatch' }
if ($actualBranch -ne $handoff.branch) { throw "Worktree branch mismatch: $actualBranch" }
if (git -C $handoff.worktree_path status --porcelain) { throw 'New worktree is not clean' }
```

Expected: worktree HEAD is exactly the persisted approved tip, `symbolic-ref` is `feat/calibrate-pro-1.1-pyside`, the plan exists, and status is empty.

- [ ] **Gate 4: Pin every subsequent command to the isolated worktree**

```powershell
$handoff = Get-Content -Raw -LiteralPath 'C:\dev\worktrees\calibrate-pro-1.1-pyside-handoff.json' | ConvertFrom-Json
$expectedRoot = (Resolve-Path -LiteralPath $handoff.worktree_path).ProviderPath
$gitRootText = (git -C $handoff.worktree_path rev-parse --show-toplevel).Trim()
$actualRoot = (Resolve-Path -LiteralPath $gitRootText).ProviderPath
if (-not [string]::Equals($actualRoot, $expectedRoot, [StringComparison]::OrdinalIgnoreCase)) {
    throw "Refusing to implement outside $expectedRoot"
}
if ((git -C $actualRoot symbolic-ref --short HEAD).Trim() -ne $handoff.branch) { throw 'Wrong implementation branch' }
Set-Location -LiteralPath $actualRoot
```

Expected: command completes silently. Re-run this complete block at the start of every implementation turn; no shell variable or working-directory state is assumed to persist.

## File Responsibility Map

- `calibrate_pro/qt_runtime.py` - deterministic PySide6 selection before QtPy/Build UI import.
- `calibrate_pro/frozen_main.py` - minimal frozen-only dispatcher for the three approved binary commands.
- `calibrate_pro/commands/doctor.py`, `gui.py`, and `hdr.py` - shared lazy command implementations used by source and frozen dispatchers.
- `packaging/pyi_rth_qt_api.py` - frozen-process `QT_API=pyside6` runtime hook.
- `calibrate_pro/core/pq.py` - one audited float64 ST 2084 implementation.
- `calibrate_pro/verification/provenance.py` - measured, estimated, simulated, replayed, and absent metric contract.
- `calibrate_pro/workflow.py` - pure Detect/Method/Preview/Apply/Verify/Save state model.
- `calibrate_pro/recovery.py` - capture/apply/verify/restore transaction and truthful failure receipts.
- `calibrate_pro/actuation.py` - one-use confirmation digest and sole application-level write coordinator.
- `calibrate_pro/adapters/windows_display_state.py` - sole production importer of DDC, ICC, VCGT, DWM LUT, and profile writer APIs.
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
- `packaging/components-win64.json` - fail-closed distribution/native binary ownership and notice classification.
- `packaging/frozen-features.json` - exact supported frozen commands and explicit developer-only exclusions.
- `packaging/frozen-modules.json` - exact approved first-party modules and third-party distribution roots.
- `packaging/source-provenance.lock.json` - exact upstream source identifiers and verified hashes.
- `scripts/release_artifacts.py` - stage audit, deterministic ZIP, receipts, hashes, and signature probes.
- `scripts/build_windows.ps1` - only source-to-release orchestration path.
- `installer/CalibratePro.iss` - per-user Inno Setup wrapper over the staged onedir tree.
- `tests/test_qt_binding_contract.py` - source, metadata, Qt selection, signals, widgets, and window closure.
- `tests/test_pq_conformance.py` - shared ST 2084 gold vectors across every compatibility surface.
- `tests/test_hdr_provenance.py` - missing/simulated/replayed/measured HDR behavior.
- `tests/test_workflow.py` - transitions, capability gating, Apply transaction, and restoration.
- `tests/test_actuator_boundary.py` - production adapter injection, one-use confirmation, and repository-wide low-level writer isolation.
- `tests/test_truthfulness_contract.py` - structured evidence through sensorless, CLI, GUI, JSON, HTML, and PDF-facing payloads.
- `tests/test_diagnostics.py` - JSON shape, dependency/resource status, and mutation prohibition.
- `tests/test_packaging_contract.py` - spec, installer, lock, TOC, manifest, and output contract.
- `tests/test_release_artifacts.py` - deterministic archive and fail-closed staged-tree audits.
- `tests/test_frozen_module_allowlist.py` - minimal entrypoint, frozen command manifest, TOC positive allowlist, and developer-only rejection behavior.

---

### Task 1: Prove the Build UI 2 PySide Candidate Before Editing Calibrate

**Files:**
- Test only: candidate `build_ui-2.0.0-py3-none-any.whl`
- Inspect: `C:\dev\public\build-ui\docs\superpowers\specs\2026-07-10-build-ui-2-qt-bridge-design.md`

**Interfaces:**
- Consumes: one Build UI 2.0.0 wheel supplied through `$env:BUILD_UI_2_WHEEL`.
- Produces: a clean-process receipt proving `qtpy.API_NAME == "PySide6"`, the approved public names import, representative widgets construct, and no PyQt distribution is installed.

- [ ] **Step 1: Validate the candidate path and persist proof state**

```powershell
if (-not $env:BUILD_UI_2_WHEEL) { throw 'Set BUILD_UI_2_WHEEL to the reviewed Build UI 2.0.0 wheel' }
$wheel = (Resolve-Path -LiteralPath $env:BUILD_UI_2_WHEEL).Path
if ([IO.Path]::GetFileName($wheel) -notlike 'build_ui-2.0.0-*.whl') { throw "Unexpected Build UI wheel: $wheel" }
$proof = Join-Path $env:TEMP ('calibrate-build-ui-proof-' + [guid]::NewGuid().ToString('N'))
$statePath = Join-Path $env:TEMP 'calibrate-build-ui-proof-state.json'
[ordered]@{
    schema_version = 1
    wheel = $wheel
    wheel_sha256 = (Get-FileHash -LiteralPath $wheel -Algorithm SHA256).Hash.ToLowerInvariant()
    proof = $proof
} | ConvertTo-Json | Set-Content -LiteralPath $statePath -Encoding utf8
Get-Content -Raw -LiteralPath $statePath
```

Expected: a reviewed Build UI 2.0.0 wheel resolves. Stop if it does not.

- [ ] **Step 2: Install the candidate with exactly the PySide binding**

```powershell
$state = Get-Content -Raw -LiteralPath (Join-Path $env:TEMP 'calibrate-build-ui-proof-state.json') | ConvertFrom-Json
py -3.12 -m venv $state.proof
$python = Join-Path $state.proof 'Scripts\python.exe'
& $python -m pip install --upgrade pip
& $python -m pip install "$($state.wheel)[pyside6]"
& $python -m pip check
```

Expected: installing only the candidate's `pyside6` extra resolves QtPy and PySide6 transitively, and `pip check` succeeds without PyQt. Do not preinstall either runtime dependency because that would mask broken wheel metadata.

- [ ] **Step 3: Parse wheel metadata and run the binding-isolated behavioral probe**

```powershell
$state = Get-Content -Raw -LiteralPath (Join-Path $env:TEMP 'calibrate-build-ui-proof-state.json') | ConvertFrom-Json
$python = Join-Path $state.proof 'Scripts\python.exe'
& $python -m pip install 'packaging>=24,<27'
$env:QT_API = 'pyside6'
$env:QT_QPA_PLATFORM = 'offscreen'
@'
import email
import sys
import zipfile
from importlib import metadata
from pathlib import Path

from packaging.requirements import Requirement
from qtpy import API_NAME
from qtpy.QtWidgets import QApplication
from build_ui.theme import C, STYLE, create_stylesheet
from build_ui.widgets import Card, Heading, NavButton, Sidebar, Stat, StatusDot, ToastNotification

wheel = Path(sys.argv[1])
with zipfile.ZipFile(wheel) as archive:
    metadata_name = next(name for name in archive.namelist() if name.endswith('.dist-info/METADATA'))
    message = email.message_from_bytes(archive.read(metadata_name))
assert message['Name'] == 'build-ui'
assert message['Version'] == '2.0.0'
assert 'pyside6' in {value.casefold() for value in message.get_all('Provides-Extra', [])}
requirements = [Requirement(value) for value in message.get_all('Requires-Dist', [])]
assert any(req.name.casefold() == 'qtpy' for req in requirements)
assert any(req.name.casefold() == 'pyside6' and req.marker and 'pyside6' in str(req.marker).casefold() for req in requirements)
assert not any(req.name.casefold() == 'pyqt5' for req in requirements)
pyqt6_requirements = [req for req in requirements if req.name.casefold() == 'pyqt6']
assert pyqt6_requirements
for requirement in pyqt6_requirements:
    assert requirement.marker is not None
    assert requirement.marker.evaluate({'extra': 'pyqt6'}) is True
    assert requirement.marker.evaluate({'extra': 'pyside6'}) is False

app = QApplication.instance() or QApplication([])
card = Card()
sidebar = Sidebar(['One', 'Two'])
seen = []
sidebar.page_changed.connect(seen.append)
sidebar.page_changed.emit(1)
assert API_NAME == 'PySide6'
assert seen == [1]
assert card.graphicsEffect() is not None
assert C and STYLE and create_stylesheet
for name in ('PyQt5', 'PyQt6'):
    try:
        metadata.version(name)
    except metadata.PackageNotFoundError:
        continue
    raise AssertionError(f'{name} must not be installed')
print('build-ui-2-pyside-proof=pass')
'@ | & $python - $state.wheel
```

Expected: `build-ui-2-pyside-proof=pass`.

- [ ] **Step 4: Preserve the proof output in the task log, not the repository**

Record the persisted wheel path and SHA-256, Python version, parsed `Provides-Extra`/`Requires-Dist`, QtPy version, PySide6 version, and probe output in the agent task handoff. Remove only the exact `$state.proof` directory after verifying it is below `[IO.Path]::GetTempPath()` and its leaf begins `calibrate-build-ui-proof-`; then remove the state JSON. Do not commit the candidate wheel or temporary environment.

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

import ast
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
BANNED_BINDINGS = ("PyQt5", "PyQt6")
BANNED_IDENTIFIERS = ("pyqtSignal", "pyqtSlot", "pyqtProperty")


def test_calibrate_source_contains_no_pyqt_imports_or_identifiers() -> None:
    offenders: list[str] = []
    for path in sorted((ROOT / "calibrate_pro").rglob("*.py")):
        text = path.read_text(encoding="utf-8")
        tree = ast.parse(text, filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module or ""]
            else:
                names = []
            if any(name == binding or name.startswith(binding + ".") for name in names for binding in BANNED_BINDINGS):
                offenders.append(f"{path.relative_to(ROOT)}:{node.lineno}:import")
            if isinstance(node, ast.Name) and node.id in BANNED_IDENTIFIERS:
                offenders.append(f"{path.relative_to(ROOT)}:{node.lineno}:{node.id}")
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


def test_qt_api_rejects_an_already_loaded_wrong_binding() -> None:
    code = """
import sys
import types
fake_qtpy = types.ModuleType('qtpy')
fake_qtpy.API_NAME = 'PyQt6'
sys.modules['qtpy'] = fake_qtpy
sys.modules['PyQt6'] = types.ModuleType('PyQt6')
from calibrate_pro.qt_runtime import configure_qt_api
try:
    configure_qt_api()
except RuntimeError as exc:
    assert 'already loaded' in str(exc)
else:
    raise AssertionError('mixed Qt binding was accepted')
"""
    result = subprocess.run([sys.executable, "-c", code], cwd=ROOT, text=True, capture_output=True, check=False)
    assert result.returncode == 0, result.stderr


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
import sys

QT_API = "pyside6"


def configure_qt_api() -> str:
    """Select PySide6 before QtPy or Build UI imports."""
    qtpy = sys.modules.get("qtpy")
    loaded_api = getattr(qtpy, "API_NAME", None) if qtpy is not None else None
    wrong_modules = sorted(
        name for name in sys.modules if name in {"PyQt5", "PyQt6"} or name.startswith(("PyQt5.", "PyQt6."))
    )
    if wrong_modules or (loaded_api is not None and loaded_api != "PySide6"):
        detail = loaded_api or wrong_modules[0]
        raise RuntimeError(f"A non-PySide Qt binding is already loaded: {detail}")
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
from calibrate_pro import __version__ as APP_VERSION
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
@'
import email
import glob
import zipfile

from packaging.requirements import Requirement

wheel = glob.glob("dist/calibrate_pro-1.1.0-*.whl")[0]
with zipfile.ZipFile(wheel) as archive:
    name = next(item for item in archive.namelist() if item.endswith(".dist-info/METADATA"))
    message = email.message_from_bytes(archive.read(name))
requirements = [Requirement(value) for value in message.get_all("Requires-Dist", [])]
build_ui = next(req for req in requirements if req.name.casefold() == "build-ui" and "pyside6" in req.extras)
assert message["Version"] == "1.1.0"
assert build_ui.specifier.contains("2.0.0")
assert not build_ui.specifier.contains("3.0.0")
print(wheel)
'@ | python -
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
- Modify: `calibrate_pro/hdr/workflow.py:78-93,120-139,312-360`
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
    assert result.peak_luminance.value == pytest.approx(1000.0)
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


@pytest.mark.parametrize("value", [None, float("nan"), float("inf"), float("-inf")])
def test_measured_metric_requires_a_finite_reading(value: float | None) -> None:
    from calibrate_pro.verification.provenance import MetricValue

    with pytest.raises(ValueError, match="finite"):
        MetricValue(value, "nits", EvidenceKind.MEASURED, "instrument receipt")


def test_estimate_requires_characterization_source() -> None:
    from calibrate_pro.verification.provenance import MetricValue

    with pytest.raises(ValueError, match="source"):
        MetricValue(1.2, "dE2000", EvidenceKind.ESTIMATED)
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

import math
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
        if self.evidence is EvidenceKind.NOT_MEASURED:
            if self.value is not None:
                raise ValueError("not-measured metrics cannot carry a value")
            return
        if self.value is None or not math.isfinite(self.value):
            raise ValueError(f"{self.evidence.value} metrics require a finite value")
        if not self.source or not self.source.strip():
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

For HDR10 patch generation, bound the signal ramp to the selected target peak rather than full-scale 10,000 nits:

```python
max_signal = float(pq_oetf(np.array([self.target.peak_luminance], dtype=np.float64))[0])
signals = np.linspace(0.0, max_signal, steps)
luminances = pq_eotf(signals)
```

If readings are absent and evidence is `NOT_MEASURED`, create `MetricValue(None, "percent", EvidenceKind.NOT_MEASURED)` and `MetricValue(None, "nits", EvidenceKind.NOT_MEASURED)` values. If evidence is `SIMULATED`, use this target-bounded expected luminance and label the derived error/peak with that source. If readings exist, require `MEASURED` or `REPLAYED` plus a source. Gamut always remains `NOT_MEASURED` in this 1.1 lane because luminance-only arrays cannot prove color volume.

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

### Task 6: Add Capability-Gated Workflow, Confirmation, and the Candidate Production Actuator Adapter

**Files:**
- Create: `calibrate_pro/workflow.py`
- Create: `calibrate_pro/recovery.py`
- Create: `calibrate_pro/actuation.py`
- Create: `calibrate_pro/adapters/__init__.py`
- Create: `calibrate_pro/adapters/windows_display_state.py`
- Create: `tests/test_workflow.py`
- Create: `tests/test_windows_display_state_adapter.py`
- Create: `tests/test_ddc_ci_safety.py`
- Create: `tests/test_profile_installer_safety.py`
- Modify: `calibrate_pro/hardware/ddc_ci.py`
- Modify: `calibrate_pro/profiles/profile_installer.py`
- Modify: `SECURITY.md`
- Modify: `docs/superpowers/specs/2026-07-09-calibrate-pro-packaging-polish-design.md`

**Interfaces:**
- Consumes: existing Windows DDC/CI, profile, gamma-ramp, and DWM LUT readers/writers only through `DefaultWindowsDisplayPorts`.
- Produces: `WorkflowStage`, `CalibrationMethod`, `CapabilityState`, `ApplyPlan`, `DisplayStateSnapshot`, `IccLifecycleSnapshot`, `IccActivationEffect`, `ApplyReceipt`, `DisplayStateAdapter`, `ActuationCoordinator`, and `WindowsDisplayStateAdapter`.

#### Task 6 safety amendment (supersedes conflicting details below)

Repository inspection showed that the existing Windows readers cannot always distinguish an absent value from a failed read, and that `DwmLutController.get_active_luts()` reports only controller-process memory while `unload_lut()` can remove the managed source file. A path-only snapshot therefore cannot support the truthful restoration promised by this task. Implement the following stricter contract:

- `CapturedState[T]` distinguishes `CAPTURED` (where `value=None` is a legitimate captured value) from `NOT_CAPTURED` (which requires a non-empty failure detail). Unrequested domains are represented by an absent `CapturedState`, not by a fabricated captured value.
- `DisplayStateSnapshot` uses typed captured state for ICC, gamma, and DWM. A requested `NOT_CAPTURED` domain aborts capture before the first write. Restoration touches only domains that were requested and captured.
- `DwmLutSnapshot` preserves explicit `DwmLutKind` (`SDR` or `HDR`), original path, exact payload bytes, and a verified SHA-256 digest. DWM verification compares kind and payload digest, not path spelling.
- `ApplyPlan` carries explicit DWM kind and SHA-256 plus SHA-256 values for every ICC/VCGT input. The confirmation digest therefore binds the exact external asset bytes. ICC and DWM inputs are capped at 64 MiB and VCGT at 16 MiB before parser allocation; the adapter verifies and parses every requested asset before its first write.
- `ApplyPlan.ddc_changes` is an exact tuple with unique uppercase codes from the closed calibration allowlist (`BRIGHTNESS`, `CONTRAST`, RGB gains, and RGB black levels), exact non-boolean integer targets, and range `[0,65535]`. The selected monitor's exact current/maximum `DdcReading` is captured with unscoped WMI fallback disabled; a target above the reported maximum aborts before writing.
- `CapabilityState` reports DWM write availability separately from authoritative DWM state-capture availability. A DWM apply or clear requires both. The default adapter reports capture failure until an authoritative Windows reader exists; process-local `get_active_luts()` is not accepted as evidence of prior display state.
- The production ICC reader uses a sized system-wide WCS default-profile query and never treats a temporary DC profile as persistent evidence. Gamma readers convert ambiguous `None` results into `NOT_CAPTURED`. Injected test ports may truthfully return `CAPTURED(None)` to prove absence and restoration behavior.
- ICC targets use the exact reserved filename `calibrate-pro-{sha256}.icc`, are published exclusively, and never overwrite a user/source basename. Reuse and newly created output are accepted only through one no-write/no-delete-share native handle that proves the exact final path is a regular disk file, is not a reparse point, has exactly one link, and contains the exact bounded content-addressed bytes. These point-in-time checks prove the object used and reject aliases observed at each validation point; they do not prove creator/ACL provenance or post-lease filesystem immutability. Later drift is rejected before reuse. A process-plus-named mutex keyed by the content digest serializes cooperating Calibrate Pro profile lifecycles across displays. System-wide WCS enumeration captures and revalidates target installation and per-display association membership; sized WCS get/set calls capture, select, and read back the persistent default. Its exact name, bytes, and digest are recaptured immediately before activation, and already-observed drift aborts before target selection. The production port holds a native read lease that denies write/delete sharing throughout activation. Stepwise effects are authoritatively reconciled after ambiguous failures; compensation withholds writes when the authoritative pre-write comparison shows a third state, restores a recognized transaction target to the prior default, and reads completed writes and target association back. Because WCS offers no atomic compare-and-swap, unrelated external post-comparison races remain possible. Transaction compensation never unregisters or deletes the globally reusable cache entry. Legacy install/uninstall holds one delete-capable verified handle across exclusive creation, native registration/unregistration, revalidation, exact-object failure cleanup, and delete disposition; it also rejects case, trailing-dot/space, resolved-path, active 8.3, symlink, and hard-link aliases of the cache namespace. Any future collector requires a separately designed authoritative all-display/all-scope scan.
- DDC resolution re-enumerates immediately before every read and write, requires exactly one exact display/path match, and binds that captured interface path to the selected enumerated physical handle. Handles enter the cleanup registry before optional capability parsing. Each cleanup pass attempts every eligible recorded destroy at most once while later handles are still attempted after a failure. False or pre-call-interrupted destroys remain registered for explicit retry; uncertain native-call outcomes remain registered and poisoned against a possible double destroy. Failures are surfaced, and only successful native destroys are claimed closed. Every used DXVA2 enumeration, capability, VCP, and destruction entrypoint has an explicit pointer-sized ctypes signature. Zero/multiple matches, probe failure, ABI ambiguity, or topology-identity drift fail closed. `DisplayStateSnapshot.ddc_values` retains the complete captured `DdcReading` current/maximum pair; apply and compensation revalidate identity and maximum before writing. DDC has no atomic external compare-and-write primitive, so the comparison protects against already-observed drift rather than unrelated post-comparison writers.
- One non-reentrant per-display process mutex and a lazy `Global\\` Windows named mutex serialize cooperating Calibrate Pro capture through verification/compensation; ICC plans additionally hold the digest mutex before the display mutex. `WAIT_ABANDONED` persistently poisons that process-wide key. Acquisition, release, and multi-lease cleanup cover `BaseException`, attempt every recorded handle, and poison uncertain ownership. Every successful compensation is authoritatively read back; a silent no-op writer is a restore failure. Applying one DWM kind preserves the other captured kind unless the plan explicitly clears all LUTs.
- `ActuationCoordinator` requires a capability provider, validates an isolated private probe at preview and immediately before capture, rechecks both the probe and submitted digests after callbacks, and gives the writer a separate private plan copy. It holds one expiring confirmation and consumes every recognized token on any apply attempt. A new preview supersedes the old token. A coordinator-wide apply lock serializes the full capability, authorization, capture, and transaction handoff so concurrent confirmed applies cannot invert the one-slot closure. Every `WindowsDisplayStateAdapter`, including one over a proxy, decorator, or custom ports implementation, always requires the separate opaque one-use authorization created by the coordinator's private closure. The adapter exposes no bind/mint hook, defaults to the production mutex, and direct recovery/helper or adapter calls fail before hardware access. Arbitrary same-process Python reflection remains inside the trusted process boundary; this is not process isolation.
- Restore accepts only the exact object-identical snapshot still owned by the adapter's active transaction. The adapter also retains private deep copies and digests of the confirmed plan and snapshot, recomputes ICC/DWM hashes from actual payload bytes, revalidates them across phases, and uses only sealed evidence for writers. Publicly constructed, copied, substituted, same-object-mutated, completed, or standalone snapshots are rejected before any writer call, and restore independently revalidates the closed DDC calibration allowlist.
- `ApplyPlan` validates exact enum/non-empty-string/tuple/boolean types, every `CapabilityState` field is an exact boolean, and every injected clock sample is a finite real number whose TTL sum remains finite.
- Recovery is explicitly `IN_PROCESS_BEST_EFFORT`, not crash-safe or power-loss-safe. Durable rollback requires a separately designed write-ahead journal/startup lifecycle and is not claimed by Task 6.
- Every underlying writer result of `False` or `(False, message)` becomes an exception. Typed GDI32 DC/profile/gamma calls fail closed when `DeleteDC` is uncertain, shared `EnumDisplayDevicesW` users retain a layout-compatible `c_void_p` ABI across import orders, and Win32 `BOOL` contracts use the four-byte `wintypes.BOOL` ABI. Empty exception messages receive a type-name fallback. Snapshot sealing and active-state publication remain inside capture cleanup; apply/verify publication either completes or marks the transaction compensatable; commit clears finished state even if cancellation arrives after mutex release. While ownership remains recorded, `KeyboardInterrupt` and `SystemExit` are deferred while every applicable compensation domain and recorded release is attempted, then the original cancellation is re-raised with recovery notes. After commit releases ownership, state is cleared without unlocked compensation. Cleanup failures remain visible and may poison the transaction; successful cleanup is not guaranteed.
- Constructors perform no dynamic hardware imports, controller construction, enumeration, reads, directory creation, or writes. All tests use injected in-memory ports and must never exercise physical display APIs.

- [ ] **Step 1: Write failing capability, confirmation, and recovery tests**

Create `tests/test_workflow.py` with a `make_plan(**changes)` helper and these assertions:

```python
def test_preview_rejects_each_missing_write_capability() -> None:
    dwm_change = {
        "dwm_lut_path": "display.cube",
        "dwm_lut_kind": DwmLutKind.SDR,
        "dwm_lut_sha256": "a" * 64,
    }
    cases = (
        (CapabilityState(True, False, True, True, True, True), {"ddc_changes": (("BRIGHTNESS", 42),)}, "DDC/CI"),
        (CapabilityState(True, True, False, True, True, True), dwm_change, "DWM LUT"),
        (CapabilityState(True, True, True, False, True, True), dwm_change, "authoritative"),
        (CapabilityState(True, True, True, True, False, True), {"icc_profile_path": "display.icc", "icc_profile_sha256": "a" * 64}, "profile association"),
        (CapabilityState(True, True, True, True, True, False), {"vcgt_path": "display.cal", "vcgt_sha256": "a" * 64}, "gamma ramp"),
    )
    for capabilities, changes, message in cases:
        controller = ready_controller(capabilities)
        with pytest.raises(ValueError, match=message):
            controller.set_preview(make_plan(**changes))


def test_confirmation_is_bound_to_one_plan_and_consumed_once() -> None:
    adapter = FakeAdapter()
    coordinator = ActuationCoordinator(adapter)
    plan = make_plan(ddc_changes=(("BRIGHTNESS", 42),))
    token = coordinator.preview(plan)
    with pytest.raises(PermissionError, match="confirmation"):
        coordinator.apply(plan, token, confirmed=False)
    token = coordinator.preview(plan)
    receipt = coordinator.apply(plan, token, confirmed=True)
    assert receipt.success is True
    with pytest.raises(PermissionError, match="consumed"):
        coordinator.apply(plan, token, confirmed=True)


def test_capture_failure_returns_a_non_apply_receipt() -> None:
    receipt = _apply_confirmed_with_best_effort_recovery(FakeAdapter(capture_error="capture failed"), make_plan())
    assert receipt == ApplyReceipt(False, False, False, False, False, False, "capture failed", None)


def test_restore_failure_preserves_both_errors() -> None:
    adapter = FakeAdapter(apply_error="apply failed", restore_error="restore failed")
    receipt = _apply_confirmed_with_best_effort_recovery(adapter, make_plan())
    assert receipt.success is False
    assert receipt.restore_attempted is True
    assert receipt.restored is False
    assert receipt.error == "apply failed"
    assert receipt.restore_error == "restore failed"
```

The test's `FakeAdapter` implements `capture(plan)`, `apply(plan)`, `verify(plan)`, and `restore(snapshot)` and records call order. Add a success assertion for `capture -> apply -> verify`, and verification-failure assertion for `capture -> apply -> verify -> restore`.

Create `tests/test_windows_display_state_adapter.py` with an injected `FakeWindowsDisplayPorts` whose `icc_profile_path` starts as `None` and whose `set_icc_profile()` records calls:

```python
def test_restore_disassociates_profile_when_capture_had_no_association(tmp_path: Path) -> None:
    ports = FakeWindowsDisplayPorts(icc_profile_path=None)
    adapter = WindowsDisplayStateAdapter(ports)
    profile = tmp_path / "new.icc"
    profile.write_bytes(b"icc")
    plan = make_plan(icc_profile_path=str(profile))
    snapshot = adapter.capture(plan)
    adapter.apply(plan)
    assert ports.icc_profile_path == str(profile)
    adapter.restore(snapshot)
    assert ports.icc_profile_path is None
    assert ports.set_icc_calls == [("display-1", str(profile)), ("display-1", None)]
```

The fake implements every `WindowsDisplayPorts` method in memory; no test imports Windows hardware modules.

- [ ] **Step 2: Verify RED**

```powershell
python -m pytest tests/test_workflow.py -q
```

Expected: the workflow, recovery, and actuation modules are absent.

- [ ] **Step 3: Add the capability-complete pure workflow**

Create `calibrate_pro/workflow.py` with the existing six `WorkflowStage` values and these exact data contracts:

```python
@dataclass(frozen=True)
class CapabilityState:
    sensor_available: bool
    ddc_available: bool
    dwm_lut_available: bool
    dwm_state_capture_available: bool
    profile_write_available: bool
    vcgt_available: bool

    def disabled_reason(self, method: CalibrationMethod) -> str | None:
        if method is CalibrationMethod.MEASURED and not self.sensor_available:
            return "Measured calibration requires a supported colorimeter."
        return None

    def validate(self, plan: ApplyPlan) -> None:
        checks = (
            (bool(plan.ddc_changes), self.ddc_available, "DDC/CI writes are unavailable for this display."),
            (
                plan.dwm_lut_path is not None or plan.clear_existing_lut,
                self.dwm_lut_available and self.dwm_state_capture_available,
                "DWM LUT application requires write and authoritative state-capture support.",
            ),
            (plan.icc_profile_path is not None, self.profile_write_available, "ICC profile association is unavailable."),
            (plan.vcgt_path is not None, self.vcgt_available, "Display gamma ramp application is unavailable."),
        )
        for requested, available, reason in checks:
            if requested and not available:
                raise ValueError(reason)


@dataclass(frozen=True)
class ApplyPlan:
    display_id: str
    method: CalibrationMethod
    target_whitepoint: str
    target_gamma: str
    target_gamut: str
    ddc_changes: tuple[tuple[str, int], ...] = ()
    icc_profile_path: str | None = None
    icc_profile_sha256: str | None = None
    vcgt_path: str | None = None
    vcgt_sha256: str | None = None
    dwm_lut_path: str | None = None
    dwm_lut_kind: DwmLutKind | None = None
    dwm_lut_sha256: str | None = None
    clear_existing_lut: bool = False
    output_files: tuple[str, ...] = ()
```

`WorkflowController.set_preview()` verifies stage, method identity, non-empty `display_id`, calls `self.capabilities.validate(plan)`, and only then stores the preview. `confirm_apply()` remains a state transition; it does not itself write hardware.

- [ ] **Step 4: Implement truthful capture/apply/verify/restore receipts**

Create `calibrate_pro/recovery.py` with:

```python
@dataclass(frozen=True)
class DisplayStateSnapshot:
    display_id: str
    ddc_target: DdcTargetIdentity | None
    ddc_values: tuple[tuple[str, DdcReading], ...]
    icc_profile: CapturedState[IccProfileSnapshot] | None
    gamma_ramp: CapturedState[tuple[tuple[int, ...], tuple[int, ...], tuple[int, ...]]] | None
    dwm_luts: CapturedState[tuple[DwmLutSnapshot, ...]] | None


@dataclass(frozen=True)
class ApplyReceipt:
    success: bool
    captured: bool
    applied: bool
    verified: bool
    restore_attempted: bool
    restored: bool
    error: str | None
    restore_error: str | None
```

`DisplayStateAdapter` is a `Protocol` whose signatures are `capture(plan: ApplyPlan, *, authorization: object | None = None) -> DisplayStateSnapshot`, `apply(plan: ApplyPlan) -> None`, `verify(plan: ApplyPlan) -> bool`, `commit(plan: ApplyPlan) -> None`, and `restore(snapshot: DisplayStateSnapshot) -> None`. Generic injected test adapters may ignore the authorization keyword; `WindowsDisplayStateAdapter` requires and consumes the opaque one-use coordinator authorization. The private `_apply_confirmed_with_best_effort_recovery()` runner catches capture failure before any write; on apply exception, non-boolean/false verification, or verification exception it attempts in-process compensation while the lease remains held, preserves both errors, and sets every receipt flag from operations actually completed. Successful verification does not release ownership; `commit()` is the sole release point. A commit/release failure returns `verified=true`, performs no now-unsafe compensation, and poisons the adapter transaction. Every receipt carries `recovery_guarantee=IN_PROCESS_BEST_EFFORT`; there is no public raw-plan recovery alias.

- [ ] **Step 5: Bind explicit confirmation to a canonical plan digest**

Create `calibrate_pro/actuation.py`. `canonical_plan_sha256(plan)` JSON-serializes `dataclasses.asdict(plan)` with `sort_keys=True`, compact separators, and UTF-8, then returns SHA-256. `ActuationCoordinator` requires a `CapabilityProvider`, an injectable monotonic clock, and a finite positive confirmation TTL. `preview(plan) -> str` invalidates any prior preview, validates current capabilities, and stores one token/digest/display/expiry tuple from `secrets.token_urlsafe(32)`. `apply(plan, token, *, confirmed)` leaves the current preview intact only for an unknown token; every recognized token is consumed before decline, expiry, digest comparison, refreshed capability validation, or best-effort application.

- [ ] **Step 6: Add the injected Windows production adapter**

Create `calibrate_pro/adapters/windows_display_state.py` with a `WindowsDisplayPorts` protocol exposing only these read/write pairs:

```python
resolve_ddc_target(display_id: str) -> DdcTargetIdentity
read_ddc(target: DdcTargetIdentity, code: str) -> DdcReading
write_ddc(target: DdcTargetIdentity, code: str, value: int, *, expected_maximum: int) -> None
capture_icc_profile(display_id: str) -> CapturedState[IccProfileSnapshot]
is_icc_profile_installed(profile_name: str) -> bool
is_icc_profile_associated(display_id: str, profile_name: str) -> bool
materialize_icc_profile(profile: IccProfileSnapshot) -> IccInstallEffect
activate_icc_profile(display_id: str, profile: IccProfileSnapshot, *, register: bool, associate: bool) -> IccActivationEffect
deactivate_icc_profile(display_id: str, profile_name: str) -> None
capture_gamma_ramp(display_id: str) -> CapturedState[GammaRamp]
set_gamma_ramp(display_id: str, ramp: GammaRamp | None) -> None
capture_dwm_luts(display_id: str) -> CapturedState[tuple[DwmLutSnapshot, ...]]
set_dwm_luts(display_id: str, luts: tuple[DwmLutSnapshot, ...]) -> None
```

`DefaultWindowsDisplayPorts` lazily maps each DDC operation to a fresh, finally-cleaned `DDCCIController` monitor session and `get_vcp/set_vcp` with WMI fallback disabled; stable `DdcTargetIdentity.monitor_device_path` comes from the exact active PnP/interface path bound to the enumerated physical handle, never an `HMONITOR` or friendly description alone. Gamma methods map to `panels.detection.get_gamma_ramp/set_gamma_ramp/reset_gamma_ramp`, and DWM writes map to `DwmLutController.load_lut_file/unload_lut/start_dwm_lut_gui`. ICC capture repeatedly samples the sized system-wide WCS default through `profile_installer.get_default_profile_for_display` around the exact-byte lease. WCS enumeration proves installation and association membership. A non-`None` target is staged into the durable cache, registered only when absent, associated only when absent, made default, and authoritatively read back; `IccActivationEffect` preserves every completed step even when a later step fails. A `None` prior target requires a provable captured absence; compensation disassociates only a newly added target, and apply fails before selection when a preexisting association makes absence non-restorable. The default DWM reader always returns `NOT_CAPTURED` without constructing the controller because `get_active_luts()` is process-local and cannot prove the prior OS state.

`WindowsDisplayStateAdapter.capture(plan, authorization=...)` first consumes the one-use plan-bound authorization, acquires all ordered leases, verifies/privately stages/parses every external asset, then reads only the domains the plan changes. `apply()` requires that exact successful capture and uses the staged evidence even if a source path later changes. `verify()` reads every changed field back; `restore()` accepts only the active object-identical snapshot, restores only captured domains, reads every compensation back, and raises one combined `RuntimeError` listing every failed restoration. No constructor probes hardware or writes state.

- [ ] **Step 7: Run focused and full tests**

```powershell
python -m pytest tests/test_workflow.py tests/test_windows_display_state_adapter.py -q
python -m pytest -q
```

Expected: capability, confirmation, capture failure, apply failure, verification failure, and restoration failure tests pass without physical hardware access.

- [ ] **Step 8: Commit the sole actuator boundary**

```powershell
git add calibrate_pro/workflow.py calibrate_pro/recovery.py calibrate_pro/actuation.py calibrate_pro/adapters calibrate_pro/hardware/ddc_ci.py calibrate_pro/profiles/profile_installer.py tests/test_workflow.py tests/test_windows_display_state_adapter.py tests/test_ddc_ci_safety.py tests/test_profile_installer_safety.py SECURITY.md docs/superpowers/specs/2026-07-09-calibrate-pro-packaging-polish-design.md docs/superpowers/plans/2026-07-10-calibrate-pro-1.1-pyside-packaging.md
git commit -m "feat: enforce one transactional display actuator"
```

---

### Task 7: Add Read-Only Runtime Diagnostics and Prove the Real Entrypoint Is Non-Mutating

**Files:**
- Create: `calibrate_pro/runtime.py`
- Create: `calibrate_pro/diagnostics.py`
- Create: `calibrate_pro/commands/__init__.py`
- Create: `calibrate_pro/commands/doctor.py`
- Create: `tests/test_diagnostics.py`
- Modify: `calibrate_pro/main.py`
- Modify: `calibrate_pro/lut_system/dwm_lut.py:632-663`

**Interfaces:**
- Produces: `application_root()`, `resource_path()`, `build_doctor_report()`, `doctor_exit_code()`, and shared command `calibrate_pro.commands.doctor.run(args) -> int`.
- Reports software support separately from device presence; it never enumerates a display, opens HID/USB, loads a profile, writes startup state, or constructs a hardware controller.

- [ ] **Step 1: Write failing report and real-entrypoint tests**

Create `tests/test_diagnostics.py`. In `tmp_path/dwm_lut`, write `DwmLutGUI.exe`, `dwm_lut.dll`, `WindowsDisplayAPI.dll`, `LICENSE`, and `LICENSE-THIRD-PARTY`. In `tmp_path/THIRD_PARTY_LICENSES`, write every notice path referenced by a minimal test `components-win64.json` plus `LGPL-3.0-only.txt`, `QT_SOURCE_OFFER.txt`, `LGPL_RELINKING.md`, and `source-provenance.json`. Assert version, `qt.api_name == "PySide6"`, PQ vectors, resources, and this exact capability schema:

```python
for name in ("display_enumeration", "ddc_ci", "icc_profile", "gamma_ramp", "colorimeter"):
    capability = report["capabilities"][name]
    assert isinstance(capability["software_supported"], bool)
    assert capability["device_presence"] == "not_probed"
    assert capability["probe"] in {"platform", "library_symbol", "module_spec"}
```

Add a subprocess test for the real source entrypoint:

```python
def test_real_doctor_entrypoint_cannot_import_mutation_layers(tmp_path: Path) -> None:
    code = r'''
import importlib.abc
import json
import sys

BLOCKED = (
    "calibrate_pro.hardware",
    "calibrate_pro.services",
    "calibrate_pro.startup",
    "calibrate_pro.adapters.windows_display_state",
)
class Blocker(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path, target=None):
        if any(fullname == item or fullname.startswith(item + ".") for item in BLOCKED):
            raise AssertionError("doctor attempted mutation import: " + fullname)
        return None
sys.meta_path.insert(0, Blocker())
from calibrate_pro.main import main
raise SystemExit(main(["doctor", "--json"]))
'''
    result = subprocess.run([sys.executable, "-c", code], cwd=ROOT, text=True, capture_output=True, check=False)
    assert result.returncode in {0, 1}, result.stderr
    assert json.loads(result.stdout)["schema_version"] == 1
```

Retain the `_MEIPASS` resource test. Assert that importing and invoking doctor adds none of the blocked module prefixes to `sys.modules`.

- [ ] **Step 2: Verify RED**

```powershell
python -m pytest tests/test_diagnostics.py -q
```

Expected: runtime/diagnostic modules and the doctor parser are absent.

- [ ] **Step 3: Add source/frozen resource resolution**

Create `calibrate_pro/runtime.py`:

```python
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

Make `resource_path("dwm_lut")` the first `DwmLutController._find_dwm_lut()` candidate without constructing that controller from diagnostics.

- [ ] **Step 4: Implement stable read-only capability reporting**

Create `calibrate_pro/diagnostics.py` with exact dependency tuples for Build Color, Build UI, QtPy, PySide6/Addons/Essentials, shiboken6, NumPy, and SciPy; literal checks for the five `dwm_lut` files and required staged notice/manifest files; and the 100-nit PQ encode/decode tolerances from Task 4. Add:

```python
def _capability(software_supported: bool, probe: str, detail: str | None = None) -> dict[str, object]:
    return {
        "software_supported": software_supported,
        "device_presence": "not_probed",
        "probe": probe,
        "detail": detail,
    }


def _windows_symbol(dll_name: str, symbol: str) -> bool:
    if os.name != "nt":
        return False
    try:
        library = ctypes.WinDLL(dll_name, use_last_error=True)
        getattr(library, symbol)
    except (OSError, AttributeError):
        return False
    return True
```

The capability values are: display enumeration from `os.name == "nt"`; DDC/CI from `Dxva2.dll/GetVCPFeatureAndVCPFeatureReply`; ICC profile from `Mscms.dll/WcsGetDefaultColorProfile`; gamma ramp from `Gdi32.dll/GetDeviceGammaRamp`; and colorimeter software support from `importlib.util.find_spec("hid") is not None`. Loading a system DLL and looking up a symbol is allowed; calling the symbol, importing `hid`, or enumerating a device is forbidden. Report schema version is 1 and `ok` depends on dependencies/resources/PQ, not physical device presence.

- [ ] **Step 5: Make source command dispatch lazy before heavy imports**

Create `calibrate_pro/commands/doctor.py`:

```python
def run(args) -> int:
    from calibrate_pro.diagnostics import build_doctor_report, doctor_exit_code, render_doctor_json

    report = build_doctor_report()
    print(render_doctor_json(report=report))
    return doctor_exit_code(report)
```

Give `render_doctor_json` the signature `render_doctor_json(*, report: dict[str, object] | None = None, root: Path | None = None) -> str`. Change `main(argv: Sequence[str] | None = None) -> int`; parse `doctor` before importing calibration engines, panels, hardware, services, startup, or GUI modules. Move the current top-level calibration-engine, panel, and target imports into only the command functions that need them. Source `cmd_doctor` delegates to `commands.doctor.run`.

- [ ] **Step 6: Verify focused behavior**

```powershell
python -m pytest tests/test_diagnostics.py -q
python -m calibrate_pro.main doctor --json
```

Expected: both tests and command produce valid schema-1 JSON. Source doctor may exit 1 until Task 11 adds notices, but stderr is empty and no blocked import occurs.

- [ ] **Step 7: Commit diagnostics**

```powershell
git add calibrate_pro/runtime.py calibrate_pro/diagnostics.py calibrate_pro/commands calibrate_pro/main.py calibrate_pro/lut_system/dwm_lut.py tests/test_diagnostics.py
git commit -m "feat: add non-mutating packaged diagnostics"
```

---

### Task 8: Remove Every GUI/Service Actuator Bypass and Keep Launch Unelevated

**Files:**
- Create: `tests/test_least_privilege.py`
- Create: `tests/test_actuator_boundary.py`
- Modify: `calibrate_pro/main.py`
- Modify: `calibrate_pro/gui/app.py`
- Modify: `calibrate_pro/gui/hdr_calibration.py`
- Modify: `calibrate_pro/gui/pages/ddc_control.py`
- Modify: `calibrate_pro/gui/pages/profiles.py`
- Modify: `calibrate_pro/gui/pages/settings.py`
- Modify: `calibrate_pro/services/calibration_guard.py`
- Modify: `calibrate_pro/tray/tray_app.py`

**Interfaces:**
- Consumes: `ApplyPlan`, `ActuationCoordinator`, and `WindowsDisplayStateAdapter` from Task 6.
- Produces: unelevated launch plus application-layer code in which every display mutation is a proposed plan signal handled by one confirmation coordinator.

- [ ] **Step 1: Write failing source-boundary and behavioral tests**

Create `tests/test_actuator_boundary.py`. Parse application-facing Python under `calibrate_pro/gui`, `calibrate_pro/services`, `calibrate_pro/tray`, and `calibrate_pro/commands`, plus `main.py` and future `frozen_main.py`. Fail on imports or calls containing `set_vcp`, `set_gamma_ramp`, `reset_gamma_ramp`, `install_profile`, `set_display_profile`, `load_lut`, `unload_lut`, `start_dwm_lut_gui`, or `ShellExecuteW`. The only application-layer file allowed to reference those primitives is `calibrate_pro/adapters/windows_display_state.py`; low-level implementation modules remain callable only by that adapter.

Add offscreen behavior tests using a fake adapter and coordinator:

```python
def test_ddc_slider_stages_without_writing(ddc_page, fake_adapter) -> None:
    ddc_page.brightness_slider.setValue(42)
    assert fake_adapter.calls == []
    assert ddc_page.pending_ddc_changes == (("BRIGHTNESS", 42),)


def test_hdr_live_update_is_removed(hdr_window, fake_adapter, qapp) -> None:
    assert not hasattr(hdr_window, "live_update")
    qapp.processEvents()
    assert fake_adapter.calls == []


def test_apply_signal_requires_shell_confirmation(calibrate_window, fake_adapter) -> None:
    plan = make_plan(ddc_changes=(("BRIGHTNESS", 42),))
    calibrate_window.stage_apply_plan(plan)
    calibrate_window.reject_staged_plan()
    assert fake_adapter.calls == []
    calibrate_window.stage_apply_plan(plan)
    receipt = calibrate_window.confirm_staged_plan_for_test()
    assert receipt.success is True
    assert fake_adapter.calls[:3] == ["capture", "apply", "verify"]
```

Create `tests/test_least_privilege.py` to assert `run_as_admin` and `"runas"` are absent from `main.py`, command modules, and GUI modules; construct main/HDR windows offscreen with injected fakes and assert zero writes/elevation. Assert CalibrationGuard exposes notification callbacks but no restore/apply method.

- [ ] **Step 2: Verify RED**

```powershell
$env:QT_QPA_PLATFORM = 'offscreen'
python -m pytest tests/test_actuator_boundary.py tests/test_least_privilege.py -q
```

Expected: current direct DDC, profile, gamma, DWM, tray, guard, HDR live-update, and elevation paths fail.

- [ ] **Step 3: Remove GUI-wide elevation and automatic HDR mutation**

Delete `is_admin()`/`run_as_admin()` from `main.py` and `gui/hdr_calibration.py`. Remove the HDR constructor's DWM auto-start timer, the live-update timer/toggle, direct `_apply_lut`, direct `_remove_lut`, and direct `_start_dwm_lut` calls. The HDR window generates files and emits `apply_plan_requested = Signal(ApplyPlan)`; its Apply, Reset, Remove, and Start-DWM controls each construct an explicit preview plan instead of writing. `commands.hdr.run` remains unelevated and connects that signal to the shared confirmation handler.

- [ ] **Step 4: Convert DDC, profile, tray, restore, and guard behavior to proposals**

- `DDCControlPage` keeps a sorted pending `(code, value)` map. Slider changes never call `set_vcp`; an `Apply DDC changes` button emits one `ApplyPlan` and shows the exact old/new values in Preview.
- `ProfilesPage` emits a profile-path plan instead of calling `install_profile`.
- `CalibrateProWindow._apply_tray_profile`, `_restore_defaults`, and `_install_profile` become plan builders passed to `stage_apply_plan(plan)`; no tray callback writes state.
- `tray/tray_app.py` opens/focuses the main window with a staged plan and never installs a profile or LUT itself.
- `CalibrationGuard` is renamed in copy to `Calibration monitor`; it detects drift and notifies only. Remove every restoration/write callback. The persisted setting is `services/calibration_monitor_enabled`, defaults false, and explicitly states that 1.1 never reapplies automatically.

All pages receive a callback `request_apply: Callable[[ApplyPlan], None]` from the shell. The shell owns `ActuationCoordinator`, calls `token = coordinator.preview(plan)`, renders the plan, and invokes `coordinator.apply(plan, token, confirmed=dialog_result == Accepted)` exactly once.

- [ ] **Step 5: Verify the sole boundary and regressions**

```powershell
$env:QT_QPA_PLATFORM = 'offscreen'
python -m pytest tests/test_actuator_boundary.py tests/test_least_privilege.py tests/test_workflow.py -q
python -m pytest -q
```

Expected: all direct application-layer writer references are absent, rejection performs zero writes, confirmation uses one transaction, and GUI/HDR launch is unelevated.

- [ ] **Step 6: Commit least privilege and bypass removal**

```powershell
git add calibrate_pro/main.py calibrate_pro/gui calibrate_pro/services/calibration_guard.py calibrate_pro/tray/tray_app.py tests/test_actuator_boundary.py tests/test_least_privilege.py
git commit -m "fix: route every display write through confirmed Apply"
```

---

### Task 9: Carry Structured Evidence Through Every User-Facing Result and Report

**Files:**
- Create: `tests/test_truthfulness_contract.py`
- Modify: `calibrate_pro/__init__.py`
- Modify: `calibrate_pro/sensorless/auto_calibration.py`
- Modify: `calibrate_pro/sensorless/neuralux.py`
- Modify: `calibrate_pro/core/calibration_engine.py`
- Modify: `calibrate_pro/verification/report_generator.py`
- Modify: `calibrate_pro/verification/reports.py`
- Modify: `calibrate_pro/verification/pdf_export.py`
- Modify: `calibrate_pro/main.py`
- Modify: `calibrate_pro/gui/app.py`
- Modify: `calibrate_pro/gui/calibration_wizard.py`
- Modify: `calibrate_pro/gui/pages/calibrate.py`
- Modify: `calibrate_pro/gui/pages/calibration_page.py`
- Modify: `calibrate_pro/gui/pages/verify.py`
- Modify: `calibrate_pro/gui/dialogs.py`
- Modify: `calibrate_pro/gui/hdr_calibration.py`

**Interfaces:**
- Consumes: `WorkflowController`, `ActuationCoordinator`, `MetricValue`, and `EvidenceKind`.
- Produces: one structured metric schema across sensorless, measured, simulated, replayed, CLI, GUI, JSON, HTML, and PDF-facing report data.

- [ ] **Step 1: Write failing structured-evidence and release-wide claim tests**

Create `tests/test_truthfulness_contract.py`:

```python
BANNED_UNQUALIFIED = (
    re.compile(r"achiev(?:e|es|ing)\s+delta\s*e\s*<", re.I),
    re.compile(r"delta\s*e\s*<\s*(?:0\.5|1\.0)\s*(?:typical|accuracy)?", re.I),
    re.compile(r"(?:99\.2%\s+DCI-P3|87\.3%\s+BT\.2020|100%\s+coverage)", re.I),
)


def test_release_runtime_contains_no_unqualified_accuracy_promises() -> None:
    files = sorted((ROOT / "calibrate_pro").rglob("*.py")) + [ROOT / "README.md", ROOT / "RELEASE_NOTES.md"]
    offenders = []
    for path in files:
        text = path.read_text(encoding="utf-8")
        for pattern in BANNED_UNQUALIFIED:
            if pattern.search(text):
                offenders.append(f"{path.relative_to(ROOT)}:{pattern.pattern}")
    assert offenders == []


def assert_metric(payload: dict[str, object], evidence: str, source_prefix: str) -> None:
    assert isinstance(payload["value"], (int, float))
    assert payload["evidence"] == evidence
    assert str(payload["source"]).startswith(source_prefix)


def test_sensorless_json_and_report_metrics_are_estimates(sensorless_result) -> None:
    payload = sensorless_result.to_dict()
    assert_metric(payload["delta_e"], "estimated", "panel-characterization:")
    assert_metric(payload["gamut_coverage_srgb"], "estimated", "panel-characterization:")
    report = build_report_payload(sensorless_result)
    assert report["schema_version"] == 1
    assert_metric(report["metrics"]["delta_e"], "estimated", "panel-characterization:")


def test_report_serializer_rejects_bare_numeric_performance_metric() -> None:
    with pytest.raises(ValueError, match="MetricValue"):
        build_report_payload({"delta_e": 0.42})


def test_missing_metric_renders_not_measured() -> None:
    assert MetricValue(None, "dE2000", EvidenceKind.NOT_MEASURED).display_text() == "Not measured"
```

Add measured-fixture assertions requiring an instrument receipt source, and simulated/replayed HDR assertions requiring explicit labels in JSON and rendered report text. The report-facing test reads generated HTML/PDF source text and asserts `estimated`, `measured`, `simulated`, or `replayed` appears beside each value.

- [ ] **Step 2: Verify RED**

```powershell
$env:QT_QPA_PLATFORM = 'offscreen'
python -m pytest tests/test_truthfulness_contract.py -q
```

Expected: current package/runtime claims, bare sensorless floats, seeded GUI values, and report serializers fail.

- [ ] **Step 3: Make sensorless and measured result schemas evidence-bearing**

Replace public performance floats in `AutoCalibrationResult` and `CalibrationResult` with `MetricValue`. Sensorless sources use `panel-characterization:<normalized-model>:<profile-sha256>`; measured sources use `instrument:<driver>:<redacted-receipt-id>`. Calculated gamut geometry from a panel database is `ESTIMATED`, never `MEASURED`. Keep raw algorithm intermediates private; every `to_dict()` serializes metrics with `MetricValue.to_dict()`.

Remove threshold promises and predicted grades from package docstrings, completion messages, CLI output, and `neuralux.py`. A sensorless completion message uses `Estimated model Delta E: <value> (panel characterization)` and always names its source. No missing value defaults to `0.0`.

- [ ] **Step 4: Make every report serializer reject unlabeled metrics**

Add `build_report_payload(result) -> dict[str, object]` in `verification/report_generator.py`. It accepts result objects whose public metrics are `MetricValue`; a dict containing a bare numeric key in `{delta_e, delta_e_avg, delta_e_max, peak_luminance, gamut_coverage_srgb, gamut_coverage_p3, gamut_coverage_bt2020}` raises `ValueError`. JSON, HTML, and PDF exporters consume only this payload and render `MetricValue.display_text()` plus source. Report schema includes `schema_version`, mode, metrics, source receipts, and generated-at time.

- [ ] **Step 5: Replace every synthetic GUI observation and bind the six stages**

Remove seeded 0.42/0.89 metrics, `_seed_grayscale_chart`, random/noise-derived readings, and `_simulate_calibration()` completion. Demonstrations require an explicit simulated result object. Missing readings render `Not measured` with neutral styling. HDR copy is `HDR target transform` until CP-HDR-1 supplies an instrument receipt.

`CalibratePage` exposes `measured_method_enabled` and `measured_disabled_reason`, renders exact ordered stages `Detect`, `Method`, `Preview`, `Apply`, `Verify`, `Save/Report`, and sends its preview to the Task 8 confirmation coordinator. Failure shows both `ApplyReceipt.error` and `restore_error`, states `restored` truthfully, and never advances to Verify. Dashboard primary copy is `Calibrate a display`.

- [ ] **Step 6: Verify all truthfulness surfaces and the full suite**

```powershell
$env:QT_QPA_PLATFORM = 'offscreen'
python -m pytest tests/test_truthfulness_contract.py tests/test_hdr_provenance.py tests/test_workflow.py tests/test_verification.py -q
python -m pytest -q
```

Expected: every public performance metric carries finite evidence/source or is `Not measured`; no unqualified promise or fabricated observation remains.

- [ ] **Step 7: Commit structured truthfulness**

```powershell
git add calibrate_pro tests/test_truthfulness_contract.py
git commit -m "feat: carry evidence through every calibration result"
```

---

### Task 10: Preserve the GUI API and Freeze a Minimal Positive-Allowlisted Onedir Graph

**Files:**
- Create: `calibrate_pro/frozen_main.py`
- Create: `calibrate_pro/commands/gui.py`
- Create: `calibrate_pro/commands/hdr.py`
- Create: `packaging/frozen-features.json`
- Create: `packaging/frozen-modules.json`
- Create: `tests/data/gui-public-api-1.0.json`
- Create: `tests/test_gui_lazy_imports.py`
- Create: `tests/test_frozen_module_allowlist.py`
- Create: `tests/test_packaging_contract.py`
- Modify: `calibrate_pro/gui/__init__.py`
- Replace: `calibrate-pro.spec`
- Delete: `CalibratePro.spec`

**Interfaces:**
- Produces: a developer source CLI with its existing commands, frozen binaries exposing only `doctor`, `gui`, and `hdr`, and a TOC in which every first-party module is explicitly approved.
- Produces: `dist/CalibratePro/CalibratePro.exe` and `CalibrateProCLI.exe` sharing one `_internal` tree.

- [ ] **Step 1: Write failing lazy-API, frozen-command, and positive-allowlist tests**

Create `tests/data/gui-public-api-1.0.json` with this exact approved-ancestor list:

```json
[
  "APP_NAME", "APP_ORGANIZATION", "APP_VERSION", "BeforeAfterView", "CIEDiagramWidget", "COLORS",
  "CalibrationConfig", "CalibrationMode", "CalibrationModeStep", "CalibrationPage", "CalibrationReport",
  "CalibrationStatus", "CalibrationWizard", "CalibrationWorker", "ColorCheckerResult", "ColorGrid",
  "ColorInfoPanel", "ColorManagementStatus", "ColorPatchDisplay", "ColorSwatch", "ComparisonSwatch",
  "ConsentDialog", "CurveData", "DARK_STYLESHEET", "DDCControlPage", "DashboardPage", "DeltaEBarChart",
  "DeltaEDisplay", "DeltaEMeasurement", "DeltaEQuality", "DeltaEStatsPanel", "DisplayInfo",
  "DisplayInfoPanel", "DisplayLayoutPreview", "DisplayMonitorWidget", "DisplaySelectionStep", "DisplaySelector",
  "DisplayTechnology", "GAMUTS", "GammaCurveWidget", "GammaInfoPanel", "GammaTarget", "GamutCoverage",
  "GamutTarget", "GrayscaleResult", "IconFactory", "LUT3D", "LUTCubeView", "LUTPreviewWidget",
  "LUTSliceView", "MainWindow", "MeasuredPoint", "Measurement", "MeasurementHistoryTable", "MeasurementStep",
  "MeasurementView", "PatternCanvas", "PatternConfig", "PatternRenderer", "PatternSequencer", "PatternType",
  "PatternWindow", "ProfileGenerationStep", "ProfilesPage", "ReportSummaryPanel", "ReportViewer",
  "SPECTRAL_LOCUS", "SettingsPage", "SimulatedMeasurementWindow", "SoftwareColorControlPage", "SummaryCard",
  "TargetSettingsStep", "VCGTToolsPage", "ValuesPanel", "VerificationPage", "VerificationStep", "WHITE_POINTS",
  "WhitepointTarget", "WizardStep", "bt1886_eotf", "classify_delta_e", "delta_e_2000",
  "get_delta_e_color", "l_star_eotf", "power_law_eotf", "rgb_to_lab", "rgb_to_xyz", "run_application",
  "srgb_eotf", "srgb_oetf", "xyz_to_lab"
]
```

`tests/test_gui_lazy_imports.py` asserts the JSON set is a subset of `gui.__all__` and the only added name is `CalibrateProWindow`; importing `calibrate_pro.gui` loads none of `main_window`, `calibration_wizard`, or `professional_calibration`, and every listed attribute resolves on first access under offscreen PySide6.

Create `tests/test_frozen_module_allowlist.py`:

```python
def test_frozen_features_are_exact_and_developer_only_commands_are_explicit() -> None:
    data = json.loads((ROOT / "packaging/frozen-features.json").read_text(encoding="utf-8"))
    assert data == {
        "schema_version": 1,
        "commands": ["doctor", "gui", "hdr"],
        "developer_only_commands": [
            "auto", "calibrate", "ddc-calibrate", "ddc-info", "detect", "disable-startup",
            "enable-startup", "export-panel", "hdr-status", "import-panel", "info", "list-panels",
            "list-targets", "match", "native-calibrate", "patterns", "plugins", "profiles-generate",
            "refine", "restore", "status", "tray", "uniformity", "verify",
        ],
    }


def test_analysis_toc_is_a_positive_first_party_subset(built_analysis_toc: Path) -> None:
    policy = json.loads((ROOT / "packaging/frozen-modules.json").read_text(encoding="utf-8"))
    observed = first_party_modules_from_toc(built_analysis_toc)
    assert observed <= set(policy["first_party_exact"])
    assert not (set(policy["first_party_exact"]) - observed - set(policy["optional_first_party_exact"]))
```

Add subprocess assertions that frozen-main `doctor --json`, `gui`, and `hdr` dispatch to the three shared command modules, while `tray` and `calibrate` exit 2 with `This command is available only in the developer wheel` and do not import their modules.

- [ ] **Step 2: Verify RED**

```powershell
python -m pytest tests/test_gui_lazy_imports.py tests/test_frozen_module_allowlist.py tests/test_packaging_contract.py -q
```

Expected: compatibility facade, frozen manifests, minimal dispatcher, and sole-spec contract are absent.

- [ ] **Step 3: Preserve the complete lazy public API**

Replace `gui/__init__.py` eager imports with a literal `_EXPORTS: dict[str, tuple[str, str]]` mapping for every name in `gui-public-api-1.0.json`. `__all__` is the sorted mapping key set; cached `__getattr__` imports only the selected module and raises normal `AttributeError` for unknown names. Add `CalibrateProWindow` as the sole new 1.1 export. The compatibility test, not a hand-maintained subset, prevents accidental removals.

- [ ] **Step 4: Add shared lazy desktop commands and the frozen dispatcher**

`commands/gui.py` and `commands/hdr.py` call `configure_qt_api()` before importing PySide6 or GUI modules, construct the production adapter/coordinator, connect Apply-plan signals to the confirmation dialog, and enter the event loop unelevated. Source `cmd_gui`/`cmd_hdr` delegate to them.

Create `frozen_main.py` with a literal string map for only the three approved modules. It parses `argv`, defaults `CalibratePro.exe` with no arguments to `gui`, defaults `CalibrateProCLI.exe` with no arguments to help, handles `--version`, and dynamically imports only the selected shared command. Before parsing, if the first argument is in `developer_only_commands`, print the exact developer-wheel message to stderr and return 2.

- [ ] **Step 5: Create exact feature and module policies**

Create `packaging/frozen-features.json` exactly as asserted in Step 1. Create `packaging/frozen-modules.json` with schema version 1, `default: reject`, exact first-party modules, optional platform-specific exact modules, and these permitted distribution roots: `build_color`, `build_ui`, `qtpy`, `PySide6`, `shiboken6`, `numpy`, `scipy`, and `hid`. Seed `first_party_exact` with `calibrate_pro`, `frozen_main`, three command modules, diagnostics/runtime/Qt/workflow/recovery/actuation/adapter modules, active GUI shell/pages/widgets, the canonical PQ/color core, panel database/detection, profile/VCGT modules, required sensor/DDC modules, HDR target-transform modules, and DWM LUT modules. No prefix wildcard is permitted for `calibrate_pro` or `build_color`; each observed module must be a literal JSON string.

- [ ] **Step 6: Replace the spec with a generated-exclusion positive graph**

The spec reads both JSON policies. It derives `all_first_party` from `Path("calibrate_pro").rglob("*.py")`, converts paths to module names without importing them, and sets `excludes` to every first-party module not in the exact allowlist plus PyQt5, PyQt6, `build_color.gui`, and the existing unrelated-framework exclusions. `hiddenimports` is exactly the approved first-party set plus the four Build Color core modules, Build UI theme/widgets, QtPy, and required PySide modules. It raises during spec evaluation if a hidden import is absent from policy.

Use one `Analysis(["calibrate_pro/frozen_main.py"])`, one `PYZ`, two `EXE` objects with `exclude_binaries=True`, and one `COLLECT`. Copy required distribution metadata and the five literal `dwm_lut` files. Set `strip=False`, `upx=False`, and `uac_admin=False` on both executables. Delete `CalibratePro.spec`.

- [ ] **Step 7: Build, produce the first exact module inventory, and fail closed**

```powershell
$env:QT_API = 'pyside6'
$env:QT_QPA_PLATFORM = 'offscreen'
python -m PyInstaller --clean --noconfirm calibrate-pro.spec
python -m pytest tests/test_frozen_module_allowlist.py tests/test_packaging_contract.py -q
```

If the build reports a required first-party module not in policy, add its exact name only after identifying the active import that requires it; do not add a prefix or use `collect_submodules`. Re-run until the TOC is a subset and both executables exist. `rg "PyQt5|PyQt6|build_color\.gui" build/CalibratePro/Analysis-00.toc` must return no match.

- [ ] **Step 8: Commit the minimal frozen graph**

```powershell
git add calibrate_pro/frozen_main.py calibrate_pro/commands calibrate_pro/gui/__init__.py packaging/frozen-features.json packaging/frozen-modules.json calibrate-pro.spec tests/data/gui-public-api-1.0.json tests/test_gui_lazy_imports.py tests/test_frozen_module_allowlist.py tests/test_packaging_contract.py
git rm CalibratePro.spec
git commit -m "build: freeze a positive-allowlisted PySide application"
```

---

### Task 11: Lock the Windows Release and Curate Qt Redistribution Inputs

**Files:**
- Create: `packaging/requirements-win64.in`
- Create: `packaging/requirements-win64-py312.lock`
- Create: `packaging/toolchain-win64.json`
- Create: `packaging/qt-components.json`
- Create: `packaging/components-win64.json`
- Create: `packaging/source-provenance.lock.json`
- Create: `scripts/verify_source_provenance.py`
- Create: `THIRD_PARTY_LICENSES/README.md`
- Create: `THIRD_PARTY_LICENSES/LGPL-3.0-only.txt`
- Create: `THIRD_PARTY_LICENSES/Qt-for-Python-NOTICE.txt`
- Create: `THIRD_PARTY_LICENSES/QT_SOURCE_OFFER.txt`
- Create: `THIRD_PARTY_LICENSES/LGPL_RELINKING.md`
- Create: `THIRD_PARTY_LICENSES/Python-3.12.10.txt`
- Create: `THIRD_PARTY_LICENSES/Build-Color-1.0.2.txt`
- Create: `THIRD_PARTY_LICENSES/Build-UI-2.0.0.txt`
- Create: `THIRD_PARTY_LICENSES/QtPy-2.4.3.txt`
- Create: `THIRD_PARTY_LICENSES/NumPy-2.5.1.txt`
- Create: `THIRD_PARTY_LICENSES/SciPy-1.18.0.txt`
- Create: `THIRD_PARTY_LICENSES/OpenBLAS.txt`
- Create: `THIRD_PARTY_LICENSES/hidapi-0.15.0.txt`
- Create: `THIRD_PARTY_LICENSES/PyInstaller-6.21.0.txt`
- Create: `tests/test_release_lock.py`
- Create: `tests/test_qt_redistribution.py`
- Delete: `requirements.txt`
- Delete: `build_installer.bat`

**Interfaces:**
- Consumes: published Build UI 2.0.0 and the proven PySide6 6.11.1 stack.
- Produces: hash-locked Python 3.12 Windows runtime and build inputs plus fail-closed owner/license/source classification for every staged distribution and native binary, including Qt.

- [ ] **Step 1: Write failing lock and redistribution tests**

Create `tests/test_release_lock.py`:

```python
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_release_lock_is_hashed_and_pyside_only() -> None:
    lock = (ROOT / "packaging" / "requirements-win64-py312.lock").read_text(encoding="utf-8")
    for name in (
        "build-color", "build-ui", "qtpy", "pyside6", "shiboken6", "numpy", "scipy",
        "hidapi", "pyinstaller", "build", "setuptools", "wheel", "pefile",
    ):
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


def test_every_runtime_owner_maps_to_notice_and_source() -> None:
    data = json.loads((ROOT / "packaging" / "components-win64.json").read_text(encoding="utf-8"))
    assert data["schema_version"] == 1
    assert data["default"] == "reject"
    required = {
        "python", "calibrate-pro", "build-color", "build-ui", "qtpy", "pyside6", "shiboken6",
        "numpy", "scipy", "openblas", "hidapi", "pyinstaller-bootloader", "dwm_lut", "windowsdisplayapi",
    }
    assert required <= {entry["owner"] for entry in data["components"]}
    for entry in data["components"]:
        assert (ROOT / entry["notice_path"]).is_file()
        assert entry["source_component"]
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
build==1.5.1
setuptools==83.0.0
wheel==0.47.0
pefile==2024.8.26
```

Create `packaging/toolchain-win64.json`:

```json
{
  "schema_version": 1,
  "python": "3.12.10",
  "architecture": "x86_64-pc-windows-msvc",
  "uv": "0.11.28",
  "pyinstaller": "6.21.0",
  "build": "1.5.1",
  "setuptools": "83.0.0",
  "wheel": "0.47.0",
  "source_date_epoch": 315532800,
  "inno_setup": "6.7.3"
}
```

Compile only after Build UI 2.0.0 is published to the release index:

```powershell
uv pip compile packaging/requirements-win64.in --python-version 3.12 --python-platform x86_64-pc-windows-msvc --only-binary :all: --generate-hashes --no-sources --output-file packaging/requirements-win64-py312.lock
```

Expected: the lock contains hashes for every resolved wheel and no direct URL, Git, local path, or PyQt requirement.

- [ ] **Step 4: Curate, do not infer, complete component and source mappings**

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

Create `packaging/components-win64.json` with `schema_version: 1`, `default: reject`, and literal path/glob records for Python 3.12.10, Calibrate Pro, Build Color, Build UI, QtPy, PySide6, shiboken6, NumPy, SciPy, their bundled OpenBLAS/runtime DLLs, hidapi, the PyInstaller bootloader, `dwm_lut`, and `WindowsDisplayAPI`. Each record contains `pattern`, `owner`, `version`, `license`, `notice_path`, and `source_component`. A broad `*.dll`, `_internal/**`, or distribution-prefix catch-all is forbidden. `scripts/verify_source_provenance.py` downloads every HTTPS source URL to a temporary directory, verifies its SHA-256, rejects redirects outside the recorded host unless the final URL is also recorded, and removes the exact temporary directory.

- [ ] **Step 5: Commit the complete notice set**

Use the verbatim GNU LGPL v3 text from `https://www.gnu.org/licenses/lgpl-3.0.txt`. Commit the exact upstream license text for every owner named by `components-win64.json` under the filenames in this task. `Qt-for-Python-NOTICE.txt` names PySide6, shiboken6, Qt 6.11.1, the selected license family, and upstream project links. `QT_SOURCE_OFFER.txt` identifies each exact source archive and checksum from the provenance lock and states how the distributor will provide corresponding source. `LGPL_RELINKING.md` explains the external onedir DLL layout and how a recipient can replace compatible Qt/PySide libraries. `README.md` states that Calibrate's FSL terms do not replace third-party licenses and preserves reverse-engineering/relinking rights needed to debug modified LGPL components.

Copy `dwm_lut/LICENSE` and `dwm_lut/LICENSE-THIRD-PARTY` during staging; retain their originals beside the bundled runtime too.

- [ ] **Step 6: Remove competing dependency/build declarations**

```powershell
git rm requirements.txt build_installer.bat
```

- [ ] **Step 7: Verify the release inputs**

```powershell
python -m pytest tests/test_release_lock.py tests/test_qt_redistribution.py -q
python scripts/verify_source_provenance.py packaging/source-provenance.lock.json
$lockProof = Join-Path $env:TEMP ('calibrate-lock-proof-' + [guid]::NewGuid().ToString('N'))
py -3.12 -m venv $lockProof
$lockPython = Join-Path $lockProof 'Scripts\python.exe'
& $lockPython -m pip install --require-hashes -r packaging/requirements-win64-py312.lock
& $lockPython -m pip check
$env:PIP_NO_INDEX = '1'
& $lockPython -m build --wheel --no-isolation
Remove-Item Env:\PIP_NO_INDEX
if (-not ((Resolve-Path $lockProof).Path.StartsWith([IO.Path]::GetTempPath(), [StringComparison]::OrdinalIgnoreCase))) { throw 'Unsafe proof path' }
Remove-Item -LiteralPath $lockProof -Recurse -Force
```

Expected: source archives re-hash correctly, the disposable locked environment is consistent, and the wheel builds without isolation or network resolution.

- [ ] **Step 8: Commit lock and redistribution inputs**

```powershell
git add packaging THIRD_PARTY_LICENSES scripts/verify_source_provenance.py tests/test_release_lock.py tests/test_qt_redistribution.py
git commit -m "build: lock Windows and Qt redistribution inputs"
```

---

### Task 12: Audit the Staged Tree, Then Package Only Its Final Signed Bytes

**Files:**
- Create: `scripts/release_artifacts.py`
- Create: `tests/test_release_artifacts.py`
- Modify: `tests/test_packaging_contract.py`
- Modify: `tests/test_qt_redistribution.py`
- Modify: `tests/test_frozen_module_allowlist.py`

**Interfaces:**
- Produces: `audit_analysis_toc`, `audit_staged_tree`, `write_reproducible_zip`, `probe_authenticode`, dependency/component/Qt/staged inventories, and self-excluding sorted `SHA256SUMS.txt`.
- Command order is `stage -> external EXE signing -> package -> external installer construction/signing -> finalize`; `package` is the only command that creates the portable ZIP.

- [ ] **Step 1: Write failing final-byte, deterministic, and fail-closed audit tests**

Create `tests/test_release_artifacts.py` with a test that writes `a.txt` and `z.txt` to a staged directory, calls `write_reproducible_zip()` twice with epoch `315532800`, and asserts both returned SHA-256 values and both ZIP byte strings are identical. Add:

```python
def test_package_inventory_and_zip_use_post_sign_bytes(tmp_path: Path) -> None:
    staged, release, policies = synthetic_valid_stage(tmp_path)
    exe = staged / "CalibratePro.exe"
    exe.write_bytes(b"unsigned")
    stage(staged, release, **policies)
    exe.write_bytes(b"signed-final-bytes")
    package(staged, release, epoch=315532800, **policies)
    inventory = json.loads((release / "staged-inventory.json").read_text(encoding="utf-8"))
    record = next(item for item in inventory["files"] if item["path"] == "CalibratePro.exe")
    assert record["sha256"] == hashlib.sha256(b"signed-final-bytes").hexdigest()
    with zipfile.ZipFile(release / "CalibratePro-1.1.0-win64.zip") as archive:
        assert archive.read("CalibratePro.exe") == b"signed-final-bytes"


def test_unknown_distribution_or_native_binary_fails_closed(tmp_path: Path) -> None:
    staged, _, policies = synthetic_valid_stage(tmp_path)
    unknown = staged / "_internal" / "unknown-native.dll"
    unknown.write_bytes(b"MZunknown")
    with pytest.raises(RuntimeError, match="unknown-native.dll"):
        audit_staged_tree(staged, **policies)


def test_sha256s_excludes_itself_and_is_sorted(tmp_path: Path) -> None:
    release = tmp_path / "release"
    release.mkdir()
    (release / "z.bin").write_bytes(b"z")
    (release / "a.bin").write_bytes(b"a")
    write_sha256s(release)
    lines = (release / "SHA256SUMS.txt").read_text(encoding="utf-8").splitlines()
    assert lines == sorted(lines, key=lambda line: line.split("  ", 1)[1])
    assert not any(line.endswith("SHA256SUMS.txt") for line in lines)
```

Retain explicit PyQt, `build_color.gui`, unknown Qt, `UPX!`, 350 MiB, required-receipt, and positive TOC allowlist tests.

- [ ] **Step 2: Verify RED**

```powershell
python -m pytest tests/test_release_artifacts.py -q
```

Expected: release module and final-byte command sequence are absent.

- [ ] **Step 3: Implement the complete artifact-tool module skeleton**

`scripts/release_artifacts.py` imports `argparse`, `ast`, `hashlib`, `json`, `os`, `shutil`, `subprocess`, `sys`, `time`, `zipfile`, `dataclass/asdict`, `importlib.metadata`, and `Path`. Define `MAXIMUM_BYTES = 350 * 1024 * 1024`, subparsers `stage`, `package`, and `finalize`, and explicit required arguments for staged directory, analysis TOC, release directory, all three policy files, and source-date epoch where applicable. Every command resolves paths and rejects a release directory inside the staged tree.

Use the deterministic ZIP function from the first draft, with epoch clamped to the ZIP-supported 1980-2107 range, sorted POSIX member names, fixed compression level 9, fixed file mode, and a top-level `CalibratePro/` archive directory so extraction cannot spill files into the current directory.

- [ ] **Step 4: Implement positive TOC, ownership, notice, and staged-tree audits**

`audit_analysis_toc()` uses `ast.literal_eval`, recursively extracts module names, rejects PyQt/Build Color GUI, and enforces every `calibrate_pro.*` name against `frozen-modules.json`. `audit_staged_tree()` enforces `components-win64.json` ownership for every distribution metadata directory and every `.dll`, `.pyd`, `.exe`, Qt plugin/helper, and Python runtime binary; applies the stricter Qt policy to Qt-owned files; rejects forbidden frameworks and UPX markers; and verifies every mapped notice/source component exists. Unknown files print their relative paths and stop packaging.

Dependency, component, Qt, and staged inventories record sorted path, owner/distribution, exact version, SHA-256, size, license, notice, and source component as applicable. `package` regenerates all inventories from current staged bytes immediately before writing the ZIP.

- [ ] **Step 5: Implement stable Authenticode probing**

Invoke PowerShell with the path supplied as a separately quoted argument and this calculated projection:

```powershell
Get-AuthenticodeSignature -LiteralPath $args[0] |
  Select-Object @{Name='Status';Expression={$_.Status.ToString()}},StatusMessage,
    @{Name='SignerThumbprint';Expression={$_.SignerCertificate.Thumbprint}},
    @{Name='SignerSubject';Expression={$_.SignerCertificate.Subject}},
    @{Name='TimestampThumbprint';Expression={$_.TimeStamperCertificate.Thumbprint}} |
  ConvertTo-Json -Compress
```

`probe_authenticode()` accepts only string statuses such as `Valid` and `NotSigned`; it never stores unstable certificate object handles or trusts an environment claim.

- [ ] **Step 6: Implement the non-overlapping command phases**

- `stage` copies notices into the onedir tree, runs TOC/tree/BOM/Qt audits, and emits `pre-sign-audit.json`; it does not emit final inventories or a ZIP.
- after external signing, `package` reruns all audits, writes final dependency/component/source/Qt/staged inventories, copies public receipts to `release/`, and creates `CalibratePro-1.1.0-win64.zip` from those exact bytes.
- after Inno construction/signing, `finalize` probes both staged EXEs and the installer, enforces installer/ZIP size gates, verifies the ZIP EXE hashes equal the final staged EXE hashes, and writes hashes for every release file except `SHA256SUMS.txt` itself.

- [ ] **Step 7: Verify unit and integration behavior**

```powershell
python -m pytest tests/test_release_artifacts.py tests/test_qt_redistribution.py tests/test_packaging_contract.py tests/test_frozen_module_allowlist.py -q
python scripts/release_artifacts.py stage --staged-dir dist/CalibratePro --analysis-toc build/CalibratePro/Analysis-00.toc --release-dir release --component-policy packaging/components-win64.json --qt-policy packaging/qt-components.json --module-policy packaging/frozen-modules.json
python scripts/release_artifacts.py package --staged-dir dist/CalibratePro --analysis-toc build/CalibratePro/Analysis-00.toc --release-dir release --component-policy packaging/components-win64.json --qt-policy packaging/qt-components.json --module-policy packaging/frozen-modules.json --source-date-epoch 315532800
.\dist\CalibratePro\CalibrateProCLI.exe doctor --json
```

Expected: synthetic byte mutation proves package uses final bytes; real audits pass and frozen doctor reports `ok: true`.

- [ ] **Step 8: Commit artifact tooling**

```powershell
git add scripts/release_artifacts.py tests/test_release_artifacts.py tests/test_packaging_contract.py tests/test_qt_redistribution.py tests/test_frozen_module_allowlist.py
git commit -m "build: package only audited final staged bytes"
```

---

### Task 13: Build the Per-User Installer and Canonical Release Pipeline

**Files:**
- Create: `installer/CalibratePro.iss`
- Create: `scripts/build_windows.ps1`
- Create: `scripts/smoke_frozen.ps1`
- Create: `scripts/verify_reproducibility.ps1`
- Create: `scripts/verify_pe_manifest.py`
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
    assert "--wheel --no-isolation" in text
    assert "SOURCE_DATE_EPOCH" in text and "PYTHONHASHSEED" in text
    assert text.index("release_artifacts.py stage") < text.index("Sign-StagedExecutables")
    assert text.index("Sign-StagedExecutables") < text.index("release_artifacts.py package")
    assert text.index("release_artifacts.py package") < text.index("ISCC.exe")


def test_built_pe_manifests_are_checked_not_inferred_from_spec() -> None:
    text = (ROOT / "scripts" / "build_windows.ps1").read_text(encoding="utf-8")
    assert "verify_pe_manifest.py" in text
    assert "asInvoker" in (ROOT / "scripts" / "verify_pe_manifest.py").read_text(encoding="utf-8")
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
#ifndef StagedDir
  #error StagedDir must be supplied with /DStagedDir
#endif
#ifndef ReleaseDir
  #error ReleaseDir must be supplied with /DReleaseDir
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
OutputDir={#ReleaseDir}
OutputBaseFilename=CalibratePro-{#AppVersion}-Setup
Compression=lzma2/ultra64
SolidCompression=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
PrivilegesRequired=lowest
UninstallDisplayIcon={app}\{#AppExeName}
WizardStyle=modern

[Files]
Source: "{#StagedDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\Calibrate Pro"; Filename: "{app}\{#AppExeName}"
Name: "{autodesktop}\Calibrate Pro"; Filename: "{app}\{#AppExeName}"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Additional shortcuts:"; Flags: unchecked

[Run]
Filename: "{app}\{#AppExeName}"; Description: "Launch Calibrate Pro"; Flags: nowait postinstall skipifsilent
```

- [ ] **Step 4: Create the canonical PowerShell build**

`scripts/build_windows.ps1` accepts `-Unsigned`, `-SkipInstaller`, and an optional new `-OutputRoot`. It verifies Windows x64/Python 3.12.10, loads the fixed epoch from `toolchain-win64.json`, and sets `SOURCE_DATE_EPOCH`, `PYTHONHASHSEED=0`, `PYTHONUTF8=1`, `TZ=UTC`, and `LANG=C` before any wheel/frozen build. It creates a unique empty output root when none is supplied and refuses a non-empty supplied root. It creates a uniquely named temporary venv, installs the hash lock with `--require-hashes`, sets `PIP_NO_INDEX=1`, builds only the Calibrate wheel with `python -m build --wheel --no-isolation --outdir $outputRoot\wheel`, installs that exact wheel with `--no-deps`, runs tests, and builds PyInstaller with explicit `--workpath` and `--distpath` below the output root.

The canonical order is exact:

1. freeze the unsigned onedir tree;
2. run `release_artifacts.py stage` and frozen doctor;
3. use `scripts/verify_pe_manifest.py` to prove both generated PE manifests request `asInvoker`;
4. `Sign-StagedExecutables` signs both staged EXEs when configured;
5. run `release_artifacts.py package`, which regenerates inventories and ZIP from the now-final EXE bytes;
6. compile Inno from that same staged tree with:

```powershell
& $iscc "/DAppVersion=$version" "/DStagedDir=$stagedDir" "/DReleaseDir=$releaseDir" '.\installer\CalibratePro.iss'
```

7. conditionally sign the installer;
8. run `release_artifacts.py finalize` to verify signatures, ZIP/stage identity, size, and final hashes.

The script resets environment variables in `finally`. It validates any temporary directory is below `[IO.Path]::GetTempPath()` and has the expected `calibrate-pro-release-`, `calibrate-pro-venv-`, or `calibrate-pro-output-` leaf prefix before recursive removal. It never cleans a caller-supplied directory. With no `-OutputRoot`, it builds in a unique temp root and, after successful finalize, atomically replaces the repository `release/` directory by renaming the completed release directory; with `-OutputRoot`, all build/dist/release files remain below that caller-owned empty root and repository `release/` is untouched.

Pin Inno Setup 6.7.3 in CI and receipt its `ISCC.exe` file version and SHA-256. The build refuses another version unless `packaging/toolchain-win64.json` changes in a reviewed commit.

Create `scripts/verify_pe_manifest.py` using locked `pefile`. It reads the RT_MANIFEST resource bytes from each supplied EXE, parses XML, requires exactly one `requestedExecutionLevel`, requires `level="asInvoker"`, rejects `requireAdministrator`/`highestAvailable`, and writes a sorted JSON receipt containing executable path, SHA-256, and requested level. Absence or malformed XML exits nonzero.

- [ ] **Step 5: Add safe frozen smoke and reproducibility scripts**

`smoke_frozen.ps1` runs CLI help, version, doctor, and starts each unelevated GUI executable long enough to verify it remains running, then stops it. It first sets `QT_QPA_PLATFORM=offscreen`; automatic actuators were removed in Tasks 8-9.

`verify_reproducibility.ps1` creates two unique empty `calibrate-pro-output-*` roots below the system temp directory, invokes the same source tree twice with `-Unsigned -SkipInstaller -OutputRoot`, compares portable ZIP SHA-256 and canonical staged-inventory JSON bytes, emits a path/hash diff on mismatch, and safely removes only its two verified roots. Signing and Inno timestamps are outside this unsigned identity comparison.

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
git add installer scripts/build_windows.ps1 scripts/smoke_frozen.ps1 scripts/verify_reproducibility.ps1 scripts/verify_pe_manifest.py tests/test_packaging_contract.py
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
        "windows-2022",
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

Set `QT_API: pyside6` and `QT_QPA_PLATFORM: offscreen`. Source tests install `.[all,test]` from published declarations. Keep Python 3.10-3.13 source coverage. Add one pinned `windows-2022` Python 3.12 packaging job that records runner image/OS, installs exactly Inno Setup 6.7.3, verifies and receipts its SHA-256, Authenticode status, and version, invokes the canonical build/smoke/reproducibility scripts, and uploads the complete `release/` directory.

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

Architecture documents the pure workflow, sole production actuator adapter, explicit frozen-only command set, positive module allowlist, Build Color core imports, Build UI 2 bridge, PySide-only freeze, onedir layout, and source/frozen diagnostics. Security documents protected signing secrets, no telemetry assumption, complete component/notice ownership, and third-party source/relinking rights.

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
9. Confirm `pe-manifest-inventory.json` reports `asInvoker` for both EXEs and that GUI/HDR launch produces no UAC prompt.
10. Confirm frozen `tray` and `calibrate` return exit 2 with the documented developer-wheel message, while source-wheel commands remain available.
11. Reject one staged Apply and confirm no DDC/profile/VCGT/DWM change; accept a harmless test-display Apply only under the separately authorized hardware protocol and retain its transaction receipt.

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
$handoff = Get-Content -Raw -LiteralPath 'C:\dev\worktrees\calibrate-pro-1.1-pyside-handoff.json' | ConvertFrom-Json
$expectedRoot = (Resolve-Path -LiteralPath $handoff.worktree_path).ProviderPath
$actualRoot = (Resolve-Path -LiteralPath ((git rev-parse --show-toplevel).Trim())).ProviderPath
if (-not [string]::Equals($actualRoot, $expectedRoot, [StringComparison]::OrdinalIgnoreCase)) { throw 'Wrong worktree' }
if ((git symbolic-ref --short HEAD).Trim() -ne $handoff.branch) { throw 'Wrong implementation branch' }
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
Get-FileHash .\release\CalibratePro-1.1.0-Setup.exe -Algorithm SHA256
Get-FileHash .\release\CalibratePro-1.1.0-win64.zip -Algorithm SHA256
git diff --check
git status --short
```

Expected: all automated gates pass, doctor reports `ok: true`, both hashes exist, and status contains only intentional implementation changes or is clean after the final commit.

## Plan Self-Review

- R1 is implemented by Tasks 10-14 and proven only by Task 14's offline clean-machine check.
- R2, R3, and R18 map to Tasks 1-3, 10-13, including candidate-extra parsing, loaded-binding rejection, positive module closure, and complete component ownership.
- R4 and R5 map to Task 10.
- R6 maps to Task 3.
- R7, R8, R9, and R10 map to Tasks 5, 6, 8, and 9 through finite sourced metrics, capability-complete previews, one-use confirmation, the sole Windows adapter, and capture/restore failure receipts.
- R11, R12, R14, and R20 map to Tasks 11-14 through the hash-locked no-isolation backend, whole-build deterministic environment, complete BOM/notices, post-sign packaging, stable signature probes, and the sole release script.
- R13 maps to Task 7 and frozen checks in Tasks 12-14; software availability is reported without device enumeration and both real entrypoints are mutation-import tested.
- R15 and R19 map to Tasks 6, 8, 10, 13, and 14; every bypass is removed, PE manifests are inspected from built bytes, and frozen commands are explicitly bounded.
- R16 maps to Tasks 5 and 9.
- R17 maps to Task 4 and doctor/release checks in Tasks 7 and 12.
- Type names and signatures are consistent: `EvidenceKind`, `MetricValue`, `ApplyPlan`, `WorkflowController`, `DisplayStateSnapshot`, `DisplayStateAdapter`, `ActuationCoordinator`, `WindowsDisplayStateAdapter`, `ApplyReceipt`, `application_root`, `resource_path`, `build_doctor_report`, and `write_reproducible_zip` retain the same spelling at every consumer.
- CP-HDR-1 measurement expansion, generalized grading, rendering-engine integration, and competitive parity remain outside this packaging plan.
- A trusted signing certificate and legal approval remain explicit external release gates; all unsigned and engineering-audit results stay truthful.

## Execution Handoff

Plan implementation may begin only after explicit operator approval of this document and consent to create the isolated worktree from the exact plan-tip recorded in the handoff. The tip must be a descendant of `10149aa8e96dc2991eae8db134b53512c5afe5b8` and contain this plan.

After approval, use **Subagent-Driven Development** with a fresh implementation agent and two-stage review per task. Inline execution is permitted only if the operator explicitly selects it; it still runs exclusively in `C:\dev\worktrees\calibrate-pro-1.1-pyside`.
