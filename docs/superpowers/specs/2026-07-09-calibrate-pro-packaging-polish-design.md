# Calibrate Pro Packaging and Product Polish Design

**Date:** 2026-07-09
**Target release:** 1.1.0
**Status:** Approved design; written-spec review pending

## Objective

Ship Calibrate Pro as a polished Windows application that installs from one
self-contained installer and does not require customers to install Python or
resolve package dependencies. Preserve the Python package for developers while
making the desktop product's claims, workflow, recovery behavior, and release
artifacts match verified behavior.

## Verified Starting Point

- `pyproject.toml` declares Calibrate Pro 1.0.1 and requires
  `build-color>=1.0.0` for its color-science core.
- The GUI launched by `calibrate_pro.main:main` imports `build_ui.theme` and
  `build_ui.widgets`, but the `all` extra omits `build-ui`.
- `build-color` 1.0.2 and `build-ui` 1.0.1 are published packages and are also
  available in the local workspace.
- The current `CalibratePro.spec` recursively collects the entire package and
  produced a 2,775,446,079-byte executable. The older targeted
  `calibrate-pro.spec` explicitly excludes unrelated frameworks and includes
  `dwm_lut`.
- The active GUI hard-codes version 1.0.0 while package metadata says 1.0.1.
- Public and GUI copy includes predicted sensorless accuracy claims and example
  values such as 0.42 and 0.89 that are not live measurements.
- The bundled `dwm_lut` directory contains both `LICENSE` and
  `LICENSE-THIRD-PARTY` beside its runtime files.
- The source contains two historical GUI/CLI paths. They remain compatibility
  surfaces, but the release entry point is `calibrate_pro.main:main` and its
  `CalibrateProWindow` shell.

These facts describe the inspected workspace; they are not release claims.

## Scope

### In scope

1. A canonical compact Windows packaging path.
2. Bundling all desktop runtime dependencies and applicable license notices.
3. Repairing Python extras and install guidance.
4. Consolidating version and launch metadata.
5. Polishing the active GUI's primary workflow and status language.
6. Removing unsupported, simulated, or ambiguous accuracy claims.
7. Explicit error and recovery states for optional hardware and Windows APIs.
8. Reproducible Windows release automation and artifact verification.
9. A portable ZIP alongside the installer for users who cannot install software.

### Out of scope

- New calibration algorithms or new hardware drivers.
- macOS support.
- Rewriting every historical GUI module.
- Guaranteeing measured accuracy without a supported instrument and recorded
  measurements.
- Purchasing or provisioning a code-signing certificate.
- A licensing, checkout, or activation service.

## Requirements

- **R1 — One customer install:** Produce one Windows x64 installer that contains
  the application runtime. A customer must not need Python, pip, Git, or a
  network connection after downloading the installer.
- **R2 — Bundled dependencies:** The installed application must contain the
  required runtime portions of `build-color`, `build-ui`, PyQt6, NumPy, SciPy,
  and `dwm_lut`, plus third-party notices required for redistribution.
- **R3 — Developer package:** Preserve a normal Python distribution. Core
  installation keeps the current numerical dependencies; `gui` installs PyQt6
  and `build-ui`; `all` contains the complete union of GUI, tray, and sensor
  dependencies.
- **R4 — Canonical build spec:** Keep `calibrate-pro.spec` as the sole
  PyInstaller specification and remove `CalibratePro.spec`. Use an explicit
  module/data allowlist and explicit exclusions rather than recursively
  collecting every Calibrate Pro module.
- **R5 — Fast installed layout:** Build a PyInstaller `onedir` application and
  wrap it in a Windows installer. Do not use the extraction-on-launch `onefile`
  layout for the primary product.
- **R6 — One version source:** Keep the release version in
  `calibrate_pro.__version__`, configure setuptools to read that attribute
  dynamically, and make the GUI, CLI, installer, and release scripts consume
  it. No independently maintained GUI or `pyproject.toml` version literal may
  remain.
- **R7 — Truthful modes:** Label sensorless results as estimates derived from
  panel characterization. Label measured results as measured only when a
  supported instrument produced the underlying readings.
