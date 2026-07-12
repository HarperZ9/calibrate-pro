# Security Policy

## Supported

Calibrate Pro follows a rolling release. Until a 2.0 line exists, only the latest release
on the default branch is supported for fixes.

## Reporting a vulnerability

Report suspected vulnerabilities privately via GitHub Security Advisories — the
"Security" tab of this repository, then "Report a vulnerability". Do NOT open a public
issue for an unfixed vulnerability. Include the affected component and version, a
reproduction, and the impact. The maintainer will acknowledge within a stated window and
agree a disclosure date.

## Trust surface (the honest part)

**Release status:** Calibrate Pro 1.1 routes confirmed display mutation through the
hardened transaction boundary described below. Repository-wide actuator-isolation,
Windows ABI, cancellation, cleanup, and boundary tests passed for the release candidate;
the residual limitations in this document remain part of the supported trust model. The
release trust surface is:

- **Confirmation-bound production adapter.** A recognized UI confirmation is consumed
  once, capabilities are revalidated against an isolated private probe, and the
  coordinator issues an opaque one-use authorization for a distinct sealed writer copy
  that the Windows adapter consumes before capture. Callback or concurrent caller
  mutation fails before authorization. A coordinator-wide apply lock serializes the
  complete capability/authorization/transaction handoff so concurrent confirmed applies
  cannot invert the one-slot gate. Every
  Windows adapter requires this gate regardless of the concrete ports implementation,
  exposes no authority-binding or minting hook, and defaults to the process-plus-global
  mutex. The raw recovery runner is private. The adapter stores a private deep seal and
  digest of the confirmed plan and captured snapshot, including hashes recomputed from
  the actual ICC/DWM payload bytes; restore accepts only the exact issued object while
  every writer uses the sealed copy. Constructed, substituted, or same-object-mutated
  evidence cannot alter a writer.

- **DDC/CI monitor control.** The confirmed workflow permits only brightness, contrast,
  RGB gain, and RGB black-level controls. It binds one stable PnP/interface identity,
  freshly enumerates physical handles for every operation, disables the legacy
  unscoped WMI brightness fallback, binds the captured interface path to the freshly
  enumerated physical handle, captures the reported maximum, and rejects identity,
  topology, maximum, or range drift before writing. Every acquired handle is registered
  for cleanup before optional capability parsing. Each cleanup pass attempts every
  eligible recorded native destroy at most once even after another destroy fails. A false
  or demonstrably pre-call-interrupted destroy remains registered for an explicit retry;
  an uncertain native-call outcome remains registered and poisoned against a possible
  double destroy. Failures are surfaced, and only successful destroys are described as
  closed.
  Recovery withholds a write if its authoritative comparison already shows a state other
  than the captured prior or this transaction's target, then reads completed writes back;
  it never claims that a reset-to-default operation restored user state. Every DXVA2 API
  used for physical-handle enumeration, VCP reads/writes, capabilities, and destruction
  has an explicit pointer-sized ctypes contract.
- **ICC profile association.** Confirmed bytes use the reserved, content-addressed,
  non-overwriting `calibrate-pro-{sha256}.icc` cache namespace. A digest-scoped
  process/global mutex and native
  no-write/no-delete-share read lease protect registration, association, persistent WCS
  default selection, and repeated stable readback. A pre-existing or newly created cache
  entry is accepted only while the same native handle proves an exact final path, disk
  file, non-reparse identity, one link, and the exact content-addressed bytes. These checks
  prove the object used and reject aliases observed at each validation point; they do not
  prove creator/ACL provenance or filesystem immutability after the lease is released.
  Later drift is rejected before reuse. Before mutation, system-wide WCS
  enumeration captures whether the target is installed and associated with that display;
  sized WCS default-profile reads capture the prior persistent default. Its exact name,
  payload, and digest are revalidated immediately before activation; concurrent default
  drift already visible at comparison aborts without selecting or restoring over that
  newer default. Registration, association, and default
  effects are journaled separately, with authoritative reconciliation after an ambiguous
  failure. Correct wide-string `CPT_ICC`/`CPST_NONE` native contracts are used. These files
  are a durable reserved cache. Legacy install/uninstall holds one delete-capable handle
  across creation, native registration/unregistration, revalidation, failure cleanup, and
  delete disposition, so a pathname replacement cannot be deleted. Those surfaces also
  reject case, trailing, resolved-path, active 8.3, symlink, and hard-link aliases of
  `calibrate-pro-{sha256}.icc`. A future collector needs a separately designed
  authoritative all-display/all-scope scan.
