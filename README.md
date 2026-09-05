<p align="center">
  <img src="https://raw.githubusercontent.com/HarperZ9/calibrate-pro/v1.1.0/docs/brand/calibrate-pro-hero.png" alt="Calibrate Pro, make screens match the work with profiles, LUTs, and verification">
</p>
<!-- Project mark: docs/brand/calibrate-pro-mark.svg -->

# Calibrate Pro

> Make screens match the work with profiles, LUTs, monitor control, and verification reports.

[Project Telos](https://harperz9.github.io) | [gather](https://github.com/HarperZ9/gather) | [crucible](https://github.com/HarperZ9/crucible) | [index](https://github.com/HarperZ9/index) | [forum](https://github.com/HarperZ9/forum) | [telos](https://github.com/HarperZ9/telos) | [calibrate-pro](https://github.com/HarperZ9/calibrate-pro)

[![license: fair-source](https://img.shields.io/badge/license-fair--source-blue.svg)](https://github.com/HarperZ9/calibrate-pro/blob/v1.1.0/LICENSE)
![python](https://img.shields.io/badge/python-3.10%2B-blue.svg)
![version](https://img.shields.io/badge/version-1.1.0-informational.svg)
[![CI](https://github.com/HarperZ9/calibrate-pro/actions/workflows/ci.yml/badge.svg)](https://github.com/HarperZ9/calibrate-pro/actions/workflows/ci.yml)
[![part of: Project Telos](https://img.shields.io/badge/part_of-Project_Telos-4636e8.svg)](https://harperz9.github.io)

Calibrate Pro is a Windows display-calibration toolkit for characterized and measured workflows. It combines display discovery, calibration targets, DDC/CI, ICC/VCGT and LUT tooling, and evidence-labelled reports behind one preview-and-confirm workflow. Sensorless values are explicitly labelled as estimates; measured values require an instrument and retain their evidence source.

## Try it

```bash
calibrate-pro doctor
calibrate-pro detect
calibrate-pro status
calibrate-pro gui
```

Install from the Windows release build or run from source with `pip install -e ".[all]"`. Those four names answer in both. The packaged binary ships a subset of the command line and refuses the rest by saying they are in the developer wheel, so the two lists are kept apart under [Usage](#usage) rather than presented as one surface.

## Why it matters

Display color is part of the creative pipeline. If the screen is wrong, every design, render, photo, video grade, and model-generated visual can be judged against a bad reference. Calibrate Pro gives a practical path to better display behavior, records what changed, and keeps verification close to the profile.

## What to test first

The terminal reads and plans, and it writes only files you name. A display change is
proposed by the window and by nothing else.

- Run `calibrate-pro detect` for the displays this machine presents and the source of each characterization.
- Run `calibrate-pro status` for the actions this session can run, each closed one carrying the reason it is closed.
- Run `calibrate-pro verify --target srgb_web` to generate a sealed plan and read its predicted accuracy. The figures are estimated from the panel characterization, and the command prints that beneath them.
- Launch `calibrate-pro gui`, select a display, and inspect the detected identity and available capabilities.
- Choose a method and target, then review the exact plan before deciding whether to confirm any supported display change.
- Complete the GUI workflow and inspect the evidence-labelled result or report; values remain estimated or **Not measured** unless they came from an instrument.

## Current status

- **Release:** Calibrate Pro 1.1.0; command `calibrate-pro`; Python 3.10+ on Windows 10/11; per-user installer and portable package.
- **Operator surface:** a PySide6 desktop workflow, a headless session that detects, plans, and publishes sealed bundles, and read-only CLI diagnostics, target and panel listings, HDR status, and plugin discovery. Legacy mutation-capable CLI names are proposal-only and point to the window rather than changing display state.
- **Safety boundary:** Detect -> Method -> Preview -> Apply -> Verify -> Save/Report. The application starts unelevated. A display change requires an exact preview and explicit confirmation; rejection performs no write.
- **Evidence boundary:** reports distinguish measured, estimated, simulated, replayed, and Not measured values instead of presenting model output as an observation.

## Install

### Standalone (Windows)

Download the per-user installer or portable ZIP from [Releases](https://github.com/HarperZ9/calibrate-pro/releases). No Python installation is required. Both desktop entry points start unelevated; unavailable hardware or operating-system capabilities fail closed and are reported by `calibrate-pro doctor`.

The 1.1.0 Windows artifacts are not Authenticode-signed, so Windows may show a SmartScreen warning. Verify the downloaded file against the release's `SHA256SUMS.txt` before running it.

### From source

```bash
git clone git@github.com:HarperZ9/calibrate-pro.git
cd calibrate-pro
pip install -e ".[all]"
calibrate-pro
```

Requires Python 3.10+ and Windows 10/11.

## Usage

Launch the installed application or run `calibrate-pro gui`. The calibration session runs headless over the same actions the window calls:

```bash
calibrate-pro detect                                  # Displays observed, with characterization sources
calibrate-pro status --closed                         # Actions this session cannot run, and why
calibrate-pro verify --target srgb_web                # Sealed plan and its predicted accuracy
calibrate-pro generate-profiles out --target srgb_web # Publish one sealed bundle into 'out'
calibrate-pro profiles out                            # Re-check the seal on published bundles
calibrate-pro diagnostics                             # List what a support bundle would carry
calibrate-pro doctor                                  # Read-only installation and capability diagnostics
calibrate-pro doctor --json                           # Stable machine-readable diagnostics
calibrate-pro hdr                                     # Open the HDR proposal application
calibrate-pro gui                                     # Launch the calibration workflow
```

`CalibrateProCLI.exe` answers every name above, so a headless run needs no Python installation.

These names exist only in the developer wheel, and the packaged binary answers each of them with `This command is available only in the developer wheel` and exit code 2:

```bash
calibrate-pro list-targets      # List calibration targets
calibrate-pro list-panels       # List characterized panel profiles
calibrate-pro info <panel>      # Show stored characterization evidence
calibrate-pro hdr-status        # Query Windows HDR state
calibrate-pro plugins           # List discovered plugins
calibrate-pro tray              # Open the read-only system tray
calibrate-pro mcp               # Serve the MCP endpoint
```

The split is a packaging decision recorded in `packaging/frozen-features.json`, and a name in neither half reaches an operator as an unknown command. Run `calibrate-pro --help` for the complete command list. Old direct-action names such as `auto`, `calibrate`, and `restore` remain proposal-only in 1.1: they do not mutate the display and instead direct the operator to preview and confirm through the window.

See the [usage guide](https://github.com/HarperZ9/calibrate-pro/blob/v1.1.0/USAGE.md) for installation, command behavior, evidence labels, troubleshooting, and the [read-only example](https://github.com/HarperZ9/calibrate-pro/tree/v1.1.0/examples).

## How It Works

1. **Detects** the selected display and reports available capabilities.
2. **Chooses** a sensorless or measured method and calibration target.
3. **Previews** an immutable plan, including bounded DDC changes and SHA-256-bound external assets.
4. **Confirms** the exact plan with a one-use confirmation before the first write.
5. **Applies** only supported operations after capturing restorable prior state; failures trigger verified compensation.
6. **Verifies** the result and labels every performance value by evidence kind.
7. **Saves** the approved profile, LUT, and/or report. Background guard behavior is monitor-and-notify only in 1.1.

## Calibration Modes

| Mode | Requires | Evidence |
|------|----------|----------|
| Sensorless | A characterized panel profile or EDID-derived inputs | Estimated; never presented as a measurement of the attached unit |
| Measured | A supported colorimeter | Closed in 1.1. See below. |

Without a colorimeter there is no measurement of the attached unit. Calibrate Pro therefore renders unavailable observations as **Not measured** and labels model-derived diagnostics as **estimated**.

**Measured calibration is closed in 1.1.** The action manifest declares `calibration.method.measured` and `verification.measured` disabled in the wheel and in the frozen binary alike, for the reason it prints when asked: measured calibration is disabled pending a distinct qualified measurement contract. No setting opens it. `calibrate-pro status --closed` reports it, the method control in the window is disabled rather than hidden, and `native-calibrate` and `refine` decline at the terminal and name that action. Everything 1.1 produces is sensorless, and it is labelled estimated.

### Native USB colorimeter driver

The package carries a USB HID driver for the X-Rite i1Display3 family (i1Display Pro, ColorMunki Display, Calibrite ColorChecker Display), which reads each unit's own calibration matrices from its EEPROM and needs no ArgyllCMS install. The device holds nine matrices for different display technologies, and the driver falls back to approximate constants when the EEPROM read fails.

No surface in 1.1 opens it. It is the implementation measured calibration will use once that contract exists, and until then it is code the release ships rather than a capability an operator can reach. Nothing in the window or the terminal enumerates or opens a colorimeter, so no product screen reports a device that the session never observed.

## Supported Displays

59 characterized panels with DDC/CI recommendations:

- **QD-OLED (17)**: ASUS PG27UCDM, Samsung G6/G7/G8/G9, Dell AW3423DW/DWF/AW2725DF/AW3225QF, MSI 321URX
- **WOLED (10)**: LG C2/C3/C4/G4, ASUS PG27AQDP/PG34WCDM, LG 34GS95QE
- **IPS (21)**: Dell U2723QE/U3224KB, ASUS ProArt PA279CRV, BenQ SW271C/SW272U, EIZO CS2740/CG2700X
- **Nano-IPS (2)**: LG UltraGear 27GP950-B, LG UltraGear 27GP850-B
- **Mini-LED (4)**: ASUS PG32UCDM, Apple Pro Display XDR
- **VA (3)**: Samsung Odyssey G7, Sony INZONE M9
- **OLED (2)**: ASUS ProArt PA32DC

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
  gui/            PySide6 desktop workflow and read-only system tray
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

# Reproducible Windows release (locked dependencies and release gates)
powershell -File scripts/build_windows.ps1
```

## Dependencies

**Required:** Python 3.10+, numpy, scipy, build-color
**GUI:** PySide6 + QtPy + Build UI 2 (`pip install ".[gui]"`)
**Sensor:** hidapi (`pip install ".[sensor]"`)
**Windows distribution:** includes the audited runtime dependencies and notices required by the release manifest, including the approved `dwm_lut` runtime files.

## License

FSL-1.1-MIT. Copyright (c) 2022-2026 Zain Dana Harper. Source-available, not open source: read it, run it, and build on it; commercial Competing Use is reserved to the Licensor to fund continued development. See the [license](https://github.com/HarperZ9/calibrate-pro/blob/v1.1.0/LICENSE).

## For developers

Keep the public README, package metadata, and examples aligned with current behavior. Before opening a PR or pushing a release, run the local package verification path.

```bash
python -m pip install -e ".[test]"
python -m pytest
```

---

**[Zentropy Labs](https://github.com/ZentropyLabs-ai)** · order out of entropy. An independent lab building evidence-first tools that leave a re-checkable artifact behind. Built by Zain Dana Harper in Seattle. The full workbench is at [Project Telos](https://harperz9.github.io).
