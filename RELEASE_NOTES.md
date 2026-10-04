# Calibrate Pro v2.0.1

Calibrate Pro 2.0.1 is a patch release. It closes a consent gap in the sensorless
Python library and refreshes the README and brand art. The desktop application and
the command line behave as they did in 2.0.0.

## Download

- `CalibratePro-2.0.1-Setup.exe`: per-user Windows x64 installer.
- `CalibratePro-2.0.1-win64.zip`: portable Windows x64 package.
- `calibrate_pro-2.0.1-py3-none-any.whl`: Python package for supported source installs.

The Windows packages include Python, Build Color, Build UI 2, PySide6/Qt, NumPy, SciPy, hidapi, and approved `dwm_lut` runtime files. They do not require Python, pip, Git, or network access after download.

The 2.0.1 Windows artifacts are not Authenticode-signed. Windows may display a SmartScreen warning; verify downloads against the release's `SHA256SUMS.txt` before execution.

## Who should upgrade

Callers of the `calibrate_pro.sensorless` library from the 2.0.0 package should
upgrade. The frozen CLI does not reach those commands, so installer and portable
users were not exposed.

## Security fix: the sensorless library path no longer grants itself hardware consent

- `one_click_calibrate` used to build a HIGH-risk `UserConsent` with `backup_created=True`
  asserted, so a library caller got DDC/CI monitor writes with no user approval. It now
  takes `consent=` from the caller and runs software-only, with a warning, when none is
  approved.
- `run_calibration` ran a DDC/CI OSD auto-setup on every call, whatever the consent said.
  The auto-setup now runs only under approved consent.
- Every DDC/CI write needs a backup the engine read itself, covering every control the
  auto-setup and correction step can write. A missing control skips the write and names it.
  A caller's `backup_created` flag is no longer trusted.
- `restore_original_settings` writes back to the display the backup came from, and the
  backup read and restore no longer raise `TypeError` on real hardware.
- `auto_calibrate_all` asks before it writes the HKCU Run key, through
  `confirm_startup(prompt)`, and takes `consent=` as one value or a per-display callable.

## Brand and art refresh

The README opens on a light and dark hero in the shared art direction. Marks, lockups,
the README header and a 1280 x 640 social preview ship under `docs/art` and `docs/brand`,
each PNG with a receipt in `docs/art/receipts.json`.

## Evidence boundary

Sensorless results are estimates derived from characterization inputs; they are not measurements of the attached unit. Missing observations display as **Not measured**, and numeric report values carry an evidence kind and source receipt.

## Known limitations

- The packaged desktop release targets Windows x64.
- Display controls differ by monitor and driver; unsupported controls fail closed.
- The consent object is not bound to a display or a time window, so a caller holding one approved `UserConsent` can reuse it.
- `one_click_calibrate` still installs an ICC profile and applies a LUT without consent by default. Both are Windows colour-management state the user can restore, not monitor hardware.
- Calibrate Pro does not promise a particular accuracy, gamut, or luminance result without recorded measurements from the attached display.

The full 2.0.0 notes are in the v2.0.0 GitHub release.
