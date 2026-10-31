# PRD: Screen2Code product requirements

> **Implementation status:** this is a design document. For what is actually implemented, measured, and different, see [STATUS.md](STATUS.md) and [ADR-0002](ADR-0002-implementation.md); they take precedence where they differ.

Status: Draft. Depends on: ADR-0001, IR_SPEC.md r2, ARCHITECTURE.md, ROADMAP.md. Technical details are not repeated here.

## 1. Summary
Screen2Code is an open-source UI reverse-engineering platform: "See it. Understand it. Rebuild it." From one or more screenshots it infers an explicit, editable, framework-independent description of the interface (the IR), generates a real project from it, renders the result, measures it against the reference, and reports what it knows and what it does not.

## 2. Problem
Screenshot-to-code tools mostly produce a single page of markup from a single image: no explicit structure, no shared components or design tokens across screens, no measurement of how close the result is, and often a cloud-only workflow. Developers get code that looks similar but is neither editable as a design nor trustworthy as an engineering artifact.

## 3. Users and jobs
| User | Job to be done |
|---|---|
| Front-end developer | Turn a reference (own app, mock, legacy UI with no source) into a maintainable starting project |
| Design-to-code engineer / agency | Recover a design system (tokens, components) from delivered screens and keep it consistent across pages |
| Privacy-sensitive team | Do this locally, with auditable handling of personal data in screenshots |
| Open-source contributor / researcher | Extend providers, generators, metrics; reproduce benchmark results |

## 4. Value and differentiation
1. An explicit, versioned IR where observation and inference are structurally distinct (IR_SPEC section 2): users can see why each claim exists.
2. Multi-screen design-system reconstruction: shared components, tokens (including theme modes), and responsive intent, not unrelated pages.
3. Measured self-verification: render, compare, localize error, refine within bounds, with a metric vector instead of a claim.
4. Local-first: no cloud dependency; remote providers are optional and explicit.
5. Honest about uncertainty: placeholders, uncertain text, fallbacks, and unknown asset rights are surfaced and reported.
Competitive context (scan dated 2026-10-08, ADR-0001 section 1; commercial products not re-scanned): existing open-source tools are LLM-centric single-pass generators; this product does not copy their architecture or code.

## 5. Principles
Correctness over speed; explicit architecture; determinism; measurable quality; local-first; no fabricated functionality, benchmark numbers, assets, or support claims; experimental features are labeled; generated code is untrusted (ADR amendment A3).

## 6. Scope by release

| Release | Phase | In scope | Acceptance (all must hold) |
|---|---|---|---|
| 0.1 | 2 | CLI: single screenshot, S0-S6 + S10; HTML/CSS generation; Tier 0 render; visual metrics; smoke benchmark; `models`, `doctor`, `ir validate` | pipeline runs end-to-end on Windows and Linux CI; golden tests pass; benchmark smoke run is pinned and reproducible; reports list uncertain text, placeholders, fallbacks |
| 0.2 | 3 | multi-screen input, page grouping, modes, responsive rules, components, tokens; React and Next.js generate-only | multi-screen synthetic scenes reconstruct with components and tokens; adapters pass the conformance suite; standard benchmark tier runs |
| 0.3 | 4 | bounded refinement loop; calibration reports; secondary dataset (visual only) | refinement improves the metric vector on synthetic scenes without structural edits, within iteration and time limits; every run logged |
| 0.5 (beta) | 5 | desktop: Home, Import, Analysis, Workspace, Compare, Export, Settings; editing as assertions | critical flows covered by tests on the packaged Windows app; no logic in the UI; inspector shows observed vs inferred |
| 0.9 (RC) | 6 | Python API stabilization, plugins, packaging abstraction in CI, SBOM, signed installer, docs, optional Docker for CLI | release workflow reproducible; security tests green |
| 1.0 | - | IR 1.0 promotion criteria met (IR_SPEC section 4.1); public API stable | no unlabeled experimental features; Tier 1 (React/Next execution) either passes its isolation ADR or is documented as unavailable |
A feature counts as done only when implemented, tested, documented, integrated, error-handled, measurable where appropriate, usable from its intended interface, and covered by CI where appropriate (product spec section 34).

