# Calibrate Pro -- Usage Guide

Calibrate Pro is a Windows display-calibration toolkit. It detects monitors,
identifies panels from a 58-entry database, and applies color corrections via
DDC/CI hardware adjustments and 3D LUTs -- with no colorimeter (sensorless) or
with an X-Rite i1Display3 family device (measured).

This guide covers installation, the CLI command set, worked examples with
expected output, and a small library example. Output blocks captured by running
the read-only commands are real; blocks that require calibration hardware or
admin/system changes are marked **illustrative** because they were not run here.

---

## Install

### Standalone (Windows)

Download `calibrate-pro.exe` from
[Releases](https://github.com/HarperZ9/calibrate-pro/releases) and run it.
No Python required. It requests admin rights (needed for the DWM LUT and DDC/CI).

### From source

```bash
git clone git@github.com:HarperZ9/calibrate-pro.git
cd calibrate-pro
pip install -e ".[all]"
```

Requires Python 3.10+ and Windows 10/11. The `[all]` extra pulls in the GUI
(PyQt6), system-tray (pystray, Pillow), and native USB sensor (hidapi) extras.
Smaller subsets are available: `.[gui]`, `.[tray]`, `.[sensor]`.

After install, the console script `calibrate-pro` is on your PATH. You can also
invoke the package directly with `python -m calibrate_pro`.

---

## Command overview

Running `calibrate-pro` (or `python -m calibrate_pro`) with no arguments launches
the GUI. The CLI exposes 26 subcommands; run `calibrate-pro --help` for the full
list. The most common ones:

| Command | Purpose |
|---------|---------|
| `detect` | Detect connected displays + colorimeters + DDC/CI monitors |
| `auto` | Fully automatic calibration of all displays (zero input) |
| `calibrate` | Calibrate one display with explicit targets |
| `ddc-calibrate` | DDC/CI-first calibration (hardware before LUT) |
| `native-calibrate` | Measured calibration with the native i1Display3 driver |
| `refine` | Refine an existing calibration with a colorimeter (ArgyllCMS) |
| `verify` | Verify calibration accuracy (ColorChecker) |
| `status` | Show calibration age and drift for all displays |
| `restore` | Undo calibration (reset to defaults) |
| `list-panels` | List the 58 supported panel profiles |
| `list-targets` | List calibration target presets |
| `info <panel>` | Show detailed information for a panel key |
| `ddc-info` | Show DDC/CI capabilities per monitor |
| `patterns` | Display fullscreen test patterns |
| `uniformity` | Measure screen uniformity |
| `generate-profiles` | Generate sRGB, P3, Rec.709, AdobeRGB profiles in one pass |
| `match` | Match multiple displays for consistent appearance |
| `hdr-status` | Show HDR mode status for all displays |
| `export-panel` / `import-panel` | Share / load community panel JSON |
| `enable-startup` / `disable-startup` | Toggle auto-start at Windows boot |
| `gui` / `hdr` / `tray` | Launch the GUI, HDR GUI, or system-tray app |
| `plugins` | List discovered plugins |

---

## Worked examples

### 1. List supported panels

```bash
calibrate-pro list-panels
```

Expected output (truncated -- 58 profiles total):

```
Calibrate Pro v1.0.0
==================================================

Supported Panel Profiles:

  MSI MAG 274QRF QD                         IPS
  Philips Momentum 27E1N8900                OLED
  LG UltraGear 27GP850-B                    Nano-IPS
  LG UltraGear OLED 27GR95QE                WOLED
  Dell Alienware AW3423DW                   QD-OLED
  EIZO ColorEdge CG2700X                    IPS
  ...

Total: 58 profiles

Use 'info <panel_key>' for detailed information
```

### 2. Inspect one panel

```bash
calibrate-pro info PG27UCDM
```

Expected output:

```
Calibrate Pro v1.0.0
==================================================

Panel Information: PG27UCDM
--------------------------------------------------
  Manufacturer: ASUS
  Model: PG27UCDM
  Type: QD-OLED

  Native Primaries:
    Red:   (0.6795, 0.3095)
    Green: (0.2325, 0.7115)
    Blue:  (0.1375, 0.0495)
    White: (0.3127, 0.3290)

  Gamma:
    Red:   2.2020
    Green: 2.1980
    Blue:  2.2000

  Capabilities:
    SDR Peak: 275.0 cd/m2
    HDR Peak: 1000.0 cd/m2
    HDR: Yes
    Wide Gamut: Yes
    VRR: Yes

  Notes: ASUS ROG Swift 27-inch 4K 240Hz QD-OLED. Samsung Display 2024 panel. 92% BT.2020.
```

### 3. List calibration target presets

```bash
calibrate-pro list-targets
```

Expected output (truncated):

```
Calibrate Pro v1.0.0
==================================================

--- Calibration Profiles ---
  sRGB Web Standard         - Standard sRGB for web and consumer content
  Rec.709 Broadcast         - EBU Grade 1 broadcast reference
  DCI-P3 Cinema             - Digital Cinema Initiative standard
  HDR10 Mastering           - HDR10 professional mastering (HDR)
  Photography               - Adobe RGB with D50 for photography
  Film Grading              - SMPTE RP 166 film grading environment

--- White Point Presets ---
  D65             (6504K) - sRGB, Rec.709, web content standard
  D50             (5003K) - ICC Profile Connection Space, photography standard
  DCI-P3          (6300K) - Digital Cinema Initiative standard
  ...

--- Luminance Presets ---
  Rec.709 Broadcast    - 100 cd/m2 [SDR]
  Consumer SDR         - 250 cd/m2 [SDR]
  HDR10                - 1000 cd/m2 [HDR]
  ...

Use these with: calibrate --profile <name> or individual --whitepoint, --luminance, --gamma, --gamut flags
```

### 4. Automatic calibration (illustrative)

`auto` requires real displays and applies a system-wide LUT, so the output below
is **illustrative**, not captured here. It detects every connected display,
matches the panel, applies DDC/CI and a 3D LUT, and (by default) persists across
reboots and opens an HTML report.

```bash
calibrate-pro auto
```

Useful flags:

```bash
calibrate-pro auto --no-ddc        # software LUT only, skip DDC/CI
calibrate-pro auto --no-persist    # do not register auto-start or save state
calibrate-pro auto --no-report     # do not open the HTML report in a browser
calibrate-pro auto --hdr           # generate an HDR (PQ/ST.2084) LUT instead of SDR
```

Illustrative output shape:

```
Calibrate Pro v1.0.0 - Automatic Calibration
============================================================
No instruments required. No input needed.
Detecting and calibrating all connected displays...

  ...

  ASUS ROG Swift OLED PG27UCDM
    PG27UCDM (QD-OLED)
    Delta E: 0.84 (sensorless)  |  Grade: A
    Gamut: sRGB 100%  P3 99%  BT.2020 92%
    Applied: DWM 3D LUT (system-wide)

  1/1 displays calibrated.
  Calibration persists across reboots.
============================================================
```

### 5. Targeted single-display calibration (illustrative)

Pick a display and target with explicit flags instead of the automatic flow:

```bash
calibrate-pro calibrate --display 1 --profile sRGB --output ./out
calibrate-pro calibrate -d 1 --whitepoint D65 --gamma 2.2 --gamut sRGB --lut-size 33
```

`--mode` chooses `sensorless` (default), `colorimeter`, or `hybrid`.
`--no-icc` / `--no-lut` skip those outputs. See `calibrate-pro calibrate --help`
for the full flag set (white point, CCT, luminance, black level, gamma, gamut).

### 6. Verify and check status (illustrative)

```bash
calibrate-pro verify -d 1            # sensorless ColorChecker verification
calibrate-pro verify -d 1 --measured # colorimeter-based (needs ArgyllCMS / manual XYZ)
calibrate-pro status                 # calibration age + drift for all displays
calibrate-pro restore -d 1           # undo calibration on display 1
```

---

## Library example

The package also exposes its color-science and panel-database internals. The
panel database is read-only and runs without hardware:

```python
from calibrate_pro.panels.database import PanelDatabase

db = PanelDatabase()
print(len(db.list_panels()))          # 58

panel = db.get_panel("PG27UCDM")
print(panel.name)                     # ASUS ROG Swift OLED PG27UCDM
print(panel.panel_type)               # QD-OLED
print(panel.native_primaries)         # red/green/blue/white chromaticities
```

Expected output:

```
58
ASUS ROG Swift OLED PG27UCDM
QD-OLED
```

Lazy-loaded submodules are also re-exported from the top-level package for
convenience, e.g. `calibrate_pro.color_math`, `calibrate_pro.lut_engine`,
`calibrate_pro.database`, `calibrate_pro.detection`.

---

## Output files

A full calibration run writes (per display): `.cube` and `.3dlut` 3D LUTs, a
`.clf` ACES LUT, an `.icc` v4 profile, ReShade / Special K / OBS / mpv exports,
and an HTML report. See the table in [README.md](README.md#output-files).

---

## Demo

A runnable, hardware-free demo lives in [`examples/`](examples/):

```bash
python examples/inspect_panels.py
```

It uses only read-only commands and library calls (panel lookup, listing), so it
is safe to run without admin rights or a connected colorimeter.