- **DWM LUT injection.** System-wide correction can install a 3D LUT via the Windows
  Desktop Window Manager. The default 1.1 actuator refuses this write until an
  authoritative OS-level SDR/HDR prior-state reader exists; process-local LUT memory is
  not accepted as recovery evidence. VCGT gamma-ramp reads/writes remain separately gated
  through typed GDI32 DC calls, and an uncertain `DeleteDC` result fails closed.
- **Native USB HID to the colorimeter.** The i1Display3 driver reads device EEPROM
  (per-unit calibration matrices) over USB HID. It reads from the sensor; it does not
  flash or write device firmware.
- **Startup monitoring.** A documented, user-visible Windows startup entry may launch a
  read-only startup monitor that reports topology and saved-plan state. It does not apply
  a calibration. Automatic reapply is disabled; every display change requires a fresh plan
  and explicit confirmation through the interactive workflow.

## What it does NOT protect against, and does NOT do

- **No ground truth without a colorimeter.** Sensorless mode is a model prediction, not a
  measurement. It cannot detect that a panel has drifted from its database profile. Only
  the measured (i1Display3) path compares against a real reading.
- **No network, no telemetry.** The core performs no network access and sends no data.
  Reports are written locally.
- **Trusted same-process Python.** The confirmation gate prevents accidental/direct API
  bypass, not hostile code already executing arbitrary Python in this process. Python
  reflection and memory mutation are inside the trusted process boundary; privilege
  separation would require a separately designed broker process.
- **Not a driver-integrity tool.** Calibrate Pro trusts the Windows GPU/DWM stack and the
  monitor firmware it talks to; it does not attempt to verify their integrity, and a
  compromised driver or monitor firmware is outside its model.
- **No crash-safe hardware transaction.** Confirmed display changes use in-process
  compensating recovery with authoritative readback. Process termination, power loss, or
  an operating-system crash can interrupt that recovery; receipts identify the guarantee
  as `IN_PROCESS_BEST_EFFORT` rather than promising durable rollback. Capture sealing,
  apply/verify phase publication, and the verified-to-commit handoff remain inside
  cleanup guards. While ownership remains recorded, cancellation is deferred while every
  applicable compensation domain and recorded release is attempted, then the original
  cancellation is re-raised. After commit releases ownership, state is cleared without
  unsafe unlocked compensation. Cleanup failures are surfaced and may poison the
  transaction; successful cleanup is not guaranteed. An abandoned mutex poisons its
  process-wide key, partial release poisons the adapter, and compensation is refused
  whenever ownership is uncertain.
- **Cooperating serialization, not operating-system compare-and-swap.** The named mutexes
  serialize Calibrate Pro transactions that honor them. DDC, WCS, gamma, and DWM APIs do
  not offer one atomic compare-and-write operation, so an unrelated external writer can
  still race after an authoritative comparison. The adapter detects already-observed
  third states, withholds stale compensation in that case, and reads its completed writes
  back; it does not claim atomic exclusion against other programs.

Confirmed ICC, VCGT, and DWM LUT files are read with explicit size ceilings before parser
allocation. Limits are a resource-safety contract, not evidence that a file is valid;
digest, schema, and domain validation still run independently.

## What counts as a vulnerability

- A path that lets untrusted input (a malicious panel profile, `.cube`/ICC/CCMX file, or
  DDC response) cause code execution, privilege escalation beyond the granted elevation,
  or a write outside the tool's own output locations.
- A crash or hang that leaves the display in an unusable state with no `restore` path.

## What does not count

- Sensorless prediction being less accurate than a measured result. That is documented
  behavior (sensorless is an estimate), not a vulnerability.
- A malformed input file that raises a normal, handled exception.
