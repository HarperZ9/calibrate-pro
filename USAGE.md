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

Run `CalibratePro.exe` for the main workflow. `CalibrateProCLI.exe` answers the headless
commands: `CalibrateProCLI.exe doctor --json` for packaged diagnostics,
`CalibrateProCLI.exe hdr` for HDR target preparation, and the calibration commands
described below. Run it with no arguments to see the list it ships.

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

1. **Detect** -- select a display and inspect available capabilities. The dashboard
   states how the session characterized the display it holds. A display the bundled
   panel database does not name is still detected, and it is held uncharacterized,
   which closes every method and every target after it. **Use Generic Panel** supplies
   a nominal sRGB characterization so the workflow opens, and the row then says the
   plan describes a nominal panel rather than that unit. A display the database does
   name keeps that control disabled, with the reason beside it.
2. **Method** -- choose a target. Sensorless is the method this build offers; the
   measured method is shown disabled with the reason it is closed.
3. **Preview** -- inspect the complete proposed DDC, ICC, VCGT, LUT, and output plan.
4. **Apply** -- explicitly confirm that exact, one-use plan. Previewing opens the
   plan beside its sha256 digest with the two answers the session accepts. Accepting
   records that digest as the plan this session confirmed. It sends nothing to the
   display and loads no profile, and it is what verification and any saved report
   then cite. Declining drops the plan, so generating again seals a new one carrying
   its own digest.
5. **Verify** -- record measured or characterized evidence without relabelling it.
6. **Save/Report** -- save the selected outputs and their source receipts.

Rejecting a preview performs no write. Apply remains unavailable when the required
capability or authoritative prior-state capture is absent. The tray and calibration
guard are read-only monitor-and-notify surfaces in 1.1.

**Add Display Profile** lists the displays the session detected. Choosing a panel
profile reads it where you keep it and prints what the file states about the panels it
describes. Nothing is copied and nothing is registered: creating a profile from EDID and
importing one into the panel database are both shown disabled with the reason the
session gives, which is the answer `import-panel` gives at the command line.

## Read-only commands

The Python package exposes the commands below. The frozen Windows CLI ships nine of
them: `detect`, `diagnostics`, `doctor`, `generate-profiles`, `gui`, `hdr`, `profiles`,
`status`, and `verify`. Naming any other command there prints that it lives in the developer wheel and
exits 2, rather than reporting it as a name that does not exist.

| Command | Purpose |
|---|---|
| `calibrate-pro --help` | Show the complete command surface |
| `calibrate-pro --version` | Show the installed version |
| `calibrate-pro doctor [--json]` | Inspect the installation without probing devices |
| `calibrate-pro list-targets` | Developer wheel only. List calibration target presets |
| `calibrate-pro list-panels` | Developer wheel only. List stored characterized-panel profiles |
| `calibrate-pro info <panel>` | Developer wheel only. Show one stored characterization |
| `calibrate-pro hdr-status` | Developer wheel only. Query the operating-system HDR state |
| `calibrate-pro plugins [--plugin-dir PATH]` | Developer wheel only. List discovered plugin metadata |
| `calibrate-pro tray` | Developer wheel only. Launch the read-only tray monitor |
| `calibrate-pro gui` | Launch the main preview-and-confirm workflow |
| `calibrate-pro hdr` | Launch the HDR target/proposal workflow |

Names marked developer wheel only are absent from the packaged binary, which answers
each of them with `This command is available only in the developer wheel` and exit
code 2. The split is recorded in `packaging/frozen-features.json`.

The stored values printed by `info` describe the characterization source. For an
attached unit they remain estimates unless a supported instrument measures that unit.

## Headless calibration commands

These drive the actions the window drives, over the same session, and print what each
action returned. A refusal is printed in the words the session refused it in. None of
them changes display state. Two of them write, both to a path you name:
`generate-profiles` writes a calibration bundle into a directory, and `diagnostics
--bundle` writes a support bundle at a file path.

| Command | Purpose |
|---|---|
| `calibrate-pro detect` | Report the displays this machine presents, and where each characterization came from |
| `calibrate-pro status [--closed]` | Report which actions this session can run, and the reason each closed one is closed |
| `calibrate-pro verify --target NAME` | Generate a sealed plan and report its predicted accuracy |
| `calibrate-pro generate-profiles DIR --target NAME [--dry-run]` | Write one calibration bundle into `DIR` |
| `calibrate-pro profiles DIR` | List the bundles published under a directory and check each one's seal |
| `calibrate-pro diagnostics [--bundle PATH] [--open]` | List the session journal, and publish it for support |

