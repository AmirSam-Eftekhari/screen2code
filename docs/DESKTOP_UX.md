> **Implementation status:** this document is the design. Implemented: a React + TypeScript web bundle (`ui/`) with project/import/analyze, regions overlay, inspector with provenance, design system and reconciliation view,
> generate, render and evaluate, refine, reports and settings, tested against the real sidecar. Not implemented from this design: Zustand store, native dialogs, credential-store bridge, custom file protocol, Vitest component tests,
> packaged-app tests. The Tauri shell is unverified (never compiled).

# DESKTOP_UX: the desktop application

> **Implementation status:** this is a design document. For what is actually implemented, measured, and different, see [STATUS.md](STATUS.md) and [ADR-0002](ADR-0002-implementation.md); they take precedence where they differ.

Status: Draft. Depends on: IR_SPEC.md r2 (section 2 for the observed/inferred display), PIPELINE.md (stage labels, events), EVALUATION.md (Compare), GENERATION.md (Export), SECURITY.md (sections 5, 7), ARCHITECTURE.md (RPC).

## 1. Principles
- U-1. The desktop contains no business logic. It displays and edits state held by the core engine through the RPC (ARCHITECTURE.md section 6).
- U-2. It shows only what the pipeline actually produced. No decorative or invented explanations.
- U-3. Observed and inferred information are visibly different everywhere they appear (IR_SPEC section 2).
- U-4. Serious engineering-tool feel: dark by default, clear hierarchy, subtle motion, no gratuitous gradients or glow.
- U-5. Honest states: partial, uncertain, unavailable, and experimental are labeled, never hidden.
- U-6. Edits are first-class and reversible (section 7).

## 2. Stack
Tauri 2 with a React + TypeScript frontend; the Rust layer is limited to window and process supervision, native dialogs, the credential-store bridge, and the custom file protocol. State: React with a small store (Zustand). Canvas: HTML/SVG overlays on image layers (no canvas framework in the MVP). WebView2 is the Windows web runtime dependency, checked at install. Component tests with Vitest and Testing Library; end-to-end tests drive the packaged app (tooling to be confirmed on Windows in Phase 5).

## 3. Information architecture (views)

| View | Purpose | MVP (Phase 5) |
|---|---|---|
| Home | New/Open project, Recent projects, Examples | yes |
| Import | drag and drop or browse; group screenshots into pages; name screens; set viewport width, device pixel ratio, mode; show detected vs declared values | yes |
| Analysis | stage progress using the PIPELINE stage names; cancel; per-stage diagnostics; resume | yes |
| Workspace | three regions: Pages/Components tree, Canvas, Inspector | yes (inspect + limited edit) |
| Compare | Reference, Generated, Overlay, Difference; metric panel | yes |
| Export | target, asset policy, navigation policy, theme mechanism, output directory | yes |
| Settings | models, providers, privacy, policies, appearance | yes |

## 4. Views in detail

### Import
- Auto-suggested grouping (PIPELINE section 8) is shown as a proposal with confidence; the user confirms or edits. Declared values are marked asserted; guessed values are marked inferred.
- Files are validated on drop (type, size, dimensions) with explicit rejection messages; no silent skipping.

### Analysis
Shows `Importing -> Reading regions -> Reading text -> Measuring -> Inferring layout -> Extracting assets -> (Reconciling screens -> Detecting components -> Building design system) -> Validating`. Each stage shows pending, running, done, degraded, or failed (PIPELINE section 3 events). Failure shows the stable error code, plain-language cause, and a remedy (for example "OCR model not installed: Install" with the license shown). There is no automatic fallback to another provider.

### Workspace
- Left: pages and components tree (with counts and status badges: partial, contested, stale).
- Center: the canvas with a layer switch: `Source` (screenshot with observed regions toggle) and `Reconstruction` (the static HTML preview in a sandboxed frame without script permission). Selecting a node highlights it in all places via the realization.
- Right: the Inspector.

