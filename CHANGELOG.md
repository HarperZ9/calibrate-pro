# Changelog

## Unreleased

- Stopped detection reporting one monitor's characterization for every display. The panel
  lookup was written against a fixed model string, so each display a session detected came
  back as that monitor: its panel type, its manufacturer, and, wherever EDID colorimetry was
  unreadable, its primaries. A display the bundled database has never heard of reported a
  panel profile it does not have. Each display now resolves against the model string its own
  EDID carries, with the name the bus reports as the fallback, and a display that neither one
  matches is reported as unmatched rather than borrowing another monitor's answer.
- Made a coverage run report a failure instead of dying. The Windows CI lane runs the suite
  under coverage, and the process was exiting with an access violation partway through, which
  reads as a crash in the product and ends the lane before the rest of the suite runs. Neither
  cause was a native call. The Win32 cancellation contracts install a trace function of their
  own, turn on opcode tracing in frames the coverage tracer had already instrumented, and raise
  out of the middle of one of them, so measurement is now suspended for the length of each of
  those windows and started again after, keeping what it had already collected. The mutex tests
  were also leaving one owner thread running for every release the operating system never
  confirmed, and a thread started while coverage is measuring carries its trace function for as
  long as it lives. Those threads are retired once the test that started them has finished
  asserting, which ends the command loop and leaves the unconfirmed handle alone. The note in
  the packaging configuration blamed native GDI calls on daemon threads, which measurement
  ruled out, and now says what was measured.
- Made a suite that passes exit as one. The Windows run finished every assertion and then
  died with an access violation raised inside a garbage collection during interpreter
  shutdown, in three of five observed runs, and the process exit status is what a runner
  reads. What was being collected was Qt. Closing a window hides it, and the C++ object
  stays alive inside a Python reference cycle until a collection that may not happen before
  PySide6 is already being taken apart. A timer or a settings store that a page holds as an
  attribute and gives no parent belongs to no widget tree, so destroying the window does not
  reach it either. Twenty timers were surviving that way, alongside six settings stores and
  three animations. The suite now destroys them after the last test, while the application
  their destructors reach for on the way out is still there. Three consecutive runs of the
  full suite then passed all 2,234 tests and exited zero.
- Turned the two lint gates green. `ruff check .` was reporting an unsorted import block and
  an assignment whose value is never read in the measured calibration script, and a loop in
  the i1d3 driver that reads as `any(...)`. The unread assignment stays as a call, because
  what it is there for is the exception it raises when the target does not resolve to
  exactly one DWM monitor. `ruff format --check .` was reporting eighteen files, seventeen
  of them written by this branch to an 88 column width the project does not use. CI pins
  ruff 0.15.21 and runs both as required checks, so neither was passing before this.
- Made `doctor` answer a person as well as it answers a parser. `--json` was declared by
  both dispatchers and printed in both usage listings, and the command emitted compact
  JSON whichever way it was called, so the first command the documentation tells an
  operator to run returned one long line of it. The flag now selects the form. Without it
  the report is laid out to read: dependencies with versions, the three whole-installation
  checks, and the capability block. The capability block states that nothing was probed,
  because `supported` beside a bus or a colorimeter otherwise reads as a device that
  answered. The JSON form is unchanged, which is what every packaged script and every
  test asks for.
- Gave a display the bundled panel database cannot name a way forward. Detection adopts
  such a display rather than rejecting it, and adopts it uncharacterized, so every
  calibration method and every target after that refused it. The one action that supplies
  a characterization was declared, resolved, and drawn by no window, which left that
  display on the Calibrate page with nothing on the page open to it. The dashboard now
  carries a row saying how the session characterized the display it holds, with the
  control that takes the generic path beside it. A matched session sees the control
  disabled in place with the resolver's own sentence rather than finding it absent.
- Made that row state the session rather than the observation behind it. Taking the
  generic path is a decision the session records, and the detection pass is unchanged, so
  the card still reports an uncharacterized panel while the resolver works from a
  characterized one. The row reads the session, and rereads it when a pass finishes and
  whenever the dashboard comes back into view, because the Calibrate page can move the
  selection while the operator is looking somewhere else.
- Added the gate that would have caught the missing control. The per-page tests read one
  direction, control to declared action, and nothing read the other. A new gate builds the
  window and both dialogs, unions every action they bound, and requires each declared
  surface to be presented or written down under one of four reasons: hidden by the
  manifest, performed from a shortcut or a signal Qt gives no control for, drawn as a
  refusal reason, or an honest null. Each reason is checked against the manifest or the
  source, so an entry cannot become a stale excuse for a control somebody removed.
- Fixed two DDC controls that were painted as though they were live. Both are disabled in
  this build, and the stylesheets they carried declared no disabled colours, so an
  unavailable accent button and an unavailable destructive button drew at full strength.
  Both now take the disabled colours the shared button style declares.
