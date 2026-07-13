# Calibrate Pro Functional Recovery Design

- **Status:** Architecture approved; awaiting written-spec review
- **Date:** 2026-07-13
- **Canonical repository:** `C:/dev/public/calibrate-pro`
- **Design worktree baseline:** `origin/main` at `8ed017577b34c7a6d2bfe04a17a254f377ad7b7c`
- **Published baseline:** `v1.1.0` at `7d34ae8d700bf96b7e96ca360edab19680ed7114`

## Decision

Calibrate Pro will undergo a functional-recovery vertical slice through its
current, active PySide6 application. The implementation will make one complete
workflow truthful and operable:

> Detect → Method → Generate → Preview → Confirm → Apply → Verify → Save/Report

The automated Phase 1 acceptance path exercises Apply only through the injected
fake adapter. A production source or frozen build keeps every physical mutation
disabled until the owning capability passes the Phase 2 supervised physical
acceptance gate.

This work is **not a regression response**. Static inspection confirms that the
affected behavior exists in the published `v1.1.0` tree and remains present on
`origin/main`. It is baseline functional recovery for actions that shipped
incompletely wired or with deterministic failure paths.

The active `calibrate_pro.gui.app.CalibrateProWindow` shell remains canonical.
The recovery will not replace it wholesale with the dormant
`calibrate_pro.gui.main_window.MainWindow` or another historical GUI. Existing
pure workflow, confirmation, actuation, and recovery primitives will be wired
into the active application instead of duplicated.

Every exposed action must tell the truth. An action that is not implemented,
packaged, tested, and supported for the current capability state will be
disabled with an actionable reason or hidden. It must not remain clickable,
report placeholder success, or imply that a display, profile, file, or setting
was changed when it was not.

## Verified Baseline

The source findings below were verified by static inspection at
`origin/main@8ed0175`, with corresponding failure patterns checked in the
`v1.1.0@7d34ae8` tree. Runtime checks are identified separately as session
observations and state when raw output was not persisted. No physical display,
USB sensor, DDC/CI path, DWM LUT path, profile writer, startup writer, or GUI
automation was invoked during design discovery.

| Finding | Evidence |
| --- | --- |
| The active source and frozen GUI instantiate `CalibrateProWindow`. | `calibrate_pro/commands/gui.py:9-25`; `calibrate_pro/frozen_main.py:12-16,57-85` |
| Dashboard population can reference `mgr` when construction of `StartupManager` failed, producing an uncaught `UnboundLocalError`. | `calibrate_pro/gui/app.py:1316-1355` |
| Dashboard panel matching is bypassed by assigning `panel = None`, so panel type, HDR capability, primaries, and related data remain unknown. | `calibrate_pro/gui/app.py:1300-1336` |
| EDID profile creation cannot become available because the scan assigns both `panel = None` and `edid_chromaticity = None`, then disables Create when chromaticity is absent. | `calibrate_pro/gui/app.py:923-1019` |
| Profiles → Generate All imports nonexistent `calibrate_pro.calibration.engine.CalibrationEngine`. | `calibrate_pro/gui/pages/profiles.py:550-581` |
| The active Calibrate workers import `calibrate_pro.calibration.native_loop`, and Test Patterns imports `calibrate_pro.patterns.display`, but neither module is in the default-deny frozen first-party manifest. | `calibrate_pro/gui/pages/calibrate.py:110-254,281-405`; `calibrate_pro/gui/app.py:2159-2165`; `packaging/frozen-modules.json` |
| Calibrate All changes only status text. Menu Export accepts a destination and reports “Exported” without creating a file. | `calibrate_pro/gui/app.py:2118-2119,2146-2157` |
| Sensorless Calibrate creates only an in-memory `ApplyPlan`; completion exposes no preview review, one-use confirmation, or Apply action. | `calibrate_pro/gui/pages/calibrate.py:35-84,921-968,1026-1043` |
| Verify advertises measured verification when a sensor is detected but always starts `VerifyWorker`, the sensorless worker. | `calibrate_pro/gui/pages/verify.py:55-127,998-1036` |
| The active DDC page stages values in `_pending_changes`, but has no active composition with `ActuationCoordinator` and no confirmed apply operation. | `calibrate_pro/gui/pages/ddc_control.py:126-135,526-593` |
| The active Settings page persists values, but its advertised startup, tray, default-target, LUT-size, OLED, HDR, and per-app settings are not consumed by the active window or calibration page. The only separate consumer found for `general/minimize_to_tray` is the dormant `gui/main_window.py`. | `calibrate_pro/gui/pages/settings.py:131-267`; `calibrate_pro/gui/main_window.py:367` |
| The active GUI writes to Python loggers but configures no durable file handler. GUI and tray sources are omitted from the main coverage run. | `calibrate_pro/gui/app.py:8-18,1551-1584,1835-1888`; `pyproject.toml:69-72` |
| The dependency-light safe suites passed on both inspected baselines during this design session: 423 tests on exact `v1.1.0` and 436 tests on `origin/main`. These results establish healthy covered code, not working GUI actions. | Session observation on 2026-07-13; raw command output was not persisted. |
| The released portable CLI started for `--version`, `--help`, and read-only `doctor --json` during this design session, so the observed action failures are not evidence of a generally broken runtime package. | Session observation on 2026-07-13; raw command output was not persisted. |
| No durable Calibrate Pro GUI log was found in the inspected per-user application-data locations, consistent with the missing active-GUI file handler. | Session observation on 2026-07-13; the log-census output was not persisted. |
| Concurrent copies of the safe suite can collide on the fixed `%TEMP%/test_export.clf` path. The same suites passed sequentially during this design session. | `tests/test_professional_features.py:97`; session observation on 2026-07-13; raw parallel-run output was not persisted. |

