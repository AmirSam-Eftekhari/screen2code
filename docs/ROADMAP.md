# ROADMAP: phases, order of work, exit criteria

> **Implementation status:** this is a design document. For what is actually implemented, measured, and different, see [STATUS.md](STATUS.md) and [ADR-0002](ADR-0002-implementation.md); they take precedence where they differ.

Status: Draft. Depends on: PRD.md (release scope), ARCHITECTURE.md (packages), PIPELINE.md (stages), ADR-0001.
No calendar dates: effort is not estimated until Phase 1 velocity is measured. Order and exit criteria are what is committed.

## 1. Phase 0: research and architecture (complete)
Delivered: ADR-0001 (approved with amendments), IR_SPEC.md r2, PIPELINE, MODEL_STRATEGY, EVALUATION, GENERATION, SECURITY, BENCHMARKS, DESKTOP_UX, ARCHITECTURE, PRD, ROADMAP. A single cross-document consistency review closes the phase (its findings are applied before Phase 1 starts).

## 2. Spikes (run early, each ends in a recorded decision)

| Spike | Question | Starts | Blocks | Exit |
|---|---|---|---|---|
| S-PKG | Does a signed `--onedir` sidecar run `doctor` and smoke analyze on Windows, and what is the antivirus outcome? | Phase 1 | release 0.5 packaging only | ADR: packager configuration and signing process |
| S-OCR | PaddleOCR ONNX on Windows CPU vs Tesseract (MODEL_STRATEGY section 7) | start of Phase 2 | S2 default provider | default OCR provider chosen |
| S-LAYOUT | Reference layout evaluator for IR_SPEC 8.6 and `IR_LAYOUT_SEMANTICS.md` | Phase 1 | IR 1.0 promotion; validation that the corpus emitter's lowering matches IR semantics (LayoutMetric and `resolve()` checks do not need it) | evaluator passes golden layouts |
| S-ISO | Windows isolation boundary for Tier 1 (SECURITY section 5.3) | Phase 3, parallel | enabling React/Next execution only | ADR accepted, or Tier 1 stays unavailable |
| S-VLM / S-ACCEL | MODEL_STRATEGY section 7 | Phase 3-4 | nothing in the MVP | keep optional features off or adopt |
No spike blocks the Phase 2 vertical slice except S-OCR, whose fallback (Tesseract) is already decided.

## 3. Phase 1: core foundation
Deliver, in this order:
1. Repository scaffolding: uv workspace, MIT LICENSE, README (not yet claiming capabilities), CONTRIBUTING, CODE_OF_CONDUCT, root SECURITY.md policy, issue and PR templates, CI on Windows and Linux (lint, type check, unit, schema-drift, license audit).
2. `ir` package: JSON Schema generation and committed schema, models, canonical serialization, content hash, ID derivation, validator L0-L3 including R-EPI-1..9, migration harness, IR_SPEC example promoted to a golden fixture.
3. `core`: `Workspace` with confinement, artifact store, config layering, error model and registry, stage runner (cache keys, atomic writes, cancellation, events), provider registry, model manager (manifest, checksum, license gate), plugin loading (disabled by default).
4. `cli`: `ir validate`, `ir migrate`, `doctor` (only commands with real behavior).
5. S-PKG and S-LAYOUT spikes started.
Exit criteria: IR golden fixture validates; schema-drift check green; path-confinement and runner tests (including caching and cancellation) pass on Windows and Linux CI; `ir validate` and `doctor` usable; repository may go public only after this phase passes, because the root security policy exists.

## 4. Phase 2: first complete reconstruction pipeline (release 0.1)
Order of work (corpus and renderer first, so there is ground truth to develop against):
1. `rendering`: Tier 0 renderer, pinned Chromium revision and font set, render records, determinism test.
2. `benchmarks`: scene spec, independent corpus emitter, smoke tier, run records and pin validation, baselines (blank page, `<img>`).
3. `vision`: S0, S1, S2 (provider per S-OCR), S3.
4. `reconstruction`: S5, S6 (basic), S10.
5. `generation`: planner, HTML/CSS adapter, project builder, report, provenance manifest.
6. `evaluation`: visual metrics (Pixel, SSIM, Edge, Color, Layout, Alignment, Typography, MissingElement), IR metrics for regions, text, layout, evaluation report.
7. CLI: `models`, `analyze`, `reconstruct` (single screen), `generate` (html), `render`, `evaluate`, `benchmark`.
Exit criteria: end-to-end CLI run on Windows and Linux CI; security tests for paths, images, injection, Tier 0 settings pass; smoke benchmark reproducible under pins; first calibrated baseline recorded (this is when numeric targets are set); documentation of every CLI command and report field exists.

