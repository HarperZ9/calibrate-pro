# Changelog

## v1.0.0 (2026-03-22)

### Features
- **58-panel database** with DDC/CI recommendations for QD-OLED, WOLED, IPS, VA, Mini-LED, and RGB OLED panels
- **Sensorless calibration** using panel-specific characterization data and Bradford chromatic adaptation
- **Hardware calibration** via DDC/CI: brightness, contrast, RGB gain/offset, gamma
- **i1Display3 native USB driver** with CCMX spectral correction (44% dE improvement on QD-OLED)
- **3D LUT generation** (33x33x33) with 6 gamut mapping algorithms including CAM16 and Jzazbz
- **13 calibration targets**: Rec.709, DCI-P3, HDR10, Netflix SDR/HDR, EBU Grade 1, and more
- **12 verification patch sets** (287 patches): grayscale, saturation sweeps, SMPTE/EBU bars, skin tones
- **LUT export formats**: .cube, .3dl, .clf (ACES), .mga, .csp, ReShade, SpecialK, OBS, mpv, MadVR, ICC v4
- **CCSS/CCMX import** for community spectral corrections
- **CalibrationGuard** watchdog (15-second polling) prevents Windows from resetting calibration
- **DwmLutGUI integration** with automatic elevation for system-wide 3D LUT
- **PyQt6 GUI** with warm pastel theme, CIE chromaticity diagram, system tray, toast notifications
- **CLI** with 26 commands for headless calibration workflows

### Platform Support
- Windows 10/11: Full support
- macOS: Planned (stubs exist)
- Linux: Planned (stubs exist)

### Tests
- 197 tests passing
