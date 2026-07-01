# Security Policy

## Supported

Calibrate Pro follows a rolling release. Until a 2.0 line exists, only the latest release
on the default branch is supported for fixes.

## Reporting a vulnerability

Report suspected vulnerabilities privately via GitHub Security Advisories — the
"Security" tab of this repository, then "Report a vulnerability". Do NOT open a public
issue for an unfixed vulnerability. Include the affected component and version, a
reproduction, and the impact. The maintainer will acknowledge within a stated window and
agree a disclosure date.

## Trust surface (the honest part)

Calibrate Pro requests administrator privileges and touches privileged Windows subsystems
to do its job. That is the real surface:

- **DDC/CI monitor control.** The tool writes to monitor OSD registers over DDC/CI to set
  picture mode, gamma, brightness, contrast, and RGB gains. A bug or hostile input here
  changes monitor state, not system state; `restore` resets to defaults.
- **DWM LUT injection.** System-wide correction installs a 3D LUT via the Windows Desktop
  Window Manager (with a VCGT gamma-ramp fallback). This runs with the elevation the app
  was granted; it does not persist code, only color-transform data.
- **Native USB HID to the colorimeter.** The i1Display3 driver reads device EEPROM
  (per-unit calibration matrices) over USB HID. It reads from the sensor; it does not
  flash or write device firmware.
- **Startup persistence.** Calibration can be re-applied on login via a Windows startup
  entry. This is a documented, user-visible mechanism, not a hidden one.

## What it does NOT protect against, and does NOT do

- **No ground truth without a colorimeter.** Sensorless mode is a model prediction, not a
  measurement. It cannot detect that a panel has drifted from its database profile. Only
  the measured (i1Display3) path compares against a real reading.
- **No network, no telemetry.** The core performs no network access and sends no data.
  Reports are written locally.
- **Not a driver-integrity tool.** Calibrate Pro trusts the Windows GPU/DWM stack and the
  monitor firmware it talks to; it does not attempt to verify their integrity, and a
  compromised driver or monitor firmware is outside its model.

## What counts as a vulnerability

- A path that lets untrusted input (a malicious panel profile, `.cube`/ICC/CCMX file, or
  DDC response) cause code execution, privilege escalation beyond the granted elevation,
  or a write outside the tool's own output locations.
- A crash or hang that leaves the display in an unusable state with no `restore` path.

## What does not count

- Sensorless prediction being less accurate than a measured result. That is documented
  behavior (sensorless is an estimate), not a vulnerability.
- A malformed input file that raises a normal, handled exception.