These findings establish a release-quality gap. They do not establish that
every dormant module is broken, nor do they authorize treating historical GUI
code as a replacement implementation.

## Goals

1. Make the active application complete one truthful, deterministic
   calibration workflow from detection through saved evidence.
2. Route every display mutation through the existing
   `WorkflowController` and `ActuationCoordinator` boundaries.
3. Keep sensorless estimates and instrument measurements separate in types,
   labels, execution paths, receipts, reports, and tests.
4. Make action availability derive from a default-deny capability manifest
   shared by menus, pages, tray actions, shortcuts, and frozen packaging.
5. Produce exact calibration assets, plan hashes, apply receipts, verification
   evidence, and export receipts before the UI can report success.
6. Add durable, bounded, redacted diagnostics that make user-visible failures
   supportable without collecting credentials or raw/direct device identifiers.
7. Test the active GUI action graph with injected fake adapters and test the
   final frozen candidate without hardware side effects.
8. Require a separate, supervised physical-acceptance lane before claiming
   that a real instrument or display actuator works.
9. Preserve least privilege: launch unelevated and elevate only a narrowly
   scoped operation if a future platform requirement proves it necessary.

## Non-Goals

- Replacing `CalibrateProWindow` with the historical `MainWindow` or
  combining every dormant GUI into a new shell.
- Expanding the visual design, HDR grading feature set, ambient automation,
  network calibration, or enterprise fleet management during recovery.
- Implementing Calibrate All as concurrent or unattended multi-display
  mutation. It is hidden for this recovery release.
- Claiming measured Delta E, gamut coverage, accuracy, or verification without
  actual instrument observations and provenance.
- Making recovery crash-safe. The existing guarantee is
  `IN_PROCESS_BEST_EFFORT`; power loss and process termination remain outside
  that guarantee.
- Running hardware writers, USB access, DDC/CI writes, DWM LUT application,
  ICC association, VCGT application, startup registration, or display mutation
  in automated tests.
- Treating all source modules as frozen dependencies. The frozen graph remains
  positive, minimal, and auditable.
- Adding telemetry, remote log upload, user tracking, or a cloud dependency.

## Architectural Principles

### One active shell, one application service

