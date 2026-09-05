# Changelog

## v2.0.0 (2026-09-05)

- Gave `doctor` a next action. A base install leaves four distributions absent, so the
  report printed four MISSING lines, `Result: NOT OK`, and nothing a reader could run.
  The dependency table now records which extra carries each name and the report ends
  with the command that installs it. `remediation` carries the same in the JSON. A
  packaged build is told to reinstall from its release instead, because pip cannot
  reach the interpreter that build ships. Verified end to end: a bare wheel install
  prints `pip install "calibrate-pro[gui]"`, and running that command reaches
  `Result: ok`.

- Stopped the product window naming the previous release. Eight strings the user
  reads said `disabled in 1.1`, `version 1.1` and `the 1.1 ApplyPlan`, and would have
  said it through 2.0. `calibrate_pro.__release_series__` derives the series from the
  one declaration and every one of those strings reads it. The version sweep could
  not see them, because it anchors on the product name and a bare `1.1` carries none,
  so a second gate parses the package and checks the string constants themselves.
  It is proved against the six strings that shipped.

- Removed the em-dash from seventeen strings the window displays, which the writing
  standard bans on a surface a reader sees. One was written `\u2014`, which a search
  for the character cannot find; reading the strings through the parser finds it.

- Made the release version derive from one declaration. `calibrate_pro/__init__.py`
  declared it and twelve other files repeated it by hand, including a release-workflow
  gate that compared the pushed tag against the literal `v1.1.0` and would have refused
  to ship any other version. The build scripts, the asset-set verifier, the workflow and
  the tests now read the declaration: `scripts/product_version.py` parses it for Python
  callers and the two PowerShell scripts read it with the same pattern. What cannot
  derive, which is prose, badge URLs, the component lock and the dispatch default tag,
  is checked against the declaration by `tests/test_version_pins_name_this_release.py`,
  so a bump that misses a file fails a test rather than shipping a page that names a
  release the build did not produce. The derivation was proved against 1.1.0 before the
  version moved, so a passing gate is not one that matches nothing.

- Removed a calibration-quality claim the repo does not measure. The EDID profiling path
  logged "This provides significantly better calibration than generic sRGB fallback" for
  every display it profiled from EDID, and `create_from_edid` repeated the claim in its
  docstring. No measurement here compares EDID-derived primaries against the sRGB fallback,
  so the line stated a result nobody produced. The log line now names what EDID does not
  carry, which is photometry, and the docstring records the comparison as unmeasured.

- Stopped an EDID that states no gamma reporting one. EDID byte 23 holds gamma, and the value
  0xFF means the gamma sits in an extension block, so `parse_edid` leaves the field at 0.0 and
  `update_from_edid` only copies it when it is above zero. `_match_panel` read
  `edid_info.get("gamma", 2.2) or 2.2`, which erased that, and its log line then printed
  "Gamma=2.20" beside six chromaticities the EDID really carried. `create_from_edid` wrote
  "Gamma assumed 2.2" into the panel notes whatever the caller passed, so a gamma read off byte
  23 and a gamma nobody read looked identical in the profile. The parameter is now
  `float | None`, the panel model still uses 2.2 when nothing was read, and the note and the log
  line each say which of the two the reader has.
- Stopped a cancelled manual measurement filing itself as black. `_manual_measure_xyz` prompts
  the operator for an XYZ reading, and on end-of-input or Ctrl+C it printed "Measurement
  cancelled" and then returned `(0.0, 0.0, 0.0)`. Black is a valid reading, so the caller could
  not tell a cancelled patch from a panel emitting nothing, and the zero went on to a Delta E
  and into a report. The ArgyllCMS backend beside it already raises when it has no data. The
  manual backend now raises the same way, so the two paths keep one contract.
- Stopped the SDR white level defaulting to a guess. `_get_sdr_white_level` reads Windows
  settings for the SDR content brightness, and when the registry carried no such value it ended
  with `return 200.0`. Its own docstring called 200 a typical figure, which is what a guess
  looks like written down. The status line then printed "SDR white level: 200 cd/m2" as though
  the OS had answered. The reader now returns `None`, `HDRDisplayState.sdr_white_level` holds
  `None`, and the status line says the OS reported no level.
- Stopped an uncomputed gamut volume reporting as zero, and an unsampled one as a perfect
  match. `calculate_gamut_volume_lab` wrapped its convex hull in `except Exception: return 0.0`,
  so degenerate samples and a missing scipy both came back as a display covering nothing.
  `_analyze_coverage` then started `volume_ratio` at 1.0, so a run given no samples published a
  ratio of 1.00 in the HTML report, meaning a volume identical to the target. Both functions
  now return `None` when they compute nothing, `GamutCoverage` and `GamutAnalysisResult` carry
  that `None` through, the console summary says the volume was not computed, the report cells
  route through the same formatter the white point uses, and the JSON emits null.
