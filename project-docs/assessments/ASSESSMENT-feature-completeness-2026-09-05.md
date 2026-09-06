# Calibrate Pro 2.0.0: launch test and domain feature-completeness

Date: 2026-09-05. Subject: the frozen `CalibratePro-2.0.0-win64.zip` built from
`979bf55`, hash `e069efb7...f667ec`, matching `SHA256SUMS.txt`. Runtime numbers
came from running that binary or from executing the shipped library. Capability
claims are cited to source files in the tree at that commit.

## Correction notice

An earlier revision of this document concluded that 2.0.0 "is not a competitor in
the same category" as ArgyllCMS, DisplayCAL, Calman, ColourSpace, i1Profiler and
Spyder, and named `novideo_srgb` as the honest comparator. That conclusion was
wrong. It was derived from the frozen build's enabled action surface and then
stated as a fact about the codebase, which is a different claim and one the
source contradicts. Three further statements in that revision were also wrong and
are corrected in place below: that `SetDeviceGammaRamp` appears nowhere in the
source, that the CCMX and CCSS parser is dead code, and that uniformity mapping is
absent.

## Verdict

Every stage of the measure, correct, apply, re-measure loop is implemented in this
repository. Instrument drivers, a patch-measurement loop, correction-matrix and
LUT construction, a transactional display-actuation layer with capture and
restore, and a runner that ties apply to verification are all present and carry
318 tests across 11,660 lines of test code. The shipped 2.0.0 build enables none
of it, because `calibrate_pro/application/session.py:205` and `:206` hardcode
`physical_apply_qualified=False` and `measured_qualified=False`.

The distance between 2.0.0 and the products it is written to replace is an
acceptance run on real hardware plus session-layer wiring. It is not a missing
capability. A user who installs the released binary today gets the sensorless
path, and findings 1 through 3 below describe what that path does and where it is
weaker than its labelling suggests.

## What is built

| Layer | Location | Lines | Evidence |
| --- | --- | --- | --- |
| Instrument drivers | `calibrate_pro/hardware/` (17 files) | 10,157 | `i1d3_native.py` drives i1Display3 / Pro / Plus, ColorMunki Display, Calibrite ColorChecker Display and NEC MDSVSENSOR3 over raw HID at VID `0x0765` PID `0x5020`. `spyder_native.py` carries `SPYDER_X_MATRIX`, `SPYDER_X2_MATRIX`, `SPYDER_5_MATRIX`. `argyll_backend.py` is a second route. `ddc_ci.py` is 1,637 lines |
| Measurement loop | `calibrate_pro/calibration/native_loop.py` | 413 | `profile_display()` drives a ramp, normalizes TRC, estimates gamma; `compute_ccmx()`, `build_correction_lut()`, `compute_de()` |
| Instrument correction | `calibrate_pro/calibration/ccss_import.py` | 361 | `load_ccmx`, `load_ccss`, `apply_ccmx`, `_BUILTIN_CORRECTIONS`, consumed by `native_loop.QDOLED_CCMX` and covered in `test_professional_features.py` |
| Apply path | `calibrate_pro/adapters/windows_display_state.py` and `calibrate_pro/actuation.py` | 4,847 | `ActuationCoordinator` with an injected adapter, `capture_dwm_luts` / `set_dwm_luts`, SHA256-exact asset reads, staged validation before write, transactional capture and restore |
| LUT load routes | `calibrate_pro/lut_system/` | 7,332 | `dwm_lut.py` 1,243, `nvidia_api.py` 1,138, `amd_api.py` 1,374, `intel_api.py` 350, `vcgt_calibration.py` 459 |
| Measured runner | `calibrate_pro/calibration/measured_runner.py` | 231 | `apply_and_verify()`, `select_exact_display()`, `validate_run_evidence()`, a `DwmPort` protocol with `apply` / `unload` / `has_active_lut` |
| Uniformity | `calibrate_pro/advanced/uniformity.py` | 820 | 5x5 and 9x9 grids, `UniformityAnalyzer`, `UniformityCompensator`, `UniformityCorrectionLUT` |
| Ambient compensation | `calibrate_pro/advanced/ambient_light.py` | 916 | `AmbientReading`, `AmbientCondition` |

