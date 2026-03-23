# Calibrate Pro — UI/UX Roadmap

## Current State

A functional but minimal GUI: sidebar navigation, dashboard with real display detection, proper color palette (navy + olive), custom app icon, menu bar with connected actions. Five placeholder pages. The backend has 82K lines of proven calibration logic, native colorimeter communication, and 24 CLI commands — none of which are accessible through the GUI yet.

The gap: the backend is professional-grade, the frontend is a skeleton.

---

## Design Principles

1. **Show, don't configure.** The dashboard should tell you everything at a glance. Calibration status, gamut coverage, white point, last calibration date — visible without clicking anything.

2. **One-click primary action.** The most common task (calibrate this display) should be one button press. Advanced options exist but don't clutter the default path.

3. **Real-time feedback.** When the colorimeter is connected, show live readings. When calibration is running, show progress with actual measurements appearing in real time.

4. **Respect the user's expertise.** This audience knows what Delta E means. Don't hide technical data behind "simple mode" toggles. Show the numbers, the chromaticity diagram, the gamma curves — but lay them out clearly.

5. **Dark environment aware.** Calibration is done in controlled lighting. The UI should never blow out the user's adapted vision with bright elements. All whites are off-white. All accents are muted.

---

## Phase 1: Dashboard That Tells a Story

The dashboard is what the user sees 90% of the time. It needs to communicate the full state of their display setup at a glance.

### 1.1 Display Cards (Enhanced)
Each display card should show:
- [ ] Display name + panel type + resolution (already done)
- [ ] **CIE xy chromaticity mini-diagram** (60x60px) showing the panel's gamut triangle
- [ ] **Gamut coverage bar** — sRGB/P3/BT.2020 as a compact horizontal bar
- [ ] **White point indicator** — measured CCT with a warm/cool visual scale
- [ ] **Calibration age** — "Calibrated 2 hours ago" or "Never calibrated"
- [ ] **Delta E badge** — the measured or predicted accuracy, color-coded
- [ ] **Quick actions** — Calibrate / Verify / Profile dropdown, right-aligned

### 1.2 Colorimeter Panel
When a colorimeter is connected:
- [ ] **Live XYZ readout** updating every 500ms
- [ ] **Live luminance** in cd/m2
- [ ] **Live CCT** with color temperature visualization
- [ ] **Sensor info** — model, serial, firmware
- [ ] **"Measure" button** — single spot measurement

When no colorimeter:
- [ ] Clean "No sensor connected" with a subtle illustration
- [ ] Link to supported sensors list

### 1.3 System Status Bar (bottom)
- [ ] Current active LUT method (DWM/VCGT/None)
- [ ] HDR mode (on/off per display)
- [ ] Auto-start status (enabled/disabled)
- [ ] Per-app profile switcher status

---

## Phase 2: Calibration Page

The core workflow. Should guide the user from start to finish while showing everything that's happening.

### 2.1 Mode Selection
- [ ] **Sensorless** — instant, panel-database calibration (default)
- [ ] **Measured** — colorimeter-assisted with iterative refinement
- [ ] **Hybrid** — sensorless + measured verification

### 2.2 Target Selection
- [ ] **Target gamut** — Native (default) / sRGB / DCI-P3 / Rec.709 / AdobeRGB
- [ ] **Target white point** — D65 / D50 / Custom CCT slider
- [ ] **Target gamma** — 2.2 / 2.4 / sRGB / BT.1886 / PQ
- [ ] **Target luminance** — slider with cd/m2 readout
- [ ] Preset buttons: "sRGB Web" / "Rec.709 Broadcast" / "DCI-P3 Cinema" / "HDR10"

### 2.3 Calibration Progress
- [ ] **Step-by-step progress** with animated transitions
- [ ] **Live measurement display** — when colorimeter is connected, show each patch measurement as it happens
- [ ] **Before/after comparison** — split-screen or overlay showing the correction being applied
- [ ] **Real-time Delta E** — updating as each ColorChecker patch is measured

### 2.4 Results Summary
- [ ] **Full ColorChecker results table** with color swatches
- [ ] **CIE diagram** showing measured vs target
- [ ] **Gamma tracking chart**
- [ ] **Generated files list** with one-click open/copy path
- [ ] **"Apply" / "Save" / "Export" buttons**

---

## Phase 3: Verification Page

Show calibration accuracy with measured data when available.

### 3.1 ColorChecker Grid
- [ ] **Visual grid** of 24 patches — each showing reference color, measured color, and Delta E
- [ ] **Click a patch** to see detailed Lab values, XYZ, and per-channel error
- [ ] **Pass/Warn/Fail** color coding

### 3.2 Grayscale Tracking
- [ ] **Interactive gamma curve chart** — target line vs measured points
- [ ] **Per-step luminance table** with Delta E per step
- [ ] **Near-black detail** — expanded view of 0-10% range

