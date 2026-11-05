> Maintainer notes from development. The release state is in RELEASE_NOTES.md and docs/STATUS.md; test counts below are historical.

> **Historical engineering handoff (October 2026).** This is a point-in-time development log and contains outdated test counts and task statuses. Do not use it as the current release-status document. Use [STATUS.md](STATUS.md) for current verified state.

# HANDOFF: state of Screen2Code for the next engineer (or the next Claude session)

Written at the end of a long session. Everything below was checked against the repository, not remembered. Authoritative companions: `docs/STATUS.md` (what exists),
`docs/ADR-0002-implementation.md` (deviations), `docs/IR_SPEC.md` (the contract). The mission text that drives the remaining work is in `NEXT_SESSION_PROMPT.md` (zip root).

## 1. Where everything is

- Repository: this directory (git history included; `git log --oneline`). Python package `src/screen2code/{ir,core,vision,reconstruction,generation,rendering,evaluation,bench,cli,server}`, plus
  `api.py` and `benchmark.py` (composition level). Tests in `tests/` (unittest, 132 tests, ~75 s). Benchmark baseline in `benchmarks/baselines/`.
- Verified state of the last commit plus the uncommitted/WIP tree: **132 tests pass, 0 skipped** (`python -W error::ResourceWarning -m unittest discover -s tests -t .`).

## 2. What is done and verified

IR + validator + canonical form; core; perception (classical CV + Tesseract); structure; tokens; shared components (cross-page, strict under-merge); HTML/CSS and React generation
(React verified by server-side rendering in tests only); Tier-0 Chromium rendering; visual evaluation; synthetic benchmark (8-scene smoke tier measured, deterministic); CLI; Python API;
JSON-RPC sidecar (`screen2code serve`); **refinement loop** (`Project.refine`, `screen2code refine`, `evaluation/refine.py`, `tests/test_refine.py`): composite 0.736 -> 0.959 on a deliberately
perturbed fixture, deterministic, bounded, traceable, never changes the committed IR without `--apply`.

## 3. Work in progress: multi-screen reconciliation (NOT finished, no tests yet)

Files: `src/screen2code/reconstruction/reconcile.py` (new), plus edits in `api.py` (reconstruct now calls `reconcile`, writes `ir/reconciliation.json`; `Project.import_manifest`),
`cli/main.py` (`import --page/--manifest`), `reconstruction/system.py` (token cluster/near-miss reports, components skip responsively patched subtrees, component near-miss report),
`generation/html.py` + `react.py` (responsive patches lowered to `@media`; `justify-content` now always explicit), `structure.py` (declared `viewport_width`/`page_hint` origins).
Fixtures: `tests/fixtures/site/{home.html,products.html,contact.html}` and rendered PNGs `home-1000, home-480, products-1000, contact-1000` (authored by us; Home is responsive: header stacks,
3-column grid becomes 1 column, heading shrinks; Products shares header/footer/cards, has a slightly different button colour #3060ea vs #2f5bea, and a "featured" card that is similar but
different; Contact is unrelated).

Design (as implemented): screens are related ONLY when declared with the same page hint (`--page`, manifest `page`, or `page_hint`). Within a group the widest screen is the base; other widths are
matched to it by order-preserving tree correspondence (text similarity, image kinds, box structure). If confidence >= 0.7, the other screen has no extra content, and every difference is expressible by
whitelisted patches (`set`/`hide`), the screens are unified into one page with viewport classes, a breakpoint recorded as an interval + selected value + basis (never as observed), and responsive
rules. Otherwise they stay separate pages linked by a `possible_responsive_variant_of` relation, and the reasons go into `ir/reconciliation.json`.