- Stopped gamut analysis scoring a primary against itself. `_analyze_coverage` read each
  measured chromaticity as `measured_primaries.get(name, target_xy)`, so an absent red, green
  or blue became the target primary of the space being scored. The delta then came out at
  exactly 0.0, the panel reported a perfect primary, and `primary_accuracy_mean` averaged those
  zeros. `analyze` now checks for the three channels up front and names the ones that are
  missing, because every triangle below it indexes them and a `KeyError` from inside an area
  computation does not tell an operator what to measure. The lookup is a direct index, so no
  default can put the answer back.
- Stopped an unmeasured white point reaching a report as D65. The same dict fell back to
  `measured_primaries.get("W", (0.3127, 0.3290))`, so a panel whose white nobody read reported
  6504K at a Duv of 0.0000, which passes on both counts. `white_point_xy`, `white_point_cct`
  and `white_point_duv` now hold `None` until an instrument reads a white. The
  console summary prints "not measured", the PDF and HTML reports print the same through one
  pair of formatters, the JSON emits null rather than a stand-in number, and the tint
  recommendation no longer fires on a white point that does not exist.
- Made the hybrid engine's progress lines name their source. The completion message already
  separates a reading from a model, but two lines above it still said "Measuring display with
  sensorless LUT" and "Measured dE: avg ..." for every source, and an operator watches those
  while the run is still going. Both now carry the source. One helper picks the wording and the
  completion message calls the same one.

- Stopped the hybrid engine filing a simulated reading under a measured name.
  `HybridCalibrationEngine` takes a `measure_fn` and writes what it returns into
  `final_measured_delta_e`, `final_measured_delta_e_max` and `measured_patches`.
  `create_measure_fn` builds exactly that callable, and its `simulated` mode returns what an
  ideal sRGB display would emit for the patch, so a run against the model converged on an
  identity correction and reported the near-zero result as an instrument reading. That is a
  property of the model and not a result about any panel. `create_measure_fn` now stamps its
  mode on the function it hands back, the engine reads that stamp into a `measurement_source`
  field on the result, and the completion message names the source instead of printing
  "Measured" for every one. A caller supplying its own colorimeter method carries no stamp and
  is reported as `unknown`, because a source the engine cannot name is not one it may call an
  instrument.
- Stopped a sensorless-only run answering with a measured accuracy. With no `measure_fn` the
  hybrid engine copied its sensorless prediction into `final_measured_delta_e` and returned,
  handing a caller that read the measured field a modelled number with no instrument anywhere
  in the run. The field now stays empty. It is typed `float | None` and starts at `None`
  rather than 0.0, because zero in a Delta E field reads as a perfect match.
- Made the synthetic uniformity report say so in every block it prints. `cmd_uniformity
  --simulated` announced the mode once at the top, then printed a statistics block, a luminance
  map in cd/m2, a correction-factor grid and a letter grade. That is the shape of a colorimeter
  report, and the announcement scrolls away above it. Each block now carries a `[synthetic]`
  marker and the run closes by stating that no colorimeter read the display.

- Stopped the HDR LUT dividing by a peak luminance nobody measured.
  `create_hdr_calibration_lut` divides absolute luminance by the panel peak at every grid point,
  which was safe while every panel came from the bundled database carrying a measured one. It
  stopped being safe once an EDID-built panel and an imported community panel began reporting
  zero for photometry that was never taken: a zero peak fills the whole grid with inf and nan
  and writes that out as a calibration file. `SensorlessEngine.create_3d_lut` read the
  capability and passed it through. Both ends now refuse, and the outer one names the panel and
  says to measure its peak brightness, because a stack trace from inside a LUT loop does not
  tell an operator what to fix.
- Removed three luminance arguments that steered nothing. `generate_mhc2_profile` took a peak
  and a black luminance and documented them as the display luminance written into the profile;
  the tag it writes is matrix type 1, which holds a signature, a reserved word, the type, and
  twelve fixed-point values, and has no field for either. `compute_color_volume` took a peak
  documented as driving rolloff modelling, where the rolloff comes from the panel family and the
  lightness level. `create_hdr_calibration_lut` took the BT.2408 reference-white level, computed
  its fraction of the peak on a line of its own, and discarded the expression, so every HDR LUT
  this has written left reference white where the panel puts it. The call site in
  `auto_calibration` read an unknown peak and an unknown black off the panel and substituted
  1000 and 0.0001 before handing them over, which is the importer's fabrication one call deeper.
  An argument that reads like a measurement input and changes no output is a false report about
  the code, so all three are gone rather than kept as controls, and the docstrings state what
  each function does read. Reference-white mapping is not implemented and is not claimed.