`CalibrateProWindow` remains the composition root used by the source command
and frozen executable. Its pages become presentation surfaces over an injected
application service rather than independently importing calibration engines,
sensors, or writers.

The application service owns one workflow session at a time and composes:

- read-only display and capability sensors;
- deterministic sensorless and measured generators;
- the existing pure `WorkflowController`;
- the existing `ActuationCoordinator`;
- method-specific verification services;
- atomic artifact exporters;
- the action capability registry; and
- the redacted diagnostic journal.

The GUI may format inputs, render plans, request transitions, and display
results. It may not import low-level DDC, ICC, VCGT, DWM, USB, or startup
writers. Historical pages may be adapted incrementally, but they do not gain a
second workflow controller or a direct mutation path.

### Stable session identity

Detection creates an immutable display observation with a stable platform
display identifier, a user-safe label, resolution, refresh rate, HDR state,
matched panel characterization when available, and capability evidence.
Device serials, raw EDID bytes, PnP paths, and monitor handles stay inside the
platform boundary and are not persisted in product diagnostics.

Changing the selected display, method, target, capability state, or generated
asset invalidates the prior preview and consumes or discards its confirmation.
No token or plan can be reused across displays or edited plans.

### Default-deny action registry

A source-controlled action capability manifest is the product truth for every
interactive action. Each record contains:

- a stable action ID;
- every GUI surface that exposes it;
- read-only or mutating classification;
- required capabilities and workflow stage;
- source and frozen availability;
- required first-party modules and runtime resources;
- whether a receipt is required;
- supported evidence mode; and
- its enabled, disabled-with-reason, or hidden policy.

The registry fails closed. An action bound in the active GUI but absent from
the manifest is disabled during development and fails CI. A manifest action
whose handler, transitive frozen dependency, fake-adapter contract, or
packaged-candidate test is absent cannot be enabled.

Menus, toolbar buttons, page controls, shortcuts, and tray actions use the same
action ID and resolved state. Duplicated UI entry points cannot drift into
different behavior.

## Recovery Action Truth Table

The first recovery candidate uses the following product states. “Enabled” means
the action has a real handler, deterministic result or receipt, action-level
test, and frozen closure. “Conditional” means the registry enables it only
after all listed capabilities and workflow state are proven.

