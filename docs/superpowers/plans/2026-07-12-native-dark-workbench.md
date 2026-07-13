# Calibrate Pro Native Dark Workbench Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace Calibrate Pro’s active light rose Build UI skin with a trustworthy dark-room native surface and add a hardware-free preview mode that can become current public evidence.

**Architecture:** Keep the existing PySide6 window, page stack, Build UI widget APIs, calibration workers, and consent boundaries. Move the active palette contract into `calibrate_pro.gui.theme`, install those tokens before importing Build UI widgets, and test that the active app can no longer fall back to the legacy light palette. Add an explicit simulated preview mode through dependency injection; it must bypass USB, DDC/CI, startup, tray, and display mutation code and label every synthetic value as simulated.

**Tech Stack:** Python 3.10+, PySide6, Qt stylesheets, pytest offscreen Qt.

## Global Constraints

- Physical scene: a colorist uses this at a Windows workstation in a dim grading suite while judging subtle display changes; the interface must stay dark, calm, high-contrast, and immediately legible.
- Product register: familiar Windows/Qt task UI. No decorative choreography, gradient text, glassmorphism, neon developer-dashboard styling, oversized metrics, or identical decorative card grids.
- Use one restrained cyan-teal accent only for primary actions, current selection, focus, and evidence-bearing state.
- Exact active tokens: `BG #0E1014`, `BG_ALT #13161C`, `SURFACE #191D24`, `SURFACE2 #202630`, `BORDER #303846`, `BORDER_LT #465165`, `TEXT #F2F4F7`, `TEXT2 #C3CBD8`, `TEXT3 #8F9AA9`, `ACCENT #37B7A5`, `ACCENT_HI #55CEBC`, `ACCENT_TX #79E0D1`, `GREEN #5DC88C`, `GREEN_HI #7ADB9F`, `CYAN #6DC8FF`, `YELLOW #E1B86A`, and `RED #E77B78`.
- Body/secondary/muted text contrast against `BG` must remain at least 4.5:1. The verified ratios for `TEXT`, `TEXT2`, and `TEXT3` are 17.28:1, 11.66:1, and 6.68:1.
- Sensorless estimates, measured observations, simulated preview values, replayed values, and `Not measured` remain semantically distinct.
- Preview mode must never open USB devices, enumerate DDC/CI writers, apply LUTs, change startup state, create tray services, or write display/profile state.
- Existing mutation-capable workflows retain preview and explicit-confirmation boundaries.
- Use test-first development for every behavior change.

---

### Task 1: Own the active theme and retire the legacy light skin

**Files:**
- Modify: `calibrate_pro/gui/theme.py`
- Modify: `calibrate_pro/gui/app.py`
- Create: `tests/test_gui_theme_contract.py`

**Interfaces:**
- Consumes: Build UI widgets that import the mutable `build_ui.theme.C` class during module import.
- Produces: local `C`, local `STYLE`, and `install_build_ui_theme() -> None`; the active app installs the local tokens before importing Build UI widgets.

- [x] **Step 1: Write the failing theme ownership test**

```python
def test_active_app_owns_dark_room_theme() -> None:
    import calibrate_pro.gui.app as app
    from calibrate_pro.gui.theme import C, STYLE

    assert app.C is C
    assert app.STYLE is STYLE
    assert C.BG == "#0E1014"
    assert C.SURFACE == "#191D24"
    assert C.TEXT == "#F2F4F7"
    assert C.ACCENT == "#37B7A5"
    assert "#fdf9f5" not in STYLE.lower()
    assert "#d4a0a0" not in STYLE.lower()
    assert "QPushButton:focus" in STYLE
    assert "QPushButton:disabled" in STYLE
```

- [x] **Step 2: Run the new test and verify RED**

Run: `python -m pytest tests/test_gui_theme_contract.py -q`

Expected: fail because `calibrate_pro.gui.app` still imports `STYLE` and `C` from installed `build_ui.theme`.

- [x] **Step 3: Replace the compatibility-only theme module with the active token contract**

Define this exact public token object in `calibrate_pro/gui/theme.py`:

```python
class C:
    BG = "#0E1014"
    BG_ALT = "#13161C"
    SURFACE = "#191D24"
    SURFACE2 = "#202630"
    BORDER = "#303846"
    BORDER_LT = "#465165"
    TEXT = "#F2F4F7"
    TEXT2 = "#C3CBD8"
    TEXT3 = "#8F9AA9"
    ACCENT = "#37B7A5"
    ACCENT_HI = "#55CEBC"
    ACCENT_TX = "#79E0D1"
    GREEN = "#5DC88C"
    GREEN_HI = "#7ADB9F"
    CYAN = "#6DC8FF"
    YELLOW = "#E1B86A"
    RED = "#E77B78"
```

Build `STYLE` from those values. Cover the widget types already used in `app.py`: `QMainWindow`, `QWidget`, `QMenuBar`, `QMenu`, `QStatusBar`, `QScrollArea`, `QPushButton`, `QComboBox`, `QLineEdit`, `QSpinBox`, `QDoubleSpinBox`, `QSlider`, `QCheckBox`, `QRadioButton`, `QProgressBar`, `QTabWidget`, `QTabBar`, `QTableWidget`, `QHeaderView`, `QListWidget`, and `QToolTip`. Use Segoe UI Variable/Segoe UI, 4–10px radii, 1px separators, 150ms-equivalent state transitions only where Qt supports them, and explicit hover/focus/pressed/disabled/checked states.

- [x] **Step 4: Install local tokens before Build UI widget import**

