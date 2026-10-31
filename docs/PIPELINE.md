# PIPELINE: the Screen2Code core pipeline

> **Implementation status:** this is a design document. For what is actually implemented, measured, and different, see [STATUS.md](STATUS.md) and [ADR-0002](ADR-0002-implementation.md); they take precedence where they differ.

Status: Draft. Depends on: ADR-0001 (as amended), IR_SPEC.md r2. Section numbers below refer to IR_SPEC unless stated.
Scope: stage contracts and MVP algorithms. No code.

## 1. Principles

- P-1. A stage is a deterministic function over content-addressed artifacts. The stage runner is the only writer of the working IR.
- P-2. The observed/inferred split of IR_SPEC section 2 is preserved by stage: S1-S4 emit only `regions` and `evidence` (observed). S5 onward emit structure and design-system data (inferred), each with inference records. No stage emits both kinds into one object.
- P-3. No silent fallback (ADR-0001, development rule 12). If a configured provider is unavailable the stage fails with an explicit error, unless the user configured a `fallback_chain`; the chain actually used is recorded in `producers`.
- P-4. Every provider call is cached by `(input hash, provider id+version, config hash, seed)`. Replaying cached outputs is what makes IR construction byte-deterministic (IR_SPEC D-5).
- P-5. Stages run only on validated, size-limited inputs (SECURITY.md section 4).

## 2. Stage table

Numbering follows execution order.

| Stage | Name | Emits | MVP method | Provider | Phase |
|---|---|---|---|---|---|
| S0 | import | `sources`, normalized image artifact | decode with limits, strip metadata, convert to sRGB, hash, apply `declared` metadata, optional pre-perception redaction | none | 2 |
| S1 | regions | `regions` (measured) | classical CV (section 4.2) | none | 2 |
| S2 | ocr | `regions` (reported), `text_reading` evidence | OCRProvider on tiles, deterministic line grouping | OCRProvider | 2 |
| S3 | measure | evidence (measured kinds) | classical measurement (section 4.4) | none | 2 |
| S4 | label | `element_label` evidence (reported) | optional VisionProvider; off by default | VisionProvider | 3 (optional) |
| S5 | structure | working IR page per screen: nodes, realizations | containment tree, layout inference, spacing attribution, role heuristics | none | 2 |
| S6 | assets | `assets` | extraction criteria AS-3, placeholders, `hint`, default rights | none | 2 (basic), 3 (full) |
| S7 | reconcile | screens, pages, modes, thresholds, responsive rules | section 4.7 | none | 3 |
| S8 | components | components, instances | signature clustering, IR_SPEC 19A merge rules | none | 3 |
| S9 | tokens | tokens, modes | clustering, scales, semantic roles, mode merge | none | 3 |
| S10 | commit | committed IR, `quality_report` | validate L0-L2, set `ir_state`, hash | none | 2 |
| S11 | plan | generation plan | GENERATION.md | none | 2 |
| S12 | generate | project file tree | GENERATION.md | none | 2 |
| S13 | render | screenshots, per-node boxes | RENDERING in EVALUATION.md section 3 | none | 2 |
| S14 | evaluate | evaluation report | EVALUATION.md | optional OCR | 2 |
| S15 | refine | IR patches, iteration log | EVALUATION.md section 8 | none | 4 |

Phase 2 (single screenshot) runs S0-S3, S5, S6, S10-S14. Phase 3 adds S7-S9 (and optional S4). Phase 4 adds S15. In Phase 2 S10 commits a single-screen, single-page IR with no components or tokens beyond literals; the validator permits this (partial-by-design, IR_SPEC section 17.3).

## 3. Stage contract and runner

```
Stage { name, version, requires[artifact types], config schema }
run(ctx) -> StageResult { status: done|degraded|failed, artifacts[], ir_patch, diagnostics[], timings, peak_memory }
```
- Cache key = hash(input artifact hashes, stage name+version, stage config hash, provider cache keys). A hit skips execution.
- `ir_patch` is a set of entity upserts and deletions keyed by ID. The runner applies patches in sorted-ID order and writes `ir/working.ir.json` atomically (temp file plus `os.replace`).
- Artifacts are content-addressed files under `artifacts/`; stages never write elsewhere.
- Progress events: `{stage, status: pending|running|done|degraded|failed, progress 0..1, message}`. The desktop and CLI render these; the stage names above are the user-facing labels.
- Cancellation is cooperative at tile/region granularity; partial outputs are discarded, not committed.
- Parallelism: S0-S6 run per image in a process pool. S7-S10 run project-wide, serially. Results merge in sorted-ID order (IR_SPEC D-3). Order-sensitive reductions are single-threaded.
- `degraded` means the stage completed with documented reduced capability the user explicitly selected (for example `--no-ocr`). It is recorded in `lineage` and the quality report. A stage never degrades on its own initiative.