- Stopped a community panel file reporting photometry nobody submitted. `import_panel` filled
  every absent capability: a 100 cd/m2 SDR peak, a 400 cd/m2 HDR peak, a 0.0001 cd/m2 black,
  10-bit colour, and 2.2 for a missing gamma channel. A community file is written under a
  submitter name, a measurement date and a measurement device, so every number in it reads as an
  instrument observation to whoever imports it next. The submission CLI made the same
  substitution one step earlier, writing 100 and 400 into the file when the submitter pressed
  enter at the brightness prompts, and it never asked for a black level at all, so every
  hand-written submission carried the importer's 0.0001. That black level is not inert. It sits
  below the 0.01 cd/m2 threshold the DDC/CI path reads as an emissive panel, so an IPS monitor
  submitted by hand was sent OLED contrast bytes over the bus, and the SDR peak divides the
  target luminance to produce the brightness byte written beside them. An imported panel is not
  a curiosity either: `cmd_import_panel` writes it into the panel database profiles directory,
  and `PanelDatabase` globs that directory at construction, so it comes back out of `find_panel`
  looking like a measured builtin. Absent photometry now imports as zero, which the consumers
  already read as not known, a blank CLI answer writes no key at all, the CLI asks for a black
  level, and a missing gamma channel raises and names the channel the way a missing primary
  already did.
- Stopped an EDID-built panel reporting photometry that EDID does not carry. `create_from_edid` is
  the fallback for a display the panel database does not hold, and it wrote the same four numbers
  for every one: a 250 cd/m2 SDR peak, a 400 cd/m2 HDR peak, a 0.1 cd/m2 black and a contrast
  ratio of 1000. It also copied the gamut flag into `hdr_capable`, which is a different property,
  because a P3 SDR monitor is wide gamut and is not HDR. EDID chromaticity carries primaries, a
  white point and a gamma byte. It carries no photometry at all, and `parse_edid` reads only the
  base block, so the CTA extension blocks that would hold HDR static metadata are never opened.
  Those numbers reach hardware. The SDR peak divides the target luminance to produce the DDC/CI
  brightness byte written to the monitor, a black level under 0.01 marks the panel as OLED and
  picks the contrast and black level bytes beside it, and the HDR peak is what the detection layer
  reports as the display's peak in nits. All four now report zero, which the consumers read as not
  known, and the profile notes say which fields have no evidence behind them. `wide_gamut` still
  follows from the primaries, which EDID does carry. The two sites that divide by the peak return
  no brightness percentage rather than a percentage of a constant, and the black level path leaves
  the monitor's settings alone rather than reading an unknown black as a perfect one.
- Derived the EDID correction matrix from the primaries instead of weighting it by hand.
  `create_from_edid` built the matrix from the distance of each primary to its sRGB counterpart
  times a fixed coefficient, and the diagonal grew as that distance grew. A panel whose red sits
  well outside sRGB red was told to drive red harder than a panel already at sRGB, which is
  backwards. A wider primary needs less drive to land on the target, not more. The matrix is
  multiplied into linear RGB in `per_display_calibration` on the way to the LUT loaded into the
  GPU, so the error moved pixels rather than a readout. NeuraLux had already stopped trusting it
  and recomputes its own from the primaries, under a comment saying a stored profile matrix may be
  incorrect. The matrix now follows the standard route, sRGB to XYZ to native RGB, the same
  derivation `sensorless_calibration` and `neuralux` use. A panel with sRGB primaries gets the
  identity, and each sRGB primary driven through the matrix lands on its own chromaticity when
  measured through the panel's own primaries. Degenerate primaries return no matrix rather than an
  identity, which would claim no correction is needed.
- Stopped a clip in the LUT path calling itself a gamut mapping. `_map_gamut` took a source and
  a target set of primaries, read neither, and clipped into the unit cube under a docstring
  reading "Simple relative colorimetric mapping". Relative colorimetric adapts the source white
  to the target white and then maps what falls outside the target gamut, so a caller reading the
  name expects out-of-gamut colour to keep its hue and gets it flattened against the cube face
  instead. The clip is unchanged, because changing it needs a mapping to be chosen and measured.
  The docstring now says what the code does and what it does not do.
- Stopped the ICC tone curve parser applying the wrong curve to the display. A `para` tag names
  the formula in a function type field, and `_parse_trc` read every type as the type 0 pure gamma
  `X ** g`. Types 1 through 4 carry a linear segment near black, so the curve the parser produced
  moved the shadow end of the tone response. That curve drives the gamma ramp, which means the
  wrong curve reached the panel rather than being misreported in a readout. Only type 0 is decoded
  now, and the rest return None so the caller falls back.