## 5. Phase 3: multi-screen intelligence (release 0.2)
Order: S7 reconcile (grouping, modes, viewport classes, correspondence, responsive diff) -> S8 components -> S9 tokens (including mode merge) -> S6 full -> React and Next.js adapters (generate-only) -> conformance suite -> standard benchmark tier with component, token, responsive, theme metrics -> optional S4 behind S-VLM. S-ISO runs in parallel.
Exit criteria: multi-screen scenes yield shared components and tokens; responsive and theme scenes validated against ground truth; both new adapters pass conformance; `IR_LAYOUT_SEMANTICS.md` and the reference evaluator complete (also an IR 1.0 criterion).
IR 1.0 promotion is evaluated at the end of this phase against IR_SPEC section 4.1, requiring two generators consuming the IR in CI (HTML/CSS plus React satisfies it).

## 6. Phase 4: self-refinement (release 0.3)
Order: per-node error localization -> deterministic patch rules -> loop controller (iteration, wall-clock, epsilon, best-so-far) -> iteration artifacts -> calibration reports -> secondary dataset visual runs (Design2Code, evaluation only, terms verified) -> full benchmark tier.
Exit criteria: refinement improves the metric vector on synthetic scenes with no structural edits, never exceeds limits, and every iteration is logged and reproducible in deterministic mode.

## 7. Phase 5: desktop application (release 0.5 beta)
Order: `server` RPC and protocol tests -> Tauri shell and supervisor -> Home, Settings (models, providers, privacy, policies) -> Import and Analysis -> Workspace with Inspector (observed vs inferred) -> Compare -> Export -> editing as assertions with undo -> packaged installer via the packaging abstraction (S-PKG decision) -> flow tests on the packaged app.
Exit criteria: critical flows pass on the packaged Windows app; no business logic in the UI (architecture test: the frontend has no import path to engine code); inspector shows only IR/evidence content.

## 8. Phase 6: developer ecosystem (release 0.9 RC, then 1.0)
Order: stabilize `screen2code.api`; error-code documentation generated from the registry; plugin documentation and examples; CLI Docker image (optional); SBOM and license audit in the release workflow; signed release pipeline; README hero demo and screenshots (only from real runs); contribution guides; public benchmark report.
1.0 gate: IR 1.0 criteria met; public API stable; no unlabeled experimental features; Tier 1 either enabled through an accepted isolation ADR or documented as unavailable.

## 9. Recommended implementation order (summary)
1. Scaffolding and CI -> `ir` -> `core` -> `cli` (`ir validate`, `doctor`).
2. In parallel: S-PKG, S-LAYOUT.
3. `rendering` -> benchmark smoke corpus -> `vision` -> `reconstruction` -> `generation` (HTML) -> `evaluation` -> CLI commands -> first baseline.
4. Multi-screen intelligence -> React/Next adapters -> IR 1.0 evaluation.
5. Refinement.
6. Desktop.
7. Ecosystem and release hardening.
Rationale: ground truth and a deterministic renderer exist before perception code is written; the IR and validator exist before anything produces IR; each later phase consumes stable outputs of the earlier one.

## 10. Definition of done and cadence
- Every phase exit criterion above is a checkable test or recorded decision, not a statement of effort.
- A change that touches IR schema semantics bumps `schema_version` (0.x) and updates IR_SPEC, golden fixtures, and migrations in the same change.
- ADRs are added for each spike outcome and each decision that reverses a document in `docs/`.
- Docs describe actual implementation: when code diverges from a document, the document is corrected in the same change.