- **R8 — No fabricated results:** Remove hard-coded completion metrics and
  unsupported threshold promises from GUI and release copy. Missing
  measurements render as “Not measured” rather than a synthetic number.
- **R9 — Clear workflow:** The active desktop path presents Detect → Method →
  Preview → Apply → Verify → Save/Report. Unsupported steps are disabled with a
  reason instead of silently simulating success.
- **R10 — Safe failure:** Missing elevation, unavailable DDC/CI, absent
  colorimeter, missing `dwm_lut`, failed profile application, and unsupported
  display detection must yield actionable errors and preserve or restore the
  prior display state.
- **R11 — Reproducible artifacts:** A Windows CI job builds and verifies the
  installer and portable ZIP from a clean environment using published package
  dependencies.
- **R12 — Verifiable release:** Publish hashes, a dependency/version inventory,
  third-party notices, and release notes beside the binaries.
- **R13 — Read-only diagnostics:** Provide `calibrate-pro doctor --json` and the
  equivalent frozen command. It verifies version metadata, dependency imports,
  packaged resources, and platform capability availability without changing a
  display, registering startup behavior, or opening a USB device.

## Architecture

### Runtime layout

The public entry point remains `calibrate_pro.main:main`. It launches the
existing `CalibrateProWindow` shell in `calibrate_pro/gui/app.py`. Historical
entry points remain as compatibility facades, but package initializers must not
eagerly import every historical GUI page. Lazy imports keep optional GUI code
optional and prevent dormant modules from expanding the frozen application.

The frozen application is an explicit `onedir` collection:

```text
Calibrate Pro installer
└── Calibrate Pro/
    ├── CalibratePro.exe
    ├── _internal/             PyInstaller runtime and selected packages
    ├── dwm_lut/               approved runtime files and notices
    └── THIRD_PARTY_LICENSES/  dependency notices
```

Inno Setup 6 wraps the frozen directory and owns Start Menu registration,
uninstall metadata, and an optional desktop shortcut. Startup persistence
remains opt-in inside the product; installation itself must not silently enable
it.

### Dependency boundary

`build-color` remains the authoritative color-science dependency. Calibrate Pro
must import its public `build_color` modules rather than copy their
implementations. `build-ui` remains the shared GUI theme/widget dependency.
Both packages are installed into the clean build environment and frozen into
the application, so users receive them as part of the product without a
separate installation step.

The developer wheel records dependency requirements normally. The standalone
artifact records the exact resolved dependency versions in
`dependency-manifest.json`.

### GUI flow

The active shell keeps the established Build/Telos visual identity while
reducing ambiguity:

1. **Detect:** show each display, connection state, HDR state, and calibration
   age where available.
2. **Method:** distinguish “Sensorless estimate” from “Measured with
   i1Display3.” State what evidence each path can and cannot provide.
3. **Preview:** show target white point, gamma, gamut, proposed DDC changes, and
   output files before modifying the display.
4. **Apply:** require a deliberate action, show progress, and retain the prior
   state needed for restoration.
5. **Verify:** present measured Delta E only for actual instrument readings;
   otherwise present model diagnostics explicitly as estimates.
6. **Save/Report:** save ICC/LUT/report outputs with mode and provenance
   attached.

The dashboard's primary action is “Calibrate a display.” Secondary controls
remain available without competing with the main workflow. Windows-only copy
replaces the current Windows/macOS wording.

## Error and Recovery Model

Errors use a typed category, plain-language summary, technical detail for logs,
and a next action. Hardware and operating-system failures never become a
successful calibration result. Application of a correction is transactional at
the workflow level: capture restorable state, attempt the change, verify the
reported outcome, and restore on failure where the platform adapter supports
restoration.

The GUI must remain usable when optional capabilities are absent. For example,
an absent colorimeter disables the measured path but leaves sensorless profile
generation available; unavailable DDC/CI leaves export available but disables
hardware-control actions.

## Packaging and Release Outputs

The release job produces:

- `CalibratePro-1.1.0-Setup.exe`
- `CalibratePro-1.1.0-win64.zip`
- `SHA256SUMS.txt`
- `dependency-manifest.json`
- `THIRD_PARTY_LICENSES/`
- release notes that distinguish estimated and measured behavior

