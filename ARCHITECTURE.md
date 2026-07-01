# Architecture

Calibrate Pro is a Windows display-calibration toolkit. It detects monitors, identifies
their panel characteristics, computes color corrections, applies them system-wide, and
verifies the result. The package is organized into focused layers, each owning one stage
of that pipeline. The pure-Python color and calibration science is type-checked and
tested; the layers that talk to native Windows/GPU/USB APIs are boundary code.

## Package layout

```
calibrate_pro/
  core/           Color math, LUT engine, ICC v4 profiles, ACES, color models, VCGT
  panels/         Display detection, the characterized-panel database, DDC recommendations
  sensorless/     Sensorless calibration engine (Oklab / JzAzBz gamut mapping)
  calibration/    Native measurement loop, CCMX spectral correction, CCSS import
  verification/   Patch sets, grayscale tracking, CIEDE2000 / CAM16-UCS grading, reports
  profiles/       Profile persistence and management
  hdr/            HDR detection, mastering standards, PQ/HLG handling
  services/       CalibrationGuard, GamutClamp, AppSwitcher, DriftMonitor (watchdogs)
  advanced/       Ambient light, automation, network calibration, uniformity, LUT optimization
  lut_system/     DWM 3D LUT, VCGT gamma ramp, AMD/NVIDIA GPU APIs (OS/GPU driver adapter)
  hardware/       i1Display3 native USB HID, DDC/CI with retry + WMI fallback (native adapter)
  platform/       Windows (full) + macOS (planned) OS integration (native adapter)
  gui/            PyQt6 dark-theme GUI, 8 pages, system tray (GUI adapter)
  app.py, main.py Application shell + CLI entry point
```

## Data flow

```
detect            panels/ + hardware/ (DDC-CI) enumerate displays and capabilities
  -> characterize panels/ matches the display against the panel database (or EDID chromaticity)
  -> profile       core/ + calibration/ derive per-channel TRC + primaries
                   (sensorless from the model, or measured via the i1Display3 loop + CCMX)
  -> correct       core/ builds a residual 3D LUT + ICC v4 profile
  -> apply         lut_system/ installs the LUT via DWM (VCGT gamma-ramp fallback)
  -> guard         services/ watches for Windows resetting the calibration (watchdog)
  -> verify        verification/ measures against patch sets and reports CIEDE2000 / CAM16-UCS
```

## Key design decisions

- **Sensorless vs measured are distinct paths, and the difference is stated honestly.**
  Sensorless calibration is a prediction from the panel-database model (no ground truth on
  the specific unit); the only measured-accuracy figure the tool reports is from the
  i1Display3 path. The two are never conflated in output.
- **DWM 3D LUT with a VCGT fallback.** System-wide correction prefers the DWM 3D LUT path
  and falls back to a VCGT gamma ramp where DWM injection is unavailable.
- **Native i1Display3 USB HID.** The colorimeter is driven directly over USB HID, reading
  per-unit calibration matrices from device EEPROM; no ArgyllCMS dependency is required.
- **Boundary-typed adapters.** `lut_system`, `hardware`, `platform`, `gui`, and the `app`
  shell interface untyped native Windows/GPU/Qt/USB libraries. They are checked at their
  public boundary; the color/calibration/verification science core is strict-typed.

## Operator surfaces

- A 26-command `calibrate-pro` CLI (`detect`, `auto`, `ddc-info`, `verify`, `status`,
  `native-calibrate`, `restore`, `list-panels`, `patterns`, …).
- An 8-page PyQt6 GUI (default when launched with no arguments).
- The Project Telos `telos.display.calibration` MCP contract, so a host agent can request
  a calibration, read the verification report, and recheck drift through the shared
  action envelope. CLI and MCP expose the same surface.

## Testing

`tests/` covers color-math round-trips, the auto-calibration path, the panel database, the
LUT engine, verification grading, HDR workflow, the native loop, platform behavior, and
professional features. `ruff check .`, `mypy`, and `pytest --cov` gate every change.