- Made the hardware calibration sweep show each patch it reads. `_measure_with_display` took the
  patch display callback as optional, and with none given it skipped straight to the colorimeter
  and filed the reading under the RGB it had been asked for. A sweep run that way reads one
  unchanged screen once per patch and reports it under as many different stimuli as the sweep has
  entries, which is a full grayscale ramp and a full primaries set describing one static image.
  The measurement now returns nothing and says why when it has no way to put the patch on screen,
  and `calibrate_hardware` refuses up front rather than working through the whole sweep first.
- Stopped a measured ICC profile carrying primaries nobody measured. `_create_icc_from_measurements`
  substituted the Rec.709 red, green and blue and the D65 white point for any chromaticity the
  sweep failed to produce, and the profile it wrote is saved under a name ending `_measured.icc`
  with a description ending "(Measured)". Those numbers describe a standard rather than the panel
  in front of the instrument, and every color managed application on the machine reads the profile
  as this display characterized. A missing primary or white point now raises and names which one
  was not measured.
- Stopped the gamma fit answering with a number it did not fit. `_calculate_gamma_from_grayscale`
  returned 2.2 when it had fewer than three points and again when fewer than three survived
  normalization, read a missing white as 100 and a missing black as 0, divided by the ramp range
  without checking that there was one, and clamped whatever came out of the least squares fit into
  1.8 to 3.0. The result goes into the profile described as measured and into the correction LUT,
  so an assumed tone response was published as this display and a flat ramp crashed on the
  division. Each of those now raises: too few points, a point with no luminance, endpoints with no
  measured range between them, and a fit outside the range a display produces, which means the
  ramp is not a power law and no single gamma describes it.
- Made the measured LUT read the measurements. `_create_lut_from_measurements` was handed the
  sweep data and never opened it: the primaries and the three channel gammas came from the panel
  database entry matched on the model string, so a run with an instrument attached discarded every
  reading and wrote the database characterization to a file named for a measured run. Two displays
  of the same model got identical corrections whatever the instrument read off each panel. The LUT
  is now built from the measured chromaticities and the gamma fitted to the measured ramp, the
  panel entry supplies the title and nothing else, and a missing measurement raises. The grayscale
  sweep measures one neutral ramp, so the one fitted gamma covers all three channels; a per
  channel figure taken from the database would be a modelled value inside a measured artifact.
- Stopped verification publishing a perfect score for a display it did not read. `_verify_hardware`
  averaged an empty list of Delta E values to 0.0, and the caller wrapped that as measured evidence
  and set the run successful, so a verification that measured none of its patches reported the best
  number the tool can produce with a passing grade. It now raises and says how many patches went
  unmeasured.
- Renamed a chromaticity distance off the Delta E field. The DDC/CI white point loop computes the
  distance between target and measured white in the CIE 1976 u'v' plane, multiplied it by 100,
  and stored it as `delta_e`, where a reader compares it against Delta E tolerances that do not
  share its scale. The loop never measures the target luminance, so no CIE Delta E is available
  from it. The field is `delta_uv` and holds the raw distance, where roughly 0.002 is a just
  noticeable white point shift.
- Gave the two calibration result classes separate names on the package surface. The DDC/CI
  white point loop and the calibration engine each define a `HardwareCalibrationResult`, and
  they hold different fields. The lazy exporter in `calibrate_pro.hardware` had a branch for
  each under that one name, so the second never ran, and `__all__` listed the name beside the
  DDC/CI calibrator while the package handed out the engine's class. Importing the name to
  read a white point result got an object without any of its fields. The DDC/CI result is now
  exported as `DDCCalibrationResult`, and `__all__` lists each result with the module it comes
  from.
- Made the simulated uniformity measurements internally consistent. `create_test_measurements`
  built tristimulus values of (0, luminance, 0) beside a chromaticity pair describing a different
  color, so anything converting the XYZ got an answer the chromaticity contradicts. X and Z now
  follow from the chromaticity, and the luminance clamp runs before both, so the Y a record
  reports is the luminance it reports.
- Made the colorimeter read the patch it is asked about. `_measure_patch` took a reading without
  putting anything on screen, on a comment saying a pattern window would be needed and that the
  patch could be assumed displayed for now, then filed the reading under the RGB it had been
  asked for. The grayscale sweep and the primaries sweep would have read whatever the desktop was
  showing, once per patch, and labelled each reading differently. The engine now takes a patch
  display callback through `initialize` or `set_patch_display`, shows the patch, gives the panel
  time to settle, and reads after that. Without the callback it returns nothing and says why.
- Made the camera engine show a pattern before capturing one. `measure_single_color` accepted a
  `PatternDisplay` and never called it, so a capture from a real camera was a frame of whatever
  the screen already held, recorded under `pattern_rgb`. It now drives the display, and raises
  when there is no display and the camera is not the simulator.