## 4. Stage specifications (MVP)

### 4.1 S0 import
- Accepts PNG, JPEG, WebP. Rejects animated images, multi-frame files, and any other format (SVG input is not accepted in 0.x).
- Limits: file size 50 MB; maximum side 16384 px; maximum 100 megapixels; header dimensions are checked before decode.
- Strips metadata (EXIF, ICC after conversion), converts to sRGB, stores a lossless normalized PNG artifact.
- `scale` = declared device pixel ratio, else `assumed` 1 with a quality warning. Filename or manifest hints (section 8) fill `declared`.
- Redaction `pre_perception` (IR_SPEC section 16) masks regions here, before any other stage sees pixels.

### 4.2 S1 regions (classical)
1. Estimate background per area by dominant border color; segment by color distance and an edge map (Canny); extract connected components.
2. Group into candidate boxes; classify box types by measured cues only (filled, bordered, textured/high-entropy, thin-and-long for dividers).
3. Resolve containment by area and overlap ratio; discard components below a minimum size.
Output: measured `regions`. Masks and rejected candidates go to artifacts.

### 4.3 S2 ocr
- Tall images are tiled (section 5). Each tile goes to the configured OCRProvider; results are merged and deduplicated by IoU.
- Words are grouped into lines and blocks by baseline proximity and gap statistics (deterministic). Each line becomes a `reported` region plus one `text_reading` evidence record per producer.
- Multiple OCR providers are allowed; each is a separate producer and separate evidence (this is what enables `verified` text, IR_SPEC case F).

### 4.4 S3 measure
Deterministic computations, each producing evidence of the matching kind: `color_sample`, `luminance_profile`, `text_metrics` (line height, cap height, ink color, stroke ratio), `border_profile`, `shadow_fit`, `gradient_fit`, `spacing_sample`, `alignment` (1-D clustering of edges, tolerance in section 9), `containment`, `size_sample`, `stack_axis`, `grid_fit`, `layout_residual`, `repetition` (perceptual hash plus normalized child-layout signature), `contrast`, `affordance_cue`, `asset_candidate`.

