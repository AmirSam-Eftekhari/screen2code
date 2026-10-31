# ADR-0002: Implementation decisions and deviations from the specifications

Status: accepted by the implementing engineer under the mission's autonomy rules. Priorities applied: security > approved ADR amendments > IR_SPEC > other specs > convenience.

| # | Decision | Why | Spec affected |
|---|---|---|---|
| 1 | One Python distribution (`screen2code`) with subpackages `ir, core, vision, reconstruction, generation, rendering, evaluation, bench, cli, server` instead of one distribution per package | offline build environment, no packaging overhead; the dependency graph is still enforced by `tests/test_generation_evaluation.py::ArchitectureTests` | ARCHITECTURE 2, 15 |
| 2 | `reconstruction` imports perception data structures from `vision` | S5 consumes `Perception`/`Node`; avoids duplicating them | ARCHITECTURE 2 (graph) |
| 3 | `api.py` and `benchmark.py` are composition-level modules at the top level; `bench/` holds only the corpus and metrics | keeps `bench` independent of the product generator | ARCHITECTURE 2, BENCHMARKS 2.4 |
| 4 | Tokens (S9) run before components (S8) | component signatures are more robust over token references | PIPELINE 2 |
| 5 | Text regions are *typographic cells* (nominal line boxes) derived deterministically from measured ink rows, estimated size, and recorded font metrics | ink boxes vary with glyph shapes, which broke stable spacing, tokens, and component identity; trade-off measured (STATUS) | IR_SPEC 8, PIPELINE 4.5 |
| 6 | `stroke_width_px` (ink mass / skeleton length) is the weight cue; threshold 0.124 em | separates regular (0.10-0.12) from bold (0.13-0.15) on the corpus; calibrated on one font family | PIPELINE 4.5 |
| 7 | Chromium launches with its sandbox by default and **fails closed** (`S2C-RENDER-002`) unless `render.allow_no_sandbox` / `--allow-no-sandbox` is set; the render record states the choice | Playwright's default silently disables the sandbox; SECURITY requires it on | SECURITY 5.1 |
| 8 | Component-internal realizations use keys `<instance id>/<definition node id>` and the validator checks them | keeps observations of repeated elements without duplicating nodes | IR_SPEC 15.6 |
| 9 | Node `children` and asset `origin` are optional in the schema (leaf nodes; placeholders) | the spec's own example needed it; found by running the real validator | IR_SPEC 7.1, 10 |
| 10 | CLI differs from ARCHITECTURE 7: `evaluate PROJECT` (not `REF GEN`), added `import`, `run`, `errors`, `serve`; no `refine` | node-level metrics need the IR; `run` is the end-to-end workflow | ARCHITECTURE 7 |
| 11 | Tests use `unittest`; the environment has no pytest | offline | ARCHITECTURE 14 |
| 12 | React target uses one global stylesheet and no lockfile; it is generate-only | shares the CSS lowering; a lockfile cannot be produced offline | GENERATION 2 |
| 13 | OCR is Tesseract through a provider interface; no model weights are bundled or downloaded; the model store exists and is tested with local files | the ONNX OCR spike could not run offline | MODEL_STRATEGY 3 |
| 14 | Fonts are system fonts; their file hashes are recorded in every render record and benchmark pin set | cannot download or bundle the pinned open font set offline | EVALUATION 3 |
| 15 | Benchmark tiers are 1 / 5 / 25 scenes per category (8 / 40 / 200 scenes), smaller than BENCHMARKS.md's initial sizes; only the smoke tier has been run | time and one CPU | BENCHMARKS 6 |
| 16 | Desktop UI, refinement loop, S7, redaction/navigation inference, Next.js: not implemented (STATUS) | desktop blocked by toolchain; remainder by time | PRD 6, ROADMAP |

Defects found and fixed by the test-first process during implementation are recorded in the git history (for example: inference mutating measured evidence,
component rules registered under instance classes, spec example failing its own schema).