- Stopped the camera engine reporting a calibration it did not apply. With `apply_to_hardware`
  set and consent given, the run reported that it was applying a correction over a statement that
  does nothing, then returned success. Nothing in that engine writes to a display. The call now
  returns unsuccessful and says to take the measured correction through the LUT or DDC/CI path.
  The second grayscale ramp was labelled a verification and its result published as the Delta E
  after correction, which measured the same uncorrected display twice. It is now named a repeat
  measurement, and the result says the correction was computed and not applied.
- Made the Spyder display analysis show white and black before reading them. `analyze_display`
  took two readings back to back, filed the first as the white point and the second as the black
  level, and never put either patch on screen. Both readings described whatever image was already
  there, so the contrast ratio built from them sat near 1.0 for any panel and the reported white
  chromaticity and CCT belonged to the desktop. The method now requires a display callback, shows
  each patch before the read it is filed under, and returns nothing with the reason on the
  progress channel when no callback is given.
- Kept the requested stimulus on a measurement record. `MeasurementResult` carried the blue
  channel of the patch and the Lab b* component in one field, so computing Lab overwrote the blue
  value the patch had been asked for. Every record in the grayscale and primaries sweeps reported
  a stimulus it had not been measured at. The Lab triple is now `lab_l`, `lab_a` and `lab_b`.
- Stopped the fleet server reporting results for displays it never contacted. A calibration job
  queued against a remote node ran a stub that waited a tenth of a second and returned a Delta E
  mean of 1.2 with a pass flag, and the server stored that under the node id and marked the job
  completed. There is no transport to a node, so nothing was measured anywhere. A fleet operator
  reading the job record could not tell that apart from a reading an instrument took on the
  remote display. All five remote operations now raise, naming the operation and the node, and
  the job ends failed with the reason recorded against the node.
- Stopped the ambient light sensors answering with a room level nobody sampled. The base sensor
  class returned 300 lux at 6500 K, and the Windows sensor returned 300 lux whether or not a
  sensor was present, while its initializer did nothing at all. The Windows.Devices.Sensors
  binding is not written, so the Windows sensor now reports itself unavailable and refuses to
  read, and the base class raises and points at the simulated sensor. `SimulatedSensor` is where
  a stand-in value belongs, and it still returns one.
- Stopped the spectrophotometer reporting rendering indices it does not compute. `calculate_cri`
  converted the spectrum to a chromaticity, discarded the result, and returned 95.0 for every
  spectrum it was handed. `calculate_tlci` returned 90.0 the same way. `measure_reflective`
  returned an emissive spot reading, which measures the display rather than the material in front
  of the instrument. All three now raise and name what is missing: the CIE 13.3 test color samples
  and reference illuminant, the TLCI camera model, and spotread in reflective mode with its white
  reference step. A device without the reflective capability still answers None.
- Stopped the fleet server confirming profile pushes that never left the machine.
  `_send_profile_to_node` built a PROFILE_PUSH message, dropped it, and returned True, so
  `push_profile_to_nodes` reported success per node and `ProfileSyncManager.sync_all` listed the
  package under `synced_profiles` with no sync errors. An operator reading that state concludes
  the display is running the profile named there while it runs whatever it had before. The method
  now returns False until a transport exists, and the sync record carries the failure per node.
- Stopped dropping a display Windows still owns because its panel went dark. `enumerate_displays`
  walked the graphics adapters and reported only the monitor devices hanging off each one, so an
  adapter that reported no monitor device contributed nothing. That is a different condition from
  no display: an adapter holds an active desktop with no enumerable monitor device whenever the
  panel is asleep or switched off at the wall, and whenever the mode comes from an indirect display
  driver. Windows still counts that desktop in `GetSystemMetrics(SM_CMONITORS)`, still enumerates
  it through `EnumDisplayMonitors`, still accepts a gamma ramp for it, and still resolves its ICC
  profile, while the tool reported no displays at all and had nothing to calibrate. The adapter is
  now reported in that case, guarded on the adapter being active and carrying a real mode. Every
  monitor-specific field stays empty: the adapter's `DeviceString` names the graphics card, so
  copying it into `monitor_name` would report the GPU as the panel under calibration.
- Stopped naming a panel model from a display mode alone. `identify_display` fell back to a
  fingerprint with the manufacturer stripped off, and `DISPLAY_FINGERPRINTS` carried two keys in
  that form. A mode is not an identity: the table itself lists four panels at 3440x1440@175 and
  five at 3840x2160@240, so the stripped lookup resolved that ambiguity by returning whichever one
  held the bare key. Every 3440x1440@175 display was reported as a Dell Alienware AW3423DW and
  every 3840x2160@240 display as an ASUS PG27UCDM, under a comment reading "assume QD-OLED". The
  key is not a label: `enrich_display_info` copies the matched panel's native gamma, peak
  luminance and gamut onto the display, `hdr_detect` reports that panel's peak luminance in nits
  as the display's, and `vcgt_calibration` builds the correction curve from that gamma, so a
  guessed identity reached the ramp loaded into the GPU. Fingerprint matching now requires the
  EDID manufacturer, and the two manufacturer-free keys are gone. A display whose manufacturer is
  unknown stays unidentified and reports a peak luminance of zero rather than 1000 cd/m2. This
  path is reachable from the enumeration fix above, which reports an adapter with an empty
  manufacturer.