Total in the measure and apply stack: 24,759 lines across four packages.

`SetDeviceGammaRamp` is called from `core/vcgt.py:473`, `lut_system/color_loader.py:443`,
`lut_system/vcgt_calibration.py:178` and `panels/detection.py:2267`, and declared in two
more modules. The earlier revision's statement that it appears nowhere came from tracing
the guard service alone and generalizing from one component to the source tree.

Test weight on this stack:

| File | Lines | Tests |
| --- | --- | --- |
| `test_windows_display_state_adapter.py` | 9,521 | 238 |
| `test_actuator_boundary.py` | 539 | 8 |
| `test_ddc_ci_safety.py` | 473 | 12 |
| `test_unmeasured_results_refused.py` | 278 | 14 |
| `test_measured_artifacts_are_measured.py` | 273 | 16 |
| `test_measured_runner.py` | 223 | 10 |
| `test_native_loop.py` | 159 | 12 |
| `test_spyder_patch_display.py` | 102 | 5 |
| `test_i1d3_protocol.py` | 92 | 3 |
| Total | 11,660 | 318 |

`test_windows_display_state_adapter.py` is the largest test file in the repository. It
exercises the apply path through the real `ActuationCoordinator` against a recording
adapter, including opcode-level cancellation injection on 3.12 and 3.13.

## Why the shipped build enables none of it

The gate is two literals with a comment stating the standard they are held to
(`application/session.py:199-206`):

```
# Both qualifications are false for the whole of this phase and are
# not session state. No physical mutation path has passed its
# acceptance evidence, and measured calibration needs an instrument
# this build does not drive. Reading them from the session would
# let a caller talk itself into a qualification it does not have.
physical_apply_qualified=False,
measured_qualified=False,
```

`application/actions.py:596-632` turns those flags into per-action refusals, each
naming what is outstanding: `"DDC/CI physical mutation is not qualified."`,
`"Physical mutation remains disabled pending the Phase 2 transactional contract."`,
`"Measured calibration requires a distinct qualified measurement contract."`

`application/fake_acceptance.py` states the standard directly: "Production performs no
physical mutation, so the apply path would otherwise ship untested," and "A test that
wants the physical path still needs hardware and an acceptance run."

The gating tightened on this branch rather than being inherited. `0fc0df8` on
2026-09-05 removed three surfaces that reached an instrument outside the session,
including a dashboard card that opened the colorimeter over raw HID and polled it every
800ms for luminance, correlated colour temperature and XYZ. Those readings were real.
They were removed because they bypassed the layer that decides whether a measurement
may be taken, attaches an evidence kind, issues a receipt, and records that it happened.

`main.py:52` marks three CLI names as having no declared action behind them:
`auto`, `match`, `uniformity`. Even that set overstates absence, since
`advanced/uniformity.py` implements the analysis at 820 lines. The set means no
declared action, not no code. The other eleven declined names map to actions the
manifest carries and this build has not qualified (`main.py:28-50`).

## Launch test

The frozen binary was extracted from the release zip after hash verification and
run with no arguments. The window opened at 1216x844, titled `Calibrate Pro
v2.0.0`.

No display was mutated. The guard service opens `CreateDCW` and
`GetDeviceGammaRamp` only. `StartupManager.__init__` reads the Run key and writes
nothing. The three `CalibratePro*` entries in `HKCU\...\Run` still point at
`C:\Users\Zain\QUANTA-UNIVERSE\calibrate\dist\...`, a dead 1.x install path, so
2.0.0 wrote no persistence.

The dashboard holds the PRODUCT.md rule at runtime. On this machine, whose panel
is absent from the bundled database, it reported `Panel not characterized`, `Peak
luminance: Not measured`, all three gamut bars `Not measured`, `Calibration: Not
measured`, and `No colorimeter detected`. Nothing was filled with an ideal.

