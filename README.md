<picture>
  <source media="(prefers-color-scheme: dark)" srcset="https://raw.githubusercontent.com/HarperZ9/calibrate-pro/v2.0.1/docs/art/hero-dark.svg">
  <img src="https://raw.githubusercontent.com/HarperZ9/calibrate-pro/v2.0.1/docs/art/hero-light.svg" alt="calibrate-pro: display calibration for Windows. Parallel rays pass through a lens drawn in fine lines, gather at a bright core and spread out past it." width="100%">
</picture>

# calibrate-pro

Calibrate a Windows monitor with or without a colorimeter. Calibrate Pro builds an ICC profile and a 3D LUT for the target you choose, adjusts the monitor's own controls over DDC/CI, and marks each accuracy figure as measured or estimated.

[![version: 2.0.1](https://img.shields.io/badge/version-2.0.1-e6e1d6?style=flat-square&labelColor=1a1712)](https://github.com/HarperZ9/calibrate-pro/releases/latest)
[![CI](https://github.com/HarperZ9/calibrate-pro/actions/workflows/ci.yml/badge.svg)](https://github.com/HarperZ9/calibrate-pro/actions/workflows/ci.yml)
[![license](https://img.shields.io/badge/license-FSL--1.1--MIT-e6e1d6?style=flat-square&labelColor=1a1712)](https://github.com/HarperZ9/calibrate-pro/blob/main/LICENSE)
![python 3.10+](https://img.shields.io/badge/python-3.10%2B-e6e1d6?style=flat-square&labelColor=1a1712)

## Try it

```bash
pip install "calibrate-pro[gui]"
calibrate-pro doctor
calibrate-pro detect
calibrate-pro verify --target srgb_web
calibrate-pro gui
```

`doctor` checks the install and probes no hardware. `detect` lists your displays and says whether each one matched a record in the panel database. `verify` builds a correction toward sRGB in memory and prints the predicted error before and after it, in dE2000. If `detect` reports `no_panel_match`, add `--edid` to build from the primaries and gamma your monitor declares about itself, or `--generic` for a nominal sRGB record. None of these four commands changes your display. `gui` opens the desktop window, which is where a correction gets applied.

You need Python 3.10 or newer on Windows 10 or 11. Without `[gui]`, `doctor` reports the missing Qt binding and the window will not start. Add `[sensor]` for colorimeter support.

## What it does

- **Calibrates without an instrument.** The panel database holds characterizations for 58 monitor models. For a monitor it does not list, Calibrate Pro can use the primaries and gamma from the monitor's EDID. Every result from this path is labelled *estimated*, because the numbers describe the model of monitor and say nothing certain about the unit on your desk.
- **Calibrates with an instrument.** A built-in USB driver reads the X-Rite i1Display3 family (i1Display Pro, ColorMunki Display, Calibrite ColorChecker Display) with no ArgyllCMS install. A measured run happens in the window. It refuses to start while a gamma-table correction is already loaded on the display.
- **Targets.** Presets for sRGB, Rec.709 (BT.1886), DCI-P3 and a D50 photography target. You can also compose a target from 11 gamuts, a white point and a tone response; `calibrate-pro list-targets` prints them.
- **Output.** Each calibration writes an ICC v4 profile, a 33-point `.cube` 3D LUT, and a manifest of SHA-256 hashes. `calibrate-pro profiles <dir>` re-reads the manifest and reports any file that changed since it was written.
- **Applying a correction.** The window shows the exact plan and asks you to confirm it. It saves the display's prior state first so the change can be undone. In 2.0.1 it applies the per-channel gamma-ramp part of a correction and attaches the ICC profile. It does not apply a system-wide 3D LUT yet, so a gamut correction stays a `.cube` file for applications that load LUTs, such as DaVinci Resolve or OBS.
- **Monitor controls over DDC/CI.** Read and set brightness, contrast, RGB gain and RGB black level, each checked against the range the monitor reports. `ddc-calibrate` stages the change and writes only with `--confirm`.
- **Windows colour management.** List, install, switch and remove ICC profiles per display. Each command that writes needs `--confirm`. On the Windows 11 Insider build 26220 used to test this README, reading the profile store failed, so these commands stopped before writing anything.
- **Test patterns.** Ten full-screen patterns, PLUGE, white clip, grey ramp and colour bars among them, for setting brightness and contrast by eye.

Calibrate Pro runs on Windows only. HDR calibration is not available in 2.0.1: `calibrate-pro hdr` opens a window that prepares an HDR target, and the HDR presets in the calibration workflow stay disabled.

## Who it is for

It suits people with a wide-gamut or OLED monitor who want sRGB and video content to look as intended. Photographers and editors get an ICC profile with a plain record of which figures came from an instrument. If you own a colorimeter and need many instrument types, or macOS and Linux, DisplayCAL covers more ground.

## How it compares

- **DisplayCAL with ArgyllCMS.** Free and open source, runs on Windows, macOS and Linux, and supports many more instruments. It needs an instrument. Calibrate Pro adds a sensorless mode and DDC/CI control, and supports one instrument family on Windows.
- **Calman and LightSpace.** Commercial suites for studio and broadcast calibration, with broad instrument and pattern-generator support. Calibrate Pro does not aim at that workflow.
- **novideo_srgb and GPU driver sRGB clamps.** These clamp a wide-gamut monitor to sRGB from its EDID primaries through the graphics driver. Calibrate Pro's sensorless mode starts from the same kind of data. It writes a profile and LUT you can inspect and reports the predicted error.
- **Windows HDR Calibration.** Microsoft's app builds an HDR profile for Windows 11. Calibrate Pro 2.0.1 does not calibrate HDR.

## Step by step

- Run `calibrate-pro detect` for the displays this machine presents and the source of each characterization.
- Run `calibrate-pro status` for the actions this session can run, with the reason each unavailable one is unavailable.
- Run `calibrate-pro verify --target srgb_web` to see the predicted error with no correction beside the error the generated correction leaves. Both figures are estimated from the panel characterization, and the command says so.
- Run `calibrate-pro generate-profiles out --target srgb_web` to write the profile, LUT and manifest into `out` (add `--edid` or `--generic` here too for an unlisted monitor), then `calibrate-pro profiles out` to check them.
- Launch `calibrate-pro gui`, select a display, and inspect the detected identity and available capabilities.
- Choose a method and target, then review the exact plan before deciding whether to confirm any display change.
- Read the result. Values stay estimated or **Not measured** unless they came from an instrument.

The [animated explainer](https://harperz9.github.io/repo-explainers/calibrate-pro.html) walks through the same steps with output from this repository. Its source is [docs/explainer/index.html](docs/explainer/index.html).

### Reporting what you find

Open a [bug report](https://github.com/HarperZ9/calibrate-pro/issues/new?template=bug_report.yml)
when the product did something other than what it said it would do, or a
[display compatibility report](https://github.com/HarperZ9/calibrate-pro/issues/new?template=display_report.yml)
for what worked and what refused on a specific monitor. A control that refused on a monitor
that advertises it is worth reporting. So is a number that reads as a measurement when nothing
was measured.

Both forms ask for `calibrate-pro doctor --json`. It reports installed versions and which
capabilities are present, probes no hardware, and reads no display identity. Report a suspected
vulnerability through [Security Advisories](https://github.com/HarperZ9/calibrate-pro/security/advisories/new),
where it stays private until a fix is out.

## Install

- **Release:** Calibrate Pro 2.0.1; command `calibrate-pro`; Python 3.10+ on Windows 10/11; PyPI package, per-user installer and portable ZIP.
- **Interfaces:** a PySide6 desktop window, and terminal commands that detect, plan, write calibration files and run the confirm-gated changes listed under [Usage](#usage).
- **Workflow:** Detect -> Method -> Preview -> Apply -> Verify -> Save/Report. The application starts unelevated. A display change needs an exact preview and explicit confirmation, and declining writes nothing. Old one-step command names such as `calibrate` and `auto` are proposal-only and point to the window.

### From PyPI

```bash
pip install "calibrate-pro[gui]"
calibrate-pro doctor
```

Use `"calibrate-pro[gui,sensor]"` to add colorimeter support.

### Standalone (Windows)

Download the per-user installer or portable ZIP from [Releases](https://github.com/HarperZ9/calibrate-pro/releases). No Python installation is required. Both desktop entry points start unelevated, and `calibrate-pro doctor` reports any hardware or operating-system capability that is missing.

The 2.0.1 Windows artifacts are not Authenticode-signed, so Windows may show a SmartScreen warning. Verify the downloaded file against the release's `SHA256SUMS.txt` before running it.

### From source

```bash
git clone https://github.com/HarperZ9/calibrate-pro.git
cd calibrate-pro
pip install -e ".[all]"
calibrate-pro gui
```

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
calibrate-pro list-targets                            # Targets a calibration can be aimed at, and the axes behind them
calibrate-pro doctor --json                           # Stable machine-readable diagnostics
calibrate-pro hdr                                     # Open the HDR target window
calibrate-pro ddc-info                                # Read the monitor's own controls over DDC/CI
calibrate-pro ddc-calibrate --brightness 40           # Stage a DDC/CI change; add --confirm to write it
calibrate-pro system-profiles                         # Read what Windows colour management holds for a display
calibrate-pro install-profile out                     # Stage a profile install; add --confirm to write it
calibrate-pro patterns                                # List the test patterns
calibrate-pro show-pattern pluge                      # Hold one pattern full screen until Escape
calibrate-pro gui                                     # Launch the calibration workflow
```

`CalibrateProCLI.exe` answers every name above, so a headless run needs no Python installation.

These names exist only in the developer wheel, and the packaged binary answers each of them with `This command is available only in the developer wheel` and exit code 2:

```bash
calibrate-pro list-panels       # List characterized panel profiles
calibrate-pro info <panel>      # Show stored characterization evidence
calibrate-pro hdr-status        # Query Windows HDR state
calibrate-pro plugins           # List discovered plugins
calibrate-pro tray              # Open the read-only system tray
calibrate-pro mcp               # Serve the MCP endpoint
```

The split is a packaging decision recorded in `packaging/frozen-features.json`, and a name in none of its lists reaches an operator as an unknown command. Run `calibrate-pro --help` for the complete command list.

Old direct-action names such as `auto`, `calibrate`, and `restore` are declined in 2.0 by the packaged binary and by the wheel alike. Neither changes display state, and the packaged binary says what it will not do rather than recommending an install that would end at the same refusal. Both point to the window, where a change is previewed and confirmed.

See the [usage guide](https://github.com/HarperZ9/calibrate-pro/blob/v2.0.1/USAGE.md) for installation, command behavior, evidence labels, troubleshooting, and the [read-only example](https://github.com/HarperZ9/calibrate-pro/tree/v2.0.1/examples).

## How It Works

1. **Detects** the selected display and reports available capabilities.
2. **Chooses** a sensorless or measured method and calibration target.
3. **Previews** the exact plan: any DDC/CI changes, and the profile and LUT files it will load, identified by SHA-256 hash.
4. **Confirms** that plan with a confirmation that works once, before the first write.
5. **Applies** the supported parts of the plan after saving the display's prior state. If a step fails, it puts that state back and checks it.
6. **Verifies** the result and labels every performance value by evidence kind.
7. **Saves** the approved profile, LUT, and/or report. Background guard behavior is monitor-and-notify only in 2.0.

## Calibration Modes

| Mode | Requires | Evidence |
|------|----------|----------|
| Sensorless | A characterized panel profile or EDID-derived inputs | Estimated; never presented as a measurement of the attached unit |
| Measured | A supported colorimeter and a display loading no correction | Instrument observations of the attached unit |

Without a colorimeter there is no measurement of the attached unit. Calibrate Pro therefore renders unavailable observations as **Not measured** and labels model-derived diagnostics as **estimated**.

Measured calibration runs in the desktop window. The measured method opens once a supported colorimeter answers on USB and a display is selected. Starting a run needs the display's video card gamma table to read back as identity, because an instrument pointed at a corrected display characterizes the panel together with whatever correction is loaded, and a second correction built from those numbers doubles the first. Calibrate Pro reads that table and refuses the run rather than clearing it, so removing a loaded correction stays something the operator does in the tool that loaded it. The check covers one layer, and the sentence it records names what it did not look at: a DWM LUT, a colour-managed application's own profile, and a correction running inside the monitor.

A run opens a patch window on the selected display and walks four 17-step ramps, neutral and then each channel, for 68 patches at full field. It records the reading with the instrument's identity and the patch geometry, since a luminance read at one window size is not the same number at another. The result becomes the session's characterization, so a plan generated afterwards is derived from the reading instead of from the panel database, and a bundle sealed before the run is dropped. Measured verification reads the display again once a plan is confirmed or applied and reports the result from that second reading; a session holding a measured result is refused sensorless verification, because a model writing into the same accuracy field would replace what the instrument found. The terminal has no measure command in 2.0, and `native-calibrate` and `refine` decline there and name the action behind them.

### Native USB colorimeter driver

The package carries a USB HID driver for the X-Rite i1Display3 family (i1Display Pro, ColorMunki Display, Calibrite ColorChecker Display), which reads each unit's own calibration matrices from its EEPROM and needs no ArgyllCMS install. The device holds nine matrices for different display technologies, and the driver falls back to approximate constants when the EEPROM read fails.

This is what a measured run reads the light through. Install the `sensor` extra (hidapi) to use it. Enumeration and connection are separate calls: the read-only capability probe walks USB descriptors and opens no device session, while opening the instrument runs the unit's own dark calibration, which costs the operator time and is asked for by name.

## Supported Displays

59 characterized panels: 58 monitor models and the generic sRGB record, which is counted under IPS.

- **QD-OLED (17)**: ASUS PG27UCDM/PG32UCDM, Samsung Odyssey OLED G6/G8/G9, Dell AW3423DW/DWF/AW2725DF/AW3225QF, MSI MPG 321URX, Sony BRAVIA A95L
- **WOLED (10)**: LG C2/C3/C4/G4, LG UltraGear 27GR95QE/32GS95UE/34GS95QE, ASUS PG27AQDP/PG34WCDM, Corsair Xeneon 27QHD240
- **IPS (21)**: Dell U2723QE/U3224KB, ASUS ProArt PA279CRV, BenQ SW271C/SW272U, EIZO CS2740/CG2700X, Sony INZONE M9
- **Nano-IPS (2)**: LG UltraGear 27GP950-B, LG UltraGear 27GP850-B
- **Mini-LED (4)**: ASUS ProArt PA32UCG/PA32UCXR, AOC AGON Pro AG274QXM, Apple Pro Display XDR
- **VA (3)**: Samsung Odyssey G7 (27-inch and ultrawide), Dell S2722DGM
- **OLED (2)**: ASUS ProArt PA32DC, Philips Momentum 27E1N8900

`calibrate-pro list-panels` prints the full list from a source install.

A monitor the database does not name is held uncharacterized until you say what it
stands on. The session offers the primaries and gamma the display declares in its EDID,
and falls back to a nominal sRGB record where the display declares nothing readable.
A declaration is labelled `edid_declared` and its evidence stays estimated, because the
numbers describe the model rather than the unit on the desk.

## Output Files

A calibration writes three files into the directory you choose:

| File | Usage |
|------|-------|
| `Calibrate_Pro.icc` | ICC v4 profile for Windows colour management and colour-managed applications |
| `Calibrate_Pro.cube` | 33x33x33 3D LUT for DaVinci Resolve, OBS and other applications that load `.cube` files |
| `calibrate-pro-manifest.json` | SHA-256 hash of each file, with the panel, target and evidence kind |

The LUT library in `calibrate_pro.core.lut_engine` can also write ACES `.clf`, MadVR `.3dlut`, ReShade and Special K PNG textures, an mpv config snippet and an OBS LUT from Python. The 2.0.1 calibration workflow produces only the three files above.

## Architecture

```
calibrate_pro/
  core/           Color math, LUT engine, ICC v4 profiles
  panels/         Display detection, 59-record panel database, DDC recommendations
  sensorless/     Sensorless calibration engine (Oklab/JzAzBz gamut mapping)
  calibration/    Native measurement loop, CCMX spectral correction
  hardware/       i1Display3 native USB, DDC/CI with retry + WMI fallback
  lut_system/     DWM 3D LUT, VCGT gamma ramp, AMD/NVIDIA API
  verification/   12 patch sets (287 patches), grayscale tracking, PDF export
  services/       CalibrationGuard, GamutClamp, AppSwitcher, DriftMonitor
  gui/            PySide6 desktop workflow and read-only system tray
  platform/       Platform layer; Windows is the supported platform
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

FSL-1.1-MIT. Copyright (c) 2022-2026 Zain Dana Harper. Source-available, not open source: read it, run it, and build on it; commercial Competing Use is reserved to the Licensor to fund continued development. See the [license](https://github.com/HarperZ9/calibrate-pro/blob/v2.0.1/LICENSE).

## For developers

Keep the public README, package metadata, and examples aligned with current behavior. Before opening a PR or pushing a release, run the local package verification path.

```bash
python -m pip install -e ".[test]"
python -m pytest
```

---

Built by **[Zain Dana Harper](https://harperz9.github.io)** in Seattle. More tools at [harperz9.github.io](https://harperz9.github.io).