**Current blocker (diagnosed, not fixed):** `Project(site).reconstruct()` on the fixtures returns decision `separate` for Home (correspondence 0.571, 6 unmatched leaves in the narrow screenshot). Most likely cause:
the gestalt `group` wrappers (S1 `_group_children`) differ between widths: desktop has a `group` wrapping the three cards (a row), the narrow screenshot stacks the cards directly under the root, so the
order-preserving matcher cannot align them. Debug first with `correspond(base, other)['mapping']` and print both trees *before* `infer_components` (they are shown after components in the project IR).
Suggested fix: treat `group` nodes as transparent during matching, and when a base group maps to a run of siblings in the other tree, synthesize a group there (layout: vertical stack of the same
children) and express grid(3 cols) -> 1 column as a `layout.grid.columns` patch (a one-track grid is equivalent to a stack; IR_SPEC 8.1 canonicalization says single-track grids "SHOULD" normalise to stack,
so decide the representation and test it). If correspondence still cannot be established, the fallback (separate pages + relation + reasons) is the correct honest behaviour; keep it.

Still to do for Phase 1: tests (shared identity across pages, deliberate inconsistencies reported, similar-but-different card NOT merged, unrelated page not merged, deterministic IR hash, per-page differences
preserved, unified Home renders at 1000 and 480 with sane metrics); theme pairing only if evidence supports it (not implemented; do not invent switching behaviour); responsive patch values currently hold
literals/px (token inference does not rewrite them); `infer_components` deliberately skips subtrees touched by responsive patches (document or model component-level variants).

## 4. Not started (from the mission)

- **Desktop app (Tauri 2 + React + TS).** No Rust toolchain and no network here, so a native build is impossible; do NOT claim one. Feasible and valuable: write the React/TS UI against the real
  sidecar protocol (`docs/ARCHITECTURE.md` section 6; server in `src/screen2code/server/main.py`; methods: initialize, project.create/open, import.images, analysis.start (+progress notifications, `$/cancel`),
  ir.get, generate.run, render.run, compare.get, models.list, settings.get; a `refine` method still has to be added). Bundle with the `esbuild` binary that ships inside the global `tsx` install
  (`$(npm root -g)/tsx/node_modules/esbuild/bin/esbuild`) against the global `react`/`react-dom` (v19). Real integration test without Tauri: load the bundle in Playwright and use
  `page.expose_function` to bridge the UI's transport to a real `screen2code serve` subprocess (no network listener). Add a Tauri scaffold (`src-tauri`: Cargo.toml, tauri.conf.json, main.rs that spawns the sidecar
  and forwards JSON-RPC) clearly labelled "not built here". No `@types/react` offline: type-check is limited; say so.
- **Next.js target**, **redaction mode** (IR schema/validator support it; nothing produces redactions), **navigation inference** (schema only), expanded benchmark (standard/full tiers exist but only smoke was
  run; add long-text/dense/responsive categories, baseline compare + regression thresholds from observed variance), static analysis (no ruff/mypy offline: at least `python -m compileall` and the architecture test),
  Windows CI (workflow exists, never executed), clean-install verification (done once for the wheel), docs alignment.

## 5. Environment facts that cost time (read before running anything)

- `/bin/sh` is dash: no brace expansion, no `${var//a/b}`. Use `bash -c` or Python for file generation.
- `pip install` is blocked (PEP 668, and there is no network). Use: `python3 -m venv --system-site-packages .venv && . .venv/bin/activate && pip install -e . --no-build-isolation --no-deps`.
- Run tests with `PYTHONPATH=$PWD/src PLAYWRIGHT_BROWSERS_PATH=/opt/pw-browsers`. Chromium is at `/opt/pw-browsers`. The sandbox cannot start (root in a container), so rendering **fails closed**; tests and demos pass the explicit
  opt-in (`render.allow_no_sandbox`, CLI `--allow-no-sandbox`). Never silently disable the sandbox; always state when it was waived.
- Tesseract 5.3 (eng) is installed. Fonts are system fonts (Liberation/DejaVu); render records hash the resolved font files.
- `/home/claude` can be empty in a new session; restore from this zip. After copying, run `git config --global --add safe.directory <path>`.
- `tests/helpers.py` skips nothing silently: tests needing OCR/Chromium use `needs_ocr`/`needs_browser` (explicit reasons).

## 6. Design facts worth knowing