| Action | Recovery state | Required behavior |
| --- | --- | --- |
| Refresh / Detect Displays | Enabled, read-only | Return immutable display observations or a typed actionable error. Never leave a partially populated dashboard. |
| Add Display Profile from EDID | Disabled until a read-only EDID provider returns validated chromaticity evidence | Do not offer a generic profile while calling it EDID-derived. Imported JSON remains a separate, validated action. |
| Select Sensorless Method | Enabled when a display and characterized or explicitly generic panel source are available | Label every derived value estimated and record the characterization source. |
| Select Measured Method | Conditional | Requires a supported instrument, the measured runner, frozen closure, and completed physical qualification. Otherwise show “Measured calibration unavailable” with the exact reason. |
| Select Hybrid Method | Disabled until it has a distinct, tested generator/verifier contract | It must not reuse the measured worker under a different label or silently mix estimated and measured evidence. |
| Custom white point | Conditional on a validated numeric target | Parse and range-check the requested CCT or chromaticity coordinates into the immutable target. The literal label `Custom` can never enter calibration math. |
| HDR mode and target | Hidden or disabled until the selected generator consumes the exact HDR target | Persisting an HDR selection without changing the plan is not functionality. Estimated HDR and measured HDR remain separately labeled. |
| Generate Calibration | Conditional by method | Create real assets in a staging directory, hash and parse them, and construct one immutable `ApplyPlan`. Generation itself performs no display write. |
| Preview Plan | Enabled after successful generation | Show exact display, method, targets, DDC changes, profile/LUT files, hashes, evidence labels, and recovery guarantee. |
| Confirm and Apply | Conditional | Requires a still-current plan, live capability revalidation, deliberate confirmation, and a one-use unexpired token. All writes route through `ActuationCoordinator`. |
| Calibrate All | Hidden | Multi-display mutation is outside this vertical slice; no no-op control remains visible. |
| Sensorless Verification | Enabled after generation or apply, with state labeled | Produce characterization-derived estimates only. It may not report measured Delta E or measured gamut. |
| Measured Verification | Conditional and separately routed | Requires a supported sensor and real patch observations. If the complete patch sequence is not qualified, the action is disabled rather than falling back to sensorless verification. |
| Profiles → Generate All | Disabled until rebuilt over the canonical generator | The nonexistent engine import is removed. When enabled later, each target produces verified files and its own receipt. |
| Profile Activate / Install | Disabled until activation is represented by a complete `ApplyPlan` | A preview message is not activation. Physical activation requires capture, confirmation, authoritative readback, and a truthful receipt. |
| Profile Delete / Unlink | Disabled until a path-confined deletion plan is implemented | Show the exact managed artifact, require deliberate confirmation, reject paths outside the managed profile root, perform the filesystem change, and verify the result before reporting success. |
| Profile Export | Enabled only for existing validated source files | Copy atomically, read back, hash, and report the exact destination. Copying zero files is a failure, not success. |
| Menu Export | Conditional on an active compatible artifact | Invoke the canonical exporter for the requested format and report success only after readback. |
| Test Patterns | Disabled in a frozen candidate until its module and resources pass closure and candidate tests | No packaged button may import an excluded module. |
| DDC sliders | Conditional preview controls | Stage allowlisted values in the current plan. They never write on slider movement. Unsupported VCP controls are disabled. |
| DDC Apply | Conditional | Available only through the canonical preview and confirmation flow when DDC capture, write, readback, and recovery capabilities are present. |
| Tray → Switch Profile | Disabled until it presents an actionable profile choice and routes activation through the canonical plan and confirmation flow | A toast or status message is not a profile switch. |
| Restore Defaults | Disabled until reset semantics, capture, readback, and compensation are represented by a tested plan | No status-only or informational substitute is presented as restore. |
| Settings: default target, LUT size, HDR selection | Enabled only after the active generator consumes them | Saved values must initialize the active workflow and appear in its plan. |
| Settings: startup, minimize-to-tray, OLED automation, per-app switching | Hidden or disabled until their advertised behavior is wired and tested | Persisting a checkbox alone is not functionality. |

## End-to-End Data and Control Flow

### 1. Detect

The application requests read-only observations and capabilities. A complete
result atomically replaces the dashboard model. A failed observation produces
a typed error and a retry action; it does not leave an unbound manager or mix
old and new display state.

Panel matching is explicit. The detector either returns a characterized panel
with provenance, returns an explicitly labeled generic characterization, or
returns no match. It never represents hard-coded `None` as a successful
database lookup.

### 2. Select method and target

The application creates a `WorkflowController` with the detected
`CapabilityState`, calls `detect_complete()`, and permits only a method for
which `disabled_reason()` returns no reason.

Sensorless and measured methods use separate generator and verifier interfaces.
The UI cannot silently substitute sensorless execution after the user selected
measured execution. A capability change invalidates the selection and returns
the workflow to a truthful state.

### 3. Generate deterministic assets

The selected generator receives an immutable display observation, target,
algorithm version, dependency versions, and method-specific evidence. It writes
to a private staging directory. It then reparses each output, verifies its
format and bounded size, computes SHA-256, and returns an immutable generation
result.

Calibration asset bytes and the canonical plan are deterministic for identical
inputs and versions. Wall-clock time, diagnostic correlation IDs, and UI state
are not inputs to calibration math. Time-bearing run metadata is stored beside,
not inside, the canonical asset hash domain.

No display state changes during generation. A generated file is not described
as installed, active, or verified.

### 4. Preview

The application constructs an immutable `ApplyPlan` containing the stable
display ID, method, targets, allowlisted DDC proposals, exact asset paths and
SHA-256 digests, processing domain, and expected output files.

