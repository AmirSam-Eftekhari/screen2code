# IR_SPEC: the Screen2Code UI Intermediate Representation

> **Implementation status:** this is a design document. For what is actually implemented, measured, and different, see [STATUS.md](STATUS.md) and [ADR-0002](ADR-0002-implementation.md); they take precedence where they differ.

Status: Draft r2 for maintainer review. `schema_version` = `0.1`. No compatibility guarantee exists before the 1.0 promotion criteria in section 4.1 are met.
Depends on: ADR-0001 (approved with amendments).
Scope: specification only. No code, no packages. All numeric thresholds are INITIAL DEFAULTS recorded in each document's `inference_config`, to be calibrated on the synthetic benchmark. Nothing here is a measured result.

Normative words: MUST, MUST NOT, SHOULD, MAY.

## 0. Decision log (maintainer-resolved)

| # | Decision | Where applied |
|---|---|---|
| 1 | `schema_version` stays `0.1`; no compatibility claims before 1.0 criteria | 4.1 |
| 2 | The IR owns framework-independent layout semantics; they are NOT defined as a CSS subset | 8 |
| 3 | Theme modes (light/dark/other) are in scope for v1, as design-system-layer token modes; no switching behavior inferred | 12.2 |
| 4 | Extracted assets keep `rights_status = unknown` plus provenance; export policy strict / default / permissive; no ownership or license claims | 10 |
| 5 | Optional, auditable redaction, recorded as provenance; must not silently alter benchmark comparability | 16 |
| 6 | `navigates_to` kept; evidenced / inferred / unknown are distinct; inference never becomes production behavior | 14.2 |
| 7 | Principle: "Pixels are observations. Structure is an inference." Enforced structurally, not by a `source` tag | 2 |

---

## 1. Design goals and non-goals

Goals
- G1. Represent the inferred UI system (structure, components, tokens, modes, responsive intent), not the pixels of one screenshot.
- G2. Framework-independent: no React, Next.js, HTML, CSS, Tailwind or Vue vocabulary in the core.
- G3. Backend-independent: nothing names a vision model, VLM, OCR engine or LLM provider. Providers appear only as opaque `producers`.
- G4. Epistemically explicit: observations and inferences are different kinds of data, stored in different places, and machine-checkable.
- G5. Deterministic: same recorded inputs produce byte-identical IR.
- G6. Versioned, validated, migratable.
- G7. Partial and uncertain IR is first-class.
- G8. Editable: stable IDs; user assertions survive re-analysis.
- G9. Multi-screen coherent: one design system and one set of pages across many screenshots.

Non-goals
- NG1. Not an HTML/DOM/CSS AST, and not round-trippable to markup.
- NG2. Not a pixel description. Source-pixel coordinates exist only as observations.
- NG3. Not a store for raw model output, masks, embeddings, OCR word boxes, or logs.
- NG4. Not an application model: no handlers, data fetching, business logic, routing, state management, or theme-switching behavior.
- NG5. Not a fidelity claim. Fidelity is measured by render-and-compare, outside the IR.
- NG6. Not a design-tool interchange format.

---

## 2. Epistemic model: pixels are observations, structure is an inference

### 2.1 Epistemic classes

Every datum in the IR belongs to exactly one class.

| Class | Meaning | Examples |
|---|---|---|
| `measured` | A deterministic function of source pixels and stated parameters; reproducible by a classical algorithm | region rectangle, color cluster, alignment residual, spacing sample, similarity score |
| `reported` | What a producer (model, recognizer, detector) said it saw. An observation about the producer's output, not about the UI | OCR string, detector label, VLM description, raw producer score |
| `asserted` | A statement by a user or import metadata | declared viewport width, device pixel ratio, user-pinned component, user-declared rights |
| `inferred` | An interpretation derived from evidence by rules or models, carrying confidence | layout mode, size intent, token value, component identity, navigation relation |
| `record` | Bookkeeping: IDs, producers, provenance enums, config, lineage, and values recomputable from other fields | `provenance`, `producers`, `content_hash`, `status` |

"Observed" means `measured` or `reported`. Pixels are observed. Structure is inferred or asserted. These never share an object.

### 2.2 How the distinction is structural and machine-validatable

1. Disjoint sections. Observed data lives only in `sources`, `regions` and `evidence`. Inferred data lives only in `screens`, `pages`, `nodes`, `realizations`, `components`, `tokens`, `modes`, `assets` (classification), `relations`, `disputes`. A closed schema (`additionalProperties: false`) gives each section its own vocabulary.
2. Disjoint vocabularies. Observed sections MUST NOT contain structural terms (kind, role, layout, component, token or node references). Inferred sections MUST NOT contain pixel measurements or `Region` records.
3. The only bridge is explicit. A node connects to pixels through `realizations` (inferred, with its own inference record). A claim connects to evidence through its inference record's `supports`.
4. Every inferred facet carries an inference record with a calibration class and a basis (section 15.4). No bare inferred values.
5. Machine rules R-EPI-1 to R-EPI-9 (section 17.2) are enforced by the validator.

### 2.3 Field classification by area

| Area | Observed (in `regions` / `evidence`) | Inferred (in structure / design system) | Bridge |
|---|---|---|---|
| Geometry | region rectangle in source pixels; measured sizes and gaps (`size_sample`, `spacing_sample`) | `size` (hug / fill / fixed / ratio), `placement`, `constraints` | `realizations`, `inference.supports` |
| Typography | `text_reading` (reported string, raw producer score); `text_metrics` (line height, cap height, ink color) | `text.content` (accepted value + status), `text.style`, heading level, truncation | content and style facets |
| Colors | `color_sample` clusters (measured hex, pixel count, spread); `contrast` | `Fill`, border color, token references, token values | style facet, `tokens[*].inference` |
| Layout | `alignment`, `stack_axis`, `grid_fit`, `layout_residual` | `layout.mode`, axis, gap, padding attribution, overlay reason, absolute fallback | layout facet |
| Components | `repetition` similarity (measured) | component definitions, instances, params, variants, identity | `components[*].inference` |
| Tokens | `color_sample`, `spacing_sample`, `text_metrics`, `border_profile` samples | canonical values, names, semantic roles, scales, per-mode values | `tokens[*].inference` |
| Responsive | declared viewport widths (asserted); per-screen measured boxes | viewport classes, selected thresholds, patches, base class | `pages[*].responsive[*].inference` |
| Navigation | `navigation_cue`, `affordance_cue` | `navigates_to` relation and its status, `affordance` | `relations[*].inference` |
| Assets | `asset_candidate` (measured occlusion, overlaid text, resolution, dominant color) | asset kind classification; extraction decision | `assets[*].inference` |
| Relationships | `repetition` score (measured) | `similar_to`, `shares_layout`, `possible_responsive_variant_of`, disputes | `relations[*].inference` |

Record-class data (not observed, not inferred): IDs, `producers`, `inference_config`, `provenance`, `origin`, `rights_status` default, `redactions`, `lineage`, node `status`, derived `hint` values.

### 2.4 Layers and the boundary of the core IR

| Layer | Contents | Sections |
|---|---|---|
| 1. Visual evidence | Normalized, producer-agnostic observations | `sources`, `regions`, `evidence` |
| 2. Inferred structure | Nodes, layout intent, content | `pages`, `nodes`, `realizations` |
| 3. Design-system knowledge | Tokens, modes, components, relations, responsive rules | `tokens`, `modes`, `components`, `relations`, `pages[*].responsive` |
| 4. Implementation output | How a target realizes the UI | NOT in the IR |

Rules
- R-LAYER-1. A `Region` (source-pixel rectangle) MAY appear only in `regions`. Everything else references a region by ID.
- R-LAYER-2. Inferred objects reference evidence by ID; evidence never references inferred objects.
- R-LAYER-3. The core names no provider, model, engine or framework. `producers[*].id` is an opaque string.

### 2.5 What lives OUTSIDE the core IR

| Category | Examples | Stored as |
|---|---|---|
| Model/provider-specific | prompts, raw completions, logits, embeddings, provider configs | Perception artifact store; core may reference one by hash via `producers[*].artifact_ref` |
| Intermediate perception data | masks, pre-NMS detections, OCR word/char boxes, edge maps, rejected candidates | Perception artifact store |
| Debugging-only | timings, logs, overlays, diff images, draft IRs, cache keys | Debug store; never read by generators |
| Renderer-specific | browser version, font-fallback results, computed styles or DOM of generated apps, rendered screenshots | Render records |
| Generator-specific | file/module names, class names, CSS strategy, import paths, `use client`, hooks, state, routes, TypeScript types, theme-selection mechanism | Generation plan / overlay keyed by IR IDs and `content_hash` |
| Export and policy settings | asset-rights export policy, navigation emission policy, placeholder-text policy | Project settings / generation plan |

Admission test for any new core field. It must pass all four:
1. It describes the UI, or the evidence for it, not how to implement it.
2. It is meaningful to at least two different generators (or is evidence).
3. It can be stated without naming a provider, engine or framework.
4. Its epistemic class is defined and its validation rule is stated.

---

## 3. Document model, serialization, determinism

### 3.1 Top-level object
```
{
  schema_version, ir_state ("working"|"committed"),
  extensions_used[], extensions_required[],
  meta{...},                                  // record; NOT part of content_hash
  project{...}, inference_config{...}, producers{...},
  // observed
  sources{id}, regions{id}, evidence{id},
  // inferred structure and design system
  screens{id}, modes{id}, pages{id}, nodes{id}, realizations{screen->...},
  components{id}, tokens{...}, assets{id}, relations[], disputes[],
  // record
  redactions{id}, lineage{...}
}
```

### 3.2 Serialization
- Normative format: JSON, UTF-8, canonicalized per RFC 8785 (JCS).
- The committed JSON Schema (draft 2020-12), one per `schema_version`, is the contract. Any Python model classes are implementation detail and MUST be tested for drift against it.
- Entities are maps keyed by ID, never arrays, so references are direct and diffs are stable.
- On-disk bundle: `ir/project.ir.json` (core; `ir/working.ir.json` while in progress), `assets/` (content-addressed bytes), `artifacts/` (outside-IR data), and a hash manifest. The core is one file; splitting is revisited only if real documents exceed about 50 MB.

### 3.3 Canonical numbers and ordering
- Lengths are in design px: an abstract, device-independent length unit. Source pixels are converted using the resolved screen `scale`. Generators map design px to their own units. Lengths are rounded to 2 decimals; ratios and angles to 3; confidence to 3. Integral values serialize as integers. NaN and Infinity are invalid.
- Colors: sRGB, uppercase `#RRGGBB`, alpha 0..1.
- Ordered arrays (order is semantic): `children`, `runs`, `shadows`, `tracks`, `stops`, `viewport_classes`, `responsive`, `patch`, `alternatives` (confidence descending, then canonical value).
- All other arrays are SETS, sorted by canonical key: `supports`, `against`, `regions`, `relations`, `when`.

### 3.4 Determinism
- D-1. `content_hash` = SHA-256 of the JCS form of the document without `meta`.
- D-2. IDs are derived deterministically (section 5). No random UUIDs. No timestamps outside `meta`.
- D-3. Parallel results merge in sorted-ID order. No dependence on map or set iteration order.
- D-4. Floating-point results are rounded to canonical precision before serialization; reductions use a fixed order.
- D-5. Honest scope: ML inference is not bit-reproducible across hardware or library versions. The guarantee is (a) identical recorded perception artifacts plus `inference_config` give byte-identical IR; (b) end-to-end determinism holds only in a pinned environment (recorded per ADR amendment A1). Documents MUST NOT claim more.
- D-6. Every threshold that influenced a decision is recorded in `inference_config.values`; `config_hash` covers it, including the redaction profile hash when redaction is on.

---

## 4. Versioning, migration, compatibility, extensions

