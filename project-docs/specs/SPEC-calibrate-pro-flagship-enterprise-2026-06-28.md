# Spec: Calibrate Pro Flagship Enterprise Track

## Objective

Bring Calibrate Pro back as a full-time flagship product with public presentation on the same level as the Project Telos flagship line, while turning the codebase into an enterprise-grade display calibration platform that can later interlock with Quantac/QuantaLang for verified color kernels, typed effects, and receipt-backed AI/ML workflows.

Calibrate Pro is not a replacement for the five Telos flagships. It is a flagship product in the Quanta line: the measurement-grade display/color surface that proves the same thesis in a physical domain. Quantac/QuantaLang remains the Telos substrate for language-level reliability, security, and effect accountability.

## Product Position

Calibrate Pro should present itself as:

- A professional display calibration application for Windows-first color workflows.
- A measurement and verification surface for creators, studios, labs, fleet admins, and AI/ML visual-data teams.
- A bridge between color science, instrumented hardware, and reproducible proof.
- A Quanta/Telos-adjacent flagship whose story is physics-grade measurement: constants, calibration, repeatability, and reality checked against instruments.

Public claims must stay honest. Sensorless results are predicted. Measured results require a colorimeter. Enterprise/fleet controls are introduced only when implemented and tested.

## Requirements

- [ ] R1: Create a public flagship presentation layer for Calibrate Pro with the same seriousness as the Telos five: clear identity, product category, proof posture, screenshots or visual assets, install path, use cases, and maturity labels.
- [ ] R2: Update README/docs copy so Calibrate Pro is framed as a revived flagship product, not only a small utility or old release artifact.
- [ ] R3: Add an enterprise architecture spine for calibration evidence: deterministic calibration receipts, verification receipts, profile manifests, source/input digests, device metadata redaction, and replayable report provenance.
- [ ] R4: Add an enterprise profile store that models displays, profiles, calibration runs, verification runs, generated artifacts, active state, and policy decisions without storing secrets or personal monitor data in git.
- [ ] R5: Add policy-driven workflows: sensorless allowed/denied, measured verification required, minimum report grade, permitted output formats, and hardware side-effect acknowledgement.
- [ ] R6: Add fleet/team readiness primitives: exportable machine-readable inventory, profile bundles, audit logs, and non-hardware dry-run checks.
- [ ] R7: Strengthen Windows calibration protection as a flagship feature: CalibrationGuard status, DWM/VCGT/ICC drift detection, HDR/SDR profile switching posture, and safe testable abstractions around hardware side effects.
- [ ] R8: Upgrade customer-facing reports toward enterprise use: branded HTML/PDF-ready reports, before/after sections, verification charts, report metadata, and exact claim labels for predicted vs measured evidence.
- [ ] R9: Add a Quantac/QuantaLang bridge plan inside the product: shared color-science golden vectors, QuantaLang receipt compatibility, capability/effect taxonomy alignment, and future `.quanta` kernels for color math and report verification.
- [ ] R10: Add AI/ML workflow readiness without overclaiming: dataset/display provenance, reproducible visual-preprocessing notes, model-evaluation display profile records, and receipts suitable for human review.
- [ ] R11: Preserve the existing anti-feature boundary: do not build a grading tool, monitor review suite, or TV service-menu editor.
- [ ] R12: Keep hardware operations gated: tests must use mocks/dry-run paths unless the operator explicitly asks for live hardware access.

## Technical Approach

### Track A: Public Flagship Surface

Replace the current small `docs/index.html` landing page with a product-grade first screen and documentation set. The first viewport should immediately signal "Calibrate Pro" as the flagship object, not just a GitHub package. The page should use concrete product visuals: calibration report excerpts, CIE/gamma charts, profile artifacts, and device/workflow panels. Claims should be bounded:

- "Sensorless predicted correction" when no colorimeter is used.
- "Measured verification" only when measurement data exists.
- "Enterprise-ready track" only for implemented and tested controls.

### Track B: Enterprise Evidence Spine

Introduce a small, dependency-light evidence model:

- `CalibrationReceipt`: one calibration run, target, display metadata, generated artifact hashes, profile policy, and claim labels.
- `VerificationReceipt`: measured or predicted verification result, patch set, metrics, thresholds, report artifact hashes, and pass/warn/fail grade.
- `ProfileManifest`: active profile bundle with ICC/LUT outputs, target color space, white point, gamma/EOTF, luminance, and install state.
- `FleetInventory`: redacted display inventory, installed profile state, guard status, and drift status.

Receipts should be JSON-serializable, stable enough for tests, and designed to map later onto QuantaLang's `quantac check --receipt` and policy profile vocabulary.

### Track C: Policy And Side-Effect Control

Add a local policy model and CLI surface before any enterprise service work:

- `calibrate-pro policy scaffold`
- `calibrate-pro receipt verify`
- `calibrate-pro enterprise inventory --dry-run`
- `calibrate-pro enterprise audit`

Policies should gate workflows but not silently run hardware operations. Hardware and OS side effects stay behind explicit commands and mocks in tests.

### Track D: Quantac/QuantaLang Bridge

The bridge starts with shared evidence, not a rewrite:

- Export color-science golden vectors from Python tests into a stable JSON corpus.
- Add a QuantaLang-facing manifest describing function names, inputs, expected outputs, tolerances, and capability effects.
- Keep Quantac/QuantaLang as the future kernel verifier for pure color math and receipt/policy checks.
- Do not claim Calibrate Pro is implemented in QuantaLang until a `.quanta` kernel compiles and is verified.