- Stopped reading HDR and wide gamut support off a display mode. `enrich_display_info` set both
  flags on any unmatched display running 4K above 120 Hz, on the reasoning that such a panel is
  usually a recent gaming monitor, then set the gamut flag again wherever `bit_depth` reached 10.
  That second test never failed. `bit_depth` holds DEVMODE's `dmBitsPerPel`, which counts bits per
  pixel rather than per channel, so an ordinary 8-bit sRGB desktop reports 32 there and every
  display the panel database did not match came back wide gamut. A 4K 144 Hz sRGB monitor came
  back HDR as well. The flags select the gamut the correction targets, so a display was calibrated
  toward a color space it cannot reach. Neither field is a spec sheet a record may fill in from a
  resolution. Both stay False on an unmatched display, which reads as not known to be capable and
  sends a caller to the EDID chromaticity primaries for the gamut and to the panel entry or
  `display.hdr_detect` for HDR.
- Stopped detection reporting one monitor's characterization for every display. The panel
  lookup was written against a fixed model string, so each display a session detected came
  back as that monitor: its panel type, its manufacturer, and, wherever EDID colorimetry was
  unreadable, its primaries. A display the bundled database has never heard of reported a
  panel profile it does not have. Each display now resolves against the model string its own
  EDID carries, with the name the bus reports as the fallback, and a display that neither one
  matches is reported as unmatched rather than borrowing another monitor's answer.
- Made a coverage run report a failure instead of dying. The Windows CI lane runs the suite
  under coverage, and the process was exiting with an access violation partway through, which
  reads as a crash in the product and ends the lane before the rest of the suite runs. Neither
  cause was a native call. The Win32 cancellation contracts install a trace function of their
  own, turn on opcode tracing in frames the coverage tracer had already instrumented, and raise
  out of the middle of one of them, so measurement is now suspended for the length of each of
  those windows and started again after, keeping what it had already collected. The mutex tests
  were also leaving one owner thread running for every release the operating system never
  confirmed, and a thread started while coverage is measuring carries its trace function for as
  long as it lives. Those threads are retired once the test that started them has finished
  asserting, which ends the command loop and leaves the unconfirmed handle alone. The note in
  the packaging configuration blamed native GDI calls on daemon threads, which measurement
  ruled out, and now says what was measured.
- Made a suite that passes exit as one. The Windows run finished every assertion and then
  died with an access violation raised inside a garbage collection during interpreter
  shutdown, in three of five observed runs, and the process exit status is what a runner
  reads. What was being collected was Qt. Closing a window hides it, and the C++ object
  stays alive inside a Python reference cycle until a collection that may not happen before
  PySide6 is already being taken apart. A timer or a settings store that a page holds as an
  attribute and gives no parent belongs to no widget tree, so destroying the window does not
  reach it either. Twenty timers were surviving that way, alongside six settings stores and
  three animations. The suite now destroys them after the last test, while the application
  their destructors reach for on the way out is still there. Three consecutive runs of the
  full suite then passed all 2,234 tests and exited zero.
- Turned the two lint gates green. `ruff check .` was reporting an unsorted import block and
  an assignment whose value is never read in the measured calibration script, and a loop in
  the i1d3 driver that reads as `any(...)`. The unread assignment stays as a call, because
  what it is there for is the exception it raises when the target does not resolve to
  exactly one DWM monitor. `ruff format --check .` was reporting eighteen files, seventeen
  of them written by this branch to an 88 column width the project does not use. CI pins
  ruff 0.15.21 and runs both as required checks, so neither was passing before this.
- Made `doctor` answer a person as well as it answers a parser. `--json` was declared by
  both dispatchers and printed in both usage listings, and the command emitted compact
  JSON whichever way it was called, so the first command the documentation tells an
  operator to run returned one long line of it. The flag now selects the form. Without it
  the report is laid out to read: dependencies with versions, the three whole-installation
  checks, and the capability block. The capability block states that nothing was probed,
  because `supported` beside a bus or a colorimeter otherwise reads as a device that
  answered. The JSON form is unchanged, which is what every packaged script and every
  test asks for.