### 4.1 Version scheme
`schema_version` = `MAJOR.MINOR`. The spec ships as `0.1`. `0.x` carries NO compatibility guarantee. Promotion to `1.0` requires all of: Phase 3 complete (multi-screen inference exercised); at least two generators consuming the IR in CI; validator and migration harness implemented; golden-fixture suite passing; layout-semantics reference evaluator implemented (section 8.7).

### 4.2 Compatibility guarantees (from 1.0 only)
Within one MAJOR:
- No field removed or renamed; no change to the meaning of an existing field.
- MINOR may add optional fields, `role` values, `evidence.kind` values, token categories, theme `mode.kind` values.
- MAJOR is required to add or change: layout `mode` values, node `kind` values, patch ops, epistemic class assignments, anything changing generator-visible semantics.
- Unknown vocabulary fallbacks: unknown `role` becomes `none`; unknown `evidence.kind` is ignored; unknown token category is ignored; unknown `mode.kind` becomes `other`. Unknown node `kind` or layout `mode` is an error.
- Reading a newer MINOR: unknown optional fields are preserved on round-trip and do not affect validation of known fields.
- Deprecation lasts at least one MINOR before removal in the next MAJOR.

### 4.3 Migration
- Pure, deterministic, forward-only functions `vN -> vN+1`, registered in order. No downgrade.
- Each ships golden before/after fixtures and an idempotence test.
- Nothing is silently dropped. Unmappable data goes to `extensions["s2c.migration.unmapped"]` and is reported. Migrations MUST NOT change the epistemic class of any datum; a datum that cannot be migrated without changing its class is rejected.
- `lineage.migrated_from` records the version chain.

### 4.4 Extensions
- Any object may carry `extensions: { "<namespace>.<name>": {...} }`. `s2c.*` is reserved; third parties use `x.<org>.<name>`.
- `extensions_used` lists namespaces present; `extensions_required` lists those a reader must understand (unknown required means refuse). Unknown optional extensions are preserved and ignored.
- Core semantics MUST NOT depend on an extension unless listed as required. Extensions MUST NOT alter validation of core fields, and an extension MUST declare the epistemic class of what it carries.
- Generator-specific data MUST NOT go in extensions; it goes in the generation overlay.

---

## 5. Identifiers

- Format: `<prefix>_<lowercase base32>`, at least 10 characters after the prefix. Prefixes: `prj src reg scr mode pg nd cmp tok ast evd rel dsp rdc rs vc bp prd`.
- IDs are opaque; consumers MUST NOT parse them or infer order from them.
- Derivation: first 80 bits of SHA-256 over a canonical tuple (stage name, parent ID, entity kind, evidence-cluster key); extend by 20 bits on collision.
- An ID, once committed, is never recomputed or reused. Deletions leave tombstones in `lineage.tombstones`.
- Re-analysis reconciliation matches new results to existing entities by structural signature plus evidence overlap, deterministically. Matched entities keep their ID. Unmatched old entities are tombstoned unless asserted (user-edited), in which case they are retained and flagged `stale`.
- Observed records (`regions`, `evidence`) are immutable. Re-analysis creates new records with content-derived IDs; it never edits them.
- User-created entities take IDs from the monotonic `lineage.counter`.

---

## 6. Project, source, screen, page

| Entity | Meaning | Epistemic class |
|---|---|---|
| Source | One imported image: hash, pixel size, optional declared capture metadata | measured + asserted |
| Region | A rectangle in a source, produced by a measurement or a detector | measured or reported |
| Screen | One view of a page: a source resolved to a page, viewport class, mode, and state | inferred (with asserted inputs) |
| Page | A logical UI destination reconstructed from one or more screens; not a route | inferred |

```
Source { id, media_type, sha256 (of the analyzed bytes), pixel_size{w,h} [measured],
         declared?{ device_pixel_ratio?, viewport_width?, mode?, state?, page_hint? } [asserted],
         redaction?{ applied, redaction_ids[] } [record] }
Region { id, source, rect{x,y,w,h} (integers, source pixels), basis: measured|reported,
         producer, redacted?: rdc id }
Screen { id, source,
         resolved{ page, viewport_width, scale, viewport_class, mode, state? },
         origin{ <each resolved field>: declared|inferred|assumed },
         inference }
Page   { id, name, name_source, root, viewport_classes[], breakpoints{}, base_class, base_basis,
         responsive[], states[], constraints[], completeness{ state: complete|partial } }
Project{ id, name, name_source, default_mode?, redaction{...} }
```
- `Screen.resolved` holds interpretation. Where a field was supplied in `Source.declared`, `origin` is `declared`; otherwise `inferred`, or `assumed` when a documented default was used (for example scale 1). `assumed` lowers confidence and is reported.
- Screen-to-page assignment below the correspondence threshold (initial default 0.7) leaves screens on separate pages linked by `possible_responsive_variant_of`.
- Normalization to design px uses `scale`. Normalized pixel arrays are not part of the IR.
- `coverage` (fraction of source area attributed to non-`opaque` nodes) is derived, never stored as an input to generation.

---

## 7. Node model

All nodes live in one flat `nodes` map. Each belongs to one scope: a page or a component definition.

### 7.1 Fields
```
Node {
  id, kind, role?, name?, name_source?, scope,
  children[]?                                  // ordered; authoritative; absent means no children
  layout?, size?, spacing?, placement?, repeat?
  style?{ fill, border, radius, shadows[], opacity, clip }
  text? | media? | instance? | opaque?         // by kind
  affordance?, presence?
  status: resolved|partial|opaque              // record; derived, recomputed by the validator
  inference{ structure?, role?, layout?, style?, content? }   // per-facet records
  extensions?
}
```
Facet map (which fields each facet covers):

| Facet | Fields |
|---|---|
| structure | `kind`, `children`, `scope`, `presence` |
| role | `role`, `affordance` |
| layout | `layout`, `size`, `spacing`, `placement`, `repeat` |
| style | `style`, `text.style`, `media.fit` |
| content | `text.content`, `media.asset`, `instance.params` |

R-EPI-3 requires a record for every facet that has populated fields.

### 7.2 Kinds (closed in 0.x)
`box`, `text`, `image`, `icon`, `shape`, `instance`, `slot`, `opaque`.
- `opaque`: a region that was not decomposed; carries a fallback asset (section 17.3).
- `slot`: in a component definition, an insertion point for caller content.

### 7.3 Roles (closed in 0.x; semantic hint, not a markup tag)
`none page header footer nav main aside section card list listitem table row cell form button link input checkbox radio switch select tab tablist heading paragraph label badge avatar logo separator dialog tooltip menu menuitem toolbar`.
The vocabulary borrows from common accessibility semantics but is the IR's own. Role is a separate inferred claim from kind. Heading level is `text.heading_level` (1-6).

### 7.4 Tree rules
- `children` is authoritative and in logical reading order; leaf nodes MAY omit it. `parent` is derived, not serialized. The validator checks single parent and acyclicity.
- Child order is not z-order.
- A node's scope is fixed; component-definition nodes appear in pages only through `instance`.
- `name` is a human-readable label; never a code identifier or file name.

### 7.5 Presence, affordance, repeat
- `presence`: optional list of page `state` IDs in which the node exists.
- `affordance { kind: clickable|editable|toggle|scrollable|none, purpose: navigation_like|action_like|unknown }`: what the node looks like it affords, from `affordance_cue` evidence. `purpose` is visual resemblance only. No behavior is inferred.
- `repeat { component, count, count_semantics: fixed|dynamic|unknown }` marks a container's children as one repeated collection.

---

## 8. Layout intent, geometry, constraints, and layout semantics

### 8.1 Modes
`layout.mode` is one of `none` (leaf), `stack`, `flex`, `grid`, `overlay`, `absolute`.

```
stack:   { axis: horizontal|vertical, gap: Dim, align: start|center|end|stretch|baseline,
           distribute: start|center|end|space-between|space-around|space-evenly }
flex:    stack fields + { wrap: bool, row_gap?: Dim }; children carry placement.flex{ grow, shrink, basis }
grid:    { columns: Track[], rows?: Track[], gap:{row,col}, flow: row|column,
           align_items?, justify_items? }; children may carry placement.grid{ col:[start,span], row:[start,span] }
overlay: { reason: badge|popover|modal|scrim|caption|decoration|sticky|floating_action|other }
           children carry placement.overlay{ base?: bool, anchor, offset{x,y}, z }
absolute:{ fallback:{ reason, supports[] } }; children carry placement.absolute{ left?, top?, right?, bottom? }
Track:   { kind: fixed|share|content, px?, weight?, min?: Dim, max?: Dim }
Dim:     { "px": number } | { "token": id }
```
- CANONICALIZATION: a `flex` with `wrap=false` and every child `grow=0, shrink=0` MUST be serialized as `stack`. A one-track `grid` with uniform placement SHOULD be normalized to `stack`.
- A child's `placement` kind MUST match its parent's mode. A child without `placement` in a `grid` is auto-placed.

### 8.2 `absolute` is a flagged fallback
- Emitted only when no other mode explains child positions within `layout.absolute.max_residual_px` (initial default 2.0).
- MUST carry `fallback.reason` (`unexplained_residual | irregular_scatter | insufficient_evidence`) and `fallback.supports` pointing to `layout_residual` evidence. The measured residual lives in that evidence, not in the node.
- Offsets are container-relative design px for the base viewport class, never source pixels.
- `quality.absolute_ratio` (derived) is reported; strict mode fails above a configurable ratio (initial default 5% of nodes).

### 8.3 Overlay versus accidental absolute (case D)
`overlay` is chosen over `absolute` when overlap is purposeful, meaning (1) the child extends over the host's available region and an anchor relation fits within tolerance (initial default 2.0 design px), or (2) evidence or role indicates layered intent. An overlay MUST declare `reason`.

### 8.4 Size
```
size { w: Size1D, h: Size1D, aspect?: number }
Size1D { kind: hug|fill|fixed|ratio, px?, portion?, min?: Dim, max?: Dim }
```
- `size` is an inferred intent. Measured extents live in evidence (`size_sample`) and regions, never in `size`.
- `fixed` is allowed only when the layout facet's `supports` includes evidence of fixed extent (consistent extent across instances, intrinsic media size, icons); otherwise the validator warns.
- Numbers in structure are design-intent values, possibly quantized from measurements. They MUST NOT be used as measurements.

### 8.5 Cross-node constraints
Page-scoped `constraints[]`: `{ id, kind: align|same_size|same_spacing|aspect, nodes[], axis?, edge?, tolerance_px, inference }`. Generators MAY ignore them.

### 8.6 Normative layout semantics (owned by this spec)

These definitions are normative and independent of any target technology. Generators lower this intent; a lowering is correct when the result is consistent with these semantics within tolerance. Where a target cannot express a semantic exactly, the generator MUST report the deviation.

Definitions
- Frame: a node's border box (content box plus padding plus border). `size` describes the frame. Margins lie outside the frame and never collapse.
- Available region: a container's frame minus its padding and border.
- Intrinsic extent: the extent a node needs for its content. For text: its single-line width capped by the available width, with wrapping beyond. Intrinsic text extents depend on fonts and shaping and are resolved by the evaluating environment; the IR does not fix glyph metrics.
- Size kinds: `hug` = intrinsic extent clamped by min/max; `fill` = the share of available extent assigned by the parent's layout, clamped; `fixed` = `px`, clamped; `ratio` = the other axis times `aspect`.
- Resolution order: `fixed`, then bottom-up `hug`, then top-down `fill`, then positions.