The end-to-end sensorless path completes. Driving the service headlessly through
METHOD, PREVIEW, VERIFY produced a sealed bundle: `Calibrate_Pro.cube` at 970,450
bytes, `Calibrate_Pro.icc` at 8,296 bytes, and a manifest carrying SHA256s,
`evidence_kind='estimated'`, `characterization_kind='explicit_generic'`.
Throughout, `physical_apply_performed=False`, `ddc_changes=()`, and
`dwm_lut_path=None`.

### Shipped capability surface, counted

| Measure | Value |
| --- | --- |
| Declared actions | 93 |
| Frozen policy: enabled / conditional / hidden / disabled | 21 / 29 / 10 / 33 |
| Reported by the running binary | 26 of 93 available |
| `physical_mutation` actions enabled | 0 of 9 (8 disabled, 1 hidden) |
| Measurement-capable actions enabled | 0 of 11 (10 disabled, 1 hidden) |
| Selectable calibration targets | 4 |
| Targets in the reference catalogue, not selectable | 13 |
| Panels in the database | 58 selectable, 59 including `GENERIC_SRGB` |
| CLI commands frozen / developer-only / declined | 9 / 7 / 14 |

## Three findings on the path that does ship

These describe the sensorless path, which is the only route a 2.0.0 user can run.
They stand unchanged from the earlier revision.

### 1. The predicted accuracy figure is computed with the display removed

`NeuralUXEngine.verify_calibration()` builds
`correction_matrix = inv(panel_to_xyz) @ srgb_to_xyz` at `neuralux.py:185`, then at
step 5 of the verification chain left-multiplies by `panel_to_xyz`. Those cancel
exactly. Steps 3 and 4 raise to `1/panel_gamma` and back to `panel_gamma`, which
also cancels. Every panel term leaves the algebra.

Reducing the chain by hand and computing it with no panel involved gives
`avg dE2000 = 0.6451695974`, `max = 2.9185615658`. That is the residual between
the model's 2.2 power law and the true piecewise sRGB EOTF carried by the 24
ColorChecker reference patches, and nothing else.

Sweeping the real `verify_calibration()` over all 58 database panels gives an
average dE range of 0.6452 to 0.6459, standard deviation 0.0002, with the
panel-free value sitting exactly at the floor. The only panel-dependent term left
is gamut clipping, which moves the fourth decimal.

The number a buyer reads as "how accurate will my display be" is a constant of
the correction model. It is labelled `estimated` everywhere it appears and is
withheld entirely for three of the four targets, so nothing is misrepresented as
measured. It still carries no information about the display.

**Resolved after this assessment.** `calibrate_pro/application/prediction.py` now
runs a reference sRGB display through the same chain and subtracts it, so the
ColorChecker round-trip cancels and what is left is the part the panel record
determines. A reference display scores 0.0. A panel narrower than the target
scores 0.2774 average and 3.3931 maximum. A panel with a D50 native white scores
0.3656 and 8.7732. The quantity is named `gamut reproduction, modelled` on every
surface that prints it, and the note beside it states that tone response is
outside the number, so a display whose grey tracks nothing like its record scores
the same as a perfect one. `tests/test_predicted_verification.py` carries the
controls, including a sweep of every distinct gamut in the shipped database
against the constant they all used to report. The frozen binary this document
tests still has the old behaviour.

### 2. For an unrecognized panel the generated 3D LUT is an exact identity

The generic path is the only route available when a panel is absent from the
database, which is the common case for any display outside the enthusiast segment
the database covers. Parsing the 970 KB `.cube` it produces: `LUT_3D_SIZE 33`,
35,937 rows as required, values in [0,1], no NaN. Compared against a true identity
lattice, **0 of 107,811 entries differ**, at a tolerance of 1e-9.

The product hands an unrecognized display a 970 KB file that performs no
transformation.

### 3. For a recognized panel the correction is real, and clusters

Across the 59 database entries, `max|M - I|` for the correction matrix has median
0.126 and maximum 0.276. Nine entries are exact identities. Sixteen fall below
0.001, which is not a correction anyone can see. The remaining 43 cluster near
0.27, which is the wide-gamut to sRGB clamp.