- Observed vs inferred is enforced structurally (IR_SPEC section 2; validator R-EPI-1..9). Inference code must never mutate evidence (a bug that did exactly that was caught by a test; S5 now copies).
- Text geometry uses a *typographic cell* (`vision/typography.py`): content-independent line boxes. Needed for stable tokens/components; costs some pixel fidelity (numbers in `docs/STATUS.md`).
- Component-internal observations are kept as realizations keyed `<instance id>/<definition node id>`; the validator and metrics understand them.
- Refinement only edits numeric intent (margin, padding, line height, fixed image width) from measured rendered-vs-observed box errors; asserted values are untouchable; evidence it adds is `layout_residual`
  (allowed to support layout and style claims).
- Benchmarks: `screen2code benchmark --tier smoke --seed 1 --repeat-check`; baseline in `benchmarks/baselines/`. Numbers are synthetic and from 8 scenes; do not generalise them.

## 7. Quick verification commands

```bash
. .venv/bin/activate && export PYTHONPATH=$PWD/src PLAYWRIGHT_BROWSERS_PATH=/opt/pw-browsers
python -W error::ResourceWarning -m unittest discover -s tests -t .          # 164 tests
python -m screen2code.ir.schema | diff - schema/ir-0.1.schema.json            # schema in sync
screen2code --allow-no-sandbox run tests/fixtures/landing.png --project /tmp/demo.s2c
screen2code --allow-no-sandbox refine /tmp/demo.s2c --max-iterations 3
```

## 8. Update (latest session)

**Done and verified (164 tests):**
- Multi-screen: `reconcile._align` folds a base grid/stack wrapper onto a run of sibling nodes (strict: same child count, every child matches); `_fold_nodes`/`_fold_spacing` build an explicit inferred wrapper on a *copy*
  of the other doc. Home 1000+480 unifies into one page (6 patches, breakpoint [480,1000] `convention_snap`). Fallback verified. Report now lists `skipped_responsive`. Tests: `tests/test_multiscreen.py`.
- Sidecar: `project.status`, `reconcile.get`, `source.image`, `artifact.read` (confined), `refine.run`, `refine.list`; parameter validation; `generate.run` output confined to the project; settings/errors scrubbed.
  Tests in `tests/test_server.py` (`UiMethodTests`).
- Desktop UI: `ui/` (React + TS, bundled by `scripts/build_ui.py` with esbuild). `tests/test_ui.py` runs the built bundle in Chromium against a REAL sidecar subprocess (the harness replaces only the Tauri shell).
  Views: project/import/analyze (progress, cancel), regions overlay, inspector with provenance, design system + reconciliation decisions, generate (files shown as text only), render+evaluate (4 image tabs, metrics,
  sandbox state), refine (history, compare), reports, settings (explicit sandbox waiver).
- Redaction (`privacy.redact_text`, off by default): post-inference, records per IR_SPEC section 16, evidence built from placeholders, profile hash in `inference_config`, leak test over IR/ir/exports, counted evaluation exclusion.

**UNVERIFIED / not done:**
- `src-tauri/` (Cargo.toml, tauri.conf.json, main.rs) was written without a Rust toolchain and has never been compiled. `ui/src/host.js` is its only JS glue. No signed Windows sidecar build exists.
- `ui/src/App.tsx` is not type-checked (no `@types/react` here); only `rpc.ts` is (`tsc -p ui`). The UI has one end-to-end test, not per-view tests, and no visual/screenshot review.
- Redaction scope: recognized TEXT only. The source screenshot and extracted raster assets stay on disk (`artifacts: retained`); pixel masking (`pre_perception`) is not implemented. Redaction does not make a project safe to share.
  There is no UI toggle or CLI flag yet (config/override `privacy.redact_text` only).
- Header/footer on Home are not componentized across pages (responsive-patched subtrees are skipped, now reported). Contact scores low (composite 0.60, layout IoU 0.27), uninvestigated.

**Still to do, ranked:** (1) compile and run the Tauri shell on Windows; (2) benchmark corpus extension with multi-seed variance and baseline versioning; (3) Next.js target; (4) CI that matches this repo and
a clean-install check of the wheel; (5) redaction toggle in UI/CLI and pre-perception masking.