```python
def install_build_ui_theme() -> None:
    from build_ui import theme as build_theme

    for name in (
        "BG", "BG_ALT", "SURFACE", "SURFACE2", "BORDER", "BORDER_LT",
        "TEXT", "TEXT2", "TEXT3", "ACCENT", "ACCENT_HI", "ACCENT_TX",
        "GREEN", "GREEN_HI", "CYAN", "YELLOW", "RED",
    ):
        setattr(build_theme.C, name, getattr(C, name))
```

Change the top of `calibrate_pro/gui/app.py` to import `C`, `STYLE`, and `install_build_ui_theme` from the local module, call the installer, then import `Card`, `Heading`, `Sidebar`, `Stat`, `StatusDot`, and `ToastNotification` from `build_ui.widgets`.

- [x] **Step 5: Add a token contrast test**

Implement a small WCAG relative-luminance helper in the test module and assert `TEXT`, `TEXT2`, and `TEXT3` each reach 4.5:1 against both `BG` and `SURFACE`.

- [x] **Step 6: Run focused and existing GUI contracts**

Run:

```powershell
python -m pytest tests/test_gui_theme_contract.py tests/test_qt_binding_contract.py tests/test_gui_truthfulness.py -q
python -m py_compile calibrate_pro/gui/theme.py calibrate_pro/gui/app.py
git diff --check -- PRODUCT.md calibrate_pro/gui/theme.py calibrate_pro/gui/app.py tests/test_gui_theme_contract.py
```

Expected: all tests pass, compile succeeds, diff check is clean.

### Task 2: Add an explicit hardware-free simulated preview

**Files:**
- Modify: `calibrate_pro/gui/app.py`
- Create: `calibrate_pro/gui/preview.py`
- Create: `scripts/render_gui_preview.py`
- Create: `tests/test_gui_preview_mode.py`

**Interfaces:**
- Consumes: `QtDisplaySnapshot`, `MetricValue`, `EvidenceKind.SIMULATED`, and the active window.
- Produces: `PreviewSnapshotProvider`, `CalibrateProWindow(preview_mode: bool = False)`, a persistent “Simulated preview” banner, and a deterministic PNG renderer.

- [x] **Step 1: Write failing preview-isolation tests**

Create a test that monkeypatches USB discovery, startup-manager construction, display-service startup, tray construction, and display mutation entrypoints to raise `AssertionError`. Construct `CalibrateProWindow(preview_mode=True)` offscreen and assert construction succeeds, the banner text contains `Simulated preview` and `No hardware access`, every populated metric uses `EvidenceKind.SIMULATED` or `EvidenceKind.NOT_MEASURED`, and Apply/Calibrate mutation actions are disabled.

- [x] **Step 2: Verify RED**

Run: `python -m pytest tests/test_gui_preview_mode.py -q`

Expected: fail because the window has no preview-mode injection boundary and dashboard population currently reaches real discovery adapters.

- [x] **Step 3: Implement the deterministic preview provider**

`calibrate_pro/gui/preview.py` must expose a frozen `PreviewDisplay` dataclass and `PreviewSnapshotProvider`. Use one generic display named `Reference Display`, resolution `3840 × 2160 @ 120 Hz`, panel type `QD-OLED`, and only explicitly simulated metrics with source `bundled public preview fixture`. Use `Not measured` for any metric the fixture does not intentionally demonstrate. Do not include a manufacturer, serial, PnP ID, ICC path, user path, or real hardware identifier.

- [x] **Step 4: Inject preview mode through the window and dashboard**

Add `preview_mode: bool = False` to `CalibrateProWindow` and `DashboardPage`. In preview mode:

- do not call `_build_tray`, `_start_services`, `_update_tray_state`, `_check_first_run`, `qt_display_snapshots`, `I1D3Driver.find_devices`, or `StartupManager`;
- populate through `PreviewSnapshotProvider` only;
- show a persistent full-width banner reading `Simulated preview · bundled public fixture · no hardware access · no display changes`;
- keep navigation available for visual review, but disable any button or action that can start calibration, verification, profile activation, DDC/CI, LUT application, startup registration, or export to a user path;
- label simulated numbers in visible text, not color alone.

- [x] **Step 5: Add the deterministic preview renderer**

`scripts/render_gui_preview.py` must set `QT_QPA_PLATFORM=offscreen` before importing PySide6, construct `CalibrateProWindow(preview_mode=True)`, resize to `1440 × 900`, process events until the dashboard is populated, save a PNG to the required `--out` path, print the output path and byte size, close the window, and return nonzero if the PNG is missing or empty.

- [x] **Step 6: Render and inspect the new native surface**

Run:

```powershell
python scripts/render_gui_preview.py --out "C:\dev\scratch\calibrate-pro-native-preview.png"
python -m pytest tests/test_gui_preview_mode.py tests/test_gui_theme_contract.py tests/test_qt_binding_contract.py -q
git diff --check -- calibrate_pro/gui/app.py calibrate_pro/gui/preview.py scripts/render_gui_preview.py tests/test_gui_preview_mode.py
```

Expected: renderer returns zero with a nonempty PNG; tests pass; diff check is clean. Inspect the PNG at original resolution before accepting the task.

- [x] **Step 7: Commit the scoped product contract and UI work**

```powershell
git add calibrate_pro/gui/app.py calibrate_pro/gui/preview.py scripts/render_gui_preview.py tests/test_gui_preview_mode.py docs/superpowers/plans/2026-07-12-native-dark-workbench.md
git commit -m "feat: add Calibrate Pro simulated preview"
```