`WorkflowController.set_preview()` validates stage and capability consistency.
`ActuationCoordinator.preview()` seals the plan and issues a short-lived,
one-use confirmation token. The token stays in memory, is never displayed or
logged, and is invalidated by any plan-affecting change.

The preview renders from the sealed plan, not from mutable widget values.

### 5. Confirm and apply

The confirmation dialog shows the exact sealed plan and clearly distinguishes:

- file creation already completed during generation;
- proposed display mutations not yet performed;
- the target physical display;
- sensorless versus measured evidence;
- expected verification mode; and
- the `IN_PROCESS_BEST_EFFORT` recovery guarantee.

Explicit acceptance invokes `ActuationCoordinator.apply(plan, token,
confirmed=True)`. Decline, expiry, replay, plan drift, display drift, and
capability loss consume or invalidate the token and perform no write.

The coordinator remains the sole application-level route to the Windows
display-state adapter. It revalidates capabilities, authorizes exact prior-state
capture, applies the sealed plan, reads back effects, and performs compensating
recovery when required.

### 6. Verify

Verification is selected from the plan's method, never merely from current
sensor presence.

- Sensorless verification reports `ESTIMATED` or `NOT_MEASURED` metrics,
  includes characterization provenance, and states whether it describes a
  generated plan or a successfully applied plan.
- Measured verification requires actual patch observations and instrument
  provenance. A white reading alone is not ColorChecker verification and cannot
  produce measured Delta E. Incomplete measurement capability disables the
  measured verification action.

Apply readback and colorimetric verification are separate evidence. A
successful adapter readback proves that requested state was observed; it does
not prove color accuracy.

### 7. Save and report

The exporter receives immutable assets, plan digest, apply receipt, and
verification evidence. It writes into a temporary sibling, closes it, reads it
back, verifies its hash and expected format, then atomically publishes it.

The UI reports success only after publication and readback. The saved manifest
records asset hashes, algorithm and dependency versions, evidence kind,
verification source, apply-receipt flags, and recovery guarantee. It contains
no confirmation token, credential, raw EDID, sensor serial, PnP path, username,
or unredacted home-directory path.

## Error, Diagnostics, and Recovery Model

### Typed action outcomes

Every action returns either a typed success value or a typed action error with:

- stable error code and action ID;
- user-facing summary;
- retryability and next action;
- workflow stage;
- redacted technical category; and
- diagnostic correlation ID.

The GUI handles expected failures at the action boundary. It does not catch all
exceptions and then report generic success. Unexpected exceptions are converted
to a failed action, journaled, and surfaced with a safe summary and correlation
ID.

### Durable redacted journal

The application writes bounded rotating JSON Lines under the per-user local
application-data directory. Each record may contain:

- UTC timestamp and random correlation ID;
- Calibrate Pro version, source/frozen mode, and platform version;
- action ID, workflow stage, resolved capability booleans, and outcome;
- exception type, stable error code, and redacted message;
- plan and asset SHA-256 values;
- apply receipt phase flags and recovery guarantee; and
- export path basename and content hash.

The journal must not contain passwords, environment variables, access tokens,
confirmation tokens, private keys, raw EDID, USB or monitor serials, customer
data, full PnP paths, full user paths, profile contents, screenshots, or raw
measurement payloads. Display identity is represented by a per-install salted
pseudonym. Free-form exception strings pass through a central redactor before
persistence.

The pseudonym salt is random, stored separately in per-user local application
data with access limited to that user, and excluded from diagnostics bundles.
It rotates when local diagnostics identity is reset or the product is
reinstalled. If private salt storage cannot be established, the journal omits a
stable display pseudonym rather than persisting a raw or weakly hashed device
identifier.

Logs remain local, are not uploaded, rotate by size and count, and have an
in-product “Open diagnostics folder” action. A diagnostics bundle requires
explicit user action, applies a second redaction pass, and previews its file
inventory before creation.

### Recovery truth

The existing `ApplyReceipt` flags distinguish captured, applied, verified,
restore-attempted, and restored phases. The UI and report reproduce those flags
without converting partial or failed recovery into success.

