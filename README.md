# Calibrate Pro

Professional display calibration for Windows. Sensorless or measured.

Calibrate Pro detects your monitors, identifies their panel characteristics from a database of 58 characterized displays, and applies color corrections via DDC/CI hardware adjustments and 3D LUTs. Works without a colorimeter (sensorless mode) or with an i1Display3 for measured accuracy with CCMX spectral correction.

## Install

### Standalone (Windows)

Download `calibrate-pro.exe` from [Releases](https://github.com/HarperZ9/calibrate-pro/releases). Run it. No Python required. Requests admin (needed for DWM LUT and DDC/CI).

### From source

```bash
git clone git@github.com:HarperZ9/calibrate-pro.git
cd calibrate-pro
pip install -e ".[all]"
calibrate-pro
```

Requires Python 3.10+ and Windows 10/11.

## Usage

Double-click the exe or run without arguments to launch the GUI. CLI:

```bash
calibrate-pro                   # Launch GUI (default)
calibrate-pro auto              # Calibrate all displays (sensorless + DDC)
calibrate-pro detect            # Show connected displays + sensors
calibrate-pro ddc-info          # Show DDC/CI capabilities per monitor
calibrate-pro verify            # Verify calibration accuracy (ColorChecker)
calibrate-pro status            # Show calibration age and drift status
calibrate-pro native-calibrate  # Measured calibration with i1Display3
calibrate-pro restore           # Undo calibration (reset to defaults)
calibrate-pro list-panels       # Show all 58 supported panel profiles
calibrate-pro patterns          # Display fullscreen test patterns
```

Run `calibrate-pro --help` for the full 26-command list.

## How It Works

1. **Configures** monitor OSD via DDC/CI (picture mode, color preset, gamma)
2. **Adjusts** brightness, contrast, RGB gains iteratively with colorimeter feedback
3. **Profiles** the hardware-calibrated display (per-channel TRC + primaries)
4. **Generates** a residual correction 3D LUT + ICC v4 profile
5. **Applies** system-wide via DWM 3D LUT (with VCGT gamma ramp fallback)
6. **Guards** calibration against Windows resetting it (15-second watchdog)
7. **Persists** across reboots via Windows startup

## Calibration Modes

| Mode | Requires | Accuracy |
|------|----------|----------|
| Sensorless | Nothing | Predicted dE < 1.0 (panel-database dependent) |
| Measured | i1Display3 | Measured dE ~3.7 (44% improvement, CCMX-corrected) |
| Hybrid | i1Display3 + ArgyllCMS | Measured + iterative refinement |

### Native USB Colorimeter

Built-in USB HID driver for the X-Rite i1Display3 family (i1Display Pro, ColorMunki Display, Calibrite ColorChecker Display). No ArgyllCMS required.

CCMX spectral correction computed from EDID vs sensor primaries — fixes sensor matrix for QD-OLED emission spectra.

## Supported Displays

58 characterized panels with DDC/CI recommendations:

- **QD-OLED (17)**: ASUS PG27UCDM, Samsung G6/G7/G8/G9, Dell AW3423DW/DWF/AW2725DF/AW3225QF, MSI 321URX
- **WOLED (10)**: LG C2/C3/C4/G4, ASUS PG27AQDP/PG34WCDM, LG 34GS95QE
- **IPS (20)**: Dell U2723QE/U3224KB, ASUS ProArt PA279CRV, BenQ SW271C/SW272U, EIZO CS2740/CG2700X
- **Mini-LED (4)**: ASUS PG32UCDM, Apple Pro Display XDR
- **VA (3)**: Samsung Odyssey G7, Sony INZONE M9
- **RGB OLED (2)**: ASUS ProArt PA32DC

Unknown monitors are calibrated using EDID chromaticity data.

## Output Files

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

## Architecture

```
calibrate_pro/
  core/           Color math, LUT engine, ICC v4 profiles
  panels/         Display detection, 58-panel database, DDC recommendations
  sensorless/     Sensorless calibration engine (Oklab/JzAzBz gamut mapping)
  calibration/    Native measurement loop, CCMX spectral correction
  hardware/       i1Display3 native USB, DDC/CI with retry + WMI fallback
  lut_system/     DWM 3D LUT, VCGT gamma ramp, AMD/NVIDIA API
  verification/   12 patch sets (287 patches), grayscale tracking, PDF export
  services/       CalibrationGuard, GamutClamp, AppSwitcher, DriftMonitor
  gui/            PyQt6 dark theme, 8 pages, system tray
  platform/       Windows (full) + macOS (planned)
```

## Color Science

- Perceptual spaces: Oklab, JzAzBz, ICtCp, CAM16-UCS, CIE Lab/Luv
- Transfer functions: PQ (ST.2084), HLG (BT.2100), sRGB, BT.1886, BT.2390 EETF
- Color spaces: sRGB, Display P3, Rec.2020, AdobeRGB, ACES
- Gamut mapping: Oklab perceptual compression (SDR), JzCzhz for HDR
- Chromatic adaptation: Bradford transform, D50/D65 illuminants
- Verification: CIEDE2000 + CAM16-UCS, 12 patch sets (287 patches)

## Building

```bash
# From source
pip install -e ".[all]"
calibrate-pro gui

# Standalone exe
pip install pyinstaller
pyinstaller calibrate-pro.spec
# Output: dist/calibrate-pro.exe
```

## Dependencies

**Required:** Python 3.10+, numpy, scipy, quanta-color
**GUI:** PyQt6 (`pip install ".[gui]"`)
**Sensor:** hidapi (`pip install ".[sensor]"`)
**System LUT:** [dwm_lut](https://github.com/ledoge/dwm_lut) (bundled)

## License

Copyright (c) 2022-2026 Zain Dana Harper. All rights reserved.