### 4.5 S5 structure
- Build the containment tree from regions into nodes and choose `kind` from measured cues and text presence.
- Layout inference per container, in this order, accepting the first that explains child boxes within tolerance: `stack` (children ordered along one axis, non-overlapping), `grid` (shared column and row tracks across at least 2x2 children), `overlay` (purposeful overlap per IR_SPEC 8.3), else `absolute` with `fallback` evidence.
- Size intent by default rules (text `hug`; boxes `hug` unless they span the parent's available extent; images get `aspect`); each defaulted claim is recorded with `basis: default`.
- Spacing attribution follows IR_SPEC 9.3. Text style is estimated from `text_metrics`: size from cap height and line height, weight from stroke ratio in three classes (400/500/700), generic family from a serif heuristic; all marked `heuristic` and `guessed`.
- Roles: rule-based from measured cues (filled and centered text means `button` candidate, large type means `heading`). S4 `element_label` evidence, when present, is an additional support, never a replacement.
- Emit realizations (node to regions) with their own inference records.

### 4.6 S6 assets
Apply IR_SPEC AS-3 per image-like node. Extracted crops are stored content-addressed under `assets/`; every asset gets `hint` and default `rights_status` (IR_SPEC section 10.1). Placeholders carry no pixel imitation.

### 4.7 S7 reconcile (Phase 3)
1. Page grouping: manifest declaration beats filename convention beats clustering. Clustering only proposes; the CLI auto-accepts above the correspondence threshold (section 9) and records confidence; the desktop asks for confirmation.
2. Mode detection from `luminance_profile`; `modes` are created only on evidence or declaration.
3. Viewport classes from resolved viewport widths; thresholds follow IR_SPEC section 13 (interval, selected, basis).
4. Node correspondence across screens by ordered-tree matching (kind, role, text equality, sibling order, relative position), producing multi-screen realizations.
5. Responsive diff: differences between matched nodes become patches only within the whitelist; hierarchy differences use duplicate-with-visibility; below the threshold the screens stay separate pages with `possible_responsive_variant_of`.

### 4.8 S8 components (Phase 3)
Cluster by (structure signature with content masked, style signature quantized to token tolerance). Promote to a component only under the IR_SPEC 19A rules (structure equal, style within tolerance or at most two variant axes, role compatible, support at least 2). Differences in text and assets become `params`; everything else is split or a `similar_to` relation. Deterministic ordering by canonical signature.

### 4.9 S9 tokens (Phase 3)
- Colors: greedy medoid clustering by CIEDE2000 within the merge threshold; canonical value is the support-weighted medoid (IR_SPEC 19I).
- Lengths: 1-D clustering within max(1 px, 2%); detect a scale (base 4 or 8 test) and record it in `scales`.
- Type styles: cluster by (size, weight, line height).
- Semantic roles by heuristic (background = largest-area color, text = most frequent ink color, border = thin-component color, primary = most saturated frequent fill), each with `heuristic` confidence.
- Mode merge only per IR_SPEC section 12.2 (at least 2 nodes with a consistent mapping).
- Replace literals with token references; record supports.

### 4.10 S10 commit
Run L0-L2 validation (strict by default), compute the quality report (L3), set `ir_state: committed`, write `ir/project.ir.json` with its `content_hash`. A failing commit leaves the working IR intact and returns diagnostics.

## 5. Tiling and resource limits
- Images taller than 2048 design px are processed in bands of 2048 px with 128 px overlap for providers (S2, S4); classical stages run on the full image when memory allows, else banded with the same overlap.
- Per-process memory budget from settings (default: 60% of free RAM at start); workers are subprocesses with enforced limits (SECURITY.md section 4). Models load lazily and unload after their stage.
- CPU is the baseline; accelerated providers are optional (MODEL_STRATEGY.md).

## 6. Failure policy
| Condition | Behavior |
|---|---|
| Undecodable or over-limit image | S0 fails for that image; other images continue; project not committed until resolved |
| Provider missing or erroring | stage fails with explicit error and remediation text; no implicit fallback |
| Provider timeout | one retry with the same config; then fail |
| Validation error at S10 | commit refused; diagnostics returned; working IR kept |
| Quality warnings | commit succeeds; listed in `quality_report` |
All failures carry stable error codes (ARCHITECTURE.md section 8).

## 7. Determinism, caching, incremental re-analysis
- Classical stages are pure functions of normalized pixels and config. Provider stages are replayed from cache. With the same artifacts, config and environment pins, S0-S10 produce byte-identical IR (IR_SPEC D-1..D-6).
- `--deterministic` mode: fixed seeds, single-threaded reductions, refuses stochastic providers without a cached result, and records the pin set (Python and dependency lock hash, OS, provider and model versions, browser revision, font set hash).
- Re-analysis after an input change reruns only stages whose cache keys changed, then reconciles IDs per IR_SPEC section 5. Asserted entities are preserved.

## 8. Multi-screen input and grouping
- Directory input: `screens/` plus optional `screen2code.toml` manifest mapping files to `{page, viewport_width, device_pixel_ratio, mode, state}`.
- Filename convention (optional, lowest precedence): `<viewport-class>-<page>[.<mode>].<ext>`, for example `desktop-home.png`, `mobile-products.dark.png`. Viewport classes map to declared widths only if the manifest defines them; otherwise widths are inferred from pixel size and `assumed` scale.
- Anything declared is recorded as `asserted`/`declared`; anything guessed is `inferred` with confidence.

## 9. Initial default thresholds
All are INITIAL DEFAULTS, recorded in `inference_config.values` and calibrated on the synthetic benchmark (BENCHMARKS.md); none is a measured result.

| Key | Default |
|---|---|
| `align.tolerance_px` | 2.0 |
| `gap.uniform_tolerance` | max(1.5 px, 5%) |
| `token.color.merge_delta_e2000` | 3.0 |
| `token.length.merge` | max(1.0 px, 2%) |
| `token.mode_merge.min_nodes` | 2 |
| `component.min_support` | 2 |
| `similarity.record_above` | 0.75 |
| `screen.correspondence.min` | 0.7 |
| `text.status.uncertain_below` / `unreadable_below` | 0.8 / 0.3 |
| `layout.absolute.max_residual_px` / `max_ratio` | 2.0 / 5% |
| `asset.extract.min_size_px` | 24 x 24 |
| `tile.height_px` / `tile.overlap_px` | 2048 / 128 |
| `refine.max_iterations` | 5 |

## 10. Interfaces
- CLI: `analyze` = S0-S5 (+S6) per screen into a working IR; `reconstruct` = full S0-S10 (multi-screen from Phase 3); `generate` = S11-S12; `render` = S13; `evaluate` = S14; `refine` = S15 (Phase 4). Full CLI contract in ARCHITECTURE.md section 7.
- Python API and the desktop RPC call the same runner; progress arrives as the events above.
