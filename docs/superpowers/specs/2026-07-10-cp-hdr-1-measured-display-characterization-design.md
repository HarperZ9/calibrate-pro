# CP-HDR-1 Measured HDR Display Characterization Design

**Date:** 2026-07-10
**Status:** Proposed; awaiting review
**Release train:** Begins after the Calibrate Pro 1.1 packaging/truthfulness base
**Primary product:** Calibrate Pro
**Shared consumers:** build-color, Project Telos, RAW, and the artistic engine

## Objective

Replace Calibrate Pro's synthetic HDR success path with a measured,
replayable, standards-traceable HDR10/PQ display-characterization workflow.
The first deliverable characterizes EOTF tracking, peak and sustained
luminance, ABL/APL behavior, thermal drift, chromaticity drift, and
repeatability. It emits a typed `DisplayCapabilityProfile` that deterministic
color and rendering code can consume.

CP-HDR-1 is the measurement foundation for later grading, scopes, dynamic
metadata, scene rendering, artistic transforms, and game-engine output. It is
not a claim of feature parity with DisplayCAL, Calman, ColourSpace, Dolby tools,
or a mastering monitor.

## Verified Starting Point

- `calibrate_pro/hdr/workflow.py:312-351` currently accepts absent
  measurements, substitutes the expected PQ/HLG values, and reports placeholder
  gamut coverage. `tests/test_hdr_workflow.py:376-420` enshrines that synthetic
  behavior as a successful default. CP-HDR-1 must remove that ambiguity.
- `calibrate_pro/hdr/pq_st2084.py:19` computes `PQ_M2` as
  `2523 / 32 * 128 = 10092` while its comment says `78.84375`. A 2026-07-10
  local comparison produced PQ(100 cd/m²) `2.2863e-38` on that path versus
  `0.5080784215` in `calibrate_pro.core.color_math`; decoding the latter code
  through the conflicting module produced about 9508.89 cd/m² instead of 100.
  The existing tests and PySide6 packaging proof did not expose this defect.
- `build-color/build_color/spaces.py` contains float64 color-space matrices,
  exact piecewise sRGB transfer functions, JzAzBz, and ICtCp primitives.
- `build-color/build_color/tonemap.py` contains several deterministic tone-map
  operators, including functions labeled for BT.2390 and BT.2446. Labels alone
  are not conformance evidence; each standards-derived operator needs pinned
  references and vectors.
- Two 2026-07-10 local probes demonstrate why labels and roundtrips are
  insufficient. `uchimura([0.219999, 0.22, 0.220001])` returned approximately
  `[0.219999, 0.088460, 0.088462]`, a discontinuity at its branch. The
  build-color `bt2390_eetf` mapping from 4000 to 1000 cd/m² became decreasing
  above about 1996 cd/m² and fell from a maximum near 1995.88 cd/m² to about
  1000 cd/m². Neither function is a reference oracle until independently fixed
  and validated.
- `build-color/build_color/lut_io.py` supports `.cube` and CLF-shaped LUT data,
  but its in-memory LUT type has no explicit input/output color contract.
- The current Community Shaders mirror is pinned at commit
  `0a81516de0797b6806dd0a9f56716d470b9c3e1e`; the RenoDX mirror is pinned at
  `8efffa2f018be65c4b4734f7cedc49bf8dfabb5a`. These repositories are design and
  behavior evidence, not numerical conformance oracles.
- The protected RAW and ENB/Community Shaders synthesis archives are available
  as behavioral research inputs. Their implementation text does not cross into
  public product code.

These are workspace observations, not product capability claims.

## Design Principles

1. **Measurement provenance is a type, not copy.** `measured`, `replayed`,
   `simulated`, `estimated`, and `not_measured` are structurally distinct.
2. **Every transform edge declares its color contract.** Domain, primaries,
   white point, transfer function, luminance scale, range, precision, alpha
   semantics, and provenance travel with the data.
3. **Separate the pipeline stages.** Scene rendering, creative appearance,
   display mapping, signal encoding, OS transport, and panel response are not a
   monolithic HDR transform.
4. **Color volume is luminance-dependent.** A 2D primary triangle is never
   presented as full HDR gamut or color-volume coverage.
5. **Models advise; deterministic code decides.** A model may classify content,
   suggest a starting preset, or explain a result. It cannot invent a reading,
   execute authoritative color math, waive an acceptance gate, or mutate the
   display without an explicit deterministic action path.