`stack` (main axis A, cross axis C)
1. Non-`fill` children take their own extents along A.
2. Let R = available extent along A minus the sum of non-fill extents, margins, and `gap` times (n-1).
3. If any child is `fill` on A, R is divided among them in proportion to `portion` (default 1), clamped by min/max; a clamped child is frozen and R is re-divided until stable. If there is no `fill` child, positive R is placed by `distribute`: `start|center|end` offset the group; `space-between|space-around|space-evenly` add space between children on top of `gap`.
4. Negative R is overflow. A `stack` never shrinks children.
5. On C: `stretch` (or a `fill` child) takes the full available cross extent less margins; `start|center|end` offset within it; `baseline` aligns first-line baselines of text-bearing children, and children without a baseline align to `start`.

`flex`: as `stack`, plus
- On the main axis `fill` is not allowed (error); elasticity is expressed through `grow`, `shrink`, `basis` (default `hug`).
- With `wrap=true`, children are broken into lines in order; a child starts a new line when adding it plus `gap` would exceed the available main extent. Lines stack along C separated by `row_gap`.
- Per line, positive free space is divided by `grow` weights; negative free space is removed in proportion to `shrink` times `basis`, never below min (or 0). Clamped children freeze and the remainder is re-divided until stable.

`grid`
- Tracks: `fixed` = `px`; `content` = the largest intrinsic contribution of single-span items; `share` tracks divide the remaining extent in proportion to `weight` after fixed and content tracks, clamped by min/max with the same freeze rule.
- Items occupy `col:[start,span]` and `row:[start,span]` (1-indexed). Overlapping explicit placements are an error. Items without placement are auto-placed in `flow` order into the first free cell. Rows beyond the declared ones are implicit `content` tracks.
- Within a cell, a `fill` child takes the cell extent less margins; others take their own size and align by `align_items` / `justify_items` (default: `stretch` for `fill` children, `start` otherwise).

`overlay`
- All children share the host's available region. Base children (`placement.overlay.base = true`; default: the first child) are laid out stretched in that region and are the only children that contribute to the host's `hug` extent.
- Other children are positioned by `anchor` `{ ref: host|<node id>, h: start|center|end, v: start|center|end, inside: bool }` plus `offset`. Paint order is `z` ascending, then child order.

`absolute`: a child frame is positioned from the available region's edges by `left/top/right/bottom`; setting both `left` and `right` (or `top` and `bottom`) defines the extent; it never contributes to the host's `hug` extent.

Other rules
- Overflow is permitted; `style.clip` decides whether overflow is cut (`clipped`), reachable by scrolling (`scroll_hint`), or visible (`none`).
- Paint order among siblings follows child order unless `overlay.z` applies.
- Resolved values are real numbers. Rounding to device pixels is the renderer's concern. The reference evaluation rounds half-to-even to 2 decimals once, at the end.

### 8.7 Obligation
A reference layout evaluator and an exhaustive algorithmic companion, `IR_LAYOUT_SEMANTICS.md`, are Phase 1 deliverables and gates for 1.0. Where this section is ambiguous, that is an IR defect to fix in a revision; it is never "implementation-defined".

---

## 9. Visual style (all inferred; evidence is in `evidence`)

### 9.1 Typography
```
text {
  content: TextValue | { "param": name },
  runs?: [ { range:[start,end], style_overrides, link?: bool } ],
  style: { token, overrides? } | inline,
  heading_level?, lang?, dir?,
  truncation?: { mode: wrap|ellipsis, max_lines? }
}
TextValue { value: string|null,
            status: verified|inferred|uncertain|unreadable|redacted,
            alternatives?: [ { value, confidence, supports[] } ],        // at most 3
            replacement?: { kind: "class_label", label },               // redacted only
            redaction?: rdc id }
TypeStyle { family{ generic: sans|serif|mono|display|unknown, candidates[], status: guessed|matched },
            size: Dim, weight: 100..900 step 100, italic, line_height{ ratio|px },
            letter_spacing{ size_ratio }, align, transform, decoration, color: ColorRef }
```
- The reading an engine produced is `reported` evidence (`text_reading`). `TextValue.value` is the inferred accepted value; they may differ.
- Font family is a request, never an identification claim. `generic` is the dependable part.
- Observed line counts and glyph metrics are evidence (`text_metrics`); `truncation` is inferred intent.
- `value` is opaque Unicode text, never markup (section 18).

### 9.2 Color
```
ColorValue { space: "srgb", hex: "#RRGGBB", alpha: 0..1 }
ColorRef   { "token": id } | { "literal": ColorValue }
Fill       { kind: none } | { kind: solid, color }
         | { kind: gradient, type: linear|radial, angle?, stops[{pos,color}], estimated: true }
         | { kind: image, asset, fit: cover|contain|stretch|none, position }
```
- `fit` semantics: `cover` scales to fill the frame and crops; `contain` scales to fit inside; `stretch` ignores aspect; `none` keeps intrinsic size.
- A `literal` is allowed only when no token covers it. A node style value that differs between modes MUST be a token (R-MODE-4).
- Fit error for gradients and shadows is recorded as `gradient_fit` / `shadow_fit` evidence in the style facet's `supports`, not inline.

### 9.3 Spacing
`padding`, `margin` as `Insets` (`{all: Dim}` or per-side), plus `gap`. Canonical attribution: (1) uniform inter-child spacing becomes `gap`; (2) space between a container's edge and its children becomes `padding`; (3) per-child deviation from (1) becomes that child's `margin`. A screenshot gap is ambiguous between these; this rule makes the choice deterministic, not necessarily "true".

### 9.4 Border, radius, shadow, opacity, clip
```
border  { sides: { top?, right?, bottom?, left? } | { all }   // each { width: Dim, style: solid|dashed|dotted, color: ColorRef }
radius  { all: Dim } | { tl, tr, br, bl }, pill?: bool
shadows [ { x, y, blur, spread, color, inset, estimated: true } ]
opacity 0..1;  clip: none|clipped|scroll_hint
```
Shadows and gradients are always `estimated`: fits to pixels, not recovered source values.

---

## 10. Assets, provenance, rights

```
Asset {
  id,
  kind: raster|vector|icon|logo|background|illustration,        // inferred
  provenance: extracted|reconstructed|placeholder,              // record
  content?{ ref: "blob:sha256:...", media_type, intrinsic{w,h} },  // record; absent for placeholder
  origin?{ region?, method?{name,version}, fidelity?, resolution_scale?, lossy? },  // record; required for extracted and reconstructed, absent for placeholder
  placeholder?{ reason, kind },                                 // record
  hint{ aspect, dominant_color, supports[] },                   // derived from evidence; required for all provenances
  rights_status: unknown|user_declared|not_applicable,          // record or asserted
  rights?{ holder?, license?, declared_by: "user", supports[] },  // only when user_declared
  mode_variants?{ mode_id -> asset id },
  inference                                                     // covers `kind`
}
```

| Provenance | Definition | Required fields |
|---|---|---|
| `extracted` | Bytes derive directly from observed pixels (crop) or recovered original bytes | `origin{ region, fidelity: pixel_crop\|original_bytes, resolution_scale, lossy }` |
| `reconstructed` | Bytes produced by a deterministic algorithm from pixel evidence (trace, gradient fit, flat fill) | `origin{ method, region }` |
| `placeholder` | No faithful content exists; the generator draws a neutral stand-in | `placeholder{ reason: occluded\|too_small\|not_separable\|unrecoverable, kind: flat\|blurred_palette }` |

Rules
- AS-1. A placeholder MUST NOT carry bytes imitating the original. `hint` describes shape and color only.
- AS-2. AI-synthesized pixel content is out of scope in 0.x. A plugin producing it MUST classify it `placeholder` with `placeholder.kind: synthesized`, never `reconstructed`.
- AS-3. Extraction criteria: unoccluded, no inseparable overlaid text, at least 24x24 design px (initial default); otherwise placeholder.
- AS-4. An extracted crop is `lossy: true` and keeps `resolution_scale`.
- AS-5. Provenance is a record fact and MUST NOT be inferred by consumers from other fields.
- AS-6. `hint` is mandatory for every asset so any asset can degrade to a placeholder.

### 10.1 Rights
- Default `rights_status`: `unknown` for `extracted` and `reconstructed` (a trace is a derivative of observed content); `not_applicable` for `placeholder`.
- `user_declared` requires a `user_assertion` evidence reference and `declared_by: "user"`. `holder` and `license` are the user's words and are echoed as "declared by user".
- The IR never asserts ownership or a license, and Screen2Code MUST NOT write ownership or license statements about extracted assets in any output.

### 10.2 Export policy contract
The policy is an export setting outside the core IR (section 2.5); default is `default`.

| Policy | Assets with `rights_status = unknown` | Warnings |
|---|---|---|
| `strict` | Excluded; replaced by a placeholder rendered from `hint` | Listed in the report |
| `default` | Included | Warning in the report and provenance manifest |
| `permissive` | Included | Recorded in the provenance manifest only |

- Every generator MUST emit a provenance manifest for all non-placeholder assets regardless of policy. Format is generator-defined; content is not: asset ID, provenance, `rights_status`, origin source and region, `lossy`, `resolution_scale`, applied policy, warnings.
- The IR carries enough to implement all three policies: `rights_status`, `provenance`, `origin`, and `hint`.

---

## 11. Components, params, variants

```
Component { id, name, name_source, category: ui|layout,
            root (node id, scope = this component),
            params{ name -> { type: text|bool|enum|number|asset|slot, required, default?, bind{ node, field } } },
            slots{ name -> { accepts: any|text|media, optional } },
            variants{ axes[ { id, kind: style|visual_state, values[] } ],
                      patches{ "<axis>=<value>" -> [ { op, target, path, value } ] } },
            inference }
Instance (node kind=instance) { component, variant{ axis -> value },
            params{ name -> value }, slot_content{ slot -> [node ids] },
            overrides[ { target, path, value, reason } ] }
```
- `params` replaces any framework-specific term for component inputs. Definitions are acyclic.
- Text param values use `TextValue`, so uncertainty travels with content.
- Variant axes are created only from observed evidence. A `visual_state` axis (selected, active, disabled, error, checked, expanded) requires a screenshot actually showing that state. Hover, focus and pressed are NOT inferable from static images and MUST NOT be invented.
- Counts and distances (instance counts, structural distance) are derived views, not stored.
- `category: layout` components express shared page chrome with a child slot.

---

## 12. Design tokens and theme modes

### 12.1 Tokens
```
tokens { color{id}, type{id}, space{id}, radius{id}, border_width{id}, shadow{id}, opacity{id}, scales{...} }
Token { id, name, name_source,
        value | by_mode{ mode_id -> { value, supports[] } },     // exactly one of the two
        aliases_of?: id,
        inference{ value, role? } }
```
- Primitive tokens hold values; semantic tokens alias them. Semantic color roles: `primary secondary background surface text text_muted border accent success warning danger info`.
- Token values are inferred. The samples that justify them are evidence (`color_sample`, `spacing_sample`, `text_metrics`, `border_profile`) referenced by `supports`. Cluster statistics are not stored on the token; they are in the evidence.
- Nodes reference tokens; they never copy values, except `literal` colors where no token covers.
- Naming is deterministic: semantic role if assigned, else category plus rank by usage, ties broken by canonical value.

### 12.2 Theme modes (design-system layer)
```
modes { id -> Mode { id, name, kind: light|dark|other, inference } }
project.default_mode
Screen.resolved.mode
Token.by_mode, Asset.mode_variants
```
- A mode exists only if a screen evidences it (`luminance_profile`), a user declares it (`Source.declared.mode`), or a user asserts it. The registry is never pre-populated with a "dark" counterpart.
- R-MODE-1. `by_mode` keys MUST be registered modes.
- R-MODE-2. A token's per-mode value MUST be supported by evidence from a screen resolved to that mode, or by a user assertion. Values are never synthesized from another mode by transformation. (Palette suggestions, if ever built, live outside the IR.)
- R-MODE-3. Incomplete coverage is valid: a token with values in only some registered modes yields a warning.
- R-MODE-4. A node style value that differs between modes MUST be expressed through a token; a mode-divergent `literal` is an error.
- Pairing a token's values across modes (merging the light and dark colors of one role into one token) is inferred from nodes realized in both modes; it requires a consistent mapping across at least 2 nodes (initial default) and records `method: token.mode_merge/1`. Otherwise the two values stay separate tokens.
- The IR has no field for how a mode is selected, persisted, or triggered (user toggle, system preference, schedule). That is generator-plan data. A switching behavior can enter only via a future asserted extension.
- Structural differences between modes are out of scope for 0.x: a mode changes token values and asset variants only.