## 7. Functional requirements (by capability)
- FR-1 Import PNG, JPEG, WebP, single or multiple; per-screen metadata (viewport width, device scale, mode, page).
- FR-2 Reconstruct IR conforming to IR_SPEC with evidence, confidence, and provenance.
- FR-3 Infer components, tokens, modes, responsive rules across screens (release 0.2).
- FR-4 Generate HTML/CSS (0.1), React and Next.js (0.2) from the IR only.
- FR-5 Render static output under the restricted renderer; compare to the reference; report metrics and exclusions.
- FR-6 Refine within hard limits (0.3).
- FR-7 Expose the same engine through CLI, Python API, and desktop.
- FR-8 Manage models locally with license and checksum metadata; no bundled weights.
- FR-9 Asset rights and navigation policies with safe defaults; always emit a provenance manifest.
- FR-10 Optional auditable redaction.
- FR-11 Edit the reconstruction as asserted structure (0.5).

## 8. Non-functional requirements
- Platform: Windows is tier-1 (signed installer, CI on Windows); Linux supported in CI; macOS not committed in the MVP.
- Privacy and security: SECURITY.md; no telemetry; local-first.
- Reproducibility: deterministic mode and pinned runs (BENCHMARKS section 5).
- Performance: measured and reported (startup, analysis, generation, rendering, memory); budgets are set after the first baseline run, not before.
- Accessibility of the desktop app: keyboard navigation and AA contrast.
- Licensing: MIT repository; permissive-only default model registry (MODEL_STRATEGY).

## 9. Success metrics
Defined as measurable quantities; numeric targets are set after the first calibrated baseline run (end of release 0.1) and until then none is claimed.
- Structure gap: structure metrics versus the `<img>` baseline on the primary corpus.
- IR accuracy: region, text, layout, component, token, responsive, theme metrics (EVALUATION section 5).
- Visual fidelity: the visual metric vector, including layout and alignment metrics, not pixel error alone.
- Honesty indicators: share of nodes with default-basis claims, absolute-fallback ratio, uncertain-text rate, calibration reliability.
- Reproducibility: share of benchmark runs that reproduce IR hashes under the same pins.
- Adoption signals (post-release): installs, issues resolved, third-party providers/adapters contributed.

## 10. Non-goals (first releases)
Video and screen-recording input; Figma/design-tool interchange; Vue and Tailwind adapters; hosted/cloud service; automatic behavior inference (handlers, data, routing, theme switching); pixel-perfect guarantees; macOS packaging; automatic execution of generated projects.

## 11. Constraints and assumptions
- Windows machine as the primary development and release platform; WebView2 required for the desktop app.
- Model licenses are checked per checkpoint; the default registry contains only permissive ones.
- Windows isolation for executing generated React/Next.js code is unresolved and cannot be promised.
- Rendering fidelity depends on fonts: references use unknown fonts, so generated renders use the pinned open font set and typographic mismatch is expected and measured.

## 12. Top risks and mitigations
| Risk | Mitigation |
|---|---|
| Layout inference from pixels is ambiguous | evidence-backed inference, flagged defaults, absolute fallback accounting, refinement within bounds, synthetic ground truth |
| Over-merging components corrupts the design system | under-merge default, `similar_to` suggestions, user merge |
| OCR quality on Windows CPU | spike S-OCR with explicit exit decision |
| Packaging and antivirus friction | replaceable packager, signing, per-release AV tracking |
| Execution isolation unsolved | Tier 0 only until the isolation ADR passes; generate-only otherwise |
| Synthetic benchmark not representative | independent corpus emitter, secondary real datasets, explicit limitation statement |
| Scope growth | phased roadmap; quality over adapter count; no empty packages |
