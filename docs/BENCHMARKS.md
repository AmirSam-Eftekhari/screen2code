# BENCHMARKS: reproducible measurement of Screen2Code

> **Implementation status:** this is a design document. For what is actually implemented, measured, and different, see [STATUS.md](STATUS.md) and [ADR-0002](ADR-0002-implementation.md); they take precedence where they differ.

Status: Draft. Depends on: ADR-0001 (D5, A1), IR_SPEC.md r2, EVALUATION.md (metrics, run record), PIPELINE.md (default thresholds).

## 1. Rules
- B-1. The primary benchmark is a reproducible synthetic/procedural corpus with known ground truth. Nothing in the benchmark system depends on any third-party dataset (amendment A1).
- B-2. Real-world licensed datasets (Design2Code and others) are secondary sources: optional, fetched by script, never vendored, never required for CI or for the benchmark to run.
- B-3. Every run records and pins the A1 set (section 5). A run missing any pin is invalid and is not publishable.
- B-4. No benchmark number appears in any document, README, or release note unless it came from a CI-reproducible run and cites the run ID. Until a baseline exists, docs say "not yet measured".
- B-5. Expected outputs are never hard-coded and no scene-specific coordinates exist in the product code (project quality bar).

## 2. Primary corpus: procedural synthetic scenes

### 2.1 What a scene is
A scene is a seeded, parametric description that is also the ground truth: an IR conforming to IR_SPEC (nodes, layout modes, tokens, components, modes, responsive patches, assets with known provenance) plus a rendering recipe. One scene yields many screenshots: viewports (for example 390, 768, 1440 wide), device scale factors (1, 2, 3), modes (light/dark where the scene defines them), and perturbation levels.

### 2.2 Categories (from the product spec)
landing pages, dashboards, SaaS interfaces, e-commerce, forms, mobile interfaces, dense applications, complex responsive layouts. Each category is a grammar: layout templates x component library x token set x content generator.

### 2.3 Difficulty axes (all recorded per sample)
JPEG quality, screenshot scale, anti-aliasing and font fallback differences, color jitter (controlled delta E), amount of overlaid text on images, density, nesting depth, presence of overlays, absolute-positioned decoration, theme modes, number of screens per project.

### 2.4 Avoiding circularity
The corpus is rendered by a separate emitter in `benchmarks/` that does not share code with the product's generation adapters, and it deliberately varies its CSS strategies (flex, grid, mixed) so the system cannot learn its own generator's idioms. Known limitation, stated in every report: synthetic scenes are cleaner and more regular than real sites, so synthetic results are not predictions of real-world performance; this is why secondary real-world sources exist.

### 2.5 Content
Text from a permissively licensed word list; images are procedural (gradients, noise, shapes) with known extractable vs non-extractable cases; fonts from the pinned open set. No third-party screenshots or brand assets are committed.

## 3. Secondary sources
- Registry file lists each dataset: name, version, license, terms URL, `usage_mode` (`evaluation_only` unless terms allow more), fetch script, content hash.
- Design2Code (484 real webpages, ODC-By, research-oriented) is the first candidate. Before use, its terms are checked for redistribution, evaluation, and training; it is evaluation-only by default.
- Secondary runs are labeled as such in all reports and are never mixed into primary aggregates. Real data has no ground-truth IR, so only visual metrics and manual spot checks apply there.

## 4. Metrics and baselines
- Metrics are defined in EVALUATION.md sections 4-5; this document selects which are headline: region detection, text error, layout accuracy, component accuracy, token accuracy, responsive and theme accuracy, visual metrics vector, code validity (HTML/CSS well-formedness; build success only in the CI isolation boundary), generation time, peak memory.
- Mandatory baselines in every report: (1) blank page; (2) a single `<img>` of the screenshot, which scores perfectly on pixel metrics and near zero on structure metrics, demonstrating why pixel metrics alone are insufficient; (3) rule-only (no learned providers) vs configured providers, to measure what models add.
- Aggregates use bootstrap confidence intervals across scenes and multiple seeds; reports show distributions, not only means.

## 5. Reproducibility and run validity

A benchmark run record (EVALUATION.md section 7) must contain at least:

| Pin | Content |
|---|---|
| dataset version | semver plus content hash of the scene manifest |
| seed | corpus seed(s) and run seed(s) |
| browser/renderer version | pinned Chromium revision and Playwright version |
| viewport | per sample |
| fonts | font set hash |
| model/provider configuration | provider ids, versions, config hashes, model ids with sha256 |
| dependency versions | lock file hash; Python and OS versions |
Also recorded: redaction profile hash and redacted-span counts (IR_SPEC section 16); runs with different redaction profiles are non-comparable and tooling flags them.
Validation rule: a run is valid only if every pin is present and the environment matches the pins ("matches" is checked, not trusted). A run that cannot meet the pins is labeled unpinned and excluded from published tables.
Determinism check: the same run repeated on the same pins must reproduce IR content hashes (given cached provider outputs, IR_SPEC D-5) and metric values within a documented tolerance; failure to reproduce is a bug report.

## 6. Tiers and cadence

| Tier | Contents (initial sizes) | When | Gate |
|---|---|---|---|
| smoke | ~10 scenes, one viewport each | every pull request | no regression beyond tolerance against the stored baseline run; determinism check |
| standard | ~200 scenes, multiple viewports and modes | nightly | trend tracking; alerts |
| full | ~2000 scenes, all axes | release candidates | release notes cite the run ID |
Sizes are initial and may change; they are recorded in the dataset manifest.
Regression gating compares to a stored baseline run produced under the same pins; changing pins requires a new baseline run, committed with its run ID.

## 7. Storage and layout
- Corpus generator and emitter live in `benchmarks/` (created in Phase 2 with the smoke tier; not before there is code to put in it).
- Scenes are generated, not stored: the repository holds the generator, manifests, and baseline run summaries. Generated images are cached outside git.
- Results go to `benchmarks/results/<run_id>/` (ignored by git) with a summary table committed only for published runs.
- Secondary dataset files are never stored in the repository.

## 8. Phase mapping
- Phase 2: smoke corpus, region/text/layout IR metrics, visual metrics, CLI `benchmark`.
- Phase 3: components, tokens, modes, responsive scenes and metrics; standard tier.
- Phase 4: refinement metrics (improvement per iteration), calibration reliability curves, full tier, secondary dataset (Design2Code) visual runs.
- Phase 6: public leaderboard-style report (optional), reproducibility docs.
