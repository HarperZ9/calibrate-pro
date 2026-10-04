# Sensorless library path: consent, backup and startup (2026-10-01)

These changes ship in v2.0.1. The entries below moved under that release's
heading in `CHANGELOG.md` when it was prepared. The changelog carries no
`Unreleased` section by rule (`tests/test_version_pins_name_this_release.py`).

## What was wrong

`calibrate_pro.sensorless` is exported from the PyPI 2.0.0 library. It is not
reachable from the frozen CLI, which declines these commands.

- `one_click_calibrate` built `UserConsent(risk_level=HIGH,
  user_acknowledged_risks=True, hardware_modification_approved=True,
  backup_created=True)` itself, so a library caller got DDC/CI monitor writes with
  no user approval. `backup_created` was asserted, never checked.
- `run_calibration` ran `_auto_ddc_setup` on every call, before its own consent
  check, so picture mode, colour preset, gamma, brightness, contrast and black
  levels were written even with `apply_ddc=False`. The Windows suite reached this
  through `test_run_calibration_software_only`, on whatever monitor the
  developer had attached.
- `auto_calibrate_all` called `StartupManager.enable_startup(silent=True)`,
  which writes an HKCU Run key, without asking.

## Changelog entries for the next release

- Security: the sensorless library path no longer grants itself hardware consent.
  `one_click_calibrate` built a HIGH-risk `UserConsent` with `backup_created=True`
  asserted, so any caller got DDC/CI monitor writes with no user approval. It now
  takes `consent=` from the caller and runs software-only, with a warning, when
  none is approved. `run_calibration` also ran a DDC/CI OSD auto-setup on every
  call, consent or not, which wrote monitor controls even with `apply_ddc=False`
  (the Windows test suite did this on the developer's monitor). The auto-setup now
  runs only under approved consent.
- Every DDC/CI write now needs a backup the engine read itself. The backup covers
  every control the auto-setup and the correction step can write (colour preset,
  picture mode, gamma, black levels, gains, brightness, contrast), and a write is
  skipped, with a warning naming the missing controls, when any of them was not
  read. A caller's `backup_created` flag is no longer trusted.
- `restore_original_settings` writes back to the display the backup came from;
  it used to write to the first display whatever was calibrated. The backup read
  and the restore also passed a bare handle where `get_vcp`/`set_vcp` index the
  monitor dict, so both raised `TypeError` on real hardware.
- `auto_calibrate_all` asks before it writes the HKCU Run key. It takes
  `confirm_startup(prompt)` and writes the key only on True; without it the key
  is left alone and the first result says so. It also takes `consent=`, either one
  `UserConsent` or a per-display callable.

## Limits

- The consent object is not bound to a display or a time window. A caller that
  holds one approved `UserConsent` can reuse it; binding it is follow-up work.
- `one_click_calibrate` still installs an ICC profile and applies a LUT without
  consent by default. Both are Windows colour-management state the user can
  restore, not monitor hardware, and they were out of this change's scope.
