# Spec: one-click closed-loop calibration

Date: 2026-11-04. Status of the code: the simulated slice in section 6 is built and tested. Everything else here is design.

## 1. The problem

A user should be able to state what a display ought to be, approve one plan, and have Calibrate Pro measure the panel, drive its own hardware controls over DDC/CI, re-measure, and repeat until the result is inside tolerance or a stop rule says it cannot get closer. The same statement of intent has to work for SDR and HDR, for a 250 cd/m2 office LCD and a 1,000 cd/m2 mini-LED, and for panels with different controls. Where a panel cannot reach the intent, the software clips the target to what the panel can do and says so, instead of chasing a value it will never reach.

The existing workflow boundary stays: Detect, Method, Preview, Apply, Verify, Save/Report, with explicit confirmation before any display write. The existing evidence boundary stays: every number is labelled measured, estimated, simulated, replayed or Not measured.

## 2. Standards the intent maps onto

Sources read for this spec, all primary or open, fetched with the user agent `research-fetch/1.0`:

| Source | Used for |
|---|---|
| Rec. ITU-R BT.709-6 | BT.709 primaries (0.640, 0.330), (0.300, 0.600), (0.150, 0.060) and D65 white (0.3127, 0.3290) |
| Rec. ITU-R BT.2020-2 | BT.2020 primaries (0.708, 0.292), (0.170, 0.797), (0.131, 0.046) |
| Rec. ITU-R BT.1886-0 | SDR reference EOTF: exponent 2.40, screen white LW, screen black LB, reference LW = 100 cd/m2 |
| Rec. ITU-R BT.2100-3 | PQ and HLG; reference viewing environment (5 cd/m2 surround, 1,000 cd/m2 peak, 0.005 cd/m2 black, Table 3); HLG system gamma 1.2 at 1,000 cd/m2 and 1.2 + 0.42 log10(LW/1000) otherwise (Note 5f); HDR Reference White 203 cd/m2 (Note 10a) |
| Rec. ITU-R BT.2124-0 | Delta E ITP: ICtCp with T = 0.5 Ct, scaled by 720 so 1 is a just noticeable difference under the most sensitive adaptation |
| ICC.1:2022-05 | Profile connection space with a D50 adopted white; adaptation from the display white recorded in `chromaticAdaptationTag` |
| VESA DisplayHDR performance criteria page, CTS 1.2 (May 2024) | Tier peaks 400 to 1,400 cd/m2; 99 % BT.709 and 90 % or 95 % DCI-P3 coverage; maximum Delta ITP of 20 at 1 and 5 cd/m2, 15 at 15 cd/m2, 10 at 50 cd/m2 and above |
| ArgyllCMS `dispcal` documentation | Display-control adjustment before calibration; LCD contrast controls usually act on the signal and are best left at neutral; LCD brightness drives the backlight; refinement passes limited by instrument accuracy and repeatability |