6. **Characterize before correcting.** CP-HDR-1 does not generate or apply a
   correction LUT. A later phase may fit a correction only with independent
   holdout and post-application measurements.

## Scope

### In scope

- HDR10/PQ measurement and replay on Windows 10/11 x64.
- A typed signal/measurement/result schema.
- Instrument-adapter abstraction with a deterministic fake/replay adapter.
- Patch scheduling with window size, background APL, dwell, settle, repeats,
  warm-up, OS HDR state, and optional temperature context.
- A product baseline PQ ramp plus exact revision-pinned EBU/VESA-derived
  profiles, peak, sustained, ABL/APL, and drift protocols.
- Chromaticity/CCT capture when the instrument supplies tristimulus data.
- JSON, human-readable report, conformance-vector, and profile outputs.
- build-color CPU reference vectors and a cross-language HLSL consumer format.
- Local, privacy-preserving measurements by default.

### Out of scope

- Dolby Vision certification or proprietary Dolby tooling.
- Claiming HDR10+ or other dynamic-metadata conformance.
- Full creative grading, timeline editing, scopes, or media ingest.
- Game injection, driver patching, or reverse-engineered implementation reuse.
- Silent DDC/CI, DWM LUT, profile, or OS HDR mutations.
- Correction LUT/profile generation or application; that is a later measured
  correction phase with a separate approval gate.
- A single universal pass/fail grade across unlike display technologies.

## Requirements

- **H1 — Explicit run provenance:** Every run declares exactly one of
  `measured`, `imported_measured`, `replayed`, or `simulated`. Production UI
  defaults to measured and cannot silently fall back. Missing readings produce
  `not_measured` fields.
- **H2 — Typed signal contract:** Every input and output edge records domain,
  primaries, white point, transfer, absolute/relative luminance units, legal or
  full range, bit depth/precision, alpha semantics, and source provenance.
- **H3 — Measurement context:** Every reading records signal value, expected
  luminance, measured Y and optional x/y, patch area, background APL, dwell and
  settle durations, repeat index, warm-up duration, OS HDR state, output path,
  adapter identity/version, and nullable sensor/panel/ambient temperature.
- **H4 — Stable identity without leakage:** A local display profile may contain
  full device identifiers. Exported research fixtures use a salted display ID
  and omit user, machine, serial-number, and path-identifying data.
- **H5 — PQ reference path:** PQ encode/decode and signal-code conversion use a
  single build-color float64 reference implementation with pinned
  standards-derived vectors and roundtrip, monotonicity, endpoint, and invalid
  input tests. Conflicting Calibrate Pro PQ implementations are retired or
  reduced to tested compatibility delegates; no duplicated constants remain.
- **H6 — Core EOTF protocols:** Provide a clearly named product baseline ramp
  plus an EBU preset using the exact code values, patch geometry, timing, and
  revision required by EBU Tech 3325. An arbitrary 21-point `linspace` ramp is
  never labeled as the EBU protocol. Every profile declares background,
  stabilization, repeated black/white, and handling below instrument
  sensitivity.
- **H7 — APL/window protocol:** Measure at least 1%, 4%, 8%, 10%, 25%, 50%,
  81%, and 100% windows across declared background APL contexts. A
  standards-named preset may be used only when its exact procedure is
  implemented; otherwise the report says `research_protocol`.
- **H8 — Sustained/thermal protocol:** Record short-duration peak, long-duration
  peak, a configurable sustained hold up to 600 seconds, temperature when
  available, luminance decay, chromaticity drift, and recovery. Preconditioning
  is part of the receipt.
- **H9 — Repeatability:** Repeat selected points, report spread and confidence,
  and flag unstable runs rather than averaging instability away.
- **H10 — Truthful color volume:** Report measured primaries/chromaticities by
  luminance slice. If insufficient data exists, 2D gamut area and 3D color
  volume remain absent rather than defaulting to 0% or 100%.
- **H11 — Characterization-only mutation boundary:** CP-HDR-1 presents declared
  test patterns and reads instrument/OS state. It does not generate or apply a
  LUT, write DDC/CI, install a profile, change startup behavior, or silently
  toggle OS HDR.
- **H12 — Deterministic receipts:** Inputs, vector-set version, transform graph,
  adapter version, configuration, readings, output hashes, and acceptance
  verdict serialize canonically and replay to the same analysis within declared
  tolerances.
