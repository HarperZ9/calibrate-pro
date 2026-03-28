# Calibrate Pro v1.0.0

Professional display calibration for Windows. Sensorless or measured.

## Download

- **calibrate-pro.exe** (233 MB) — Standalone Windows executable. No Python required. Requests admin for DWM LUT and DDC/CI access.

## What's Included

### Calibration Modes
- **Sensorless**: Calibrate any of 58 characterized displays without hardware. Predicted dE < 1.0.
- **Measured**: Native USB driver for i1Display3 family with CCMX spectral correction. Measured dE ~3.7 (44% improvement over uncorrected).
- **Hybrid**: Measured + iterative refinement via ArgyllCMS.

### Hardware Control
- DDC/CI monitor control (brightness, contrast, RGB gains, color presets, gamma)
- Automatic OSD configuration before calibration
- 58-panel database with per-display DDC/CI recommendations

### Output
- 3D LUT (.cube, .clf, .3dlut) for DaVinci Resolve, OBS, MadVR
- ICC v4 profiles for Windows color management
- ReShade/Special K LUT textures (.png)
- mpv player config, OBS LUT
- HTML calibration report with CIE diagram and gamma curves

### GUI
- 8-page dark-themed interface (Dashboard, Calibrate, Verify, Profiles, VCGT Tools, Color Control, DDC Control, Settings)
- System tray with color-coded status icon
- Keyboard shortcuts (Ctrl+1-6, F5, Esc)

### System Integration
- DWM 3D LUT (system-wide, via bundled dwm_lut)
- VCGT gamma ramp fallback
- CalibrationGuard watchdog (re-applies every 15 seconds)
- Persists across reboots via Windows startup

## Supported Displays

58 characterized panels: QD-OLED (17), WOLED (10), IPS (20), Mini-LED (4), VA (3), RGB OLED (2). Unknown monitors calibrated via EDID chromaticity.

## Requirements

- Windows 10/11
- Admin rights (for DWM LUT and DDC/CI)
- Optional: i1Display3 for measured calibration

## Known Limitations

- Windows only (macOS/Linux planned)
- QD-OLED spectral correction requires EDID with valid chromaticity data
- Some monitors have limited DDC/CI support (ASUS ROG series fully tested)