---

## 13. Responsive rules

```
Page.viewport_classes[] : ordered partition of [0, inf): { id, min, max_exclusive (number | breakpoint id | null) }
Page.breakpoints{ id -> { known_interval:[lo,hi] (derived), selected, basis: interval_midpoint|convention_snap|user_specified, inference } }
Page.base_class, Page.base_basis (screen id)
Page.responsive[] : { id, target (node id), when: [class ids], patch: [ PatchOp ], inference }
PatchOp { op: set|hide|reorder|swap_variant, path?, value? }
```
- Observed: each screen's declared or measured viewport width (`asserted`/`measured`) and the boxes realized at that width. Inferred: classes, `selected` thresholds, patches.
- `known_interval` is derived from adjacent observed widths; the validator recomputes it. The true threshold lies within it. `selected` is the value generators MUST use; `basis` records how it was chosen (project breakpoint scale value inside the interval = `convention_snap`; else rounded midpoint; or user pin). A selected threshold is never presented as observed.
- The IR is viewport-neutral; mobile-first versus desktop-first is a generator choice.
- Allowed `set` paths (whitelist): `layout.*`, `size.*`, `spacing.*`, `placement.*`, `style.fill|border|radius|shadows|opacity`, `text.style`, `text.truncation`; plus `reorder` on `children`, `hide` on `presence`, `swap_variant` on `instance.variant`.
- Patches MUST NOT change `kind`, change component identity, or reparent. Differing hierarchy uses duplicate-with-visibility.
- Normative `resolve(page, class_id)` applies the base tree plus matching patches in document order. The validator checks that for each screen, `resolve` yields a tree structurally consistent with that screen's realizations. This is structural, not pixel, consistency.

---

## 14. Relations, navigation, interaction and state

### 14.1 Relations
```
Relation { id, kind: similar_to|possible_responsive_variant_of|shares_layout|navigates_to,
           a, b, status?, inference }
```
`similar_to` is a non-committal resemblance backed by a measured `repetition` score. It is not identity. Identity is structural: a shared `component`, or one node realized on several screens.

### 14.2 Navigation (evidence-aware, never promoted silently)
`navigates_to`: `a` is the source node; `b` is a page ID or `null`.