- **H13 — Cross-language conformance:** The same versioned JSON vectors exercise
  build-color float64, Calibrate Pro NumPy, and RAW/Telos HLSL implementations.
  CPU float64 is the reference; GPU FP32/FP16 tolerances are declared per case.
- **H14 — Least privilege:** The run remains unelevated and read-only except for
  deliberate pattern presentation. Unsupported HDR presentation or instrument
  access fails with an actionable state rather than switching to SDR/simulation.
- **H15 — Evidence corridor:** Every external source is classified by revision,
  license/access class, evidence type, permitted use, and derivation. Protected,
  decompiled, GPL, forum, and Discord material can produce leads, behavioral
  tests, or independently written specifications; it is not copied into the
  product.

## Canonical Color Pipeline Contract

The shared deterministic pipeline is a graph of typed transforms:

```text
SceneLinear
  -> creative / ACES-style appearance transform
  -> appearance representation (for example JMh)
  -> luminance-conditioned gamut mapping
  -> display EETF / dynamic mapping
  -> encoding (PQ, HLG, scRGB, or SDR)
  -> OS and wire transport
  -> measured panel response
```

No edge accepts an untyped `float3`. The minimum descriptor is:

```text
ColorSignalDescriptor
  domain: scene_linear | display_linear | encoded | appearance
  primaries: named revision or explicit xy coordinates
  white_point: named revision or explicit xy coordinates
  transfer: linear | srgb | gamma | pq | hlg | named custom
  luminance: relative(scale, reference_white) | absolute_cd_m2
  range: full | limited(code_min, code_max)
  precision: float64 | float32 | float16 | integer(bit_depth)
  alpha: none | straight | premultiplied
  provenance: source ID, revision, vector-set version
```

The contract distinguishes Windows scRGB convention (`1.0` associated with
80 cd/m² in the Windows advanced-color path) from BT.2100/production conventions
that use a 203 cd/m² graphics/diffuse-white reference. Content white, UI white,
display peak, mastering peak, and measured sustained peak are separate fields.

## Measurement Model

### Core records

`MeasurementRun` owns configuration, environment, patch schedule, readings,
analysis, and receipts. `PatchReading` contains:

```text
patch_id
signal_descriptor
rgb_or_gray_code
expected_cd_m2
measured_cd_m2 | not_measured
measured_xyz_absolute | not_measured
measured_xy | not_measured
measured_cct | not_measured
measured_delta_uv | not_measured
patch_area_percent
background_apl_percent
settle_ms
dwell_ms
elapsed_ms
monotonic_timestamp_ns
utc_timestamp
integration_time_ms
repeat_index
os_hdr_state
display_mode
swapchain_color_space
output_bit_depth_and_range
hdr_metadata_payload_hash | null
sensor_temperature_c | null
panel_temperature_c | null
ambient_temperature_c | null
ambient_lux | null
adapter_id_and_version
instrument_model
instrument_serial_hash | null
instrument_correction_hash | null
instrument_calibration_state | null
display_id_hash
display_firmware | null
windows_build
gpu_driver_and_output_path
provenance: measured | imported_measured | replayed | simulated
quality_flags[]
```

Raw adapter payloads stay local and are referenced by hash. Canonical exported
records contain only the fields required for reproducibility and analysis.
Physical temperature and correlated color temperature are different typed
fields and are never inferred from one another. Absolute XYZ/Y units may not be
silently substituted with normalized readings.

The existing `ColorMeasurement` and tkinter measurement coordinator are not an
HDR presenter contract: the former permits ambiguous absolute-or-normalized Y,
and the latter presents 8-bit sRGB patches. They may supply compatibility data
only after an adapter proves units and presentation provenance.

### Protocol tiers

1. **Quick characterization:** warm-up receipt, product baseline PQ ramp,
   repeated
   black/white, 1%, 10%, and 100% peak windows.
2. **Reference characterization:** adds the exact 20-code EBU Tech 3325 profile,
   1%, 4%, 8%, 25%, 50%, and 81% windows, multiple background APLs,
   primary/secondary chromaticity slices, and short/long peak measurements.
3. **Thermal/ABL study:** configurable dense window sweep, selected 600-second
   holds, recovery intervals, repeated temperature/context capture, and panel
   state notes.