The function of the sensorless path is gamut clamping for wide-gamut panels,
selected by database lookup. The clamp lives in the 3D LUT, and a 3D LUT is the
one artifact Windows cannot load through an ICC. The `vcgt` tag carries
per-channel 1D curves only, so it cannot express the 3x3. The DWM and vendor GPU
routes in `lut_system/` are what load a 3D LUT, and they are behind the apply gate.

The ICC itself is well formed: `acsp` magic, `mntr` class, RGB to XYZ, 11 tags
including `rXYZ`/`gXYZ`/`bXYZ`/`wtpt`, a `chad` adaptation tag, three 1024-point
`curv` TRCs, and `vcgt`.

## Feature completeness against the domain

Comparator column confidence: **moderate**, from established capability of
long-standing products rather than from a run performed here. No prices or version
numbers are asserted. The Calibrate Pro columns are **high** confidence, each read
from source or executed against the shipped build.

| Domain capability | Built in the repository | Enabled in 2.0.0 | Domain norm |
| --- | --- | --- | --- |
| Colorimeter support | Yes. Native HID for the i1Display and Spyder families plus an ArgyllCMS route, 10,157 lines, `hidapi` shipped under the `[sensor]` and `[all]` extras | No. 11 measurement actions hidden or disabled | Defining feature |
| Measurement patch loop | Yes. `native_loop.profile_display()`, 12 tests | No | Standard |
| CCMX / CCSS instrument correction | Yes. `ccss_import.py` parses both, ships built-in corrections, consumed by `native_loop` | Not reachable while measured calibration is closed | Standard where colorimeters are supported |
| Calibration targets selectable | 17 in the catalogue | 4 (sRGB D65 2.2, Rec.709 BT.1886, DCI-P3 2.4, sRGB D50) | Rec.709, BT.1886, DCI-P3, Display P3, Adobe RGB, Rec.2020 |
| HDR targets (PQ, HLG) | Defined in the catalogue, `hdr/` is 5,106 lines | Not selectable | Standard in grading tools |
| 1D LUT / TRC generation | Yes | Yes, 1024-point curves in the ICC | Standard |
| 3x3 matrix generation | Yes | Yes | Standard |
| 3D LUT generation | Yes | Yes, 33-point `.cube` | Standard in grading tools |
| Applying the correction | Yes. `ActuationCoordinator` plus a transactional adapter, DWM and NVIDIA and AMD and Intel LUT routes, VCGT and gamma-ramp writes, 238 tests through the real coordinator | No. 0 of 9 mutation actions enabled, pending an acceptance run | Defining feature |
| ICC profile creation | Yes | Yes, valid and complete | Standard |
| ICC installation and activation | Yes, `profiles/profile_installer.py` | No, `profile.install` and `profile.activate` disabled | Standard |
| Verification against measurement | Yes. `measured_runner.apply_and_verify()` and `native_loop.compute_de()` | No | Defining feature |
| Predicted accuracy reported | Yes | 1 of 4 targets, others return `None` with a limitation string | Measurement products report measured dE |
| DDC/CI display control | Yes, `ddc_ci.py` 1,637 lines with a 473-line safety suite | No, `ddc_changes=()` on every run | Common |
| Uniformity mapping | Yes, `advanced/uniformity.py` 820 lines, 5x5 and 9x9 grids | No declared action | Present in higher-tier tools |
| Ambient light compensation | Yes, `advanced/ambient_light.py` 916 lines | Not reachable from a shipped action | Present in several tools |
| Drift monitoring | Yes, `CalibrationGuard` plus `hardware/drift_compensation.py` | Monitor-only, registered with `vcgt_red` unset so `_check_and_restore` returns immediately | Present in several tools |
| Automation / CLI | 30-command parser in `main.py` | 9 commands, and none reaches `use_generic_characterization` | Varies |
| Evidence provenance labelling | Yes | Yes. Every displayed quantity carries `not_measured` / `estimated` / `measured` | **No comparator does this** |

### Where it actually sits

The comparison to ArgyllCMS, DisplayCAL, Calman, ColourSpace, i1Profiler and Spyder is
the right one. This repository implements the same loop those products implement, with
a transactional apply layer and a capture-and-restore contract that several of them do
not offer, and with an evidence discipline none of them has. What separates 2.0.0 from
them is that they ship the loop open and this build ships it closed.