Written from memory of common practice, with no document read for it (moderate confidence): Calman and ColourSpace both run a pre-calibration hardware step (white balance at a two-point or multi-point grayscale with the display's own controls), then profile and build a 3D LUT, then verify on a separate patch set, and both interleave reference white reads to correct drift during long runs. Calibrate Pro's `calibrate_pro/hardware/drift_compensation.py` already implements that interleaved-reference correction.

## 3. Display intent

### 3.1 Format

A `DisplayIntent` (`calibrate_pro/calibration/closed_loop/intent.py`) holds:

| Field | Meaning |
|---|---|
| `white_xy` | Target white chromaticity, CIE 1931 2 degree. Default D65. |
| `white_luminance` | SDR: diffuse white in cd/m2. HDR: peak in cd/m2. |
| `black_luminance` | Target black in cd/m2. Zero means as deep as the panel goes. |
| `eotf` | `srgb`, `gamma`, `bt1886`, `pq` or `hlg`. |
| `gamma` | Exponent for `gamma` and `bt1886`. |
| `gamut` | `srgb`, `display_p3` or `bt2020`. |
| `min_gamut_coverage` | Coverage goal as a share of the target triangle's u'v' area. |
| `tolerances` | Per patch class: white, gray and color, in dE2000 for SDR and Delta E ITP for HDR, plus a relative luminance bound on white. |
| `observer` | Reserved. Only `cie1931_2deg` is accepted today. See 3.4. |

Default tolerances are a choice made in this spec: white 1.0, gray 2.0, color 3.0 dE2000; white 5, gray 8, color 10 Delta E ITP; white luminance within 3 %. The HDR color bound matches the DisplayHDR ceiling for 50 cd/m2 and above, so a calibrated panel at least meets the certification bound.

### 3.2 Capability and clipping

A `PanelCapability` records peak luminance at the target white, native contrast, measured primaries and native white, each with its evidence kind and source. `resolve_intent` turns intent plus capability into an `AchievableTarget`, and every change is a `Clip` with the field, the requested value, the achievable value, the unit, a reason and the evidence kind:

- White luminance above the panel's peak at the target white, less 2 % kept as gain headroom, is clipped to that value.
- Black below what the panel leaks at the chosen white (white over native contrast) is clipped up.
- A white outside the panel's primary triangle falls back to the panel's native white.
- Gamut coverage under the goal is reported with the coverage the panel has. Patches the panel cannot reach are listed in verification and not graded.
- An HDR intent on a panel whose achievable peak is under 203 cd/m2 is flagged against HDR Reference White.
- HLG system gamma is derived from the achievable peak by the BT.2100-3 formula.

One intent therefore works across panels: the same "D65, 2.2, 120 cd/m2, sRGB" runs unchanged on a 250 cd/m2 LCD and a wide-gamut OLED, and the report shows what each panel gave up.

### 3.3 SDR and HDR in one format

SDR targets use relative colorimetry with the target white as reference white, so a luminance miss on white appears as an L* error. HDR targets use absolute colorimetry and Delta E ITP. Capability is always absolute. The first built slice runs only SDR transfer functions; an HDR intent is resolved and clipped and then refused before any write, with stop reason `hdr_not_built`.

### 3.4 Room for a per-viewer observer

The T1b study (2026-11-04, the author's colour-system research) simulated 1,000 individual observers with the Asano 2016 model. Median observer-to-observer mismatch on white, against a broadband D65 reference, was 0.57 CAM16-UCS at 128 nm primary width, 3.30 at 40 nm and 5.92 at 1 nm. Per-viewer calibration crosses its own decision line at 45 nm FWHM and narrower for the main primary set. The model overpredicted one validation set by 22 %, and the primaries were Gaussians, not measured panel spectra.

The intent keeps an `observer` field for this. A later version may accept a per-viewer observer, which would change the colour-matching functions used to turn a spectrum into the target, and so needs a spectroradiometer or a spectral characterization of the panel. Nothing is built for it now.

## 4. The closed loop

### 4.1 One click

One click is one confirmation of a previewed plan. The `ClosedLoopPlan` lists the display, the intent, each writable control with a hard minimum, maximum and largest step per write, the write budget, and the stop rules. Its SHA-256 digest is what the user approves. `PlanApproval` is bound to that digest and is consumed by the first run. `BoundedWriter` refuses any write the plan does not name, any value outside the hard range, any step larger than the bound, and any write past the budget.

The loop writes only controls the panel advertises in its capabilities string. Contrast stays at its neutral setting, after the ArgyllCMS guidance for LCDs, and preset or mode changes are a separate, previewed step. On a real panel the writer must route through the existing confirmation coordinator and `DefaultWindowsDisplayAdapter`, so prior state is captured and compensation runs on failure. That wiring is not in the first slice.

### 4.2 Steps

1. Consume the approval or refuse.
2. Estimate the instrument noise floor from repeated white reads.
3. Warm-up gate: read white at intervals until drift is under 0.1 % per minute over three intervals for three readings in a row, the criterion of `warmup_monitor.py`, or until noise explains the change. If the panel is still drifting at the time limit, stop with `warmup_unstable` and write nothing.
4. Characterize the panel as it stands: black, three primaries, white. If white already meets the target, stop with zero writes.
5. Probe capability: ramp brightness and gains to their maximum within the step bound, characterize again, compute peak at the target white and native contrast, clip the intent.
6. Iterate. Read white averaged over repeats. Solve in the panel's own primaries: the ratio of target to measured channel amounts gives the gain change, the largest ratio gives the brightness change, and the brightness response exponent is learned by a secant estimate. Write the result through the bounded writer.
7. Stop on the first rule that fires: `converged` (white dE and luminance inside tolerance), `noise_floor` (error under the floor, confirmed with four times the averaging, or progress stalled inside twice the floor), `no_improvement` (no 5 % gain over two iterations above the noise band), `control_resolution` (the solver asks for no change the controls can express), `write_budget`, or `max_iterations`.
8. Residual LUT: designed, not built. After the hardware stage, profile the panel with the existing `native_loop.profile_display` and build the residual correction with `build_correction_lut`, so the LUT only carries what the controls could not.
9. Verify on a held-out set the loop never tuned on: grays at 25, 50 and 75 %, primaries and secondaries at 75 %, and one skin tone. Each patch is graded against its class bound, or listed as outside the panel gamut.
10. Seal. Every step goes into a hash-chained ledger: plan digest, warm-up, capability and clips, each iteration's error, each write with its prior value, the stop reason, and verification. The seal is the last digest. Editing any entry breaks every digest after it.

Drift during the loop is handled by the warm-up gate before writes and by the noise-aware stop rules. Interleaved reference reads with `DriftCompensator` belong in the residual LUT profiling, where runs are long.

### 4.3 Evidence

The loop takes the evidence kind from the instrument port. A device port is `measured`. The simulated instrument declares `simulated`, and every metric, clip and patch result from it carries that label and the instrument's identity string.

## 5. Without an instrument

Author direction, 2026-11-04: fully automatic, no human input or tuning, and no phone or webcam. The target is dE2000 0.1 to 0.2, about one 10-bit step on the drive signal.

### 5.1 The information limit

With no sensor in the light path, software cannot observe what the panel emits. It knows what it sent and, over DDC/CI, what the panel reports about its own settings. Ageing of the backlight or emitters, temperature shifts and unit-to-unit variation all happen after the signal leaves the PC. Without a sensor they can be predicted from models and priors, never observed. Every value this mode produces is `estimated`, and the report must say so.

### 5.2 Precision floors

| Floor | Size | Source |
|---|---|---|
| 8-bit drive step | 1/255 = 0.0039. At mid-gray on a 2.2 display one code moves L* by 0.40, about 0.40 dE2000; near 5 % gray, 0.73 L*. | Computed here |
| 10-bit drive step | 1/1023 = 0.00098. At mid-gray, 0.10 L*, about 0.10 dE2000; near 5 % gray, 0.18 L*. | Computed here |
| Instrument repeatability | The Calibrite Display Pro HL product page and comparison chart read for this spec publish no numeric repeatability. Unknown from sources read. The loop measures its own noise floor each run, which is what bounds a claim. | Saved vendor pages |
| Observer spread | Median 0.57 to 5.92 CAM16-UCS between individual observers on white, depending on primary width. | T1b, 2026-11-04 |

The author's target sits at the 10-bit step. It is a physically meaningful bound for a closed loop with a good instrument: one code is the smallest change the PC can command. Without an instrument the bound is set by the prediction error of the models in 5.3, which is unknown until the bench study in 5.5 measures it.

A target such as 1e-7 of perfect is not a defined quantity on a display. The drive signal moves in steps four to five orders of magnitude larger. A colour difference that small sits far below the spread between two people with normal colour vision, and below the repeatability of any instrument that would have to confirm it. Spatial nonuniformity across one panel, from memory and low confidence, is typically several per cent of luminance on consumer LCDs, so "the panel's colour" is itself a spread of values across the screen.

### 5.3 Machine-observable channels

Each channel plugs into one interface (5.4). Method identifiers follow the instrumentless bench study.

| Method | Channel | Observes | Cannot observe | Expected accuracy |
|---|---|---|---|---|
| M2 | DDC/CI readback | Control state; on some panels usage hours and other vendor codes. The K32 answers VCP C0 (display usage time) with 3447 although it does not advertise C0. | Emitted light, ageing, temperature unless a vendor code exposes it | Exact for control state. As a drift predictor, unknown until M6 and M8 give a model to feed. |
| M6 | Rendered-content dose recorder | What the PC sent, per screen region and channel, over time, the way OLED makers keep per-subpixel stress counters for compensation (from memory, moderate confidence). On an LCD the dose is backlight level times hours. | How the panel responded to that dose | Bounded by the ageing model's error. Unknown. |
| M7 | Thermal model | On-board temperatures the PC can read, plus content and brightness history, feeding a warm-up and temperature model like `warmup_monitor.py`'s | Panel temperature itself, unless DDC exposes it | Unknown. |
| M8 | Fleet-learned per-model priors | A commons dataset from owners who did measure: the distribution of white, gamut, gamma and ageing curves for a model | This unit's deviation from the model's mean | Bounded by unit-to-unit spread for the model. From memory, low confidence, out-of-box white points vary by several dE2000 between units of a consumer model. |
| M9 | USB-C Power Delivery telemetry | Power drawn when the PC powers the panel. On emissive panels power tracks displayed luminance; on LCDs it tracks the backlight. | Chromaticity; anything when the panel has its own supply | Unknown; depends on what the port's telemetry reports and how often. |
| M10 | Fusion | A state estimator (Kalman-style) combining M8 priors with M2, M6, M7 and M9 into one predicted panel state with an uncertainty | Anything none of the inputs carries | Its stated uncertainty, which must be checked against a measured session before it is trusted. |

A panel with a built-in calibration sensor is a measured channel and runs the closed loop of section 4 directly.

### 5.4 Interfaces

Design only. Names chosen so the bench study's methods plug in unchanged.

```python
class StateChannel(Protocol):
    method_id: str                      # "M2", "M6", "M7", "M8", "M9"
    def observe(self, now: float) -> ChannelObservation: ...

@dataclass(frozen=True)
class ChannelObservation:
    method_id: str
    values: Mapping[str, float]         # e.g. {"usage_hours": 3447.0}
    sigma: Mapping[str, float]          # one standard deviation per value
    evidence: EvidenceKind              # ESTIMATED, or MEASURED for M2 control state
    source: str

class StateFusion(Protocol):            # M10
    def update(self, observation: ChannelObservation) -> None: ...
    def predict(self, at: float) -> PanelStateEstimate: ...

@dataclass(frozen=True)
class PanelStateEstimate:
    white_xyz: tuple[float, float, float]
    white_de_sigma: float               # predicted one-sigma white error, dE2000
    evidence: EvidenceKind              # always ESTIMATED
    inputs: tuple[str, ...]             # method ids that contributed
```

The fusion's prediction feeds the same solver and bounded writer as section 4, as a correction proposal labelled `estimated`. It never becomes a verification result.

### 5.5 Hybrid: most accuracy per instrument use

1. One measured session with the instrument, which also records the panel's state for M2, M6, M7 and M9 at that time.
2. Between sessions, M10 predicts drift from that anchor and proposes small corrections, each labelled estimated.
3. Ask for the instrument again when any of these holds: the predicted one-sigma white error exceeds half the white tolerance; a channel reports a discontinuity (firmware level C9 changes, mode or preset changes, usage hours jump, the panel is moved to another port); or a set interval passes with no measured session, the interval learned per model from M8.

A separate instrumentless bench study measures M2 to M10 against a virtual panel. The interfaces above are what it should implement.

## 6. Built in this slice

Code: `calibrate_pro/calibration/closed_loop/` and `calibrate_pro/hardware/mccs_caps.py`. Tests: `tests/test_closed_loop_planted.py`, `tests/test_closed_loop_parts.py`.

The simulated panel's physics differ from what the solver assumes: gains act through an exponent of 1.08 and quantize to 8-bit steps, the backlight has an 8 % floor and a 1.4 exponent, black is leakage at 1000:1 raised by offsets, and warm-up decays exponentially with an extra blue term. The simulated instrument adds seeded multiplicative and additive noise and implements `InstrumentPort`. All results below are simulated.

| Planted case | Stop | Iterations | Writes | Final white dE2000 (reported / true) | Criterion in the test |
|---|---|---|---|---|---|
| Known miscalibration: red gain 90, brightness 30, cool white, 3 % warm-up drift; target D65 120 cd/m2 | converged | 7 | 31 | 0.65 / 0.70 | true dE at most 1.0, luminance within 3 %, at most 8 iterations, held-out grays within 2.0 |
| Target outside capability: 400 cd/m2, 0.05 cd/m2 black, 90 % P3 on a 254 cd/m2 sRGB-gamut panel | converged on the clipped target | 3 | 13 | 0.95 / 0.92 | clips reported: white 400 to 253.8, black 0.05 to 0.254, P3 coverage 0.90 to 0.797; at most 5 iterations |
| Noisy instrument (1 % per reading), tolerance 0.05 dE | noise_floor in 5 of 5 seeds | 5 to 8 | 23 to 33 | true 0.83 to 2.59 against floors 1.96 to 4.01 | stop reason noise_floor, true dE at most the floor, fewer than 12 iterations |
| Zero control: perfect panel | converged | 0 | 0 | 0.07 / 0.01 | zero writes |
| Warm-up still drifting at the limit | warmup_unstable | 0 | 0 | Not measured | zero writes |

Most writes in the first two cases are the capability probe's ramps, bounded at 10 steps per write. The noise floor estimate varies by a factor of two across seeds because it rests on six readings.

A real fault found on the way: the DDC/CI capabilities parser stopped at the first closing parenthesis, so on the K32 string `14(05 08 0B 0C)` it read 08, 0B and 0C as codes and dropped every code after them, reporting no RGB gain on a panel that advertises all three. `parse_capabilities` reads the group balanced, and `DDCCIController` now uses it. The K32 string is a test fixture.

## 7. Next

- Wire the bounded writer to the confirmation coordinator and `DefaultWindowsDisplayAdapter` for real panels, with prior-state capture and compensation.
- Offsets for near-black balance, the residual LUT stage, and the HDR loop with Delta E ITP.
- A measured run needs an instrument. The repo's strongest driver is the native i1Display3 family (its module names i1Display3, i1Display Pro, i1Display Pro Plus, ColorMunki Display and Calibrite ColorChecker Display), with per-unit EEPROM calibration and CCSS import. Repo history points to the author's own unit being one of these (moderate confidence; the model was not named in this session). `UsbInstrumentSource` already opens it through `NativeBackend` behind the `InstrumentPort` protocol the loop uses. Spyder and ArgyllCMS backends exist too.

## Appendix A. Optional viewer-assisted checks (outside the main path)

The main path takes no human input. A later option could let a viewer act as the instrument through null-matching tasks: a flicker null between a gray and a reference, or a gray-balance null where the viewer nudges a patch until it reads neutral. Such a task also yields the per-viewer observer adjustment that T1b motivates. It is listed here so the observer field in 3.4 has a route, and nothing in sections 4 or 5 depends on it.
