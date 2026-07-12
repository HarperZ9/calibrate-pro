# Changelog

## v1.1.0 (2026-07-11)

- Updated GitHub Actions workflows to current checkout/setup-python majors.
- Added the documented `test` extra so `pip install -e ".[test]"` works.
- Normalized scanner-blocking dash punctuation in public docs and developer-facing strings.
- Project Telos presentation and operator-surface pass: README hero, brand assets under `docs/brand/`, cross-flagship navigation, and Current status / Operator surface blocks.
- Documented the operator surface across the PySide6 desktop workflow and read-only CLI.
- Relicensed to the FSL-1.1-MIT as part of Project Telos flagship promotion.
- Migrated the desktop runtime and Build UI integration to PySide6.
- Added the explicit Detect -> Method -> Preview -> Apply -> Verify -> Save/Report workflow.
- Consolidated display mutation behind one confirmation-bound Windows adapter; legacy
  direct-action CLI commands are proposal-only in 1.1.
- Added immutable, SHA-256-bound apply plans, bounded inputs, prior-state capture,
  compensating recovery, authoritative read-back, and concurrency/resource-lifecycle
  gates.
- Removed automatic GUI, tray, guard, and startup actuator paths; packaged entry points
  launch unelevated.
- Added measured/estimated/simulated/replayed/Not measured provenance throughout the GUI
  and report paths; removed seeded or unsupported observations.
- Added read-only `doctor` diagnostics with stable JSON output.
- Added hash-locked Windows builds, exact frozen-module auditing, third-party notices and
  source provenance, PE-manifest checks, per-user installer/portable packaging, and
  frozen smoke/reproducibility verification.

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
