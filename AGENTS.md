# AGENTS.md - Calibrate Pro

## Scope

This file applies to the `calibrate-pro` repository. Root workspace
instructions still apply; this repo is a public product-shaped Python package
for Windows display calibration.

## Product Boundary

Calibrate Pro is a display-calibration application and library surface. Keep the
public repo focused on color science, monitor control, LUT/profile generation,
verification reports, GUI/CLI workflow, and reproducible packaging.

Publishable surfaces:

- `calibrate_pro/` - package code.
- `tests/` - regression coverage for color math, calibration, platform, panel,
  LUT, native-loop, and verification behavior.
- `docs/`, `README.md`, `CHANGELOG.md`, `RELEASE_NOTES.md`, and
  `pyproject.toml` - public product and package posture.
- Bundled third-party runtime artifacts only when license files remain present
  beside them.

Keep local-only unless explicitly scrubbed:

- `.env`, `.env.*`, `.warden-safe-cache/`, local settings, generated logs, and
  build artifacts.
- Personal monitor profiles, measured reports, hardware dumps, screenshots,
  calibration exports, ICC/LUT outputs, and customer or device-identifying data.

## Editing Rules

- Treat Windows hardware paths, USB/colorimeter access, DDC/CI, DWM LUT loading,
  and startup persistence as side-effecting code. Do not run them during routine
  docs or package cleanup.
- Keep sensorless algorithms, measured calibration, and verification claims
  separated in docs; do not blur predicted accuracy with measured accuracy.
- Keep package metadata aligned with README install instructions and CLI entry
  points.
- Prefer targeted tests for the module touched; full GUI and hardware paths need
  explicit operator direction or safe mocks.

## Verification

For documentation or release-boundary changes:

```powershell
git diff --check
```

For a dependency-light package smoke check from this workspace:

```powershell
$env:PYTHONPATH = "C:\dev\public\pubscan\build-color;."
python -m pytest tests/test_color_math.py -q
```

For behavior changes after installing declared dependencies, run the narrow
test slice first:

```powershell
python -m pip install -e .
$env:PYTHONPATH = "C:\dev\public\pubscan\build-color;."
python -m pytest tests/test_lut_engine.py -q
python -m pytest tests/test_verification.py -q
```

Before committing or pushing, scan changed files for credential-shaped content
and confirm `.env` remains ignored.