The compressed installer and portable ZIP must each be no larger than 350 MB.
If that gate fails, the build fails and emits the PyInstaller dependency report;
the limit is not waived silently.

Signing is conditional on a configured signing identity. The workflow must
state whether an artifact is signed and must never describe an unsigned binary
as signed.

## Files Expected to Change

- `pyproject.toml` — version and extras alignment.
- `calibrate_pro/__init__.py` — authoritative version and truthful package
  description.
- `calibrate-pro.spec` — canonical allowlisted `onedir` build.
- `CalibratePro.spec` — removed after the canonical spec covers its real needs.
- `calibrate_pro/main.py` — dependency-aware launch behavior if required.
- `calibrate_pro/gui/app.py` — version source, workflow labels, primary UX, and
  actionable states.
- `calibrate_pro/gui/__init__.py` — lazy compatibility exports instead of eager
  import of the historical GUI graph.
- `calibrate_pro/gui/calibration_wizard.py` — no fabricated metrics or
  unsupported promises.
- relevant active GUI pages — clear estimated/measured language and disabled
  capability states.
- `README.md`, `RELEASE_NOTES.md`, `CHANGELOG.md`, `ARCHITECTURE.md` — aligned
  install, behavior, and release claims.
- `.github/workflows/ci.yml`, `.github/workflows/release.yml` — published
  dependency installs, Windows packaging, and artifact gates.
- `installer/CalibratePro.iss` and `scripts/` — Inno Setup definition and
  deterministic release verification utilities.
- `tests/` — metadata, claims, GUI-state, dependency, and packaging regression
  coverage.

This list may narrow during planning, but implementation may not expand beyond
the approved requirements without updating and re-approving this specification.

## Verification Strategy

Implementation follows test-first development for behavior changes.

1. **Metadata tests:** package version, GUI version, extras, and dependency
   manifest remain aligned.
2. **Claims tests:** public/release/GUI copy contains no prohibited fabricated
   values or unqualified sensorless accuracy thresholds.
3. **GUI-state tests:** offscreen tests exercise missing hardware, sensorless,
   measured, failure, and recovery states without invoking physical devices.
4. **Core regression:** run the complete existing test suite against the
   declared `build-color` dependency.
5. **Wheel smoke:** install the built wheel into a clean virtual environment and
   exercise CLI metadata plus GUI dependency diagnostics.
6. **Frozen smoke:** build on Windows, run `CalibratePro.exe doctor --json`, and
   verify `build_color`, `build_ui`, PyQt6, NumPy, SciPy, and packaged `dwm_lut`
   resources resolve without a hardware mutation.
7. **Artifact audit:** assert the size gates, hash every published file, verify
   the dependency manifest, and assert excluded frameworks such as Torch,
   Transformers, pandas, Jupyter, and OpenCV are absent.
8. **Clean-machine check:** install and uninstall in a disposable Windows
   environment, confirm the GUI starts, and confirm no Python installation is
   used.

Physical display mutation, USB access, DDC/CI writes, DWM LUT application, and
startup registration are not exercised during automated packaging tests.

## Success Criteria

- [ ] One installer installs and launches Calibrate Pro on Windows 10/11 x64
  without Python or network access.
- [ ] The installed application resolves every bundled dependency and required
  runtime resource.
- [ ] `build-color` and `build-ui` are present in both package metadata and the
  frozen dependency manifest where appropriate.
- [ ] The primary installer and portable ZIP each pass the 350 MB gate.
- [ ] The GUI has one metadata-backed version and one primary calibration flow.
- [ ] Sensorless estimates and measured results are visually and semantically
  distinct.
- [ ] No hard-coded calibration result is presented as an observed result.
- [ ] Optional capability failures are actionable and do not falsely report
  success.
- [ ] Existing tests plus new metadata, GUI-state, claims, and packaging tests
  pass.
- [ ] Release hashes, dependency inventory, notices, and truthful release notes
  are generated from the same build.

## Known External Constraint

A trusted Windows code-signing certificate is not present in the inspected
repository. The build will be signing-ready and will identify unsigned output
honestly; a trusted signed public release additionally requires the operator to
provide a certificate through the protected CI secret path.