### 3.3 Gamut Visualization
- [ ] **Interactive CIE 1931 diagram** — zoom, pan, hover for coordinates
- [ ] **Gamut coverage numbers** — 2D area + 3D volume side by side
- [ ] **Per-lightness gamut chart** — bar chart showing gamut width at each L* level

### 3.4 Report Export
- [ ] **HTML report** (already exists, wire the button)
- [ ] **PDF export** via system print dialog
- [ ] **Copy summary to clipboard** for pasting in Discord/forums

---

## Phase 4: Profiles Page

Manage calibration profiles, switch between targets.

### 4.1 Profile List
- [ ] **Card per profile** showing target, display, creation date, file sizes
- [ ] **Active profile indicator** (green dot)
- [ ] **One-click activate** — applies the LUT immediately

### 4.2 Profile Details
- [ ] Selecting a profile shows its CIE diagram, gamma curves, white point
- [ ] **Export buttons** for each format (cube, 3dlut, png, icc, mpv, obs)
- [ ] **Delete / Rename / Duplicate**

### 4.3 Multi-Profile Generation
- [ ] **"Generate All" button** — creates sRGB + P3 + Rec.709 + AdobeRGB profiles in one pass
- [ ] Progress indicator for batch generation

---

## Phase 5: DDC Control Page

Direct hardware control of the monitor via DDC/CI.

### 5.1 Common Controls
- [ ] **Brightness slider** with live DDC write
- [ ] **Contrast slider**
- [ ] **RGB Gain sliders** (red/green/blue) with live preview
- [ ] **RGB Offset sliders**
- [ ] **Color preset selector** (6500K / 9300K / User / sRGB / etc.)

### 5.2 Advanced
- [ ] **VCP code scanner** — discover all supported codes
- [ ] **Raw VCP read/write** — for power users
- [ ] **Preset save/load** — save DDC settings as named presets

---

## Phase 6: Settings Page

Application configuration.

### 6.1 General
- [ ] **Start with Windows** toggle
- [ ] **Minimize to tray** toggle
- [ ] **Per-app profile switching** toggle + app rules editor
- [ ] **Default calibration target** selector

### 6.2 Calibration
- [ ] **Default LUT size** (17/33/65)
- [ ] **OLED compensation** toggle
- [ ] **Integration time** for colorimeter
- [ ] **Measurement settle time**

### 6.3 Paths
- [ ] **Output directory** for calibration files
- [ ] **ArgyllCMS path** override
- [ ] **Plugin directory**

### 6.4 About
- [ ] Version, build date, license
- [ ] Color science credits (Oklab, JzAzBz, CAM16 papers)
- [ ] Link to documentation

---

## Phase 7: System Tray

Background operation without the main window.

- [ ] **Icon color** reflects state: olive=calibrated, gray=uncalibrated, amber=stale
- [ ] **Right-click menu**: Show Window / Calibrate All / Switch Profile submenu / HDR Toggle / Restore / Exit
- [ ] **Left-click** opens/focuses the main window
- [ ] **Tooltip** shows current calibration status per display
- [ ] **Notification** when calibration drifts past threshold

---

## Phase 8: Polish

### 8.1 Animations
- [ ] Page transitions (subtle fade or slide)
- [ ] Progress bars with smooth animation
- [ ] Card hover effects (slight elevation/border change)

### 8.2 Keyboard Shortcuts
- [ ] Ctrl+1 through Ctrl+6 for page navigation
- [ ] Ctrl+Shift+C for Calibrate All
- [ ] F5 for Refresh
- [ ] Escape to minimize to tray

### 8.3 High DPI
- [ ] Test and fix at 100%, 125%, 150%, 200% scaling
- [ ] Icon rendering at all DPI levels

### 8.4 Error Handling
- [ ] Toast notifications instead of modal QMessageBox for non-critical errors
- [ ] Inline error states on cards (red border, error message) instead of popups
- [ ] Graceful degradation when backend modules aren't available

### 8.5 First-Run Experience
- [ ] Welcome screen on first launch
- [ ] Auto-detect displays and offer to calibrate
- [ ] If colorimeter is connected, highlight the "Measured" option

---

## What We Don't Build in the GUI

- **A color grading tool.** We don't add RGB wheels, color curves, or creative LUT editing. That's Resolve's job.
- **A monitor test suite.** We don't measure response time, input lag, or uniformity mapping in the GUI. Those are CLI tools for power users.
- **A settings labyrinth.** Every setting that can have a sane default should have one. The settings page is for overrides, not configuration.

---

## Priority Order

1. **Dashboard enhanced** (Phase 1) — this is what sells the tool on first impression
2. **Calibration page** (Phase 2) — the core workflow must be excellent
3. **System tray** (Phase 7) — the tool should live in the background
4. **Verification page** (Phase 3) — proof that calibration works
5. **Profiles page** (Phase 4) — switching between targets
6. **DDC Control** (Phase 5) — hardware control
7. **Settings** (Phase 6) — last, because defaults should work
8. **Polish** (Phase 8) — ongoing, never "done"
