# Calibrate Pro v2.0.0

Calibrate Pro 2.0 removes the numbers the product used to supply on its own. An earlier
release met a failed read with a plausible default and printed it where a reading goes.
This one reports the absence.

## Download

- `CalibratePro-2.0.0-Setup.exe`: per-user Windows x64 installer.
- `CalibratePro-2.0.0-win64.zip`: portable Windows x64 package.
- `calibrate_pro-2.0.0-py3-none-any.whl`: Python package for supported source installs.

The Windows packages include Python, Build Color, Build UI 2, PySide6/Qt, NumPy, SciPy, hidapi, and approved `dwm_lut` runtime files. They do not require Python, pip, Git, or network access after download.

The 2.0.0 Windows artifacts are not Authenticode-signed. Windows may display a SmartScreen warning; verify downloads against the release's `SHA256SUMS.txt` before execution.

## Why the major version

Report fields typed `float` now carry `None` when nothing was observed, and the JSON
report emits `null` in their place. A parser that assumed a number in `volume_ratio`,
`volume_lab`, `total_volume_lab`, `white_point_cct`, `white_point_duv`,
`sdr_white_level`, `brightness_adjustment`, `final_measured_delta_e`, or
`final_measured_delta_e_max` needs a null branch. Four fields were also renamed. See
Breaking changes below.

## What a value now says about itself

A quantity the session could not observe reads **Not measured** on every surface that
prints it, and the JSON emits `null`. The cases that used to print something else:

- A white point nobody read reported 6504 K at a Duv of 0.0000, which passes on both
  counts.
- A gamut volume whose hull computation failed reported zero, and a run given no samples
  published a coverage ratio of 1.00, meaning a volume identical to the target.
- An absent red, green, or blue primary was scored against the target primary of the
  space being scored, so the delta came out at exactly 0.0.
- A Windows SDR white level the OS declined to give reported 200 cd/m2.
- An EDID that states no gamma reported 2.2, and the profile note read the same whether
  byte 23 was read or assumed.
- A panel built from EDID reported a 250 cd/m2 peak, a 0.1 cd/m2 black, and a contrast
  ratio of 1000. EDID carries none of that. Those numbers divided the target luminance
  that produces the DDC/CI brightness byte.
- A community panel file filled every absent capability on import, so photometry nobody
  submitted arrived under a submitter name and a measurement date.
- A hybrid run against the simulated model reported its near-zero result under the
  measured Delta E field. The engine now stamps the source on every result.
- A verification that measured none of its patches averaged an empty list to 0.0 and
  reported a passing grade.
- A fleet job queued against a remote node returned a Delta E mean of 1.2 with a pass
  flag. There is no transport to a node.

## What now refuses instead of guessing

- A measured ICC profile substituted the Rec.709 primaries and D65 for any chromaticity
  the sweep failed to produce, then wrote the file under a name ending `_measured.icc`.
  A missing primary raises and names it.
- A measured LUT read the panel database entry rather than the sweep it was handed, so
  two displays of the same model got identical corrections whatever the instrument read.
  It is now built from the measured chromaticities and the gamma fitted to the measured
  ramp.
- A colorimeter sweep read the screen without putting the patch on it, once per patch,
  and filed each reading under a different stimulus. Every measurement path now requires
  a patch display callback and reads after the panel settles.
- An HDR LUT divided by a peak luminance of zero, filling the grid with `inf` and `nan`
  and writing that out as a calibration file.
- A gamma fit answered 2.2 when it had too few points, and clamped whatever the least
  squares produced into 1.8 to 3.0.
- CRI and TLCI returned 95.0 and 90.0 for every spectrum handed to them.
- The ambient light sensors returned 300 lux whether or not a sensor was present.

## Corrections that reach the display

Four defects moved pixels rather than a readout.

- The EDID correction matrix grew its diagonal as a primary sat further from sRGB, which
  is backwards. It now follows sRGB to XYZ to native RGB, the derivation the sensorless
  and NeuraLux paths already use.
- The ICC `para` tone curve parser read every function type as the type 0 pure gamma, so
  types 1 through 4 lost their linear segment near black and the wrong curve reached the
  gamma ramp. Only type 0 is decoded now.
- A display fingerprint matched on resolution and refresh rate alone, so every
  3440x1440 at 175 Hz panel was reported as one specific monitor and its native gamma
  built the correction curve. Matching now requires the EDID manufacturer.
- HDR and wide gamut were read off the display mode, and the wide gamut test compared
  `dmBitsPerPel` against 10, which never failed. Every unmatched display came back wide
  gamut and was calibrated toward a color space it cannot reach.

