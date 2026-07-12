# Calibrate Pro 1.1 -- Usage Guide

Calibrate Pro is a Windows display-calibration toolkit with two evidence paths:
characterization-based estimates and instrument measurements. Display changes are
available only through an interactive preview-and-confirm workflow.

## Install

### Windows package

Download either `CalibratePro-1.1.0-Setup.exe` or
`CalibratePro-1.1.0-win64.zip` from
[GitHub Releases](https://github.com/HarperZ9/calibrate-pro/releases).

Calibrate Pro starts unelevated: the per-user installer uses lowest privilege and both
desktop executables use the Windows `asInvoker` manifest. The packaged
application includes its Python, Build Color, Build UI 2, PySide6/Qt, NumPy, SciPy,
hidapi, and approved Windows runtime dependencies. It does not need a separate Python
installation.

Run `CalibratePro.exe` for the main workflow. Use `CalibrateProCLI.exe doctor --json`
for packaged diagnostics or `CalibrateProCLI.exe hdr` for HDR target preparation.

### Python package

```powershell
py -m pip install "calibrate-pro[gui,sensor]==1.1.0"
calibrate-pro doctor
calibrate-pro gui
```

Python installs require Python 3.10 or newer on Windows. The `gui` extra installs
PySide6, QtPy, and Build UI 2; the `sensor` extra installs the HID transport used by
supported colorimeters.

## First run

Start with the read-only installation report:

```powershell
calibrate-pro doctor
calibrate-pro doctor --json
```

`doctor` checks the installed dependency versions, Qt binding, packaged notices and
runtime resources, PQ reference math, and software capability surfaces. It does not
probe a physical display, open a colorimeter, or change system state. The JSON form is
schema-versioned and suitable for a support attachment.

Then launch the desktop workflow:

```powershell
calibrate-pro gui
```

The workflow is:

1. **Detect** -- select a display and inspect available capabilities.
2. **Method** -- choose sensorless or measured evidence and a target.
3. **Preview** -- inspect the complete proposed DDC, ICC, VCGT, LUT, and output plan.
4. **Apply** -- explicitly confirm that exact, one-use plan.
5. **Verify** -- record measured or characterized evidence without relabelling it.
6. **Save/Report** -- save the selected outputs and their source receipts.

Rejecting a preview performs no write. Apply remains unavailable when the required
capability or authoritative prior-state capture is absent. The tray and calibration
guard are read-only monitor-and-notify surfaces in 1.1.

## Read-only commands

The Python package exposes the commands below. The frozen Windows CLI intentionally
ships only `doctor`, `gui`, and `hdr`; the broader developer command surface is not
bundled into the desktop package.

| Command | Purpose |
|---|---|
| `calibrate-pro --help` | Show the complete command surface |
| `calibrate-pro --version` | Show the installed version |
| `calibrate-pro doctor [--json]` | Inspect the installation without probing devices |
| `calibrate-pro list-targets` | List calibration target presets |
| `calibrate-pro list-panels` | List stored characterized-panel profiles |
| `calibrate-pro info <panel>` | Show one stored characterization |
| `calibrate-pro hdr-status` | Query the operating-system HDR state |
| `calibrate-pro patterns [--display N]` | Show visual test patterns |
| `calibrate-pro plugins [--plugin-dir PATH]` | List discovered plugin metadata |
| `calibrate-pro tray` | Launch the read-only tray monitor |
| `calibrate-pro gui` | Launch the main preview-and-confirm workflow |
| `calibrate-pro hdr` | Launch the HDR target/proposal workflow |

The stored values printed by `info` describe the characterization source. For an
attached unit they remain estimates unless a supported instrument measures that unit.

## Proposal-only legacy commands

The following names are retained so an older script fails safely and explains the new
workflow:

```text
auto                 calibrate             ddc-calibrate
ddc-info             detect                disable-startup
enable-startup       export-panel          generate-profiles
import-panel         match                 native-calibrate
refine               restore               status
uniformity           verify
```

Each returns exit code 2 without changing display state and directs the operator to the
GUI. Command-line flags from 1.0 are not accepted as an unattended actuation path.

## Evidence labels

Every performance metric in a 1.1 report is one of:

- **measured** -- observed with an instrument and linked to its source;
- **estimated** -- derived from characterization/model inputs;
- **simulated** -- produced by an explicit simulation;
- **replayed** -- loaded from recorded evidence; or
- **Not measured** -- no observation exists.

Sensorless output is not a measurement of the connected unit, and Calibrate Pro does
not promise a particular dE, gamut, luminance, or grade without recorded measurements.

## Panel database example

The panel database can be inspected without hardware:

```python
from calibrate_pro.panels.database import PanelDatabase

database = PanelDatabase()
print(len(database.list_panels()))

panel = database.get_panel("PG27UCDM")
if panel is not None:
    print(panel.name)
    print(panel.panel_type)
    print(panel.native_primaries)
```

## Troubleshooting

- Run `calibrate-pro doctor --json` and retain the complete output.
- Confirm that the package came from the GitHub release or the `calibrate-pro` project
  on PyPI and verify its SHA-256 against `SHA256SUMS.txt`.
- If a display control is unavailable, treat that as a capability result; do not run the
  whole application as administrator to bypass it.
- A measured workflow requires a supported colorimeter. Missing hardware is reported,
  not replaced with fabricated readings.
- Report defects through [GitHub Issues](https://github.com/HarperZ9/calibrate-pro/issues)
  and suspected vulnerabilities through the repository's private Security Advisory
  form.

## Build from source

```powershell
git clone https://github.com/HarperZ9/calibrate-pro.git
cd calibrate-pro
py -m pip install -e ".[dev,gui,sensor]"
python -m pytest
```

The Windows release uses the committed hash lock and release gates:

```powershell
powershell -File scripts/build_windows.ps1
```

See [README.md](README.md), [SECURITY.md](SECURITY.md), and the release notes for the
current limitations and trust boundary.
