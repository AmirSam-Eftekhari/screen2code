# EVALUATION: rendering, visual evaluation, IR evaluation, refinement

> **Implementation status:** this is a design document. For what is actually implemented, measured, and different, see [STATUS.md](STATUS.md) and [ADR-0002](ADR-0002-implementation.md); they take precedence where they differ.

Status: Draft. Depends on: ADR-0001 (A1, A3), IR_SPEC.md r2 (sections 8.6, 10, 15, 16), PIPELINE.md (S13-S15), GENERATION.md, SECURITY.md.

## 1. Two kinds of evaluation

| Kind | Compares | Needs | Used for |
|---|---|---|---|
| Visual evaluation | reference screenshot vs rendered generated output | a render (S13) | product reporting, refinement loop, CI visual regression |
| IR evaluation | produced IR vs ground-truth IR | a synthetic scene with ground truth | benchmarks and perception/inference calibration (BENCHMARKS.md) |

Neither is reduced to one number. Every report is a metric vector with explicit exclusions.

## 2. Metric interface

```
Metric { name, version, kind: visual|ir, higher_is_better }
compute(inputs, context) -> MetricResult { name, version, value, unit, per_region?{}, per_node?{}, details, exclusions }
CompositeMetric { members[], weights (recorded), method }     // never the only output
```
- Metrics are registered via the plugin entry points (ARCHITECTURE.md section 9).
- A report always includes every member's value; a composite is additional, never a replacement.
- No pass/fail is emitted unless thresholds are configured (CI mode). Until the first calibrated baseline exists, no default thresholds are claimed.

## 3. Rendering (S13)

- Renderer: a pinned Chromium revision driven by Playwright, downloaded on demand into the managed directory (not bundled), checksum-verified.
- Tier 0 only (SECURITY.md section 5): static HTML/CSS output, JavaScript disabled, fresh temporary profile, all network requests aborted, file access limited to the project directory, no extensions, no downloads, sandbox left enabled.
- Viewport and scale come from the screen being compared: width = `viewport_width`, device scale factor = `scale`, full-page capture so height matches the reference; if heights differ the mismatch is recorded as the metric `size_mismatch` and the comparison pads/crops to the larger extent (policy recorded).
- Fonts: the renderer environment ships a pinned open-licensed font set (Noto Sans, Noto Serif, Noto Sans Mono, OFL) used for the generic families in the generation plan. Font files are small and bundled with the rendering package; this does not conflict with the model-weights rule. The font set hash is part of the pins.
- Theme: for screens resolved to a mode, the renderer forces that mode through the plan's theme mechanism (GENERATION.md section 6), so each reference is compared in its own mode.
- Render output: `RenderRecord { screenshot hash, viewport, scale, browser revision, font set hash, load time, per-node boxes }`.
- Per-node boxes: the evaluation build of the generated page carries node-ID attributes (GENERATION.md section 8). The renderer reads each element's border box and returns `{node_id -> box in design px}`. Export builds strip these attributes by default.
- Determinism as far as practical: animations disabled, fixed locale and timezone, no random content; two renders of the same project in the same environment must be byte-identical or the pair is flagged non-deterministic (tested in CI).
- Any generated project that needs JavaScript, a build step, or dependencies is not rendered here until an isolation mechanism passes its spike (SECURITY.md section 5).

## 4. Visual metrics (MVP set, Phase 2)

| Metric | Definition | Notes |
|---|---|---|
| `PixelMetric` | mean absolute error in sRGB over aligned images, plus the fraction of pixels whose difference exceeds a tolerance | baseline only; trivially gamed by an `<img>` of the screenshot, which is why it is never alone |
| `SSIMMetric` | structural similarity (windowed) on luminance, with per-window map | map used for error localization |
| `EdgeMetric` | F-score of edge maps (Canny) with a 2 px matching tolerance | sensitive to layout, insensitive to color |
| `ColorMetric` | mean CIEDE2000 between region-wise dominant colors, and palette distance between token sets | uses realizations to compare node-by-node |
| `LayoutMetric` | per matched node: IoU between observed region (converted to design px) and rendered box; plus position and size error in px; matched via IR realizations | requires node boxes from S13; also reports unmatched and missing nodes |
| `AlignmentMetric` | residual of IR `constraints` (align/same_size/same_spacing) measured on rendered boxes | uses IR constraints |
| `TypographyMetric` | rendered font size, line height and ink color vs `text_metrics` evidence; text agreement as character error rate between OCR(reference) and OCR(generated) using the same provider | OCR cost applies |
| `MissingElementMetric` | nodes with IoU below 0.1 or no rendered box; opaque regions listed separately | |