| status | Meaning | Required |
|---|---|---|
| `unknown` | The node looks navigational (`affordance.purpose = navigation_like`) but no target is known | `b = null`; supports may be affordance evidence |
| `inferred` | A heuristic suggests a target (for example label similarity, position) | `b` set; supports non-empty; no direct cue |
| `evidenced` | The screenshots contain a direct cue tying the control to the target (for example an active-state indicator on the destination's own screen) | at least one `navigation_cue` evidence naming that cue |
| `user_asserted` | A user stated the target | `user_assertion` evidence |

- R-NAV-1. These relations carry NO behavioral semantics. They annotate what the screenshots suggest.
- R-NAV-2. Generators MUST NOT emit functional navigation (links, routes, handlers) from `unknown` or `inferred`. They MAY emit it from `evidenced` only if the generation plan's navigation policy explicitly enables it. Only `user_asserted` navigation is emitted by default. Every `navigates_to` relation and its status MUST appear in the generation report.
- R-NAV-3. Automatic re-analysis may move a relation between `unknown`, `inferred` and `evidenced` as evidence changes, recording the change in `lineage`. It MUST NOT produce `user_asserted`, and it MUST NOT overwrite or delete a `user_asserted` relation (a contradicted one is flagged `stale`).
- R-NAV-4. Navigation never appears as a node field or an implicit link target; it exists only as relations.

### 14.3 Interaction and state (deliberately minimal)
Included: `affordance`; visual states as component variant axes; page `states[]` with `presence`; `navigates_to` relations; theme modes (as design-system data only).
Excluded from core: event handlers, transitions, animation, validation logic, data sources, API calls, routing, theme-switching mechanisms. Future video input or user authoring would add these under `s2c.*` extensions first, each declaring its epistemic class.

---

## 15. Evidence, inference, confidence

### 15.1 Regions
`Region { id, source, rect{x,y,w,h}, basis: measured|reported, producer }`. Rectangles only in 0.x; masks stay in artifacts. Source-pixel coordinates exist nowhere else.

### 15.2 Evidence
```
Evidence { id, kind, basis: measured|reported|asserted, regions[], measure{...typed by kind...}, producer }
```
Kinds (closed in 0.x), with their usual basis:
- measured: `alignment`, `stack_axis`, `grid_fit`, `spacing_sample`, `size_sample`, `color_sample`, `luminance_profile`, `border_profile`, `shadow_fit`, `gradient_fit`, `text_metrics`, `repetition`, `containment`, `contrast`, `asset_candidate`, `layout_residual`, `affordance_cue`, `navigation_cue` (styling cues)
- reported: `text_reading`, `element_label`, and `navigation_cue` where the cue depends on a producer reading (for example label match)
- asserted: `user_assertion`

Rules
- Evidence MUST be expressible without knowing which backend produced it; `measure` has a typed schema per kind with no provider-specific fields.
- Evidence is small and immutable. Heavy payloads stay in artifacts.
- Only signals actually computed are recorded. A `contrast` record exists only if contrast was measured.
- A producer's own score is carried as `reported_confidence` inside the measure. It is opaque, uncalibrated, and never copied into a confidence.

### 15.3 Producers
`producers{ id -> { class: classical|model|heuristic|user, id: opaque string, version, config_hash?, artifact_ref? } }`. No enum of engines, models or vendors exists anywhere in the schema.

### 15.4 Inference record
```
InferenceRecord { method: "<stage.name>/<version>",
                  calibration: calibrated|heuristic|asserted,
                  basis: evidence|default|asserted,
                  confidence: 0..1,
                  supports[] (evidence ids), against[] (evidence ids) }
```
- `basis: default` marks a documented default rule with no direct evidence; `supports` may be empty only then (and for `asserted`). Defaults are reported in the quality report and make the node `partial`.
- `calibrated` means mapped to measured accuracy on a named calibration set. `heuristic` is a rule score, not a probability. `asserted` is set by a user and is 1.0.
- Confidences of different calibration classes MUST NOT be compared or averaged as probabilities.
- Explainability is a derived view: claim, then record, then `supports`, then evidence, then regions. There is no free-text rationale field, and a UI may display only what this chain contains.

### 15.5 Which evidence may support which claim (R-EPI-4)

| Claim | Allowed `supports` kinds |
|---|---|
| node structure | containment, alignment, stack_axis, grid_fit, repetition, element_label, text_reading, asset_candidate, user_assertion |
| node role / affordance | element_label, affordance_cue, repetition, text_reading, text_metrics, user_assertion |
| node layout | alignment, stack_axis, grid_fit, spacing_sample, size_sample, layout_residual, containment, repetition, asset_candidate, user_assertion |
| node style (including media fit) | color_sample, border_profile, shadow_fit, gradient_fit, text_metrics, contrast, asset_candidate, layout_residual, user_assertion |
| node content | text_reading, asset_candidate, user_assertion |
| realization | containment, alignment, stack_axis, grid_fit, repetition, text_reading, asset_candidate, user_assertion |
| token value | color_sample, spacing_sample, text_metrics, border_profile, shadow_fit, user_assertion |
| mode, screen resolution | luminance_profile, user_assertion |
| responsive rule, breakpoint | alignment, stack_axis, grid_fit, containment, size_sample, user_assertion |
| component identity, `similar_to` | repetition, user_assertion |
| `navigates_to` | navigation_cue, affordance_cue, text_reading, user_assertion |
| asset kind and `hint` | asset_candidate, user_assertion |

### 15.6 Realizations (the bridge from regions to nodes)
```
realizations{ screen_id -> { inference (default record), nodes{ node_id -> { regions[], inference? } } } }
```
- A realization states: this node is what that region shows on that screen. It is inferred. A node realized on two screens is the cross-screen correspondence.
- Every page-scope node visible in an observing screen MUST have a realization. Component-internal nodes use the key `<instance id>/<definition node id>` and are OPTIONAL in 0.x.

### 15.7 Disputes (producers disagree)
```
Dispute { id, target, field, kind, selected{value}, alternatives[ { value, producers[], supports[] } ],
          resolution: user|geometric_consistency|weighted_vote|tie_break|unresolved, status: contested|resolved }
```
The IR always holds exactly ONE selected structure; alternatives are annotations, never a second structure. Precedence: (1) user assertion; (2) eliminate hypotheses violating hard geometric consistency; (3) weighted agreement across producers using configured weights; (4) deterministic tie-break by canonical value order. Unresolved disputes keep `status: contested`, are reported, and do not block generation.

---

## 16. Redaction (optional, auditable)

```
project.redaction { mode: off|on, profile_id?, profile_hash?, stage: pre_perception|post_inference|both,
                    artifacts: purged|retained|redacted, keep_original_digest: false }
Redaction (record) { id, stage, target{ kind: region|text|asset, ref ... },
                     action: mask|replace_text|remove,
                     replacement?{ kind: "class_label", label },
                     reason: rule|user, rule_id?, producer,
                     scrubbed_paths[] (JSON Pointers) }
```
- Redaction is a record-class provenance fact: it is itself auditable data, listed in `redactions`, and affected locations point back to it (`Region.redacted`, `Source.redaction`, `TextValue.redaction`).
- Pre-perception redaction masks pixels before analysis, so evidence derived afterward describes the masked image; the `Region` rectangle stays, with no measured payload. Post-inference redaction replaces content in the IR.
- Transitive scrubbing: redacting content MUST also scrub every copy in the IR (evidence readings, alternatives, disputes). Each scrubbed JSON Pointer is listed in `scrubbed_paths`. Names MUST NOT be derived from redacted text.
- Text becomes `status: redacted`, `value: null`, optionally with a class label such as `email`. No hash of redacted content is stored; hashes of low-entropy personal data are guessable. `Source.sha256` is the hash of the analyzed (redacted) bytes; an original digest is stored only if `keep_original_digest` is explicitly enabled.
- Redaction does not touch outside-IR artifacts unless `artifacts` says so; the chosen handling is recorded. Redaction does not make an IR safe to share by itself.
- Benchmark comparability: the redaction profile hash is part of `inference_config` and therefore of `content_hash`. Benchmark run records MUST include the profile hash and the number of redacted spans. Runs with differing profile hashes MUST be flagged non-comparable by tooling. Evaluations report redacted spans as an explicit, counted exclusion; they are never silently dropped. The synthetic benchmark contains no personal data, so redaction is off by default there.

---

## 17. Validation, partial IR, error handling

### 17.1 Levels
| Level | Checks | Failure |
|---|---|---|
| L0 schema | types, required fields, enums, ranges, canonical forms | error |
| L1 referential | IDs resolve and are unique; single parent; no cycles in trees or component definitions; scope integrity; instance/param/slot conformity | error |
| L2 semantic | R-EPI rules; placement matches parent mode; patch paths whitelisted; token types match usage; viewport classes partition; `known_interval` recomputation; `resolve()` consistency; provenance fields complete; absolute needs `fallback`; overlay needs `reason`; R-MODE, R-NAV, redaction rules | error |
| L3 quality | absolute ratio; repeated literals; `fixed` without support; uncertain/unreadable text; contested disputes; `basis: default` claims; opaque coverage; claims resting on one reported producer; incomplete mode coverage; unknown-rights assets | warning/info in `quality_report` |

### 17.2 Epistemic rules
- R-EPI-1. `sources`, `regions`, `evidence` contain only measured/reported/asserted fields. They MUST NOT contain node, component, token, asset or relation references (only region and producer IDs), nor structural vocabulary. Closed schema.
- R-EPI-2. Structure and design-system sections MUST NOT contain `Region` records or `measured` payloads.
- R-EPI-3. Every populated facet has an inference record. `supports` is non-empty unless `basis` is `default` or `asserted`.
- R-EPI-4. Every `supports` entry resolves, and its evidence kind is allowed for that claim (section 15.5).
- R-EPI-5. `asserted` values come only from `user_assertion` evidence, with `calibration: asserted`, confidence 1. Re-analysis preserves them.
- R-EPI-6. No silent promotion. A claim's `calibration` and `basis` change only by recomputation or by a user action. Nothing becomes `asserted` automatically.
- R-EPI-7. Observed evidence is immutable; user edits are asserted structure, never edits to observations.
- R-EPI-8. Record and derived fields (`status`, `known_interval`, `hint`) MUST equal their recomputation.
- R-EPI-9. Migrations and extensions preserve epistemic class (sections 4.3, 4.4).

### 17.3 Diagnostics, modes, partial IR
- Diagnostic: `{ code, severity: error|warning|info, path (JSON Pointer), message, related[] }`.
- `strict`: any error aborts. `lenient`: only these deterministic repairs, each logged in `lineage.repairs`: drop dangling evidence references; clamp confidence to [0,1]; round to canonical precision; sort sets. Lenient mode never guesses and never creates evidence.
- `ir_state`: `working` documents may be invalid; `commit` runs L0-L2. Generators and the desktop UI accept `committed` documents only.
- Partial reconstruction: node `status` is `resolved`, `partial` (any facet `basis: default`, or any text or param with status `uncertain` or `unreadable`), or `opaque`. `redacted` content is intentional and does not make a node `partial`.
- An `opaque` node is a region the pipeline could not decompose. It carries a fallback asset (extracted crop, or placeholder if not separable). It is legitimate, not an error.
- `Page.completeness.state` is `complete` only if no node is `opaque` and no required text is `unreadable`; otherwise `partial`.
- Generators MUST handle `opaque` explicitly (emit the asset and report it) or refuse in strict mode. Absence of a node is never read as intent.

---

## 18. Trust of IR content

Per ADR-0001 amendment A3, the IR is derived from untrusted images and untrusted model output, and is itself untrusted input to every generator.
- T-1. Text values, names and alternatives are opaque strings that may contain markup, script or injection-like text. Generators MUST escape for their target.
- T-2. Vector asset content is validated and sanitized before storage; scripts, external references and event attributes are rejected.
- T-3. Asset references are content-addressed blobs inside the bundle. Paths from IR data are never used for filesystem access.
- T-4. The IR contains nothing executable and nothing that causes execution.
- T-5. Personal data in source images can reach the IR as text; section 16 provides redaction.

---

## 19. Hard cases and the decisions made

### A. Two similar buttons that may not be the same component
Similarity and identity are separate. A `repetition` score above the record threshold (initial default 0.75) yields only a `similar_to` relation. Promotion to a shared component requires ALL of: (S) structure signature equal after masking content, allowing optional slots; (V) style within token tolerance or explained by at most two variant axes; (R) role compatibility; and minimum support of 2 (or a user pin). Decision: under-merge. A wrong merge corrupts the design system and is hard to notice; a wrong split is cheap to fix by a user merge, and the system emits merge suggestions as `similar_to` relations. Roles that differ with confidence (for example static tag versus button, from `affordance_cue`) block merging.

### B. Same component, different content
Content is not identity. The signature masks text values and asset bytes; content moves to instance `params` and `slot_content`. Size differences caused by content are absorbed by `hug`/`fill` and `truncation`. An optional element becomes an optional slot or a `style` variant axis; otherwise the components stay separate with `similar_to`.

### C. Horizontal layout becomes vertical on narrow screens
One page when screen correspondence is strong: base `stack.axis = horizontal` plus a responsive rule setting `vertical` for the narrow class. Hierarchy differences use duplicate-with-visibility. If correspondence is weak or the change exceeds what patches can express, the screens stay separate pages linked by `possible_responsive_variant_of`, with a quality warning. Thresholds are recorded as intervals with a selected value and basis.

### D. Intentional overlay versus accidental absolute
Section 8.3. Overlay needs purposeful overlap plus an anchor fit (or a layered role) and a declared `reason`; absolute is a flagged fallback with measured residual in evidence, counted in `quality.absolute_ratio`.

### E. An image whose original cannot be recovered
Unoccluded, separable, large enough: `extracted` pixel crop (lossy, `resolution_scale` kept, `rights_status: unknown`). Flat or gradient regions with low fit error: `reconstructed`. Otherwise `placeholder` with a `hint`. A placeholder never imitates the image, and reports list it as a placeholder. Under `strict` export policy even an extracted asset degrades to a placeholder from its `hint`.

### F. OCR is uncertain or wrong
Readings are `reported` evidence. `TextValue.status`: `verified` (user, or agreement across producers above threshold), `inferred` (single producer above threshold), `uncertain` (confidence below `text.status.uncertain_below`, initial default 0.8), `unreadable` (below 0.3, `value: null`). Up to three alternatives are kept. No silent autocorrection: a language-model correction is just another producer whose output is an alternative. Uncertain text is emitted verbatim and listed in the report; unreadable text is emitted as a visibly marked, project-configured placeholder string, never invented content.

### G. Multiple models disagree about structure
Section 15.7: one selected structure, alternatives as annotations, deterministic precedence, unresolved disputes reported.

### H. A partially reconstructed page
Section 17.3: valid, marked `partial`, with `opaque` nodes carrying fallback assets. Coverage is derived. Strict generation may refuse; lenient generation emits and reports.

### I. Same token, slightly different observed values
Observed values are `measured` `color_sample` clusters with their spread. Clustering merges samples by perceptual distance (colors: CIEDE2000 <= 3.0; lengths: within max(1.0 px, 2%); initial defaults). The token's canonical value is the support-weighted medoid quantized to 8 bits, not snapped to "nice" values unless the medoid is exactly that. Because the spread stays in the evidence, compression jitter is visible, not hidden. The canonical value changes on re-analysis only if cluster membership changes.

### J. A generator needs information that must not leak into the IR
Apply the admission test (section 2.5). Implementation facts (file names, classes, imports, routing, hooks, CSS strategy, image-component choice, theme-selection mechanism) go to the generation overlay keyed by IR IDs and `content_hash`. Missing UI knowledge that at least two generators would use (for example `repeat.count_semantics`) is added to core in a MINOR release. Interim framework-independent data uses an `s2c.*` extension with a declared epistemic class, never a `gen.*` one.

### K. Theme modes (new)
Light and dark screenshots of one page share structure. Realizations of the same node on both screens, with consistent token mappings, merge into one token with `by_mode` values. Only modes with evidence exist; no palette is synthesized; switching behavior is not represented (section 12.2).

---

## 20. Complete example

Hand-written for exposition. IDs are readable here but real IDs are opaque; hashes are shortened. It has NOT been machine-validated because no validator exists; Phase 1 must add it as a golden fixture and validate it against the generated JSON Schema. Component-internal realizations are omitted, which section 15.6 permits. The mobile screen is resolved to the dark mode and the desktop screen to the light mode, so the example also shows mode-pairing with a confounded viewport (open item 1).

```json
{
  "schema_version": "0.1",
  "ir_state": "committed",
  "extensions_used": [],
  "extensions_required": [],
  "meta": { "created_by": "spec-example", "created_at": "2026-10-08T00:00:00Z" },
  "project": { "id": "prj_acme", "name": "Acme Shop", "name_source": "user",
               "default_mode": "mode_light", "redaction": { "mode": "off" } },
  "inference_config": {
    "config_hash": "sha256:example-cfg",
    "values": { "component.min_support": 2, "similarity.record_above": 0.75,
                "token.color.merge_delta_e2000": 3.0, "token.mode_merge.min_nodes": 2,
                "text.status.uncertain_below": 0.8, "layout.absolute.max_residual_px": 2.0 }
  },
  "producers": {
    "prd_seg":   { "class": "classical", "id": "s2c.region-segmenter", "version": "0.1.0" },
    "prd_ocr_a": { "class": "model", "id": "ocr.engine-a", "version": "1.2.0" },
    "prd_ocr_b": { "class": "model", "id": "ocr.engine-b", "version": "3.0.1" }
  },

  "sources": {
    "src_d": { "id": "src_d", "media_type": "image/png", "sha256": "example-d",
               "pixel_size": { "w": 1440, "h": 868 },
               "declared": { "device_pixel_ratio": 1, "viewport_width": 1440 } },
    "src_m": { "id": "src_m", "media_type": "image/png", "sha256": "example-m",
               "pixel_size": { "w": 1170, "h": 4830 },
               "declared": { "device_pixel_ratio": 3, "viewport_width": 390 } }
  },

  "regions": {
    "reg_d_root":  { "id": "reg_d_root",  "source": "src_d", "rect": { "x": 0,   "y": 0,   "w": 1440, "h": 868 }, "basis": "measured", "producer": "prd_seg" },
    "reg_d_hero":  { "id": "reg_d_hero",  "source": "src_d", "rect": { "x": 24,  "y": 24,  "w": 1392, "h": 420 }, "basis": "measured", "producer": "prd_seg" },
    "reg_d_h1":    { "id": "reg_d_h1",    "source": "src_d", "rect": { "x": 24,  "y": 179, "w": 560,  "h": 110 }, "basis": "measured", "producer": "prd_seg" },
    "reg_d_himg":  { "id": "reg_d_himg",  "source": "src_d", "rect": { "x": 856, "y": 48,  "w": 560,  "h": 373 }, "basis": "measured", "producer": "prd_seg" },
    "reg_d_grid":  { "id": "reg_d_grid",  "source": "src_d", "rect": { "x": 24,  "y": 468, "w": 1392, "h": 376 }, "basis": "measured", "producer": "prd_seg" },
    "reg_d_c1":    { "id": "reg_d_c1",    "source": "src_d", "rect": { "x": 24,  "y": 468, "w": 448,  "h": 376 }, "basis": "measured", "producer": "prd_seg" },
    "reg_d_c2":    { "id": "reg_d_c2",    "source": "src_d", "rect": { "x": 496, "y": 468, "w": 448,  "h": 376 }, "basis": "measured", "producer": "prd_seg" },
    "reg_d_c3":    { "id": "reg_d_c3",    "source": "src_d", "rect": { "x": 968, "y": 468, "w": 448,  "h": 376 }, "basis": "measured", "producer": "prd_seg" },
    "reg_d_c1img": { "id": "reg_d_c1img", "source": "src_d", "rect": { "x": 40,  "y": 484, "w": 416,  "h": 312 }, "basis": "measured", "producer": "prd_seg" },
    "reg_d_c1t":   { "id": "reg_d_c1t",   "source": "src_d", "rect": { "x": 40,  "y": 804, "w": 416,  "h": 24 },  "basis": "measured", "producer": "prd_seg" },
    "reg_d_c2t":   { "id": "reg_d_c2t",   "source": "src_d", "rect": { "x": 512, "y": 804, "w": 416,  "h": 24 },  "basis": "measured", "producer": "prd_seg" },
    "reg_d_c3t":   { "id": "reg_d_c3t",   "source": "src_d", "rect": { "x": 984, "y": 804, "w": 416,  "h": 24 },  "basis": "measured", "producer": "prd_seg" },
    "reg_m_root":  { "id": "reg_m_root",  "source": "src_m", "rect": { "x": 0,  "y": 0,    "w": 1170, "h": 4830 }, "basis": "measured", "producer": "prd_seg" },
    "reg_m_hero":  { "id": "reg_m_hero",  "source": "src_m", "rect": { "x": 72, "y": 72,   "w": 1026, "h": 1086 }, "basis": "measured", "producer": "prd_seg" },
    "reg_m_h1":    { "id": "reg_m_h1",    "source": "src_m", "rect": { "x": 72, "y": 72,   "w": 1026, "h": 330 },  "basis": "measured", "producer": "prd_seg" },
    "reg_m_himg":  { "id": "reg_m_himg",  "source": "src_m", "rect": { "x": 72, "y": 474,  "w": 1026, "h": 684 },  "basis": "measured", "producer": "prd_seg" },
    "reg_m_grid":  { "id": "reg_m_grid",  "source": "src_m", "rect": { "x": 72, "y": 1230, "w": 1026, "h": 3528 }, "basis": "measured", "producer": "prd_seg" },
    "reg_m_c1":    { "id": "reg_m_c1",    "source": "src_m", "rect": { "x": 72, "y": 1230, "w": 1026, "h": 1128 }, "basis": "measured", "producer": "prd_seg" },
    "reg_m_c2":    { "id": "reg_m_c2",    "source": "src_m", "rect": { "x": 72, "y": 2430, "w": 1026, "h": 1128 }, "basis": "measured", "producer": "prd_seg" },
    "reg_m_c3":    { "id": "reg_m_c3",    "source": "src_m", "rect": { "x": 72, "y": 3630, "w": 1026, "h": 1128 }, "basis": "measured", "producer": "prd_seg" }
  },

  "evidence": {
    "evd_1": { "id": "evd_1", "kind": "alignment", "basis": "measured", "producer": "prd_seg",
               "regions": ["reg_d_h1", "reg_d_himg"], "measure": { "axis": "y", "edge": "center", "residual_px": 0.5 } },
    "evd_2": { "id": "evd_2", "kind": "stack_axis", "basis": "measured", "producer": "prd_seg",
               "regions": ["reg_m_h1", "reg_m_himg"], "measure": { "axis": "vertical", "order_consistency": 1.0, "gap_samples_px": [24] } },
    "evd_3": { "id": "evd_3", "kind": "stack_axis", "basis": "measured", "producer": "prd_seg",
               "regions": ["reg_d_h1", "reg_d_himg"], "measure": { "axis": "horizontal", "order_consistency": 1.0, "gap_samples_px": [272] } },
    "evd_4": { "id": "evd_4", "kind": "repetition", "basis": "measured", "producer": "prd_seg",
               "regions": ["reg_d_c1", "reg_d_c2", "reg_d_c3"], "measure": { "similarity": 0.96, "count": 3, "axis": "x" } },
    "evd_5": { "id": "evd_5", "kind": "repetition", "basis": "measured", "producer": "prd_seg",
               "regions": ["reg_m_c1", "reg_m_c2", "reg_m_c3"], "measure": { "similarity": 0.96, "count": 3, "axis": "y" } },
    "evd_6": { "id": "evd_6", "kind": "text_reading", "basis": "reported", "producer": "prd_ocr_a",
               "regions": ["reg_d_h1", "reg_d_c1t", "reg_d_c2t", "reg_d_c3t"],
               "measure": { "readings": [
                 { "region": "reg_d_h1",  "value": "Summer essentials", "reported_confidence": 0.97 },
                 { "region": "reg_d_c1t", "value": "Canvas tote",       "reported_confidence": 0.96 },
                 { "region": "reg_d_c2t", "value": "Linen shirl",       "reported_confidence": 0.58 },
                 { "region": "reg_d_c3t", "value": "Wool beanie",       "reported_confidence": 0.95 } ] } },
    "evd_7": { "id": "evd_7", "kind": "text_reading", "basis": "reported", "producer": "prd_ocr_b",
               "regions": ["reg_d_h1", "reg_d_c1t", "reg_d_c2t", "reg_d_c3t"],
               "measure": { "readings": [
                 { "region": "reg_d_h1",  "value": "Summer essentials", "reported_confidence": 0.95 },
                 { "region": "reg_d_c1t", "value": "Canvas tote",       "reported_confidence": 0.93 },
                 { "region": "reg_d_c2t", "value": "Linen shirt",       "reported_confidence": 0.74 },
                 { "region": "reg_d_c3t", "value": "Wool beanie",       "reported_confidence": 0.92 } ] } },
    "evd_8": { "id": "evd_8", "kind": "asset_candidate", "basis": "measured", "producer": "prd_seg",
               "regions": ["reg_d_himg"], "measure": { "occluded_ratio": 0.0, "overlaid_text": false, "aspect": 1.5, "dominant_color": "#9DB4D8", "resolution_scale": 1.0 } },
    "evd_9": { "id": "evd_9", "kind": "asset_candidate", "basis": "measured", "producer": "prd_seg",
               "regions": ["reg_d_c1img"], "measure": { "occluded_ratio": 0.18, "overlaid_text": true, "aspect": 1.333, "dominant_color": "#C9CED6", "resolution_scale": 1.0 } },
    "evd_10": { "id": "evd_10", "kind": "luminance_profile", "basis": "measured", "producer": "prd_seg",
                "regions": ["reg_d_root"], "measure": { "mean_luma": 0.98 } },
    "evd_11": { "id": "evd_11", "kind": "luminance_profile", "basis": "measured", "producer": "prd_seg",
                "regions": ["reg_m_root"], "measure": { "mean_luma": 0.07 } },
    "evd_12": { "id": "evd_12", "kind": "color_sample", "basis": "measured", "producer": "prd_seg",
                "regions": ["reg_d_root", "reg_d_c1", "reg_d_h1"],
                "measure": { "clusters": [
                  { "hex": "#FFFFFF", "usage": "area_fill", "n_px": 902000, "spread_de2000": 0.0 },
                  { "hex": "#E5E7EB", "usage": "border",    "n_px": 3100,   "spread_de2000": 1.1 },
                  { "hex": "#111827", "usage": "text",      "n_px": 21000,  "spread_de2000": 0.4 } ] } },
    "evd_13": { "id": "evd_13", "kind": "color_sample", "basis": "measured", "producer": "prd_seg",
                "regions": ["reg_m_root", "reg_m_c1", "reg_m_h1"],
                "measure": { "clusters": [
                  { "hex": "#0B1020", "usage": "area_fill", "n_px": 5200000, "spread_de2000": 0.0 },
                  { "hex": "#2A3350", "usage": "border",    "n_px": 9800,    "spread_de2000": 1.4 },
                  { "hex": "#F3F4F6", "usage": "text",      "n_px": 64000,   "spread_de2000": 0.6 } ] } },
    "evd_14": { "id": "evd_14", "kind": "grid_fit", "basis": "measured", "producer": "prd_seg",
                "regions": ["reg_d_c1", "reg_d_c2", "reg_d_c3"], "measure": { "columns": 3, "track_widths_px": [448, 448, 448], "gap_px": 24, "residual_px": 0.0 } },
    "evd_15": { "id": "evd_15", "kind": "grid_fit", "basis": "measured", "producer": "prd_seg",
                "regions": ["reg_m_c1", "reg_m_c2", "reg_m_c3"], "measure": { "columns": 1, "track_widths_px": [342], "gap_px": 24, "residual_px": 0.0 } },
    "evd_16": { "id": "evd_16", "kind": "spacing_sample", "basis": "measured", "producer": "prd_seg",
                "regions": ["reg_d_root", "reg_d_c1"], "measure": { "samples": [ { "px": 24, "n": 4 }, { "px": 16, "n": 4 }, { "px": 8, "n": 2 } ] } },
    "evd_17": { "id": "evd_17", "kind": "text_metrics", "basis": "measured", "producer": "prd_seg",
                "regions": ["reg_d_h1", "reg_d_c1t"],
                "measure": { "items": [
                  { "region": "reg_d_h1",  "line_height_px": 55.2, "cap_height_px": 34.0, "weight_hint": "bold" },
                  { "region": "reg_d_c1t", "line_height_px": 24.0, "cap_height_px": 11.5, "weight_hint": "regular" } ] } },
    "evd_18": { "id": "evd_18", "kind": "border_profile", "basis": "measured", "producer": "prd_seg",
                "regions": ["reg_d_c1"], "measure": { "corner_radius_px": 8, "border_width_px": 1 } },
    "evd_19": { "id": "evd_19", "kind": "containment", "basis": "measured", "producer": "prd_seg",
                "regions": ["reg_d_root", "reg_d_hero", "reg_d_grid"], "measure": { "nested_pairs": 2, "max_overlap_ratio": 0.0 } },
    "evd_20": { "id": "evd_20", "kind": "size_sample", "basis": "measured", "producer": "prd_seg",
                "regions": ["reg_m_himg", "reg_m_hero"], "measure": { "axis": "x", "extent_ratio_of_container": 1.0 } }
  },

  "screens": {
    "scr_d": { "id": "scr_d", "source": "src_d",
               "resolved": { "page": "pg_home", "viewport_width": 1440, "scale": 1, "viewport_class": "vc_wide", "mode": "mode_light" },
               "origin": { "page": "inferred", "viewport_width": "declared", "scale": "declared", "viewport_class": "inferred", "mode": "inferred" },
               "inference": { "method": "screen.resolve/1", "calibration": "heuristic", "basis": "evidence", "confidence": 0.9, "supports": ["evd_10"] } },
    "scr_m": { "id": "scr_m", "source": "src_m",
               "resolved": { "page": "pg_home", "viewport_width": 390, "scale": 3, "viewport_class": "vc_narrow", "mode": "mode_dark" },
               "origin": { "page": "inferred", "viewport_width": "declared", "scale": "declared", "viewport_class": "inferred", "mode": "inferred" },
               "inference": { "method": "screen.resolve/1", "calibration": "heuristic", "basis": "evidence", "confidence": 0.9, "supports": ["evd_11"] } }
  },

  "modes": {
    "mode_light": { "id": "mode_light", "name": "Light", "kind": "light",
                    "inference": { "method": "mode.detect/1", "calibration": "heuristic", "basis": "evidence", "confidence": 0.9, "supports": ["evd_10"] } },
    "mode_dark":  { "id": "mode_dark",  "name": "Dark",  "kind": "dark",
                    "inference": { "method": "mode.detect/1", "calibration": "heuristic", "basis": "evidence", "confidence": 0.9, "supports": ["evd_11"] } }
  },

  "pages": {
    "pg_home": {
      "id": "pg_home", "name": "Home", "name_source": "inferred", "root": "nd_root",
      "viewport_classes": [
        { "id": "vc_narrow", "min": 0, "max_exclusive": "bp_1" },
        { "id": "vc_wide", "min": "bp_1", "max_exclusive": null }
      ],
      "breakpoints": { "bp_1": { "known_interval": [390, 1440], "selected": 768, "basis": "convention_snap",
        "inference": { "method": "breakpoint.select/1", "calibration": "heuristic", "basis": "default", "confidence": 0.5, "supports": [] } } },
      "base_class": "vc_wide", "base_basis": "scr_d",
      "responsive": [
        { "id": "rs_1", "target": "nd_hero", "when": ["vc_narrow"],
          "patch": [ { "op": "set", "path": "layout.stack.axis", "value": "vertical" },
                     { "op": "set", "path": "layout.stack.align", "value": "stretch" },
                     { "op": "set", "path": "layout.stack.distribute", "value": "start" } ],
          "inference": { "method": "responsive.diff/1", "calibration": "heuristic", "basis": "evidence", "confidence": 0.88, "supports": ["evd_1", "evd_2", "evd_3"] } },
        { "id": "rs_2", "target": "nd_himg", "when": ["vc_narrow"],
          "patch": [ { "op": "set", "path": "size.w", "value": { "kind": "fill" } } ],
          "inference": { "method": "responsive.diff/1", "calibration": "heuristic", "basis": "evidence", "confidence": 0.85, "supports": ["evd_2", "evd_20"] } },
        { "id": "rs_3", "target": "nd_grid", "when": ["vc_narrow"],
          "patch": [ { "op": "set", "path": "layout.grid.columns", "value": [ { "kind": "share", "weight": 1 } ] } ],
          "inference": { "method": "responsive.diff/1", "calibration": "heuristic", "basis": "evidence", "confidence": 0.93, "supports": ["evd_14", "evd_15"] } }
      ],
      "states": [],
      "constraints": [],
      "completeness": { "state": "complete" }
    }
  },

  "nodes": {
    "nd_root": { "id": "nd_root", "kind": "box", "scope": "pg_home", "name": "Page",
      "children": ["nd_hero", "nd_grid"],
      "layout": { "mode": "stack", "stack": { "axis": "vertical", "gap": { "token": "tok_s6" }, "align": "stretch", "distribute": "start" } },
      "size": { "w": { "kind": "fill" }, "h": { "kind": "hug" } },
      "spacing": { "padding": { "all": { "token": "tok_s6" } } },
      "style": { "fill": { "kind": "solid", "color": { "token": "tok_bg" } } },
      "status": "resolved",
      "inference": {
        "structure": { "method": "tree.build/1", "calibration": "heuristic", "basis": "evidence", "confidence": 0.95, "supports": ["evd_19"] },
        "layout": { "method": "layout.stack/1", "calibration": "heuristic", "basis": "evidence", "confidence": 0.9, "supports": ["evd_16", "evd_19"] },
        "style": { "method": "style.fill/1", "calibration": "heuristic", "basis": "evidence", "confidence": 0.92, "supports": ["evd_12", "evd_13"] } } },
    "nd_hero": { "id": "nd_hero", "kind": "box", "scope": "pg_home", "name": "Hero",
      "children": ["nd_h1", "nd_himg"],
      "layout": { "mode": "stack", "stack": { "axis": "horizontal", "gap": { "token": "tok_s6" }, "align": "center", "distribute": "space-between" } },
      "size": { "w": { "kind": "fill" }, "h": { "kind": "hug" } },
      "status": "resolved",
      "inference": {
        "structure": { "method": "tree.build/1", "calibration": "heuristic", "basis": "evidence", "confidence": 0.93, "supports": ["evd_19"] },
        "layout": { "method": "layout.stack/1", "calibration": "heuristic", "basis": "evidence", "confidence": 0.88, "supports": ["evd_1", "evd_2", "evd_3"] } } },
    "nd_h1": { "id": "nd_h1", "kind": "text", "role": "heading", "scope": "pg_home",
      "text": { "content": { "value": "Summer essentials", "status": "verified" }, "style": { "token": "tok_t_h1" }, "heading_level": 1 },
      "size": { "w": { "kind": "hug" }, "h": { "kind": "hug" } },
      "status": "partial",
      "inference": {
        "structure": { "method": "tree.build/1", "calibration": "heuristic", "basis": "evidence", "confidence": 0.97, "supports": ["evd_6", "evd_7"] },
        "role": { "method": "role.classify/1", "calibration": "heuristic", "basis": "evidence", "confidence": 0.8, "supports": ["evd_17"] },
        "layout": { "method": "layout.size/1", "calibration": "heuristic", "basis": "default", "confidence": 0.6, "supports": [] },
        "style": { "method": "style.text/1", "calibration": "heuristic", "basis": "evidence", "confidence": 0.9, "supports": ["evd_17"] },
        "content": { "method": "text.accept/1", "calibration": "heuristic", "basis": "evidence", "confidence": 0.96, "supports": ["evd_6", "evd_7"] } } },
    "nd_himg": { "id": "nd_himg", "kind": "image", "scope": "pg_home", "name": "Hero image",
      "media": { "asset": "ast_hero", "fit": "cover" },
      "size": { "w": { "kind": "fixed", "px": 560 }, "h": { "kind": "hug" }, "aspect": 1.5 },
      "status": "resolved",
      "inference": {
        "structure": { "method": "tree.build/1", "calibration": "heuristic", "basis": "evidence", "confidence": 0.92, "supports": ["evd_8"] },
        "layout": { "method": "layout.size/1", "calibration": "heuristic", "basis": "evidence", "confidence": 0.85, "supports": ["evd_8"] },
        "style": { "method": "style.media/1", "calibration": "heuristic", "basis": "evidence", "confidence": 0.8, "supports": ["evd_8"] },
        "content": { "method": "asset.bind/1", "calibration": "heuristic", "basis": "evidence", "confidence": 0.9, "supports": ["evd_8"] } } },
    "nd_grid": { "id": "nd_grid", "kind": "box", "role": "list", "scope": "pg_home", "name": "Product grid",
      "children": ["nd_c1", "nd_c2", "nd_c3"],
      "layout": { "mode": "grid", "grid": { "columns": [ { "kind": "share", "weight": 1 }, { "kind": "share", "weight": 1 }, { "kind": "share", "weight": 1 } ],
                  "gap": { "row": { "token": "tok_s6" }, "col": { "token": "tok_s6" } }, "flow": "row" } },
      "size": { "w": { "kind": "fill" }, "h": { "kind": "hug" } },
      "repeat": { "component": "cmp_card", "count": 3, "count_semantics": "dynamic" },
      "status": "resolved",
      "inference": {
        "structure": { "method": "tree.build/1", "calibration": "heuristic", "basis": "evidence", "confidence": 0.94, "supports": ["evd_19", "evd_4"] },
        "role": { "method": "role.classify/1", "calibration": "heuristic", "basis": "evidence", "confidence": 0.75, "supports": ["evd_4", "evd_5"] },
        "layout": { "method": "layout.grid/1", "calibration": "heuristic", "basis": "evidence", "confidence": 0.93, "supports": ["evd_14", "evd_15", "evd_16"] } } },
    "nd_c1": { "id": "nd_c1", "kind": "instance", "scope": "pg_home",
      "instance": { "component": "cmp_card", "variant": {}, "overrides": [],
        "params": { "title": { "value": "Canvas tote", "status": "verified" }, "image": { "asset": "ast_card_ph" } } },
      "status": "resolved",
      "inference": {
        "structure": { "method": "component.cluster/1", "calibration": "heuristic", "basis": "evidence", "confidence": 0.95, "supports": ["evd_4", "evd_5"] },
        "content": { "method": "text.accept/1", "calibration": "heuristic", "basis": "evidence", "confidence": 0.95, "supports": ["evd_6", "evd_7", "evd_9"] } } },
    "nd_c2": { "id": "nd_c2", "kind": "instance", "scope": "pg_home",
      "instance": { "component": "cmp_card", "variant": {}, "overrides": [],
        "params": { "title": { "value": "Linen shirt", "status": "uncertain",
                               "alternatives": [ { "value": "Linen shirl", "confidence": 0.58, "supports": ["evd_6"] } ] },
                    "image": { "asset": "ast_card_ph" } } },
      "status": "partial",
      "inference": {
        "structure": { "method": "component.cluster/1", "calibration": "heuristic", "basis": "evidence", "confidence": 0.95, "supports": ["evd_4", "evd_5"] },
        "content": { "method": "text.accept/1", "calibration": "heuristic", "basis": "evidence", "confidence": 0.74, "supports": ["evd_6", "evd_7", "evd_9"] } } },
    "nd_c3": { "id": "nd_c3", "kind": "instance", "scope": "pg_home",
      "instance": { "component": "cmp_card", "variant": {}, "overrides": [],
        "params": { "title": { "value": "Wool beanie", "status": "verified" }, "image": { "asset": "ast_card_ph" } } },
      "status": "resolved",
      "inference": {
        "structure": { "method": "component.cluster/1", "calibration": "heuristic", "basis": "evidence", "confidence": 0.95, "supports": ["evd_4", "evd_5"] },
        "content": { "method": "text.accept/1", "calibration": "heuristic", "basis": "evidence", "confidence": 0.94, "supports": ["evd_6", "evd_7", "evd_9"] } } },

    "nd_card_root": { "id": "nd_card_root", "kind": "box", "role": "card", "scope": "cmp_card",
      "children": ["nd_card_img", "nd_card_title"],
      "layout": { "mode": "stack", "stack": { "axis": "vertical", "gap": { "token": "tok_s2" }, "align": "stretch", "distribute": "start" } },
      "spacing": { "padding": { "all": { "token": "tok_s4" } } },
      "style": { "fill": { "kind": "solid", "color": { "token": "tok_bg" } },
                 "border": { "sides": { "all": { "width": { "px": 1 }, "style": "solid", "color": { "token": "tok_border" } } } },
                 "radius": { "all": { "token": "tok_r_md" } } },
      "status": "resolved",
      "inference": {
        "structure": { "method": "component.cluster/1", "calibration": "heuristic", "basis": "evidence", "confidence": 0.94, "supports": ["evd_4"] },
        "role": { "method": "role.classify/1", "calibration": "heuristic", "basis": "evidence", "confidence": 0.7, "supports": ["evd_4"] },
        "layout": { "method": "layout.stack/1", "calibration": "heuristic", "basis": "evidence", "confidence": 0.9, "supports": ["evd_16"] },
        "style": { "method": "style.box/1", "calibration": "heuristic", "basis": "evidence", "confidence": 0.9, "supports": ["evd_12", "evd_13", "evd_18"] } } },
    "nd_card_img": { "id": "nd_card_img", "kind": "image", "scope": "cmp_card",
      "media": { "asset": { "param": "image" }, "fit": "cover" },
      "size": { "w": { "kind": "fill" }, "h": { "kind": "hug" }, "aspect": 1.333 },
      "status": "resolved",
      "inference": {
        "structure": { "method": "tree.build/1", "calibration": "heuristic", "basis": "evidence", "confidence": 0.9, "supports": ["evd_9"] },
        "layout": { "method": "layout.size/1", "calibration": "heuristic", "basis": "evidence", "confidence": 0.85, "supports": ["evd_9"] },
        "style": { "method": "style.media/1", "calibration": "heuristic", "basis": "evidence", "confidence": 0.8, "supports": ["evd_9"] } } },
    "nd_card_title": { "id": "nd_card_title", "kind": "text", "scope": "cmp_card",
      "text": { "content": { "param": "title" }, "style": { "token": "tok_t_body" }, "heading_level": 3 },
      "size": { "w": { "kind": "hug" }, "h": { "kind": "hug" } },
      "status": "partial",
      "inference": {
        "structure": { "method": "tree.build/1", "calibration": "heuristic", "basis": "evidence", "confidence": 0.9, "supports": ["evd_6"] },
        "layout": { "method": "layout.size/1", "calibration": "heuristic", "basis": "default", "confidence": 0.6, "supports": [] },
        "style": { "method": "style.text/1", "calibration": "heuristic", "basis": "evidence", "confidence": 0.9, "supports": ["evd_17"] } } }
  },

  "realizations": {
    "scr_d": {
      "inference": { "method": "realize.match/1", "calibration": "heuristic", "basis": "evidence", "confidence": 0.95, "supports": ["evd_19", "evd_4"] },
      "nodes": {
        "nd_root": { "regions": ["reg_d_root"] }, "nd_hero": { "regions": ["reg_d_hero"] },
        "nd_h1": { "regions": ["reg_d_h1"] }, "nd_himg": { "regions": ["reg_d_himg"] },
        "nd_grid": { "regions": ["reg_d_grid"] }, "nd_c1": { "regions": ["reg_d_c1"] },
        "nd_c2": { "regions": ["reg_d_c2"] }, "nd_c3": { "regions": ["reg_d_c3"] }
      }
    },
    "scr_m": {
      "inference": { "method": "realize.match/1", "calibration": "heuristic", "basis": "evidence", "confidence": 0.88, "supports": ["evd_2", "evd_5"] },
      "nodes": {
        "nd_root": { "regions": ["reg_m_root"] }, "nd_hero": { "regions": ["reg_m_hero"] },
        "nd_h1": { "regions": ["reg_m_h1"] }, "nd_himg": { "regions": ["reg_m_himg"] },
        "nd_grid": { "regions": ["reg_m_grid"] }, "nd_c1": { "regions": ["reg_m_c1"] },
        "nd_c2": { "regions": ["reg_m_c2"] }, "nd_c3": { "regions": ["reg_m_c3"] }
      }
    }
  },

  "components": {
    "cmp_card": { "id": "cmp_card", "name": "ProductCard", "name_source": "inferred", "category": "ui",
      "root": "nd_card_root",
      "params": { "title": { "type": "text", "required": true, "bind": { "node": "nd_card_title", "field": "text.content" } },
                  "image": { "type": "asset", "required": true, "bind": { "node": "nd_card_img", "field": "media.asset" } } },
      "slots": {}, "variants": { "axes": [], "patches": {} },
      "inference": { "method": "component.cluster/1", "calibration": "heuristic", "basis": "evidence", "confidence": 0.94, "supports": ["evd_4", "evd_5"] } }
  },

  "tokens": {
    "color": {
      "tok_bg": { "id": "tok_bg", "name": "color/background", "name_source": "inferred",
        "by_mode": { "mode_light": { "value": { "space": "srgb", "hex": "#FFFFFF", "alpha": 1 }, "supports": ["evd_12"] },
                     "mode_dark":  { "value": { "space": "srgb", "hex": "#0B1020", "alpha": 1 }, "supports": ["evd_13"] } },
        "inference": {
          "value": { "method": "token.mode_merge/1", "calibration": "heuristic", "basis": "evidence", "confidence": 0.85, "supports": ["evd_12", "evd_13"] },
          "role": { "method": "token.role/1", "calibration": "heuristic", "basis": "evidence", "confidence": 0.9, "supports": ["evd_12", "evd_13"] } } },
      "tok_text": { "id": "tok_text", "name": "color/text", "name_source": "inferred",
        "by_mode": { "mode_light": { "value": { "space": "srgb", "hex": "#111827", "alpha": 1 }, "supports": ["evd_12"] },
                     "mode_dark":  { "value": { "space": "srgb", "hex": "#F3F4F6", "alpha": 1 }, "supports": ["evd_13"] } },
        "inference": {
          "value": { "method": "token.mode_merge/1", "calibration": "heuristic", "basis": "evidence", "confidence": 0.85, "supports": ["evd_12", "evd_13"] },
          "role": { "method": "token.role/1", "calibration": "heuristic", "basis": "evidence", "confidence": 0.85, "supports": ["evd_12", "evd_13"] } } },
      "tok_border": { "id": "tok_border", "name": "color/border", "name_source": "inferred",
        "by_mode": { "mode_light": { "value": { "space": "srgb", "hex": "#E5E7EB", "alpha": 1 }, "supports": ["evd_12"] },
                     "mode_dark":  { "value": { "space": "srgb", "hex": "#2A3350", "alpha": 1 }, "supports": ["evd_13"] } },
        "inference": {
          "value": { "method": "token.mode_merge/1", "calibration": "heuristic", "basis": "evidence", "confidence": 0.8, "supports": ["evd_12", "evd_13"] },
          "role": { "method": "token.role/1", "calibration": "heuristic", "basis": "evidence", "confidence": 0.75, "supports": ["evd_12", "evd_13"] } } }
    },
    "type": {
      "tok_t_h1": { "id": "tok_t_h1", "name": "type/heading-1", "name_source": "inferred",
        "value": { "family": { "generic": "sans", "candidates": [], "status": "guessed" }, "size": { "px": 48 }, "weight": 700,
                   "italic": false, "line_height": { "ratio": 1.15 }, "color": { "token": "tok_text" } },
        "inference": { "value": { "method": "token.type/1", "calibration": "heuristic", "basis": "evidence", "confidence": 0.85, "supports": ["evd_17"] } } },
      "tok_t_body": { "id": "tok_t_body", "name": "type/body", "name_source": "inferred",
        "value": { "family": { "generic": "sans", "candidates": [], "status": "guessed" }, "size": { "px": 16 }, "weight": 400,
                   "italic": false, "line_height": { "ratio": 1.5 }, "color": { "token": "tok_text" } },
        "inference": { "value": { "method": "token.type/1", "calibration": "heuristic", "basis": "evidence", "confidence": 0.85, "supports": ["evd_17"] } } }
    },
    "space": {
      "tok_s2": { "id": "tok_s2", "name": "space/2", "name_source": "inferred", "value": { "px": 8 },
        "inference": { "value": { "method": "token.scale/1", "calibration": "heuristic", "basis": "evidence", "confidence": 0.9, "supports": ["evd_16"] } } },
      "tok_s4": { "id": "tok_s4", "name": "space/4", "name_source": "inferred", "value": { "px": 16 },
        "inference": { "value": { "method": "token.scale/1", "calibration": "heuristic", "basis": "evidence", "confidence": 0.9, "supports": ["evd_16"] } } },
      "tok_s6": { "id": "tok_s6", "name": "space/6", "name_source": "inferred", "value": { "px": 24 },
        "inference": { "value": { "method": "token.scale/1", "calibration": "heuristic", "basis": "evidence", "confidence": 0.9, "supports": ["evd_16"] } } }
    },
    "radius": {
      "tok_r_md": { "id": "tok_r_md", "name": "radius/md", "name_source": "inferred", "value": { "px": 8 },
        "inference": { "value": { "method": "token.scale/1", "calibration": "heuristic", "basis": "evidence", "confidence": 0.85, "supports": ["evd_18"] } } }
    },
    "scales": { "space": ["tok_s2", "tok_s4", "tok_s6"] }
  },

  "assets": {
    "ast_hero": { "id": "ast_hero", "kind": "raster", "provenance": "extracted",
      "content": { "ref": "blob:sha256:example-hero", "media_type": "image/png", "intrinsic": { "w": 560, "h": 373 } },
      "origin": { "region": "reg_d_himg", "fidelity": "pixel_crop", "resolution_scale": 1.0, "lossy": true },
      "hint": { "aspect": 1.5, "dominant_color": { "space": "srgb", "hex": "#9DB4D8", "alpha": 1 }, "supports": ["evd_8"] },
      "rights_status": "unknown",
      "inference": { "method": "asset.classify/1", "calibration": "heuristic", "basis": "evidence", "confidence": 0.85, "supports": ["evd_8"] } },
    "ast_card_ph": { "id": "ast_card_ph", "kind": "raster", "provenance": "placeholder",
      "placeholder": { "reason": "not_separable", "kind": "flat" },
      "hint": { "aspect": 1.333, "dominant_color": { "space": "srgb", "hex": "#C9CED6", "alpha": 1 }, "supports": ["evd_9"] },
      "rights_status": "not_applicable",
      "inference": { "method": "asset.classify/1", "calibration": "heuristic", "basis": "evidence", "confidence": 0.8, "supports": ["evd_9"] } }
  },

  "relations": [],
  "disputes": [
    { "id": "dsp_1", "target": "nd_c2", "field": "instance.params.title", "kind": "text",
      "selected": { "value": "Linen shirt" },
      "alternatives": [ { "value": "Linen shirl", "producers": ["prd_ocr_a"], "supports": ["evd_6"] } ],
      "resolution": "weighted_vote", "status": "contested" }
  ],
  "redactions": {},
  "lineage": { "tombstones": [], "counter": 0, "migrated_from": [], "repairs": [] }
}
```

What the example demonstrates
- Epistemic separation: regions and evidence (measured or reported) are disjoint from nodes and tokens (inferred). Pixel rectangles appear only in `regions`; `size.fixed 560` is an inferred intent supported by `evd_8`, not a measurement.
- Bridge: `realizations` connect nodes to regions per screen; the same node realized on two screens is the cross-screen correspondence.
- Reported versus inferred text: two OCR readings (`evd_6`, `evd_7`) disagree for one card; the node holds one accepted value, `status: uncertain`, one alternative, and a dispute.
- Honest defaults: `basis: default` records (two layout size claims, the breakpoint) with empty `supports`, which makes affected nodes `partial` and appears in the quality report.
- Theme modes: tokens with per-mode values supported by evidence from the screen resolved to that mode, no synthesized values.
- Responsive intent: base tree plus three patches; the breakpoint is an interval with a selected value.
- Provenance and rights: an extracted asset with `rights_status: unknown` beside a placeholder with a `hint`.

---

## 21. One IR, several generators

Illustrative lowering of `nd_grid`, `rs_3`, and the token modes. These snippets are hand-written to show the IR/generator boundary; no generator exists yet and this is not generated output.

Every generator reads: `layout.grid`, `repeat`, `cmp_card`, `tokens` (including `by_mode`), `responsive` (`bp_1.selected = 768`), `ast_card_ph`, `ast_hero`, `rights_status`, `instance.params`. Every generator reports: uncertain text ("Linen shirt"), placeholders, unknown-rights assets, and any `navigates_to` relations with their status.

HTML/CSS target (static; mobile-first is this generator's choice; the theme-selection mechanism is a plan decision, shown here as a system preference only as an example):
```html
<section class="grid">
  <article class="card"><div class="ph" data-placeholder></div><h3>Canvas tote</h3></article>
  <!-- repeated; count_semantics=dynamic lowered to static markup here -->
</section>
```
```css
:root { --space-6: 24px; --color-bg: #FFFFFF; --color-border: #E5E7EB; }
@media (prefers-color-scheme: dark) { :root { --color-bg: #0B1020; --color-border: #2A3350; } }
.grid { display: grid; grid-template-columns: minmax(0, 1fr); gap: var(--space-6); }
@media (min-width: 768px) { .grid { grid-template-columns: repeat(3, minmax(0, 1fr)); } }
.ph { aspect-ratio: 1.333; background: #C9CED6; }   /* placeholder: shape and color only */
```

React target (same IR; the dynamic collection becomes data-mapped; tokens become a theme object):
```tsx
export function ProductCard({ title, image }: ProductCardProps) { /* from cmp_card */ }
const items = [{ title: "Canvas tote" } /* sample data from observed params */];
<section className={styles.grid}>{items.map(i => <ProductCard key={i.title} {...i} />)}</section>
```

Next.js target (same component; differences come from the generation plan):
- Same `ProductCard`; the page file location and name come from the plan (the IR has no route).
- Image handling and client/server boundaries are plan decisions. `ast_card_ph` still renders as a labelled placeholder.
- Under `strict` export policy, `ast_hero` would be replaced by a placeholder drawn from its `hint`; under `default` it is included with a warning; the provenance manifest is emitted in every case.

What differed between targets was never in the IR: file names, class-name strategy, `key` props, `use client`, media-query direction, theme-selection mechanism, import paths. What stayed identical: grid intent, the 3-to-1 change at the selected 768 threshold, component boundaries, tokens and their per-mode values, provenance and rights labels, and the uncertain-text report entry.

---

## 22. Open items and Phase 1 obligations

Phase 1 obligations (not started): generate and commit the JSON Schema; implement validator L0-L3 including R-EPI-1..9; migration harness; add section 20's example as a golden fixture and validate it; write `IR_LAYOUT_SEMANTICS.md` and a reference layout evaluator for `resolve()` checks (a 1.0 gate); determinism test (same artifacts twice, equal `content_hash`); redaction audit test (every scrubbed path listed).

Open items (none blocks writing the next document):
1. Mode pairing when a screen differs in both mode and viewport (as in the example): is `token.mode_merge` allowed on such evidence, or must it require same-viewport pairs? Currently allowed with a recorded method and at least 2 nodes.
2. Whether `evidenced` navigation may ever be emitted by default. Currently only on an explicit plan policy.
3. Region shape: rectangles only in 0.x; masks and polygons stay in artifacts.
