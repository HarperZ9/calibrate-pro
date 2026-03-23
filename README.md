# Calibrate Pro

Professional display calibration for Windows. Sensorless or measured.

Calibrate Pro detects your monitors, identifies their panel characteristics from a database of 58 characterized displays, and applies color corrections via DDC/CI hardware adjustments and 3D LUTs. Works without a colorimeter (sensorless mode) or with an i1Display3 for measured accuracy with CCMX spectral correction.

## Quick Start

```bash
pip install ".[all]"
calibrate-pro
```

Double-click the exe or run without arguments to launch the GUI. For CLI:

```bash
calibrate-pro auto          # Calibrate all displays (sensorless)
calibrate-pro detect        # Show connected displays + sensors
calibrate-pro ddc-info      # Show DDC/CI capabilities per monitor
```

## How It Works

1. **Configures** monitor OSD via DDC/CI (picture mode, color preset, gamma — touch-free)
2. **Adjusts** brightness, contrast, RGB gains iteratively with colorimeter feedback
3. **Profiles** the hardware-calibrated display (per-channel TRC + primaries)
4. **Generates** a residual correction 3D LUT + ICC v4 profile
5. **Applies** system-wide via DWM 3D LUT (with VCGT gamma ramp fallback)
6. **Guards** calibration against Windows resetting it (15-second watchdog)
7. **Persists** across reboots via Windows startup / macOS launchd

## Calibration Modes

Hardware DDC/CI setup runs first in every mode, then:

| Mode | Requires | Accuracy |
|------|----------|----------|
| **Sensorless** | Nothing | Predicted dE < 1.0 (panel-database dependent) |
| **Measured** | i1Display3 | Measured dE ~3.7 (44% improvement, CCMX-corrected) |
| **Hybrid** | i1Display3 + ArgyllCMS | Measured + iterative refinement |

### Native USB Colorimeter

Built-in USB HID driver for the X-Rite i1Display3 family (i1Display Pro, ColorMunki Display, Calibrite ColorChecker Display, NEC MDSVSENSOR3). No ArgyllCMS or DisplayCAL required.

CCMX spectral correction computed from EDID vs sensor primaries — fixes the WOLED-calibrated sensor matrix for QD-OLED emission spectra.

## GUI Features

- **Dashboard**: Display cards with gamut diagrams, live sensor readout, calibration status
- **Calibration**: 3 modes, 5 target presets (sRGB Web, Rec.709, DCI-P3, HDR10, Photography), fullscreen patch measurement
- **Verification**: ColorChecker grid, grayscale tracking chart, interactive CIE 1931 diagram with zoom/pan, PDF/HTML export
- **Profiles**: Manage calibration profiles, detail view with CIE diagram, rename, activate, export
- **DDC Control**: Brightness, contrast, RGB gain/offset sliders, picture mode/color preset/gamma selectors, raw VCP read/write
- **Settings**: Per-app profile rules editor, display warm-up, tooltips on every option
- **System Tray**: Color-coded state icon (green/yellow/gray), profile switch submenu, toast notifications
- **Polish**: First-run wizard, keyboard shortcuts (Ctrl+1-6, F5, Esc), page transitions, View menu

## Commands

| Command | Description |
|---------|-------------|
| `calibrate-pro` | Launch GUI (default) |
| `calibrate-pro auto` | Calibrate all displays (sensorless + DDC) |
| `calibrate-pro detect` | Show displays, sensors, DDC capabilities |
| `calibrate-pro ddc-info` | Detailed DDC/CI capabilities per monitor |
| `calibrate-pro verify` | Verify calibration accuracy (ColorChecker) |
| `calibrate-pro status` | Show calibration age and drift status |
| `calibrate-pro native-calibrate` | Measured calibration with i1Display3 |
| `calibrate-pro ddc-calibrate` | DDC/CI hardware-first calibration |
| `calibrate-pro generate-profiles` | Generate sRGB, P3, Rec.709, AdobeRGB profiles |
| `calibrate-pro restore` | Undo calibration (reset to defaults) |
| `calibrate-pro list-panels` | Show all 58 supported panel profiles |
| `calibrate-pro patterns` | Display fullscreen test patterns |
| `calibrate-pro gui` | Launch GUI explicitly |
| `calibrate-pro tray` | Launch system tray application |

Run `calibrate-pro --help` for the full 26-command list.

## Installation

### From source

```bash
git clone <repository>
cd calibrate-pro
pip install ".[all]"
```

### Standalone (Windows)

Download `calibrate-pro/` from releases. Run `calibrate-pro.exe`. No Python required.

