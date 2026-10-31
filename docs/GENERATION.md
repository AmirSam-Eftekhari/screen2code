# GENERATION: from committed IR to a project

> **Implementation status:** this is a design document. For what is actually implemented, measured, and different, see [STATUS.md](STATUS.md) and [ADR-0002](ADR-0002-implementation.md); they take precedence where they differ.

Status: Draft. Depends on: IR_SPEC.md r2 (sections 8.6, 10, 12, 13, 14, 17, 18, 21), ADR-0001 (A3), PIPELINE.md (S11-S12), SECURITY.md.

## 1. Architecture

```
Committed IR (never raw screenshots)
   -> Component Planner  -> Generation Plan (deterministic, user-editable sidecar)
   -> Framework Adapter  -> Code Generator -> virtual file tree (path -> bytes)
   -> Project Builder    -> writes under a confined output directory + report
```
- The generator accepts only `committed` IR (IR_SPEC section 17.3). It never reads source images except to copy extracted assets already stored in `assets/`.
- Generator-specific data lives in the plan (IR_SPEC section 2.5), never in the IR.
- The same IR and the same plan produce byte-identical output (determinism test, section 9).
- No language model is used in generation in the MVP. A `CodeGenerationProvider` is reserved and experimental; its output would be untrusted and re-verified by render and evaluation.

## 2. Targets and phasing

| Target | Phase | Style strategy | Notes |
|---|---|---|---|
| HTML/CSS | 2 | one stylesheet, CSS custom properties for tokens | static, renderable under Tier 0; reference target |
| React (TypeScript) | 3 | CSS Modules plus a tokens stylesheet; no CSS framework | generate-only until isolation spike passes |
| Next.js (App Router) | 3 | same as React | generate-only until isolation spike passes |
Not in scope until after 1.0 criteria: Vue, Tailwind (as a style-strategy plugin), others. Quality over adapter count.

## 3. Framework adapter interface

```
FrameworkAdapter { id, version, capabilities{ components, responsive, modes, ... },
                   default_plan_options(),
                   emit(ir, plan) -> FileTree }
```
Adapters are pure: no filesystem, network, subprocess, or clock. They are discovered through plugin entry points (ARCHITECTURE.md section 9).

## 4. Generation plan

The plan is a JSON document keyed by IR IDs and the IR `content_hash`; it is stale if the hash differs (IR_SPEC 19J).

| Field | Decision |
|---|---|
| `target`, `adapter_version` | selected adapter |
| `names` | file, component and class names derived from IR `name`s: sanitized, ASCII-folded, de-duplicated deterministically by canonical order; never from redacted text |
| `layout_files` | HTML: one file per page; React/Next: one component file per component and one per page |
| `style_strategy` | per target (section 2) |
| `breakpoint_direction` | `mobile_first` (default) or `desktop_first` |
| `theme_mechanism` | `prefers_color_scheme` (default when at least 2 modes exist) or `data_attribute`; modes never imply behavior (IR_SPEC 12.2) |
| `font_policy` | generic family to the pinned open font set (EVALUATION.md section 3) |
| `asset_policy` | `strict` / `default` / `permissive` (IR_SPEC 10.2); default `default` |
| `navigation_policy` | `asserted_only` (default) or `evidenced_and_asserted` (IR_SPEC R-NAV-2) |
| `placeholder_text` | string used for `unreadable` text; default `[unreadable text]` |
| `evaluation_instrumentation` | include node-ID attributes (section 8); default on for evaluation builds, off for exports |
| `output_dir` | confined by the Project Builder (SECURITY.md section 3) |
The Component Planner computes defaults from the IR and the user's settings, and the desktop/CLI may edit them.

## 5. Lowering rules (IR intent to output)

The IR owns layout semantics (IR_SPEC 8.6); a lowering is correct if the rendered result is consistent with them. Deviations a target cannot avoid are listed in the report.