- Widened the GUI truthfulness gates to the window they are about. Three source scans
  read a list of filenames written by hand, and nine of the fourteen modules the window
  reaches were not on it, so both dialogs, the DDC page, the settings page, and the
  binder every control is registered with were reported as covered by a suite that never
  opened them. The list is now read off what the window imports, and a gate fails when a
  module the window reaches is missing from it.
- Gave the window somewhere to answer a plan. Confirming and declining are declared
  actions whose two dialog surfaces no window presented, so a session driven from the
  window sealed a plan, previewed it, and stopped there. Everything downstream stopped
  with it, because sensorless verification reads a plan the session confirmed and the
  report and export actions read that verification, which left three reachable pages
  permanently refused. Previewing now opens the plan beside its digest with both answers
  bound to the resolver. Accepting records the digest and sends nothing to the display,
  which the dialog states beside the button, because Accept under a list of ICC and LUT
  files otherwise reads as a promise to load them.
- Made the add-profile dialog do only what the session permits. It opened a file chooser,
  copied the chosen file into the panel profiles directory, and registered whatever it held,
  with no action resolved and nothing journalled, while the manifest declared both of those
  writes disabled and the command line declined them by name. Reading a chosen file is now a
  declared action: it parses the file where it sits, reports what the file states about the
  panels it describes, and is recorded like any other action. The two write controls stay on
  the dialog, disabled, carrying the resolver's own sentence, so an operator reads why this
  build will not write yet instead of finding a button that quietly does nothing.
- Removed the second display enumeration the same dialog ran. It now lists what the
  session's own detection pass observed, so opening the dialog is one action rather than a
  scan nobody asked for.

- Added the headless calibration session. `detect`, `status`, `verify`,
  `generate-profiles`, and `profiles` drive the actions the window drives, over one
  service, and print what each action returned. A refusal arrives in the words the
  session refused it in rather than a sentence written for the command line.
- Shipped those five commands in the frozen binary, so a headless run no longer requires
  installing Python and the developer wheel. `CalibrateProCLI.exe` answers nine commands
  and refuses the rest by naming the package they live in.
- Added `diagnostics`, which reads back the redacted journal every action writes to. It
  lists each file a support bundle would carry with its digest, publishes exactly those
  bytes when `--bundle PATH` is given, and opens the folder with `--open`. The three
  actions behind it were declared in the manifest and reachable from no surface.
- Built the same three actions into the window, under Diagnostics on the settings page.
  The listing names each member and its digest before anything is written, the save
  button opens only against a live preview, and the token that preview issued is spent by
  the attempt that follows rather than by that attempt succeeding.
- Made the settings page mean what it draws. It rendered eleven declared surfaces and
  handed one to the resolver; the rest wrote into the application's configuration store,
  where nothing read them back, so ticking Start with Windows reported a preference the
  product did not hold. Those controls are gone, along with the writes behind them.
- Made LUT size a preference the work uses. Choosing a grid runs as a declared action, is
  journalled, and is read when the next bundle is generated, which the bundle then records
  in its own manifest. A grid this build does not generate is refused by name.
- Withdrew the default-target claim. Its predicate required a target the session had
  already selected, which is not what a default is, and applying one at startup would
  pre-select before the Method stage. The manifest now declares it hidden rather than
  offering a preference that never existed.
- Kept the HDR checkbox on the page and bound it closed, so it renders disabled carrying
  the session's own reason. Removing it would read as a build that never had the feature.
- Gated the action manifest against the code it names. A required module was checked for
  the shape of a dotted name and never imported, so the manifest declared a module that
  did not exist across a green suite. The gate imports what the manifest requires and
  reads the frozen policy back against it.
- Gated the headless command table in the usage guide against the parsers the commands
  are built from, so a command that runs but has no row fails a gate.
- Added the one-session application service: read-only detection with default-deny
  capabilities, deterministic asset generation, and an atomic export bundle sealed by a
  SHA-256 manifest.
- Added bundle read-back. `profiles` recomputes each digest from the bytes on disk, so a
  bundle whose files changed is reported as changed instead of listed as published.
- Bound the desktop DDC controls, the detection view, and the verification view to the
  actions they stand for, so the window renders the session's observation rather than
  reading hardware beneath it.
- Gated the frozen module closure and the shipped command policy against the dispatcher
  the binary runs. A command added to one list and not the other now fails a gate.
- Fixed the tray reporting a startup registry record in place of the detection the
  running session had performed.
- Corrected the public documentation. `detect`, `status`, `verify`, `generate-profiles`,
  and `profiles` were documented as proposal-only names that exit 2, which they no longer
  are.
- Stopped `patterns` from opening a fullscreen viewer. The manifest declares
  `patterns.open` disabled, the window routes it through the resolver, and the frozen
  binary does not ship the name, so the developer command line now declines it in the
  same words rather than being the one surface that acts.
- Gated the declared calibration presets against the table a session selects from. A
  preset declared without an entry there inherited a refusal naming conditions the
  session already met, which reads as a fault in the session.

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