Initial bridge vocabulary:

| Calibrate Pro Domain | QuantaLang Effect/Receipt Mapping |
| --- | --- |
| File profile read/write | `FileSystem` |
| Console CLI reporting | `Console` |
| Windows DWM/DDC/USB/ICC operations | `Foreign` plus domain-specific wrapper notes until modeled more precisely |
| GPU/LUT application | `Gpu` where runtime helper integration exists |
| Policy receipt verification | `quantalang-check-policy/v1`-compatible ideas, not identical schema yet |

### Track E: AI/ML Visual Reliability

Add product primitives for AI/ML teams:

- Record display profile and verification state for dataset review sessions.
- Emit "visual environment receipt" for model-evaluation screenshots or human label review.
- Provide a clear statement that calibration improves visual reproducibility but does not certify model correctness.
- Keep private datasets, images, and customer data out of public artifacts.

## Files To Modify

- `README.md` - flagship positioning, install, proof posture, enterprise track summary, Quantac/QuantaLang bridge note.
- `USAGE.md` - enterprise commands, receipts, policy workflow, dry-run examples.
- `docs/index.html` - flagship landing page.
- `docs/TECHNICAL.md` - receipt architecture, profile manifests, policy gates, QuantaLang bridge.
- `docs/INDUSTRY_FEATURES.md` - enterprise priority refresh and maturity labels.
- `docs/UI_ROADMAP.md` - align GUI roadmap with enterprise evidence, reports, profiles, guard, and fleet status.
- `calibrate_pro/enterprise/` - new package for receipt models, profile manifests, policy, inventory, and audit helpers.
- `calibrate_pro/main.py` - CLI wiring for enterprise commands.
- `tests/test_enterprise_receipts.py` - deterministic receipt tests.
- `tests/test_enterprise_policy.py` - policy and side-effect gate tests.
- `tests/test_enterprise_inventory.py` - redacted inventory/dry-run tests.
- `tests/test_quantalang_bridge.py` - golden-vector manifest and bridge metadata tests.
- `examples/enterprise/` - sample policy, receipt, profile manifest, and visual environment receipt.
- `project-docs/specs/SPEC-calibrate-pro-flagship-enterprise-2026-06-28.md` - this spec.

## Success Criteria

- [ ] S1: `docs/index.html` and README make Calibrate Pro legible as a flagship product, with no unverified enterprise claims.
- [ ] S2: A user can create or inspect at least one deterministic calibration/verification receipt without touching live hardware.
- [ ] S3: A policy can reject a workflow based on measured-vs-predicted status, grade threshold, or disallowed output format.
- [ ] S4: Enterprise inventory dry-run emits redacted display/profile state and never prints secrets, `.env` values, or customer data.
- [ ] S5: Report metadata includes receipt IDs, artifact hashes, display target, measurement mode, and claim labels.
- [ ] S6: Quantac/QuantaLang bridge artifacts exist as stable manifests/golden vectors with honest future-facing status.
- [ ] S7: Targeted tests pass for the enterprise package and existing color/HDR slices.
- [ ] S8: `git diff --check` is clean.
- [ ] S9: No live DDC/CI, DWM LUT, ICC install, USB sensor, startup persistence, network, or production deployment operation is run during routine test verification.

## Verification Plan

Default targeted test slice:

```powershell
$env:PYTHONPATH = "C:\dev\public\pubscan\quanta-color;."
python -m pytest tests/test_enterprise_receipts.py tests/test_enterprise_policy.py tests/test_enterprise_inventory.py tests/test_quantalang_bridge.py -q
python -m pytest tests/test_hdr_workflow.py tests/test_color_math.py -q
git diff --check
```

Optional wider slice after shared CLI wiring:

```powershell
$env:PYTHONPATH = "C:\dev\public\pubscan\quanta-color;."
python -m pytest tests/test_professional_features.py tests/test_verification.py tests/test_platform.py -q
```

Quantac/QuantaLang bridge verification, when a `.quanta` bridge artifact exists:

```powershell
cargo test --manifest-path C:\dev\public\pubscan\quantalang\compiler\Cargo.toml semantic_corpus_manifest --quiet
cargo test --manifest-path C:\dev\public\pubscan\quantalang\compiler\Cargo.toml semantic_corpus_receipt --quiet
```

## Implementation Slices

1. **Flagship presentation refresh**: public docs/README, no code side effects.
2. **Enterprise receipt core**: dataclasses, JSON serialization, artifact hashing, tests.
3. **Policy gates**: local policy schema, scaffold/verify helpers, tests.
4. **Profile and inventory manifests**: redacted inventory and profile bundle models, tests.
5. **CLI wiring**: dry-run enterprise commands and receipt verification.
6. **Report integration**: receipt metadata and artifact hashes in HTML/PDF-ready reports.
7. **QuantaLang bridge corpus**: golden-vector manifest and future `.quanta` kernel contract.
8. **GUI/fleet surface**: dashboard/report/profile UI work after the evidence model is stable.

## Blockers

- The user has approved Calibrate Pro migration to `C:\dev`, but this DRAFT spec still needs approval before implementation.
- Live enterprise/fleet behavior depends on hardware and Windows APIs; first implementation must use dry-run and mockable boundaries.
- QuantaLang can verify C-backed semantic corpus and effect receipts today, but Calibrate Pro is Python; the bridge must begin with manifests/golden vectors rather than claiming native QuantaLang implementation.

## Status: DRAFT
