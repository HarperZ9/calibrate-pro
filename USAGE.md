# Calibrate Pro 2.0 -- Usage Guide

Calibrate Pro is a Windows display-calibration toolkit with two evidence paths:
characterization-based estimates and instrument measurements. Display changes are
available only through an interactive preview-and-confirm workflow.

## Install

### Windows package

Download either `CalibratePro-2.0.0-Setup.exe` or
`CalibratePro-2.0.0-win64.zip` from
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
py -m pip install "calibrate-pro[gui,sensor]==2.0.0"
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

A report that finds a dependency missing prints the command that installs it under a
`To fix` heading, and the JSON carries the same under `remediation`. A base install
reports four missing names and answers with the `gui` extra. A packaged build is told
to reinstall from its release, because pip cannot reach the interpreter it ships.

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
guard are read-only monitor-and-notify surfaces in 2.0.

**Add Display Profile** lists the displays the session detected. Choosing a panel
profile reads it where you keep it and prints what the file states about the panels it
describes. Nothing is copied and nothing is registered: creating a profile from EDID and
importing one into the panel database are both shown disabled with the reason the
session gives, which is the answer `import-panel` gives at the command line.

## Read-only commands

The Python package exposes the commands below. The frozen Windows CLI ships every name
in the tables that follow except the seven marked developer wheel only, and
`packaging/frozen-features.json` is the list the binary is built from. That list is read
back against these tables by a test, because the count here was hand-kept and fell seven
commands behind the build twice. Naming a command the binary does not carry exits 2 with
a sentence about that name rather than an unknown-command error. The seven run in the
developer wheel and say so. The rest are declined by the wheel as well, and the binary
reports that instead of recommending an install.

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
| `calibrate-pro mcp` | Developer wheel only. Serve the read-only catalogue and doctor over MCP stdio |
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
action returned. A refusal is printed in the words the session refused it in. Two of
them write to a path you name: `generate-profiles` writes a calibration bundle into a
directory, and `diagnostics --bundle` writes a support bundle at a file path. One
changes the display itself and four change this machine's colour management, and each
of those five writes only when you pass `--confirm`.