### Dependencies

**Required:** Python 3.10+, numpy, scipy

**Platform support:**
- **Windows 10/11** — Full support (DWM 3D LUT, VCGT, DDC/CI, ICC, calibration guard)
- **macOS** — Planned (CoreGraphics/ColorSync stubs exist, not yet functional)
- **Linux** — Planned (not yet implemented)

**Recommended:**
- [dwm_lut](https://github.com/ledoge/dwm_lut) — System-wide 3D LUT (Windows). Auto-launched with elevation.
- PyQt6 — GUI (`pip install ".[gui]"`)
- hidapi — Native i1Display3 driver (`pip install hidapi`)

## Output Files

Each calibration produces:

| File | Usage |
|------|-------|
| `.cube` | 33x33x33 3D LUT (DaVinci Resolve, OBS, any LUT app) |
| `.clf` | ACES Common LUT Format (SMPTE ST 2136-1) |
| `.icc` | ICC v4 profile (Windows/macOS color management) |
| `.3dlut` | MadVR format |
| `_reshade.png` | ReShade LUT texture |
| `_specialk.png` | Special K LUT texture |
| `_obs.cube` | OBS Studio LUT |
| `_mpv.conf` | mpv player config snippet |
| `_report.html` | Calibration report with CIE diagram, gamma curves, gamut coverage |

## Supported Displays

58 characterized panels with DDC/CI calibration recommendations:

- **QD-OLED (17)**: ASUS PG27UCDM, Samsung G6/G7/G8/G9, Dell AW3423DW/DWF/AW2725DF/AW3225QF, MSI 321URX, Philips 27E1N8900
- **WOLED (10)**: LG C2/C3/C4/G4, ASUS PG27AQDP/PG34WCDM/PG42UQ, LG 34GS95QE/27GR95QE, Corsair Xeneon
- **IPS (20)**: Dell U2723QE/U3224KB, ASUS ProArt PA279CRV/PA32UCG/PA32UCXR, BenQ PD2706U/SW271C/SW272U, EIZO CS2740/CG2700X, NEC PA271Q, HP Z27k G3, ViewSonic VP2786-4K
- **Mini-LED (4)**: ASUS PG32UCDM/PA32UCXR, Apple Pro Display XDR, AOC AG274QXM
- **VA (3)**: Samsung Odyssey G7 variants, Sony INZONE M9
- **RGB OLED (2)**: ASUS ProArt PA32DC, Philips 27E1N8900

Unknown monitors are calibrated using EDID chromaticity data.

## Architecture

```
calibrate_pro/
  core/           Color math, LUT engine (.cube/.clf/.3dl), ICC v4 profiles
  panels/         Display detection, 58-panel database with DDC recommendations
  sensorless/     Sensorless calibration engine (Oklab/JzAzBz gamut mapping)
  calibration/    Native measurement loop, CCMX spectral correction, hardware-first workflow
  hardware/       i1Display3 native USB, DDC/CI (retry + WMI fallback), warm-up monitor, drift compensation
  lut_system/     DWM 3D LUT (auto-launch), VCGT gamma ramp
  verification/   12 patch sets (287 patches), grayscale tracking, PDF export
  services/       CalibrationGuard, GamutClamp, AppSwitcher, DriftMonitor
  gui/            PyQt6 (warm pastel theme), CIE diagram, toast notifications
  platform/       Windows (full) + macOS (CoreGraphics/ColorSync/launchd)
  startup/        Boot-time calibration restoration
```

## Color Science

- **Perceptual spaces**: Oklab/Oklch, JzAzBz/JzCzhz, ICtCp, CAM16-UCS, CIE Lab/Luv
- **Transfer functions**: PQ (ST.2084), HLG (BT.2100), sRGB, BT.1886, BT.2390 EETF
- **Color spaces**: sRGB, Display P3, Rec.2020, AdobeRGB, ACES (ACEScg, ACEScc, ACEScct)
- **Gamut mapping**: Oklab perceptual compression (SDR), JzCzhz for HDR
- **Spectral correction**: CCMX from EDID primaries, CCSS/CCMX file import
- **Chromatic adaptation**: Bradford transform, D50/D65 illuminants
- **Calibration targets**: 13 standards (Rec.709, DCI-P3, HDR10, Netflix, EBU Grade 1)
- **Verification**: CIEDE2000 + CAM16-UCS, 12 patch sets (287 patches)

## License

Copyright (c) 2022-2026 Zain Dana Harper. All rights reserved. See [LICENSE](LICENSE).
