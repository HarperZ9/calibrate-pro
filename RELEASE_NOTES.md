# Calibrate Pro v1.1.0

Calibrate Pro 1.1 is a safety, truthfulness, Qt, and Windows-packaging release.

## Download

- `CalibratePro-1.1.0-Setup.exe`: per-user Windows x64 installer.
- `CalibratePro-1.1.0-win64.zip`: portable Windows x64 package.
- `calibrate_pro-1.1.0-py3-none-any.whl`: Python package for supported source installs.

The Windows packages include Python, Build Color, Build UI 2, PySide6/Qt, NumPy, SciPy, hidapi, and approved `dwm_lut` runtime files. They do not require Python, pip, Git, or network access after download.

The 1.1.0 Windows artifacts are not Authenticode-signed. Windows may display a SmartScreen warning; verify downloads against the release's `SHA256SUMS.txt` before execution.

## Highlights

- Migrated the desktop interface to PySide6 through a fail-closed Qt runtime boundary.
- Added the six-stage Detect -> Method -> Preview -> Apply -> Verify -> Save/Report workflow.
- Made legacy mutation-capable CLI commands proposal-only; direct CLI invocation performs no display write.
- Added immutable, digest-bound apply plans, prior-state capture, bounded inputs, explicit confirmation, compensation, and read-back verification.
- Consolidated display writers behind one Windows adapter and removed application-layer actuator bypasses.
- Made the tray and calibration guard read-only, monitor-and-notify surfaces.
- Added evidence-labelled report values: measured, estimated, simulated, replayed, or **Not measured**.
- Removed seeded/random observations and unsupported accuracy grades from the desktop and report paths.
- Added read-only `doctor` diagnostics, including stable JSON output.
- Added a hash-locked Windows build, exact frozen-module allowlist, redistribution notices, source provenance, installer/portable packaging, manifest inspection, and frozen smoke tests.

## Least-privilege behavior

Both desktop executables start unelevated (`asInvoker`). An Apply is available only when the requested capability and authoritative prior-state capture are present. Rejected, expired, substituted, or unsupported plans perform no write. Hardware-dependent operations can remain unavailable on displays, drivers, or systems that cannot meet those checks.

## Evidence boundary

Sensorless results are estimates derived from characterization inputs; they are not measurements of the attached unit. Measured results require a supported instrument. Missing observations display as **Not measured**, and numeric report values carry an evidence kind and source receipt.

## Known limitations

- The packaged desktop release targets Windows x64.
- Display controls differ by monitor and driver; unsupported controls fail closed.
- Measured calibration requires a supported colorimeter.
- DWM LUT application remains unavailable unless authoritative prior-state capture is possible.
- Calibrate Pro does not promise a particular accuracy, gamut, or luminance result without recorded measurements from the attached display.