Phase 4+ (experimental until validated): `PerceptualMetric` (LPIPS), `ResponsiveMetric` (the same comparison at each observed viewport), `ThemeMetric` (comparison per mode).

### 4.1 Exclusions (explicit, counted)
These regions are masked from pixel-based metrics and listed in the report with counts and areas; they are never dropped silently:
- redacted regions (IR_SPEC section 16);
- placeholder-rendered image areas and `opaque` regions (reported both masked and unmasked);
- regions with `reported` readings below the unreadable threshold are not excluded from pixels but are flagged.

## 5. IR metrics (synthetic ground truth)

| Metric | Definition |
|---|---|
| Region detection | precision and recall at IoU 0.5 and 0.75 between produced and true regions |
| Text | character and word error rate of accepted `TextValue` vs truth; status calibration (share of `verified` that are correct) |
| Layout | per-container layout mode accuracy; axis, gap, align accuracy; share of nodes using `absolute` vs truth |
| Component | pairwise precision/recall/F1 of instance-to-component assignment; adjusted Rand index |
| Token | color error in CIEDE2000 between inferred and true tokens (matched by usage); spacing scale match; type style error |
| Responsive | match of viewport classes, thresholds (within the known interval), and patches |
| Theme | per-mode token value error; pairing accuracy |
| Assets | provenance classification accuracy (extracted/reconstructed/placeholder) |
| Calibration | reliability curve for `calibrated` confidences |
Definitions use the IR schema directly because the ground truth is an IR conforming to IR_SPEC.

## 6. Evaluation report

```
EvaluationReport { schema_version, kind, reference_hash, generated_hash?, ir_content_hash,
                   render: RenderRecord, metrics[ MetricResult ], per_node[], exclusions{}, pins{}, warnings[] }
```
Stored in `evaluations/<id>.json`; the desktop Compare view and the CLI `evaluate` command read this one format. Error maps (heatmaps) are artifacts referenced by hash.

## 7. Run record and measurement

Every evaluation, benchmark and CLI run writes `runs/<id>/run.json`:
```
{ run_id, command, started_at, durations{startup, analysis, generation, rendering, evaluation},
  peak_ram_mb, accelerator_mem_mb?, pins{ python, dependency_lock_hash, os, cpu_features?,
  browser_revision, font_set_hash, viewport, providers[ {id, version, config_hash, execution_provider?} ],
  models[ {id, version, sha256} ] }, seeds{}, dataset?{ version, content_hash }, redaction_profile_hash? }
```
Benchmark runs additionally require the full ADR amendment A1 pin set; a run missing any pin is invalid and is not publishable (BENCHMARKS.md section 5). Timestamps live only here, never in the IR core.

## 8. Refinement loop (S15, Phase 4)

```
generate -> render -> evaluate -> localize -> propose patch -> apply -> generate ...
```
- Operates on the IR, never on generated code. Patches are `inferred` changes with `method: refine.<rule>/<v>`, `calibration: heuristic`, and `supports` pointing to new measured `layout_residual` evidence computed between rendered boxes and observed regions.
- Allowed actions in the MVP: adjust numeric intent (gap, padding, `fixed` size, line height, font size) within a bounded range; swap `align` / `distribute`; re-select a threshold within its known interval. Structural edits (kind, hierarchy, component identity, layout mode) are NOT allowed in the loop; they are reported as suggestions.
- Localization: rank nodes by error contribution using per-node metrics and SSIM windows; act on the top K (default 5) per iteration.
- Proposal is deterministic heuristics, not a language model. The patch rules are pure functions in `evaluation`; the loop controller lives in `core` and calls the registered generate, render, and evaluate stages by name, so no package depends on another outside the ARCHITECTURE.md DAG.
- Control: maximum iterations (default 5), wall-clock budget, minimum improvement (stop if the composite improves by less than a configured epsilon), and best-so-far retention: if an iteration worsens the composite it is reverted. Deterministic mode fixes ordering and seeds.
- Logging: each iteration stores its patch, render record, report, and decision in `runs/<id>/refine/<n>/`. Asserted (user) values are never modified by the loop.
- Failure handling: a failing render or generation aborts the loop and returns the best committed IR so far; the loop can never run unbounded.