Current compensation is in-process best effort. Startup crash recovery,
power-loss recovery, and durable write-ahead journaling require a separate
design. This recovery release must state that limitation anywhere it presents
the recovery guarantee.

## Frozen Transitive-Closure Contract

`packaging/frozen-modules.json` remains default-deny. Recovery does not solve
missing modules by collecting the entire `calibrate_pro` tree.

The action manifest and frozen module manifest become mechanically linked:

1. Each enabled frozen action declares its first-party modules and resources.
2. A static import-closure check computes reachable first-party modules from
   the action handler and compares them with the positive manifest.
3. Optional imports are exercised in their enabled and capability-missing
   states.
4. A frozen analysis report fails if an enabled action reaches an excluded
   first-party module or an undeclared distribution.
5. A packaged action smoke invokes each enabled action with injected fake
   services and verifies a typed result.
6. A staged-tree audit verifies every required runtime file and license record.

`calibrate_pro.calibration.native_loop` and
`calibrate_pro.patterns.display` are included only if their owning actions
pass this full closure and packaged-candidate lane. Otherwise those actions
remain disabled or hidden. A source-only import success is insufficient.

## Test and Evaluation Strategy

Implementation follows test-first development. Tests are layered so pure
contracts receive dense coverage while platform and GUI boundaries use injected
fakes.

### Pure contract tests

- action-manifest schema, default-deny behavior, duplicate surfaces, and
  handler/manifest parity;
- deterministic generation and plan hashing from fixed fixtures;
- workflow transition legality and invalidation rules;
- sensorless/measured type and provenance separation;
- one-use, expired, declined, replayed, mismatched, and capability-drifted
  confirmation behavior;
- export atomicity, readback, zero-file failure, and receipt truth;
- diagnostic redaction and retention; and
- apply-receipt and recovery-copy truth.

### Active GUI action tests

Offscreen PySide6 tests instantiate the real `CalibrateProWindow` with fake
display sensors, generators, verifiers, exporters, capability providers, and
display-state adapters. They exercise every enabled, disabled, and hidden action
through its public UI signal:

- dashboard population success and each detector failure;
- panel matched, generic, and unknown states;
- sensorless flow from Detect through Save/Report;
- measured capability missing, present-but-unqualified, and qualified routing;
- preview invalidation after every plan-affecting edit;
- confirmation decline, expiry, replay, and exact-plan success;
- capture, apply, readback, recovery, and recovery-failure receipts;
- export write, readback, and disk failure;
- settings that are consumed, and the absence of inert advertised settings;
- every menu/page/tray/shortcut alias resolving the same action; and
- no success message without a verified success value.

The broad `*/gui/*` coverage omission is removed for the active shell and
action handlers. Strictly visual paint-only widgets may remain explicitly
excluded, but active action orchestration receives its own meaningful coverage
threshold and branch report.

Fake adapters record calls and fail the test if an unconfirmed write is
attempted. Automated tests must not import or open USB, DDC/CI, DWM, WCS, VCGT,
startup, or other physical writer implementations.

### Packaged-candidate tests

The final Windows candidate is installed in a disposable unelevated VM and
tested without network access or a Python installation. The lane verifies:

- `CalibrateProCLI.exe doctor --json`;
- frozen feature and module manifests;
- active GUI launch and orderly exit;
- the packaged action registry and all disabled-reason text;
- the complete fake-adapter sensorless vertical slice in offscreen smoke mode;
- measured-mode fail-closed behavior without a sensor;
- deterministic asset/export hashes from a bundled public fixture;
- durable redacted diagnostics after injected action failures;
- absence of excluded first-party imports for enabled actions;
- dependency and license inventory;
- installer and portable artifact integrity; and
- unelevated executable manifests.

The packaged smoke mode must inject fake services before the active window is
constructed and must refuse physical adapters. It is a product diagnostic path,
not a hidden hardware bypass.

### Physical acceptance boundary

Real hardware validation is a separate, supervised, manual release gate on a
designated test workstation. It is never part of CI and is not authorized by
this design session.

