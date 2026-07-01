# Calibrate Pro Enterprise Readiness

Calibrate Pro is the measured-color flagship of Project Telos: it detects displays,
corrects them, and keeps a verifiable record of what changed and how far off the result
is. The goal is calibration that a person or an agent can request, inspect, and re-check
later — not a black-box "make it look right" button.

## Enterprise role

- Detect monitors and their DDC/CI capabilities, identify panel characteristics from the
  characterized-panel database, and apply corrections via DDC/CI and a system-wide 3D LUT.
- Produce durable, inspectable artifacts: `.cube` / `.clf` 3D LUTs, ICC v4 profiles, and
  an HTML verification report with CIE diagram, gamma curves, and gamut coverage.
- Keep calibration drift on the record so a later check can tell whether the display still
  matches the profile that was applied.

## Operator surface

- The `calibrate-pro` CLI exposes a 26-command surface (`detect`, `auto`, `ddc-info`,
  `verify`, `status`, `native-calibrate`, `restore`, `list-panels`, `patterns`, …).
- An 8-page PyQt6 GUI (default with no arguments).
- Within Project Telos, the `telos.display.calibration` MCP contract lets a host agent
  request a calibration, read the verification report, and recheck drift through the same
  action envelope the other flagships use. CLI and MCP share one surface.

## Context envelope and action receipt contribution

- A calibration action carries what it changed (DDC settings, the applied LUT/ICC) and the
  verification verdict (measured dE per patch set), so downstream context references the
  report and profile rather than re-deriving them.
- The side-effect class is a privileged local change (monitor state + DWM LUT), not an
  external call; the receipt records the profile applied and the measured result.
- Verification verdicts come from the patch-set grading (CIEDE2000 / CAM16-UCS). A run
  with no colorimeter reports its result as a model estimate, never as a measurement.

## Accuracy honesty (read this before quoting a number)

- **Sensorless mode is a panel-database model estimate, not a measured guarantee.** Without
  a colorimeter there is nothing to measure against on the specific unit.
- **The only measured-accuracy figure Calibrate Pro reports is ~3.7 dE via the i1Display3
  path** (CCMX-corrected). Do not present the sensorless estimate as if it were measured.

## Platform boundary and limits

- **Windows 10/11 only** today (DDC/CI, DWM LUT, hidapi, WMI). macOS is planned, not
  shipped. CI runs the pure-Python core cross-platform; hardware paths are exercised on
  Windows.
- **License:** Calibrate Pro Fair-Source License 1.0 — source-available, not open source;
  commercial competing use is reserved to the licensor.
- **Dependencies:** numpy, scipy, and the color-science library at the core; PyQt6 (GUI),
  hidapi (sensor), and others behind optional extras. The GUI/hardware/OS-LUT layers are
  boundary code over untyped native libraries; the color/calibration/verification core is
  type-checked and tested.

## Quality gates

`ruff check .`, `mypy` (core strict-typed; native adapters boundary-typed), and
`pytest --cov` run in CI on every push and pull request across Python 3.10–3.13. Releases
build a wheel and publish to PyPI via OIDC trusted publishing; no API token is stored.
Publishing is gated on the color-science dependency being resolvable on PyPI first.