## New in this release

- A headless calibration session. `detect`, `status`, `verify`, `generate-profiles`, and
  `profiles` drive the same actions the window drives, over one service, and a refusal
  arrives in the words the session refused it in. `CalibrateProCLI.exe` answers nine
  commands in the frozen binary and names the package the rest live in.
- `diagnostics`, which reads back the redacted journal every action writes to. It lists
  each file a support bundle would carry with its digest, publishes exactly those bytes
  with `--bundle PATH`, and opens the folder with `--open`. The same three actions are on
  the settings page under Diagnostics.
- Bundle read-back. `profiles` recomputes each digest from the bytes on disk, so a bundle
  whose files changed is reported as changed rather than listed as published.
- `doctor` in a form a person reads. Dependencies with versions, the three
  whole-installation checks, and a capability block that states nothing was probed.
  `--json` is unchanged.
- A plan preview in the window, with Accept and Decline bound to the resolver. Accepting
  records the digest and sends nothing to the display, which the dialog states beside the
  button.
- A dashboard row saying how the session characterized the display it holds, with the
  generic-characterization control beside it, so a display the panel database cannot name
  has somewhere to go.
- LUT size as a declared, journalled preference that the next bundle reads and records in
  its own manifest.
- A release version that derives from one declaration, so the build scripts, the release
  workflow, the installer, and the artifact names cannot disagree about which release
  they are.

## Breaking changes

Callers of the Python package should read this section. The desktop application and the
command line are unaffected.

**Widened to `float | None`, and `null` in the JSON report.** Each is `None` when the
quantity was not computed or not read:

| Field | Class |
| --- | --- |
| `volume_ratio`, `volume_lab` | `verification.gamut_volume.GamutCoverage` |
| `total_volume_lab`, `white_point_cct`, `white_point_duv` | `verification.gamut_volume.GamutAnalysisResult` |
| `sdr_white_level` | `display.hdr.HDRDisplayState` |
| `brightness_adjustment` | `calibration.multi_display.DisplayTarget` |
| `final_measured_delta_e`, `final_measured_delta_e_max` | `calibration.hybrid.HybridCalibrationResult` |

**Renamed fields.**

- `hardware.ddc_ci.HardwareCalibrationResult.delta_e` is now `delta_uv`. The white point
  loop computes a chromaticity distance in the CIE 1976 u'v' plane, which a reader was
  comparing against Delta E tolerances that do not share its scale. Roughly 0.002 is a
  just noticeable white point shift.
- `hardware.hardware_calibration.MeasurementResult.a` and `.b` are now `lab_a` and
  `lab_b`, beside a new `lab_l`. The Lab `b` component shared a field with the blue
  stimulus on the same record, so computing Lab overwrote the blue value the patch had
  been asked for.

**Removed parameters that steered nothing.** `profiles.mhc2.generate_mhc2_profile` no
longer accepts `target_white_luminance`, `peak_luminance`, or `min_luminance`. The tag it
writes is matrix type 1, which has no field for any of them.

**Changed default.** `panels.database.create_from_edid` takes `gamma: float | None = None`
in place of `gamma: float = 2.2`, and returns a `PanelCharacterization` whose note says
whether the gamma was read or assumed.

**Added export.** `calibrate_pro.hardware.DDCCalibrationResult` names the DDC/CI result
class, which a second class of the same name had left unreachable through the package.
`HardwareCalibrationResult` still resolves to the calibration engine's class, which is
what it resolved to before.

## Least-privilege behavior

Both desktop executables start unelevated (`asInvoker`). An Apply is available only when the requested capability and authoritative prior-state capture are present. Rejected, expired, substituted, or unsupported plans perform no write. Hardware-dependent operations can remain unavailable on displays, drivers, or systems that cannot meet those checks.

## Evidence boundary

Sensorless results are estimates derived from characterization inputs; they are not measurements of the attached unit. Missing observations display as **Not measured**, and numeric report values carry an evidence kind and source receipt.

## Known limitations

- The packaged desktop release targets Windows x64.
- Display controls differ by monitor and driver; unsupported controls fail closed.
- Measured calibration is closed in 2.0. The action manifest declares `calibration.method.measured` and `verification.measured` disabled in both builds, pending a distinct qualified measurement contract, so a supported colorimeter does not open it. Every result 2.0 produces is sensorless and labelled estimated.
- DWM LUT application remains unavailable unless authoritative prior-state capture is possible.
- Calibrate Pro does not promise a particular accuracy, gamut, or luminance result without recorded measurements from the attached display.