| IR | HTML/CSS lowering (React/Next identical in CSS) |
|---|---|
| frame size | `box-sizing: border-box` globally (frame = border box) |
| `box` with `stack` | `display:flex` with `flex-direction`, `gap`, `align-items`, `justify-content`; `distribute: space-*` maps to `justify-content` |
| `box` with `flex` | flex with `flex-wrap` and per-child `flex` shorthand from grow/shrink/basis |
| `box` with `grid` | `display:grid`; `fixed` track = px, `share` = `minmax(0, <weight>fr)`, `content` = `auto`; explicit placement to `grid-column`/`grid-row` |
| `overlay` | host `position:relative`; non-base children absolutely positioned from `anchor` + `offset`; `z` to `z-index` |
| `absolute` | `position:absolute` offsets; each use is listed in the report as a fallback |
| `hug` / `fill` / `fixed` / `aspect` | `fit-content` or auto / `flex:1` or `width:100%` (by parent mode) / px / `aspect-ratio` |
| margins | explicit margins; no margin collapse is relied on because every container is a flex or grid container |
| text | escaped; `truncation` to line clamp or ellipsis; `runs` to inline spans |
| `clip` | `overflow` hidden / auto / visible |
| `fit` | `object-fit`: cover, contain, fill, none |
Roles map to semantic elements without behavior: `heading` to `h1`-`h6`, `nav` to `nav`, `list`/`listitem` to `ul`/`li` only when the children conform, `button` to `<button type="button">` with no handler, `link` to `<a>` without `href` unless the navigation policy permits, otherwise generic containers.

## 6. Tokens, modes, responsive

- Tokens become CSS custom properties (HTML, CSS Modules). Per-mode values are emitted for each registered mode using the plan's `theme_mechanism`. Tokens lacking a value in a registered mode fall back to the default mode's value and the gap is listed in the report.
- Responsive: the generator evaluates `resolve(page, class)` for every viewport class (IR_SPEC section 13) and emits the minimal differences between classes as media queries at the `selected` thresholds, in the plan's direction. Thresholds are never described as observed.
- Components: HTML repeats markup per instance (shared CSS classes by component). React/Next emit one function component per IR component with typed props from `params`; `repeat` with `count_semantics: dynamic` becomes a data array seeded with the observed values; `fixed` and `unknown` become static children.

## 7. Content policies (all enforced by the generator; all reported)

- Escaping: all text values are escaped for the target; `TextValue.status` `uncertain` is emitted verbatim and listed; `unreadable` uses `placeholder_text`; `redacted` emits the class label or an empty string with a report entry.
- Assets (IR_SPEC section 10): extracted assets are written to `assets/` as PNG; `strict` replaces unknown-rights assets with a placeholder drawn from `hint`; placeholders render as a neutral box with the hint color and aspect ratio and a `data-s2c-placeholder` marker; nothing imitates the original.
- Provenance manifest: always emitted, regardless of policy (asset ID, provenance, `rights_status`, origin source and region, `lossy`, `resolution_scale`, applied policy, warnings). No file written by Screen2Code states ownership or a license for extracted assets (IR_SPEC section 10.1).
- Navigation: functional links, routes or handlers are emitted only as allowed by R-NAV-2; every `navigates_to` relation and its status is listed in the report.
- `opaque` nodes emit their fallback asset and are listed; strict generation refuses if configured to.

## 8. Evaluation instrumentation
When `evaluation_instrumentation` is on, each emitted element corresponding to an IR node carries a node-ID attribute (`data-s2c-id`). The renderer reads these to report per-node boxes (EVALUATION.md section 3). Export builds strip the attribute unless the user keeps it.

## 9. Project builder, report, validation, tests
- The builder writes the file tree under the confined output directory (reject traversal, absolute paths, reserved Windows names, collisions; SECURITY.md section 3), then writes `s2c-report.json` and a human-readable `REPORT.md`: IR hash, plan hash, adapter version, file hashes, asset provenance table, uncertain text, placeholders, fallbacks, deviations, navigation statuses, warnings.
- Pinned dependencies for React/Next come only from an allowlisted template with a lockfile containing integrity hashes. Nothing in model output or the IR can add a dependency.
- Checks that run without executing generated code: HTML and CSS well-formedness via parsers; TypeScript source is emitted but only type-checked or built under explicit user action inside an isolation boundary (SECURITY.md section 5); in CI the boundary is an ephemeral runner, and only on Screen2Code's own golden fixtures.
- Tests: golden file-tree snapshots from golden IR fixtures; byte-determinism (same IR and plan produce identical bytes); escape tests with hostile strings (SECURITY.md section 9); adapter conformance suite shared by all adapters (every IR feature either lowers or is reported as a deviation).
