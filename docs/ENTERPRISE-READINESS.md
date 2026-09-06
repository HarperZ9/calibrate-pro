# Calibrate Pro 2.0 Enterprise Readiness

Calibrate Pro combines display-calibration planning, deterministic color transforms,
hardware adapters, and evidence-labelled reporting in one Windows application. Its 2.0
release boundary favors inspectable, reversible operations over unattended display
mutation.

## Product role

- Discover display capabilities and stored panel characterizations.
- Prepare SDR/HDR targets, ICC/VCGT assets, and 3D LUT outputs.
- Support characterized and instrument-measured workflows without confusing estimates
  with observations.
- Preview an exact display-change plan, require explicit operator confirmation, capture
  restorable state, and verify both application and compensation.
- Produce local reports and source receipts that can be reviewed after the session.

## Operator surface

- A PySide6 desktop workflow: Detect -> Method -> Preview -> Apply -> Verify ->
  Save/Report.
- Read-only CLI diagnostics, target/panel information, HDR status, pattern display, and
  plugin metadata.
- Stable `doctor --json` installation diagnostics for support automation.
- A headless session (`detect`, `status`, `verify`, `generate-profiles`, `profiles`,
  `diagnostics`) that runs the same actions the window runs, for unattended inventory,
  planning, and bundle publication. It performs no display write.
- A redacted action journal an operator can read back and publish as a support bundle,
  after being shown the digest of every file it would carry.
- Legacy mutation-capable CLI names are proposal-only and perform no display write.
- A read-only tray and monitor-and-notify calibration guard.

## Trust and evidence boundaries

- Both packaged desktop executables use an `asInvoker` manifest and start unelevated.
- Application-facing modules do not import or call low-level display writers. One
  Windows adapter owns the DDC/CI, ICC, VCGT, and DWM write boundary.
- Apply plans are immutable, one-use, capability-checked, and bind external assets by
  SHA-256. Bounded inputs are parsed before the first write.
- Prior state is captured before mutation. Failed transactions attempt compensation and
  require authoritative read-back before describing restoration as successful.
- DWM LUT application is withheld when authoritative prior-state capture is unavailable.
- Reports label values as measured, estimated, simulated, replayed, or **Not measured**.
  A sensorless value is never represented as an observation of the attached unit.

The complete supported and unsupported trust surface is documented in
[SECURITY.md](../SECURITY.md).

## Platform and packaging

- Packaged desktop target: Windows x64.
- Source package: Python 3.10 or newer.
- Desktop stack: PySide6, QtPy, and Build UI 2.
- Color/numerical stack: Build Color, NumPy, and SciPy.
- Optional instrument transport: hidapi.
- License: FSL-1.1-MIT; see [LICENSE](../LICENSE).

The release build uses a committed hash lock, an exact frozen-module allowlist, pinned
toolchain receipts, a per-user Inno Setup installer, a portable ZIP, third-party
notices, and source-provenance records. Unknown staged modules, native files, Qt
components, or distributions fail the release audit.

## Quality gates

A publish candidate must pass:

- the complete Python test suite;
- Ruff formatting and lint checks plus the configured mypy boundary;
- safety, truthfulness, least-privilege, Qt-binding, package-lock, and redistribution
  contract tests;
- frozen module/component audits and the package size limit;
- Windows PE manifest inspection for both executables;
- offscreen frozen GUI, HDR, CLI, and `doctor` smoke tests;
- installer and portable archive inventory/hash generation; and
- a clean installation proof from the published artifact.

Release artifacts include `SHA256SUMS.txt` and machine-readable receipts so a later
build or support investigation can identify the exact inputs and outputs.

## Current limitations

- Hardware controls vary by display, firmware, GPU driver, and Windows capability.
  Unsupported or non-restorable operations remain unavailable.
- Measured calibration runs from the desktop window and needs a supported colorimeter at the workstation. Procuring instruments is necessary and not sufficient: a run is refused while the display is loading a correction, and that check reads the video card gamma table rather than every layer that can sit between a signal and the light.
- Sensorless characterization cannot measure unit variation or drift.
- Recovery is an in-process compensating transaction, not a crash-proof hardware
  transaction across power loss or operating-system failure.
- Calibrate Pro does not promise a specific accuracy, gamut, luminance, or commercial
  grading classification without recorded measurements from the attached display.
