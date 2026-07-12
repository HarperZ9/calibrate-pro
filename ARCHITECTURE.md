# Architecture

Calibrate Pro 1.1 separates color computation, workflow policy, user confirmation, and
Windows display actuation. The central rule is simple: application-facing code can
propose a display change, but only the confirmation coordinator and canonical Windows
adapter can execute it.

## Layers

```text
calibrate_pro/
  core/             color math, profiles, LUT generation, transforms
  targets/          SDR/HDR calibration target definitions
  panels/           characterized-panel data and read-only detection
  calibration/      instrument measurement and calibration algorithms
  sensorless/       characterization-derived estimation algorithms
  verification/     evidence types, patch analysis, reports, PDF export

  workflow.py       pure six-stage state machine and immutable ApplyPlan
  actuation.py      one-use confirmation and transaction coordination
  recovery.py       transaction phases, compensation, and receipts
  diagnostics.py    deterministic, read-only installation report
  runtime.py        source/frozen resource resolution

  adapters/
    windows_display_state.py
                    canonical DDC/CI, ICC, VCGT, and DWM write boundary

  gui/              PySide6 presentation; emits proposals, never raw writes
  commands/         unelevated desktop/HDR launch and read-only doctor command
  main.py           read-only CLI dispatch and proposal-only legacy names
  frozen_main.py    two frozen executable entry points
```

Low-level Windows modules still contain native API wrappers. Application code cannot
import or call their writer primitives directly; `DefaultWindowsDisplayAdapter` is the
sole production bridge from a confirmed transaction to those wrappers.

## Workflow

The user-visible state machine is:

```text
Detect -> Method -> Preview -> Apply -> Verify -> Save/Report
```

1. Detection gathers display identity and capability information without granting write
   authority.
2. Method selection chooses sensorless or measured evidence.
3. Preview constructs an immutable `ApplyPlan`. External ICC, VCGT, and DWM inputs are
   bounded and bound to the plan by SHA-256.
4. Confirmation is consumed once. The coordinator revalidates capabilities and hands an
   opaque authorization to the adapter while holding the apply gate.
5. The adapter captures the requested prior state, applies the sealed plan, and reads the
   result back. A failure invokes compensation and verifies that compensation before it
   reports restoration.
6. Verification and reports preserve the evidence kind and source of every performance
   metric.

Rejecting, expiring, copying, substituting, or mutating a plan does not authorize a
write. Legacy mutation-capable CLI names are proposal-only and return without changing
display state.

## Capability and recovery model

`CapabilityState` distinguishes sensor, DDC/CI, DWM write, authoritative DWM capture,
ICC association, and VCGT capabilities. A requested operation is disabled unless its
capability is positively present. In particular, DWM application requires both write
support and authoritative prior-state capture; process-local LUT memory is not accepted
as evidence of operating-system state.

Transactions use per-display process and Windows named mutexes. ICC content-addressed
cache operations also use a digest-scoped mutex and native file lease. Native resources
remain registered until cleanup is positively known, and uncertain outcomes fail closed.
Recovery is an in-process compensating transaction rather than a promise of crash-safe
rollback across power loss or operating-system termination.

## Evidence model

Performance fields cross the report boundary as `MetricValue`, not bare numbers. Each is
labelled `measured`, `estimated`, `simulated`, `replayed`, or `not_measured`, and numeric
values retain a source receipt. Sensorless computation can inform a plan, but it does not
become an observation of the attached display.

## Entry points

- `CalibratePro.exe` / `calibrate-pro gui`: main PySide6 workflow.
- `CalibrateProCLI.exe`: frozen `doctor`, `gui`, and `hdr` dispatcher; `hdr` opens the
  HDR target/proposal workflow.
- `calibrate-pro doctor [--json]`: deterministic, read-only installation diagnostics.
- `list-targets`, `list-panels`, `info`, `hdr-status`, `patterns`, and `plugins`:
  read-only or visual-inspection utilities.
- Tray and calibration guard: monitor-and-notify only in 1.1.

Both frozen executables use `asInvoker`; the installer is per-user and lowest privilege.

## Release architecture

The Windows release uses one PyInstaller analysis and two onedir executables. An exact
first-party/distribution allowlist, Qt-component policy, component-to-notice policy, and
source-provenance lock fail closed on unknown staged content. The build produces a
portable ZIP, per-user installer, wheel, analysis/manifest/smoke receipts, and sorted
SHA-256 inventory from a hash-locked environment.

## Verification

Tests cover the pure color/HDR core, workflow state machine, confirmation and recovery,
Windows API contracts, native-resource lifecycle, least-privilege boundary, GUI
truthfulness, Qt selection, frozen module closure, redistribution notices, and release
artifact construction. Publication additionally requires frozen offscreen smoke tests,
PE manifest inspection, component/source audits, and a clean install proof.