| Command | Purpose |
|---|---|
| `calibrate-pro detect` | Report the displays this machine presents, and where each characterization came from |
| `calibrate-pro ddc-info [--display ID]` | Read the selected display's own brightness, contrast, and RGB controls over DDC/CI |
| `calibrate-pro ddc-calibrate [--brightness N] [...] [--confirm]` | Set those controls, after reading what each one holds now |
| `calibrate-pro status [--closed]` | Report which actions this session can run, and the reason each closed one is closed |
| `calibrate-pro verify --target NAME` | Generate a sealed plan and report its predicted accuracy |
| `calibrate-pro generate-profiles DIR --target NAME [--dry-run]` | Write one calibration bundle into `DIR` |
| `calibrate-pro profiles DIR` | List the bundles published under a directory and check each one's seal |
| `calibrate-pro system-profiles [--display ID]` | Read what Windows colour management holds, and which profile the display uses |
| `calibrate-pro install-profile BUNDLE [--activate] [--confirm]` | Register a published bundle's profile and attach it to the display |
| `calibrate-pro switch-profile NAME [--confirm]` | Make an installed profile the display's default |
| `calibrate-pro remove-profile BUNDLE [--confirm]` | Detach a published bundle's profile and unregister it |
| `calibrate-pro restore-profiles [--confirm]` | Take every profile this product attached back off the display |
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
calibrate-pro install-profile profiles/srgb --activate --confirm
```

`install-profile` takes the bundle directory rather than a profile name. The name a
bundle is registered under is derived from its manifest digest, so the command prints
it and you never have to copy it out of a dialog. Attaching is not activating: Windows
lets a display carry several profiles and hands one of them to colour-managed software,
which is why `--activate` is a separate word. Every command in this family reads the
store before it writes and reads it back afterwards, and reports what the second reading
found rather than whether the call returned.

`remove-profile` takes back what `install-profile` put into colour management and leaves
the bundle directory alone. `restore-profiles` detaches every profile this product
attached to the display and leaves the files registered, so a bundle attached to a
second monitor keeps working. Neither will touch a profile this product did not publish.

`verify` prints a plan digest, the panel and target the plan was built for, what the
figures measure, and an average dE. On a sensorless plan the figure is **estimated** and
the quantity is gamut reproduction: how far the corrected output falls from a display
with exact sRGB primaries. No display was measured and no sensor was read, and the
command prints that sentence under the figures. Tone response is outside the number. The
correction encodes for the gamma the panel record claims and the panel decodes with the
same number, so grey tracking cancels before anything is compared and a display whose
grey is badly wrong scores the same as a perfect one. Measure to establish grey. A
display whose panel is not in the characterization database is refused with `Sensorless
calibration requires a selected characterized display.` rather than estimated from a
stand-in panel.

The measured path answers a different question in the same unit, which is why both paths
name their own quantity on the line above the figures. A measured dE is colour accuracy
read off the display through an instrument. A predicted dE is a residual computed from a
panel record. Reading one for the other is the mistake the label exists to prevent.

`generate-profiles` prints every file it wrote and the SHA-256 of the manifest sealing
them. `--dry-run` stops at the plan and writes nothing. `profiles` recomputes those
digests from the bytes on disk, so a bundle whose files changed is reported as `CHANGED`
and the run exits 1. A path with nothing at it is refused with exit code 2 instead of
being counted as a directory holding no bundles.

### Setting the display's own controls

`ddc-info` and `ddc-calibrate` speak to the panel over DDC/CI, which is the display's
own control bus. This is the one place the product changes hardware rather than the
signal sent to it, so it works the way the window does: read first, stage against what
was read, and write only on an explicit word.

```powershell
calibrate-pro ddc-info
calibrate-pro ddc-calibrate --brightness 40 --red-gain 47
calibrate-pro ddc-calibrate --brightness 40 --red-gain 47 --confirm
```

`ddc-info` prints every control the display answered for, at the value and out of the
maximum the display itself reported, with the VCP code and the flag that sets it. A
control this build asks about and the display declines is listed with the reason,
rather than left out, so you can tell the two cases apart.

`ddc-calibrate` reads the display, then checks each value you named against the range
that reading reported. Without `--confirm` it stops there and prints what it would
write, one line per control showing the current value beside the staged one. With
`--confirm` it writes them as one transaction and reads every code back.

That read-back is why the output shows two numbers. A display answers a write it
ignored exactly the way it answers one it took, so a control that lands somewhere else
is printed as `asked for N, reads M` and the run exits 1. Panels do this: a value out of
range for a mode the display is in, a control the firmware reports and does not drive,
or DDC/CI switched off in the display's own menu. Nothing here reports light. These are
the display's own account of its control state, not a measurement.

`--restore-defaults` asks the display to restore its factory settings. It takes no other
control, because the values you would stage are checked against a reading the restore is
about to invalidate. The display answers nothing to this request, so what the command
prints is the two readings around it and the controls that moved between them.

Setting these controls invalidates a sealed plan and any instrument run in the same
session, and the session says so rather than resetting quietly. Run them before
generating a plan, not after: panel brightness and RGB gain sit upstream of every table
this build writes.

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

## Test patterns

A test pattern is the one thing here judged by eye rather than read off a report, and
the two panel controls it sets sit upstream of every table this build writes. Set them
before generating a plan.

| Command | Purpose |
|---|---|
| `calibrate-pro patterns` | List the test patterns this build carries and the decision each one is for |
| `calibrate-pro show-pattern NAME [--display ID]` | Hold one pattern fullscreen on the selected display until you dismiss it |

```powershell
calibrate-pro patterns
calibrate-pro show-pattern pluge
```

`patterns` reads a table of exact code values and needs no display, no instrument, and
no window toolkit. `show-pattern` opens a frameless fullscreen window on the display you
selected, prints what the pattern decides and what to watch for before the window covers
the terminal, and returns when you press Escape.

This build carries 10 patterns. `pluge` sets the display's brightness control and `white-clip` sets
its contrast, which are the two an operator sets first. `black`, `white`, and `grey` show
uniformity and cast at one level each. `grey-ramp` shows the tone response, `primaries`
and `colour-bars` show channel drive, and `colorchecker` draws the chart the rest of this
package grades against. `crosshatch` draws one-pixel lines and is refused on a scaled
surface rather than drawn blurred, because a blurred line there would be this program's
resampling read as the display's.

Nothing is antialiased, no text is drawn inside the pattern, and every rectangle is one
flat 8-bit triple. What the window cannot establish is whether Windows is applying a
colour transform between these values and the cable. No process can read that about
itself, so it is reported as unestablished with every pattern rather than assumed absent.

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

These are 1.x names, retained so an older script fails safely rather than appearing to
work:

```text
auto                 calibrate             disable-startup
enable-startup       export-panel          import-panel
match                native-calibrate      refine
restore              uniformity
```

Each returns exit code 2 without changing display state. A name with a declared action
behind it is declined in the resolver's own words and names that action, so a terminal
and a window give one answer about what this build does. The rest report that this build
declares no capability behind them, without inventing an action to cite.

`CalibrateProCLI.exe` ships none of these names and reaches the same conclusion for each,
adding that installing the developer wheel would not add the command.

Command-line flags from 1.0 are not accepted as an unattended actuation path. A supported
display change still requires the window's preview and an explicit confirmation.

## Evidence labels

Every performance metric in a 2.0 report is one of:

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
- If the measured method will not open, check that a supported colorimeter is attached and
  that a display is selected. `calibrate-pro status --closed` prints the reason the
  resolver gave for every action that is currently unavailable.
- A measurement run that refuses before it starts is reporting that the display is loading
  a gamma table other than identity. Clear the correction in whatever loaded it and start
  the run again. Calibrate Pro reads that table and never writes to it, and the check does
  not cover a DWM LUT, a colour-managed application's own profile, or a correction running
  inside the monitor.
- Sensorless results remain estimates derived from a panel record rather than measurements
  of the attached unit, and a missing observation is reported as **Not measured** rather
  than replaced with a fabricated reading.
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