- Gave a display the bundled panel database cannot name a way forward. Detection adopts
  such a display rather than rejecting it, and adopts it uncharacterized, so every
  calibration method and every target after that refused it. The one action that supplies
  a characterization was declared, resolved, and drawn by no window, which left that
  display on the Calibrate page with nothing on the page open to it. The dashboard now
  carries a row saying how the session characterized the display it holds, with the
  control that takes the generic path beside it. A matched session sees the control
  disabled in place with the resolver's own sentence rather than finding it absent.
- Made that row state the session rather than the observation behind it. Taking the
  generic path is a decision the session records, and the detection pass is unchanged, so
  the card still reports an uncharacterized panel while the resolver works from a
  characterized one. The row reads the session, and rereads it when a pass finishes and
  whenever the dashboard comes back into view, because the Calibrate page can move the
  selection while the operator is looking somewhere else.
- Added the gate that would have caught the missing control. The per-page tests read one
  direction, control to declared action, and nothing read the other. A new gate builds the
  window and both dialogs, unions every action they bound, and requires each declared
  surface to be presented or written down under one of four reasons: hidden by the
  manifest, performed from a shortcut or a signal Qt gives no control for, drawn as a
  refusal reason, or an honest null. Each reason is checked against the manifest or the
  source, so an entry cannot become a stale excuse for a control somebody removed.
- Fixed two DDC controls that were painted as though they were live. Both are disabled in
  this build, and the stylesheets they carried declared no disabled colours, so an
  unavailable accent button and an unavailable destructive button drew at full strength.
  Both now take the disabled colours the shared button style declares.
- Widened the GUI truthfulness gates to the window they are about. Three source scans
  read a list of filenames written by hand, and nine of the fourteen modules the window
  reaches were not on it, so both dialogs, the DDC page, the settings page, and the
  binder every control is registered with were reported as covered by a suite that never
  opened them. The list is now read off what the window imports, and a gate fails when a
  module the window reaches is missing from it.
- Gave the window somewhere to answer a plan. Confirming and declining are declared
  actions whose two dialog surfaces no window presented, so a session driven from the
  window sealed a plan, previewed it, and stopped there. Everything downstream stopped
  with it, because sensorless verification reads a plan the session confirmed and the
  report and export actions read that verification, which left three reachable pages
  permanently refused. Previewing now opens the plan beside its digest with both answers
  bound to the resolver. Accepting records the digest and sends nothing to the display,
  which the dialog states beside the button, because Accept under a list of ICC and LUT
  files otherwise reads as a promise to load them.
- Made the add-profile dialog do only what the session permits. It opened a file chooser,
  copied the chosen file into the panel profiles directory, and registered whatever it held,
  with no action resolved and nothing journalled, while the manifest declared both of those
  writes disabled and the command line declined them by name. Reading a chosen file is now a
  declared action: it parses the file where it sits, reports what the file states about the
  panels it describes, and is recorded like any other action. The two write controls stay on
  the dialog, disabled, carrying the resolver's own sentence, so an operator reads why this
  build will not write yet instead of finding a button that quietly does nothing.
- Removed the second display enumeration the same dialog ran. It now lists what the
  session's own detection pass observed, so opening the dialog is one action rather than a
  scan nobody asked for.

- Added the headless calibration session. `detect`, `status`, `verify`,
  `generate-profiles`, and `profiles` drive the actions the window drives, over one
  service, and print what each action returned. A refusal arrives in the words the
  session refused it in rather than a sentence written for the command line.
- Shipped those five commands in the frozen binary, so a headless run no longer requires
  installing Python and the developer wheel. `CalibrateProCLI.exe` answers nine commands
  and refuses the rest by naming the package they live in.
- Added `diagnostics`, which reads back the redacted journal every action writes to. It
  lists each file a support bundle would carry with its digest, publishes exactly those
  bytes when `--bundle PATH` is given, and opens the folder with `--open`. The three
  actions behind it were declared in the manifest and reachable from no surface.
- Built the same three actions into the window, under Diagnostics on the settings page.
  The listing names each member and its digest before anything is written, the save
  button opens only against a live preview, and the token that preview issued is spent by
  the attempt that follows rather than by that attempt succeeding.
- Made the settings page mean what it draws. It rendered eleven declared surfaces and
  handed one to the resolver; the rest wrote into the application's configuration store,
  where nothing read them back, so ticking Start with Windows reported a preference the
  product did not hold. Those controls are gone, along with the writes behind them.
- Made LUT size a preference the work uses. Choosing a grid runs as a declared action, is
  journalled, and is read when the next bundle is generated, which the bundle then records
  in its own manifest. A grid this build does not generate is refused by name.
- Withdrew the default-target claim. Its predicate required a target the session had
  already selected, which is not what a default is, and applying one at startup would
  pre-select before the Method stage. The manifest now declares it hidden rather than
  offering a preference that never existed.
- Kept the HDR checkbox on the page and bound it closed, so it renders disabled carrying
  the session's own reason. Removing it would read as a build that never had the feature.