A VESA-style research profile adds an 8% center patch over 2% APL plus declared
flash and long-duration measurements. It is not labeled DisplayHDR conformance
unless the complete pinned DisplayHDR 1.2 procedure and criteria are executed.

Presets derived from EBU Tech 3325, VESA DisplayHDR 1.2, or another published
procedure pin the exact revision and retain its required timing and pattern
geometry. Partial implementations use neutral product names and cannot display
the source organization's conformance mark.

## Analysis and Output

The deterministic analyzer produces:

- PQ EOTF error by point and declared aggregate metrics;
- monotonicity, clipping, near-black sensitivity, and code-value diagnostics;
- peak luminance as a function of patch area, APL, elapsed time, and temperature;
- sustained decay, recovery, repeatability, and instability flags;
- xy/CCT and primary drift where tristimulus readings exist;
- a sampled ABL response surface rather than a single unexplained peak number;
- explicit missing-data fields and limitations.

Outputs are:

- `hdr-characterization-v1.json` — canonical receipt, schema version, and
  readings;
- raw observation CSV for independent inspection;
- `display-capability-profile.json` — stable consumer contract;
- `analysis.json` — metrics, flags, and verdicts;
- `report.html` or PDF — human-readable evidence with provenance badges;
- `color-conformance-v1.json` — standards/reference vectors;
- pattern and source-vector hashes;
- SHA-256 inventory covering every output.

## Cross-Language Conformance Pipeline

`build-color` owns the independent CPU reference and vector generator. The
vector set contains scalar boundaries, neutral ramps, primaries, pathological
values, roundtrips, and transform-chain cases. Each case declares:

- source and destination `ColorSignalDescriptor`;
- exact input and expected output;
- normative source or algorithm provenance;
- absolute, relative, and perceptual tolerances by precision;
- expected handling for negative, over-range, NaN, and infinity inputs;
- vector generator version and content hash.

Consumers run the same cases through:

1. build-color NumPy float64 reference;
2. Calibrate Pro's product path;
3. RAW/Telos HLSL under an offscreen D3D11 WARP runner;
4. optional hardware GPU runners as additional evidence, never as the sole
   oracle.

The first vector tranche covers exact piecewise sRGB, PQ encode/decode, HLG
OETF/inverse/OOTF/EOTF, BT.709/BT.2020 matrix transforms, luminance scaling,
full/limited range, and identity/roundtrip cases. Tone mapping, ICtCp,
appearance transforms, gamut mapping, LUT interpolation, and dithering enter
only after their contracts and reference provenance are independently audited.
Every piecewise or mapping function must also pass continuity, monotonicity,
boundedness, endpoint, dense-sweep, and independently calculated known-value
tests; roundtrip tests alone are not an oracle.

## Research and Clean-Room Corridor

External evidence is normalized to one of:

- `standards_derived` — pinned standards/recommendations and official vectors;
- `public_open_source` — pinned repository commit and license;
- `experimental_public` — open PR/branch, explicitly not merged behavior;
- `community_claim` — forum/Discord statement requiring corroboration;
- `protected_behavioral_lead` — protected/decompiled/closed implementation
  observation that cannot cross as source;
- `local_measurement` — instrument receipt;
- `inference` — a stated hypothesis awaiting evidence.

Observers may produce a behavior statement, black-box test, standards link,
and provenance packet. Independent implementers receive that packet, not
protected implementation text. Public product commits must be explainable from
standards, independently authored math, permissively compatible sources, or
black-box tests. A provenance audit is a release gate.

Community research collected through Gather uses an official Discord bot,
query/channel allowlists, identity redaction, attachment hashes, checkpoints,
and rate-limit receipts. Raw chat is transient by default and is not treated as
fine-tuning data. Community claims enter the graph as leads, not facts.

## Integration Boundaries

- **Calibrate Pro** owns sensor adapters, patch presentation, measurement
  orchestration, reports, user consent, apply/rollback, and profile management.
- **build-color** owns deterministic CPU color math, typed transform contracts,
  reference vectors, LUT contracts, and serialization primitives.
- **RAW** owns D3D11/HLSL execution, WARP/offscreen conformance, frame capture,
  and renderer integration.
- **Project Telos** owns evidence routing, capability/catalog integration,
  model/agent policy, and superapp composition.
- **Artistic engine** owns human/model-authored intent and high-level controls;
  it consumes typed deterministic transforms and measured display profiles.