The operator checklist must identify the test display and instrument in a
private local record, capture a restorable baseline, verify preview accuracy,
exercise decline with zero mutation, apply one bounded plan, verify authoritative
readback, exercise restoration, and collect evidence-labeled verification. It
must also test application restart, cancellation, and a controlled failure.

Public release claims are capability-specific:

- Sensorless generation may ship after automated and packaged-candidate gates.
- DDC/ICC/VCGT/DWM application may be enabled only after its physical lane
  passes on supported hardware.
- Measured calibration and measured verification may be enabled only after the
  complete instrument and patch workflow passes physical qualification.

An unqualified capability remains disabled even when its source code exists.

## Rollout

### Phase 0 — Truth and observability

- Add the action capability manifest and bind every active surface.
- Hide Calibrate All and disable guaranteed-failure or placeholder-success
  actions.
- Fix dashboard atomic population and install durable redacted diagnostics.
- Add action-level offscreen tests for the current UI truth states.
- Replace the fixed `%TEMP%/test_export.clf` test artifact with per-test
  isolation before enabling parallel safe-suite execution.

This phase may produce an urgent patch candidate because it removes false
success and deterministic exceptions without expanding mutation scope.

### Phase 1 — Sensorless vertical slice

- Introduce the injected application service and session model.
- Wire detection, target selection, deterministic sensorless generation,
  preview, one-use confirmation, coordinator apply, estimated verification,
  and atomic save/report.
- Consume only the settings supported by this flow.
- Complete fake-adapter and packaged-candidate tests.

Phase 1 coordinator Apply is an automated fake-adapter proof only. The
production application may generate, preview, confirm, verify estimates, and
save artifacts, but it keeps DDC, ICC, VCGT, DWM, and every other physical
writer disabled until the specific capability completes Phase 2 acceptance.

### Phase 2 — Existing mutation capabilities

- Route supported DDC, ICC, VCGT, and DWM proposals into the same immutable
  plan and confirmation boundary.
- Keep unsupported controls disabled.
- Complete the supervised physical acceptance checklist per capability.

### Phase 3 — Measured workflow

- Implement or adapt a complete measured generator and patch verifier under
  the separately gated CP-HDR-1 measured-HDR proposal after that proposal
  receives its own written approval.
- Preserve instrument provenance and refuse sensorless fallback.
- Enable measured actions only after frozen closure and physical qualification.

### Phase 4 — Recovery release

- Build twice from the pinned release environment.
- Run source, frozen, installer, portability, redaction, and artifact audits.
- Publish release notes that call this functional recovery, list disabled
  capabilities honestly, and do not call it a regression.
- Retain `v1.1.0` for lineage while identifying its known functional limits;
  do not rewrite release history.

## Risks and Mitigations

| Risk | Mitigation |
| --- | --- |
| Historical GUI code appears more complete and invites a wholesale swap. | Keep `CalibrateProWindow` canonical; reuse only isolated, tested logic behind the new application service. |
| Enabling source modules makes the frozen artifact large or introduces unlicensed dependencies. | Positive transitive closure, staged inventory, size gate, and license/source-provenance gate. |
| A device is detected but cannot perform the claimed operation. | Separate detection from qualified capability; revalidate immediately before capture and apply. |
| Sensorless values are mistaken for instrument observations. | Separate interfaces and evidence types; plan-bound verifier selection; truthfulness tests and report gates. |
| A GUI alias bypasses confirmation. | One action registry and one handler per action ID across menus, pages, tray, and shortcuts. |
| Concurrent or stale UI state applies to the wrong display. | Immutable stable display identity, plan digest, serialized apply, one active session, and invalidation on any relevant change. |
| Diagnostics disclose private device or user data. | Allowlisted event fields, central redaction, salted display pseudonyms, bounded local retention, and bundle preview. |
| Recovery is overstated. | Surface receipt flags and `IN_PROCESS_BEST_EFFORT` verbatim; defer crash-safe claims to a separate design. |
| Automated verification touches real hardware. | Dependency-injected fakes, writer-import guards, disposable VM candidate tests, and a separate manual physical gate. |
| Scope expands into every advertised feature. | Recover one vertical slice first; hide or disable unqualified actions; require a new approved spec for unrelated functionality. |