- Gated the action manifest against the code it names. A required module was checked for
  the shape of a dotted name and never imported, so the manifest declared a module that
  did not exist across a green suite. The gate imports what the manifest requires and
  reads the frozen policy back against it.
- Gated the headless command table in the usage guide against the parsers the commands
  are built from, so a command that runs but has no row fails a gate.
- Added the one-session application service: read-only detection with default-deny
  capabilities, deterministic asset generation, and an atomic export bundle sealed by a
  SHA-256 manifest.
- Added bundle read-back. `profiles` recomputes each digest from the bytes on disk, so a
  bundle whose files changed is reported as changed instead of listed as published.
- Bound the desktop DDC controls, the detection view, and the verification view to the
  actions they stand for, so the window renders the session's observation rather than
  reading hardware beneath it.
- Gated the frozen module closure and the shipped command policy against the dispatcher
  the binary runs. A command added to one list and not the other now fails a gate.
- Fixed the tray reporting a startup registry record in place of the detection the
  running session had performed.
- Corrected the public documentation. `detect`, `status`, `verify`, `generate-profiles`,
  and `profiles` were documented as proposal-only names that exit 2, which they no longer
  are.
- Stopped `patterns` from opening a fullscreen viewer. The manifest declares
  `patterns.open` disabled, the window routes it through the resolver, and the frozen
  binary does not ship the name, so the developer command line now declines it in the
  same words rather than being the one surface that acts.
- Gated the declared calibration presets against the table a session selects from. A
  preset declared without an entry there inherited a refusal naming conditions the
  session already met, which reads as a fault in the session.

## v1.1.0 (2026-07-11)

- Updated GitHub Actions workflows to current checkout/setup-python majors.
- Added the documented `test` extra so `pip install -e ".[test]"` works.
- Normalized scanner-blocking dash punctuation in public docs and developer-facing strings.
- Project Telos presentation and operator-surface pass: README hero, brand assets under `docs/brand/`, cross-flagship navigation, and Current status / Operator surface blocks.
- Documented the operator surface across the PySide6 desktop workflow and read-only CLI.
- Relicensed to the FSL-1.1-MIT as part of Project Telos flagship promotion.
- Migrated the desktop runtime and Build UI integration to PySide6.
- Added the explicit Detect -> Method -> Preview -> Apply -> Verify -> Save/Report workflow.
- Consolidated display mutation behind one confirmation-bound Windows adapter; legacy
  direct-action CLI commands are proposal-only in 1.1.
- Added immutable, SHA-256-bound apply plans, bounded inputs, prior-state capture,
  compensating recovery, authoritative read-back, and concurrency/resource-lifecycle
  gates.
- Removed automatic GUI, tray, guard, and startup actuator paths; packaged entry points
  launch unelevated.
- Added measured/estimated/simulated/replayed/Not measured provenance throughout the GUI
  and report paths; removed seeded or unsupported observations.
- Added read-only `doctor` diagnostics with stable JSON output.
- Added hash-locked Windows builds, exact frozen-module auditing, third-party notices and
  source provenance, PE-manifest checks, per-user installer/portable packaging, and
  frozen smoke/reproducibility verification.

## v1.0.0 (2026-03-22)

### Features
- **58-panel database** with DDC/CI recommendations for QD-OLED, WOLED, IPS, VA, Mini-LED, and RGB OLED panels
- **Sensorless calibration** using panel-specific characterization data and Bradford chromatic adaptation
- **Hardware calibration** via DDC/CI: brightness, contrast, RGB gain/offset, gamma
- **i1Display3 native USB driver** with CCMX spectral correction (44% dE improvement on QD-OLED)
- **3D LUT generation** (33x33x33) with 6 gamut mapping algorithms including CAM16 and Jzazbz
- **13 calibration targets**: Rec.709, DCI-P3, HDR10, Netflix SDR/HDR, EBU Grade 1, and more
- **12 verification patch sets** (287 patches): grayscale, saturation sweeps, SMPTE/EBU bars, skin tones
- **LUT export formats**: .cube, .3dl, .clf (ACES), .mga, .csp, ReShade, SpecialK, OBS, mpv, MadVR, ICC v4
- **CCSS/CCMX import** for community spectral corrections
- **CalibrationGuard** watchdog (15-second polling) prevents Windows from resetting calibration
- **DwmLutGUI integration** with automatic elevation for system-wide 3D LUT
- **PyQt6 GUI** with warm pastel theme, CIE chromaticity diagram, system tray, toast notifications
- **CLI** with 26 commands for headless calibration workflows

### Platform Support
- Windows 10/11: Full support
- macOS: Planned (stubs exist)
- Linux: Planned (stubs exist)

### Tests
- 197 tests passing