## Verification Strategy

1. Schema tests reject missing provenance, units, color contracts, and required
   timing/context fields.
2. Standards-vector tests cover boundaries, known points, monotonicity, and
   roundtrips with pinned revisions.
3. Dense-sweep tests reject branch discontinuities and decreasing display maps;
   regression fixtures include the observed Uchimura `0.22` discontinuity and
   the observed 4000-to-1000-nit BT.2390 decrease above about 1996 cd/m².
4. Fake-sensor tests cover timeouts, disconnects, invalid/unstable readings,
   below-floor readings, partial tristimulus data, and temperature absence.
5. Replay tests reproduce analysis and output hashes within declared numerical
   tolerances.
6. Protocol tests verify patch geometry/APL/timing schedules without touching a
   physical display.
7. WARP tests compare HLSL outputs to shared vectors by declared FP32/FP16
   tolerances and emit failure captures.
8. Mutation tests prove that no measurement command applies a LUT, writes DDC,
   changes startup state, or silently toggles OS HDR.
9. Physical acceptance uses a named instrument/display pair and records the
   adapter, firmware, OS/GPU path, warm-up, environment, raw receipt hash, and
   limitations.
10. A later correction phase uses disjoint fit/holdout patches and verifies
    rollback; CP-HDR-1 itself remains characterization-only.
11. Provenance scanning confirms no protected implementation or secret enters
    public artifacts.

## Delivery Sequence

1. Land Calibrate Pro 1.1 packaging, PySide6 migration, truthful provenance,
   diagnostics, and least-privilege release gates.
2. Land one audited build-color PQ implementation, official/pinned gold
   vectors, the typed color-signal contract, and `color-conformance-v1.json`.
3. Add Calibrate Pro fake/replay adapters and the canonical measurement schema.
4. Replace the implicit perfect-display HDR path with explicit
   measured/replay/simulation modes.
5. Implement the quick and reference PQ protocols plus deterministic analysis.
6. Add RAW WARP/offscreen conformance consumption.
7. Validate on named physical hardware and publish redacted receipts.
8. Feed `DisplayCapabilityProfile` into Telos, RAW, and the artistic engine.
9. Design the separate measured-correction phase with disjoint fit/holdout and
   rollback requirements.
10. Expand into HLG, grading/scopes, dynamic metadata research, and
    grade-once/output-many workflows through separately approved designs.

## Success Criteria

- [ ] No product path can turn missing HDR readings into a perfect measured
  result or placeholder gamut coverage.
- [ ] PQ(100 cd/m²) and its inverse pass the pinned gold-vector gate on every
  public CPU/GPU path; the conflicting `PQ_M2=10092` implementation is no
  longer reachable as an independent implementation.
- [ ] Every reading and transform edge carries units, color contract, and
  provenance.
- [ ] A replay fixture deterministically reproduces analysis and receipts.
- [ ] A named physical run records EOTF, window/APL, sustained, repeatability,
  and available temperature/chromaticity context.
- [ ] CP-HDR-1 produces no correction artifact and performs no display/profile
  mutation beyond deliberate test-pattern presentation.
- [ ] build-color, Calibrate Pro, and RAW HLSL pass the same versioned vector
  corpus within declared tolerances.
- [ ] The generated profile is consumed without reinterpretation by at least
  one RAW/Telos render path.
- [ ] Public artifacts pass privacy, secret, license, and clean-room provenance
  review.

## Approval Gate

No CP-HDR-1 product implementation begins while this document is `Proposed`.
After review, its status changes to `Approved`, then a test-first implementation
plan is written. The Calibrate Pro 1.1 packaging work may proceed independently
once its revised design is re-approved.

## Primary References

- [ITU-R BT.2100-3: HDR television image parameter values](https://www.itu.int/rec/R-REC-BT.2100-3-202502-I)
- [Microsoft: High Dynamic Range and Wide Color Gamut](https://learn.microsoft.com/windows/win32/direct3darticles/high-dynamic-range)
- [EBU Tech 3325 v2.0: Methods for measuring the performance of studio monitors](https://tech.ebu.ch/docs/tech/tech3325.pdf)
- [VESA DisplayHDR 1.2 performance criteria](https://displayhdr.org/performance-criteria/)
- [OLED monitor ABL and thermal measurement study](https://pmc.ncbi.nlm.nih.gov/articles/PMC13161341/)
