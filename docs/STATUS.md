# STATUS: what is implemented, measured, and missing

Authoritative for the state of the code. Where a design document in this folder differs from the code, this file and
[ADR-0002](ADR-0002-implementation.md) are correct. Last verified: 165 automated tests pass (`python -m unittest discover -s tests -t .`), 0 skipped,
on Linux (Python 3.12, Tesseract 5.3.4, Chromium 141).

## Pipeline and features

| Area | State | Evidence |
|---|---|---|
| IR 0.1 schema, canonical serialization, content hash, IDs, migration harness | implemented | `tests/test_ir.py` (37 tests), committed schema with drift test |
| Validator L0-L3 incl. epistemic rules R-EPI-1..9 (observed vs inferred), R-MODE, R-NAV, asset/rights, partial IR | implemented | one mutation test per rule; golden fixture validates |
| Confined workspace, atomic writes, artifact store, config layering, error registry, runner, provider registry, model store | implemented | `tests/test_core.py` |
| S0 import (limits, content sniffing, metadata stripped, sRGB, alpha flattened) | implemented | adversarial import tests |
| S1 regions (flat-region, frame, gradient-image, glyph-grouping segmentation) | implemented, classical baseline | segmentation tests on a real screenshot |
| S2 OCR (Tesseract provider; malformed responses rejected; timeouts) | implemented | provider-response and timeout tests |
| S3 measurement (colour, text metrics, borders, spacing, alignment, grid/stack fits, repetition, asset candidates) | implemented | evidence is measured/reported only |
| S5/S6/S10 structure, assets, commit | implemented | determinism, layout and typography tests |
| S9 tokens (colour, spacing, radius, border width, type) and S8 components (cross-page, under-merge) | implemented, heuristic | `infer_tokens`, `infer_components`; component-internal observations kept as `<instance>/<node>` realizations |
| S11/S12 generation: HTML/CSS (components -> shared classes) | implemented | well-formedness, escaping, policy, determinism tests |
| React (TypeScript) target | experimental, generate-only | server-side rendered with react-dom in tests; hostile text verified inert; no Vite build, no lockfile |
| S13 rendering (Tier 0) | implemented | JS-off, offline, out-of-project reads blocked, byte-identical re-render (tests) |
| S14 evaluation: pixel, SSIM, edge, colour (CIEDE2000), layout, missing elements, composite; exclusions counted | implemented | artifacts: reference, generated, overlay, difference, SSIM map, JSON + Markdown reports |
| Synthetic benchmark corpus, structure metrics, runner with pin validation, determinism check | implemented (smoke tier measured) | `benchmarks/baselines/` |
| CLI, Python API, JSON-RPC sidecar (progress, cancellation, errors) | implemented | CLI and protocol tests |
| Wheel build and clean-environment install | verified | `pip wheel .`; installed CLI ran |

## Implemented after the first report

- **Refinement loop (S15) and `screen2code refine`:** deterministic, bounded, explainable rules (`evaluation/refine.py`) driven by `Project.refine`; every iteration's patches, IR, render and
  evaluation are kept under `refinements/run-NNN/`; the committed IR changes only with `--apply` (with backup). Tested on an intentionally perturbed fixture: composite 0.736 -> 0.959,
  no tracked metric degraded; deterministic; limits and cancellation tested (`tests/test_refine.py`). Measured on one fixture only.

## Not implemented (honest list)

- **Desktop application.** Blocked in the build environment (no Rust toolchain, no network, so Tauri/npm cannot be installed). The sidecar protocol the UI
  needs is implemented and tested (`screen2code serve`, docs/ARCHITECTURE.md section 6); no UI code was written because it could not be built or tested.
- **Cross-screen reconciliation (S7): work in progress, NOT verified.** `reconstruction/reconcile.py` implements explicit grouping (`--page` / manifest), tree correspondence,
  viewport classes, responsive patches, and media-query lowering, but it has no tests and currently falls back to separate pages for the responsive fixture
  (`tests/fixtures/site/home-1000.png` vs `home-480.png`) because wrapper groups differ between widths. See docs/HANDOFF.md. Mode pairing is not implemented.
- Redaction mode, navigation inference: the IR schema and validator support them; nothing produces them.
- Next.js target, learned detector / VLM labelling (S4), ONNX OCR, accelerators, model downloads, Typography/Perceptual/Responsive/Theme metrics
  (reported as unavailable, never faked), Tier 1 execution (no isolation mechanism exists; Screen2Code never runs generated code).
- Windows installer/signing: not built. Only a wheel was produced; no PyInstaller, no certificate.
- Windows, macOS: untested here.

## Known limitations that affect results

- Text geometry uses a *typographic cell model* (nominal line boxes, Liberation-Sans-like metrics). It makes tokens and components stable across content, at a
  measured cost to pixel fidelity versus raw ink boxes (smoke benchmark SSIM 0.965 -> 0.961, edge F1 0.888 -> 0.851, layout IoU 0.881 -> 0.825).
- Fonts come from the system. Generated pages reference a font stack; the renderer records which concrete font files resolved (hashes). Other typefaces will deviate.
- Invisible layout wrappers are only found by gestalt grouping; container recall over *all* ground-truth containers is 0.51 (0.93 for visible ones).
- Component clustering is strict (structure and style equal after masking content); similar-but-different elements are left separate by design.
- The benchmark is synthetic and measured on 8 scenes; confidence intervals are wide. The README demo is a page we authored.
- This environment ran Chromium without its sandbox (root in a container). The renderer refuses to do that unless explicitly allowed, and every render record says so.

## Release-candidate additions (verified unless stated)

| Area | State | Evidence |
|---|---|---|
| Multi-screen: one page at several widths unified with responsive patches; honest fallback with reasons | implemented | `tests/test_multiscreen.py` (17 tests) |
| JSON-RPC sidecar: status, reconcile, source image, confined artifact reads, refine; parameter validation; confined exports; scrubbed errors | implemented | `tests/test_server.py` |
| Desktop UI (React bundle) against the real sidecar | implemented (web bundle) | `tests/test_ui.py`; `tsc --strict` via `ui/tsconfig.offline.json` against a hand-written React type subset (real `@types/react` could not be installed offline) |
| Tauri shell | **built, never compiled** | `src-tauri/`; steps in INSTALL |
| Text redaction (`privacy.redact_text`, CLI `--redact-text`, UI Settings) | implemented, text only | `tests/test_redaction.py` (leak scan of IR, `ir/`, exports); pixels and raster assets are NOT redacted |