### Inspector (mirrors IR_SPEC section 2)
For the selected node:
- Header: kind, role, name, status (resolved / partial / opaque).
- Observed: the realized regions on each screen (coordinates in source pixels) and the evidence records supporting it, labeled measured or reported, with producer names and raw scores marked as producer scores.
- Inferred: each facet (structure, role, layout, style, content) with its method, calibration class (calibrated / heuristic / asserted), basis, confidence, supports and against, and the resulting values (layout intent, size intent, tokens, text value with status and alternatives).
- Design system: component and instance details, token references with per-mode values, responsive patches affecting the node.
- Provenance for assets: extracted, reconstructed, or placeholder, `rights_status`, origin region.
- Relations and navigation: status shown as unknown, inferred, evidenced, or asserted; the UI never presents a non-asserted navigation as functional behavior.
- Disputes: selected value and alternatives, with a control to choose one.
Nothing is shown that is not in the IR or evidence chain.

### Compare
Four modes (Reference | Generated | Overlay with opacity slider | Difference heatmap). Side panel: metric vector (EVALUATION section 4), exclusions with counts, per-node error ranking; clicking an item selects the node. Per-viewport and per-mode switchers. Missing and unrendered elements are listed. Labels distinguish "static HTML rendering" from any other source; nothing claims React/Next output was rendered unless the isolation boundary exists.

### Export
Choose target (HTML/CSS; React and Next.js as generate-only until the isolation spike passes), style strategy, asset policy (default: include with warning), navigation policy (default: asserted only), theme mechanism, output directory (confined), instrumentation attributes (default stripped). Shows the pre-export report summary (uncertain text, placeholders, fallbacks, unknown-rights assets). An "Open in isolated build" action is present only when Tier 1 is available and always asks for confirmation (SECURITY section 5).

### Settings
- Models: installed models, install/verify/remove, license and checksum shown, license acceptance flow (MODEL_STRATEGY section 4).
- Providers: enable/disable; remote providers off by default with an explicit disclosure of what is sent; keys saved to the credential store.
- Privacy: redaction profile on/off with stage and artifact handling (IR_SPEC section 16); logging level; no telemetry.
- Policies: asset rights policy, navigation policy, placeholder text.
- Appearance: dark (default), light, reduced motion.

## 5. Empty, loading, and error states
- Empty: each view has a purposeful empty state with the next action (for example, Home with no projects offers Import and Examples).
- Loading: skeletons for lists; determinate progress for stages; never an indefinite spinner without a stage label.
- Errors: stable code, plain cause, remedy, "Copy diagnostics" (redacted of content by default), and a link to the log location.
- Sidecar crash: the app shows a recoverable error, restarts the sidecar, and reloads project state from disk; work in the working IR is preserved by atomic saves.
- Partial/uncertain IR: banners explain the state; actions (accept alternative, mark verified, re-run stage) are offered.

## 6. Live preview
Edits trigger regeneration of the static HTML target and a re-render (debounced). The preview frame has script permission disabled and loads only from the project directory through the custom protocol. The preview is an engineering aid, not a fidelity claim; metrics come from explicit evaluation runs.

## 7. Editing model
- Every edit becomes a user assertion: `asserted` structure with a `user_assertion` evidence record, preserved across re-analysis (IR_SPEC R-EPI-5, section 5).
- MVP edits: rename page/component/node labels; set screen grouping, viewport width, scale, mode; accept or choose text alternatives (marks `verified`); merge or split component clusters; pin or rename tokens; set declared rights for an asset; assert a navigation target; mark a region opaque or request re-analysis of a node.
- Undo/redo is a command stack over IR edits recorded in `lineage`; undo restores the prior committed state.
- The UI cannot produce an IR that fails L0-L2 validation: commands are validated by the core before acceptance.

## 8. Accessibility, performance, platform
- Full keyboard navigation, visible focus, AA contrast, resizable panels, high-DPI support.
- Virtualized lists and trees, lazy thumbnails, large images served by file path and tiled, never as base64.
- Windows is tier-1: signed installer, WebView2 check, per-user install, long-path safe file handling.

## 9. RPC surface used by the desktop (see ARCHITECTURE.md section 6)
`project.*`, `import.*`, `analysis.start|cancel`, `ir.get|query`, `edit.apply|undo|redo`, `compare.get`, `generate.run`, `export.run`, `models.*`, `settings.*`, plus notifications for progress and diagnostics. Binary data moves by workspace file path, not through messages.