## Alternatives Considered

### 1. Recommended: recover the active GUI through one canonical service

This approach keeps the shipped visual shell, reuses the existing pure workflow
and hardened actuation boundary, and adds deterministic action and packaging
contracts. It minimizes migration risk while making behavior testable.

### 2. Popup and import patch

Fixing the dashboard exception and missing imports would reduce visible errors
quickly, but Calibrate All, export, settings, DDC, confirmation, and verification
would remain incomplete. Green imports would still not establish functional
behavior. This approach is rejected as the final architecture, though Phase 0
contains its truthful emergency subset.

### 3. Replace the active GUI with a dormant historical GUI or broad rewrite

Historical surfaces contain more controls but also have separate state,
hardware, and compatibility assumptions. A broad replacement would expand the
audit and physical-risk surface before a measurable vertical slice exists.
This approach is rejected for functional recovery.

## Success Criteria

- [ ] The source and frozen application use
  `calibrate_pro.gui.app.CalibrateProWindow` as the single active shell.
- [ ] Every interactive menu, page, tray, and shortcut action has one
  source-controlled action ID and default-deny capability record.
- [ ] No unsupported action is clickable. Unsupported actions are disabled with
  an accurate reason or hidden.
- [ ] Dashboard refresh is atomic and cannot reference an uninitialized object.
- [ ] Panel and EDID states reflect real read-only evidence rather than
  hard-coded `None`.
- [ ] The fake-adapter sensorless workflow completes Detect → Method → Generate
  → Preview → Confirm → Apply → Verify → Save/Report.
- [ ] Generation produces real, reparsed, hashed assets and performs no display
  write.
- [ ] Preview renders the exact immutable plan and every plan-affecting change
  invalidates its confirmation.
- [ ] Declined, expired, replayed, mismatched, or capability-drifted
  confirmations perform zero writes.
- [ ] Every supported mutation routes only through
  `ActuationCoordinator.apply()` and yields a truthful `ApplyReceipt`.
- [ ] Sensorless verification is always estimated or not measured.
- [ ] Measured verification never routes to the sensorless worker and remains
  disabled until a complete instrument path is qualified.
- [ ] Hybrid, custom-white-point, and HDR selections either bind validated
  method-specific target data into the immutable plan or remain disabled.
- [ ] Calibrate All is hidden until separately designed and tested.
- [ ] Profile Activate/Install, Profile Delete/Unlink, and tray Switch Profile
  each have an explicit default-deny state and cannot report status-only
  success.
- [ ] Export success requires at least one published file, readback, and hash
  verification.
- [ ] Only settings consumed by active behavior are exposed.
- [ ] Durable diagnostics survive restart, rotate, and pass credential, token,
  user-path, and device-identity redaction tests.
- [ ] Active GUI action orchestration is included in a dedicated coverage lane.
- [ ] The safe suite uses isolated temporary artifacts and passes its supported
  parallel execution lane without the fixed `test_export.clf` collision.
- [ ] Every frozen-enabled action passes transitive-closure and packaged
  fake-adapter tests.
- [ ] Automated source, CI, and packaged-candidate tests perform no physical
  hardware actuation.
- [ ] Each real mutation or measurement capability is enabled publicly only
  after its supervised physical-acceptance checklist passes.
- [ ] Release notes describe functional recovery and known limitations without
  claiming a regression or rewriting `v1.1.0` lineage.

## Written-Spec Review Gate

The architecture has been approved conversationally. This written specification
is awaiting user review. Committing this design document records the proposal
only; it does not authorize an implementation plan, product-source change,
build, hardware action, product-code commit, push, or publication. After
written-spec approval, the next step is a Superpowers implementation plan that
decomposes Phase 0 and Phase 1 into test-first, reviewable tasks in an isolated
worktree.