The closure is deliberate and its standard is written down. The apply path has been
proven for ordering and gating against a recording adapter and has never been run
against a display under acceptance conditions. The measured path has drivers, a
measurement loop and a runner, and no assembled route from a session to them. Shipping
either one open without that evidence would break the rule the whole 2.0.0 branch was
built to enforce.

`novideo_srgb` describes what a user can do with the released binary today, minus the
apply. Naming it as the comparator for the product was the error, because it compares a
tool to a release configuration rather than to the thing that was built.

## What qualification actually requires

Ranked by what stands between the current tree and an open loop.

1. **An acceptance run for the apply path.** One run through
   `WindowsDisplayStateAdapter` against a real display, with capture verified before the
   write and restore verified after, is what `physical_apply_qualified` is waiting on.
   The recording proof in `fake_acceptance.py` already covers ordering and gating, and
   its own docstring names hardware as the remaining half.
2. **A session route to the measured runner.** `measured_runner.apply_and_verify()`
   takes a `DwmPort`; `WindowsDisplayStateAdapter` exposes `set_dwm_luts` and
   `capture_dwm_luts` rather than that shape. The adapter between the two is the missing
   code. `hardware_first.py` sits in `WRITER_CAPABLE_MODULES` in
   `test_actuator_boundary.py`, so any wiring has to arrive through `ActuationCoordinator`
   and not by importing it from an application surface.
3. **One instrument acceptance run.** A single supported colorimeter carried end to end
   turns `estimated` into `measured` and converts the evidence layer from a disclaimer
   into the product's strongest feature.
4. **Derive the two flags.** `session.py:205-206` become a derivation over recorded
   acceptance evidence once 1 through 3 exist. Until then the literals are correct.
5. **Fix or withdraw the predicted-accuracy figure.** As built it is a constant.
   Withdrawing it costs little, because it is already withheld for three of four targets.
   A measured path supersedes it entirely.
6. **Make the generic path do something, or refuse it.** Shipping an identity LUT under a
   filename implying a correction is where the product's own PRODUCT.md rule is strained.
7. **Reach the generic path from the CLI.** A one-flag change in `session_args.py`.

Items 1 through 3 are the release-blocking set. Items 5 through 7 are defects in the path
that ships today and are independent of the gate.

## The asset worth keeping

The evidence-provenance layer is differentiated. Nothing else in this domain
distinguishes a measured quantity from a modelled one at every display site and refuses
to print a number it cannot source. The launch test confirmed it holds under real
conditions on an unrecognized panel. That discipline is why findings 1 through 3 are
visible from inside the product rather than hidden behind plausible defaults, and it is
the reason the loop is closed rather than shipped unqualified.

## Addendum, 2026-09-05: what the branch changed after this test ran

Everything above describes the frozen `CalibratePro-2.0.0-win64.zip` built from `979bf55`,
and it is left as the record of that artifact. `feat/flagship-completion-20260904` has since
built the qualification the two hardcoded literals were standing in for, so the following
statements in the body no longer describe the tree.

- `session.py` no longer hardcodes `measured_qualified=False`. The property now reads a
  wired measurement port together with what the capability probe found on the selected
  display, so a session answers True when an instrument actually answered on USB.
- `action-capabilities.json` declares `calibration.method.measured`, `calibration.measure`
  and `verification.measured` conditional in the wheel and in the frozen binary. Their
  reasons name the conditions rather than a pending contract.
- The measured path exists end to end: `application/measurement.py` runs the ramps,
  `adapters/qt_patch_presenter.py` puts the patches on the selected screen,
  `application/correction_state.py` refuses a run against a display that is loading a gamma
  table other than identity, and `application/measured_verification.py` reports the result
  from a second reading.
- The window carries a Measure Display control and a measured method card that perform.
  The terminal still has no measure command, so item 7's observation about CLI reach is
  unchanged for the measured path.

Item 4 of the recommendations is therefore closed by construction rather than by deriving
the literals: there are no literals left to derive. Items 5 through 7 remain open. The
acceptance run against a real display and a real colorimeter has not been performed, so
nothing here reports an instrument result.