`--target` is required rather than defaulted; `calibrate-pro list-targets` prints the
names it accepts. Pass `--display ID` to `verify` or `generate-profiles` to choose among
several displays, using the identifier `detect` printed for the one you want.

A worked run:

```powershell
calibrate-pro detect
calibrate-pro verify --target srgb_web
calibrate-pro generate-profiles profiles/srgb --target srgb_web
calibrate-pro profiles profiles/srgb
```

`verify` prints a plan digest, the panel and target the plan was built for, and an
average dE. That figure is **estimated** from the panel characterization: no display was
measured and no sensor was read, and the command prints that sentence under the figures.
A display whose panel is not in the characterization database is refused with `Sensorless
calibration requires a selected characterized display.` rather than estimated from a
stand-in panel.

`generate-profiles` prints every file it wrote and the SHA-256 of the manifest sealing
them. `--dry-run` stops at the plan and writes nothing. `profiles` recomputes those
digests from the bytes on disk, so a bundle whose files changed is reported as `CHANGED`
and the run exits 1. A path with nothing at it is refused with exit code 2 instead of
being counted as a directory holding no bundles.

`diagnostics` reads back the redacted journal every action writes to. With no arguments
it lists each file a support bundle would carry, its byte length, and its SHA-256, and
writes nothing. Pass `--bundle PATH` to publish exactly those bytes at `PATH`, which
must not already exist. Pass `--open` to open the folder the journal is kept in, on a
platform that can open one. The listing and the bundle come from one run because the
grant between them is held in memory: what you were shown is what you send.

The window offers the same three actions under Diagnostics on the settings page. Preview
draws the listing, Save bundle asks where the archive goes and writes exactly the members
above it, and Open folder opens the journal directory. A preview goes stale once the
session records another action, so take a fresh one if a publish is refused.

## Settings

The settings page holds what the session can be asked for, and each control on it goes
through the same resolver the rest of the window uses.

**LUT size** picks the grid the next generated bundle is built on. This build generates
17, 33, and 65 point grids. The choice applies at the next generation. A bundle that has
already been sealed records the grid it was built with in its own manifest, so changing
this later does not restate anything already published.

**Output directory** is where saved reports and exports are written. Saving a report is
refused until a directory has been accepted. A folder that cannot be written to is shown
as the folder that was turned down, rather than cleared, and saving stays closed.

**HDR mode** is drawn and closed, carrying the reason the session gives for closing it.
Everything this build generates is SDR.

**Diagnostics** holds the three journal actions described above.

Eight controls were removed in this version: Start with Windows, Minimize to tray, OLED
automation, per-app profile switching, its rules table, the ArgyllCMS path, the panel
profiles path, and the default target selector. Each wrote a value into the application's
configuration store that nothing read back, so ticking one reported a preference the
product did not hold. The action manifest declares all eight hidden, with the reason that
their product workflow is not specified.

## Commands this build declines

Most of these are retained so an older script fails safely rather than appearing to
work. `patterns` is a current name whose action this build has not qualified:

```text
auto                 calibrate             ddc-calibrate
ddc-info             disable-startup       enable-startup
export-panel         import-panel          match
native-calibrate     patterns              refine
restore              uniformity
```

Each returns exit code 2 without changing display state. A name with a declared action
behind it is declined in the resolver's own words and names that action, so a terminal
and a window give one answer about what this build does. The rest report that this build
declares no capability behind them, without inventing an action to cite.

Command-line flags from 1.0 are not accepted as an unattended actuation path. A supported
display change still requires the window's preview and an explicit confirmation.

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
- Attach a support bundle. Settings -> Diagnostics -> Preview lists what the bundle
  carries and Save bundle writes it, or run `calibrate-pro diagnostics --bundle PATH`.
  The journal is redacted before it is written, and the listing is what you send.
- Confirm that the package came from the GitHub release or the `calibrate-pro` project
  on PyPI and verify its SHA-256 against `SHA256SUMS.txt`.
- If a display control is unavailable, treat that as a capability result; do not run the
  whole application as administrator to bypass it.
- Measured calibration is closed in 1.1, so owning a colorimeter does not open it. The
  action manifest declares `calibration.method.measured` and `verification.measured`
  disabled in the wheel and in the packaged binary alike, pending a distinct qualified
  measurement contract. `calibrate-pro status --closed` prints the reason. Everything
  1.1 produces is sensorless and labelled estimated, and a missing observation is
  reported as **Not measured** rather than replaced with a fabricated reading.
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
