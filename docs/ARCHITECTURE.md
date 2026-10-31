# ARCHITECTURE: system structure and contracts

> **Implementation status:** this is a design document. For what is actually implemented, measured, and different, see [STATUS.md](STATUS.md) and [ADR-0002](ADR-0002-implementation.md); they take precedence where they differ.

Status: Draft. Depends on: ADR-0001 (D1, D2/A2, D6/A3), IR_SPEC.md r2, PIPELINE.md, MODEL_STRATEGY.md, EVALUATION.md, GENERATION.md, SECURITY.md.
This document defines structure, dependency rules, and cross-cutting contracts. It does not repeat the specifications it references.

## 1. Context and shape

```
 Desktop (Tauri 2 + React + TS) ---- JSON-RPC over stdio ----+
 CLI --------------------------------------------------------+--> Core engine (Python 3.11+)
 Python API (screen2code.api) -------------------------------+        |
                                                                      +- Perception  (S1-S4)
                                                                      +- Reconstruction (S5-S9)
                                                                      +- Generation (S11-S12)
                                                                      +- Rendering + Evaluation (S13-S15)
                                                                      +- IR (schema, validator, migrations)
```
- Local application and developer tool. No services, no microservices, no database in the MVP.
- The UI contains no business logic; the core does not depend on the UI; the CLI and the desktop call the same core API (product spec section 6).

## 2. Packages (a package exists only when it contains code)

| Package | Responsibility | Depends on | First phase |
|---|---|---|---|
| `ir` | JSON Schema, models, validator (L0-L3), canonical serialization, migrations, content hash, ID derivation | none | 1 |
| `core` | `Workspace`, project storage, artifact store, config, stage runner, refinement loop controller (runs registered stages S11-S14 by name), provider registry, model manager, error model, public API (`screen2code.api`), plugin loading | `ir` | 1 |
| `cli` | command-line interface (section 7) | `core` and the engine packages (composition root) | 1 |
| `vision` | S1-S4 classical perception, OCR adapters | `core`, `ir` | 2 |
| `reconstruction` | S5-S9 | `core`, `ir` | 2 |
| `generation` | planner, adapters, project builder | `core`, `ir` | 2 |
| `rendering` | Tier 0 renderer (Playwright/Chromium), font set | `core` | 2 |
| `evaluation` | metrics, reports, refinement patch rules (the pure `report + IR -> patches` step of S15) | `core`, `ir` | 2 |
| `server` | JSON-RPC server for the desktop | `core` and engine packages | 5 |
| `apps/desktop` | Tauri + React application | `server` (via process) | 5 |
Notes
- A separate `python-api` package is not created: the public Python API is `core`'s `screen2code.api` facade, re-exported by the umbrella distribution when it ships. This is the justified adaptation of the product spec's sketch structure.
- Dependency graph is acyclic: `ir` <- `core` <- {`vision`, `reconstruction`, `generation`, `rendering`, `evaluation`} <- {`cli`, `server`}. `evaluation` and `generation` exchange data through records on disk (render records, plans), not imports of each other. The composition root (`cli`/`server`/`api` entry) registers stages and adapters with `core`; `core` never imports engine packages.

## 3. Dependency rules
- DR-1. Nothing imports `apps/desktop`. Nothing in the engine imports a UI or RPC type.
- DR-2. Only `ir` knows the IR schema details; other packages use its models and validator.
- DR-3. Packaging and signing code (`tools/packaging`) is never imported by the engine (section 10).
- DR-4. Providers, adapters, metrics, renderers, storage backends, and exporters are reached through the interfaces in section 9, never by direct import across package boundaries.
- DR-5. Observed and inferred separation (IR_SPEC section 2) is enforced in the runner: a stage's `ir_patch` is validated to touch only the sections its phase permits (S1-S4: observed sections; S5+: structure/design-system sections).

## 4. Workspace and storage
```
<project>/
  project.toml                # settings: providers, policies, redaction profile, paths
  ir/working.ir.json  ir/project.ir.json
  assets/                     # content-addressed asset bytes
  artifacts/                  # normalized images, perception artifacts (content-addressed)
  cache/                      # provider output cache (keyed per PIPELINE P-4)
  plans/<hash>.plan.json
  renders/  evaluations/  runs/<id>/  exports/
  .lock                       # single-writer lock
```
- Filesystem only. `ArtifactStore` and `Storage` are Protocols so another backend can replace them later; no second backend is built now.
- Writes are atomic (`os.replace`) and confined by `Workspace` (SECURITY section 3). One writer per project; readers do not take the lock.
- The models directory and the browser directory are managed outside projects (MODEL_STRATEGY section 4).

## 5. Public Python API (design contract)

Principles: explicit objects, immutable results, synchronous with progress listeners and a cancellation token (async variant deferred), typed errors (section 8), no hidden global state, all paths via `Workspace`.

```
Project.create(path, settings) / Project.open(path)
project.import_images(paths | dir, manifest=None) -> list[ScreenRef]
project.analyze(options, listener=None, cancel=None) -> AnalysisResult        # S0-S6
project.reconstruct(options, listener=None, cancel=None) -> CommitResult      # S0-S10
project.generate(target, plan=None) -> GenerationResult                       # S11-S12
project.render(options) -> RenderResult                                       # S13 (Tier 0)
project.evaluate(reference=None, generated=None) -> EvaluationReport          # S14
project.refine(options) -> RefineResult                                       # S15 (Phase 4)
project.export(destination, policies) -> ExportResult
project.ir -> read-only validated view of the committed IR
```
This is a contract, not an implementation. Stability: `0.x` is unstable; compatibility promises begin at 1.0 together with IR 1.0.

## 6. Desktop RPC
- JSON-RPC 2.0 over stdio with `Content-Length` framing (UTF-8). The Tauri shell supervises one sidecar process per app instance. No network listener.
- Handshake `initialize { rpc_version, client }` returns server version and capabilities; incompatible versions fail clearly.
- Methods (grouped): `project.*`, `import.*`, `analysis.start|cancel`, `ir.get|query`, `edit.apply|undo|redo`, `compare.get`, `generate.run`, `export.run`, `models.*`, `settings.*`. Notifications: `progress`, `diagnostic`, `project.changed`. Cancellation by request ID.
- Binary payloads (images, artifacts) move by workspace path and the custom file protocol (confined to the project directory), never inside messages.
- The command surface is minimal and validated; unknown methods and oversized messages are rejected (SECURITY section 9).

## 7. CLI contract
Commands exist only when implemented; none are stubs.

| Command | Purpose | Phase |
|---|---|---|
| `ir validate <file>` / `ir migrate <file>` | validate or migrate an IR document | 1 |
| `doctor` | environment, models, browser, fonts, limits check | 1 |
| `models list|install|verify|remove` | model manager | 2 |
| `analyze <image|dir>` | S0-S6, produces a working IR | 2 |
| `reconstruct <image|dir>` | S0-S10 and commit | 2 (single), 3 (multi) |
| `generate <project> --target html|react|next` | S11-S12 | 2 (html), 3 (react/next) |
| `render <project>` | S13 (Tier 0) | 2 |
| `evaluate <reference> <generated>` | S14 | 2 |
| `refine <project>` | S15 | 4 |
| `benchmark [--tier smoke|standard|full]` | benchmark run (BENCHMARKS) | 2 |
Global flags: `--workspace`, `--config`, `--deterministic`, `--strict|--lenient`, `--json`, `--no-color`, `--allow-execute` (Tier 1 only, per invocation, SECURITY section 5).
Exit codes: 0 success; 1 general failure; 2 usage error; 3 IR validation failure; 4 provider or model unavailable; 5 input rejected (limits/security); 6 execution refused (consent or isolation missing); 130 cancelled.
`--json` emits one JSON document per command (events as JSON lines); suitable for CI. No interactive prompts when stdin is not a TTY.

## 8. Error model
```
S2CError { code: "S2C-<AREA>-<NNN>", category: input|provider|validation|security|io|internal,
           message, remedy, details? }
```
- Codes are stable and registered in one `core` registry; documentation of codes is generated from the registry (Phase 6).
- Stage failures, validation diagnostics (IR_SPEC section 17.3), and RPC errors all use this shape. Messages never include image content or OCR text by default.
- "Unavailable" and "degraded" are explicit states, never silent behavior (PIPELINE P-3).

## 9. Extension points and plugins
Interfaces (Python Protocols): `OCRProvider`, `VisionProvider`, `EmbeddingProvider`, `LanguageProvider`, `CodeGenerationProvider` (MODEL_STRATEGY section 2), `FrameworkAdapter` (GENERATION section 3), `Renderer`, `Metric` (EVALUATION section 2), `Exporter`, `ArtifactStore`/`Storage`, `Stage`.
- Discovery: Python entry-point groups `screen2code.providers`, `.adapters`, `.metrics`, `.exporters`, `.stages`, `.renderers`.
- A plugin declares id, version, supported `screen2code` range, capabilities, and license metadata. Plugins are disabled by default and enabled per plugin in settings. They are arbitrary code and therefore trusted-code (SECURITY section 8).
- A plugin cannot weaken the validator, the confined writer, or Tier 0 render restrictions.
- Plugin contribution of IR content must declare epistemic classes for any extension data (IR_SPEC section 4.4).

## 10. Packaging abstraction (amendment A2)
```
Packager { build(spec) -> BuildArtifact, sign(artifact, identity), verify(artifact) }
PackagerSpec { entry, include, exclude (always excludes model weights), layout: onedir }
```
- Initial implementation: a signed Windows `--onedir` sidecar via `PyInstallerPackager` in `tools/packaging/`. PyInstaller is an implementation detail behind the interface, not an architectural dependency; the engine never imports it.
- The Tauri build consumes only the `BuildArtifact` path. Replacing the packager (for example with Nuitka) changes only `tools/packaging/`.
- CI on Windows runs the packaged sidecar through `doctor` and a smoke `analyze`; every release records antivirus scan results and false-positive reports.
- Model weights are never part of a `BuildArtifact`; the browser binary is downloaded on demand into the managed directory.

## 11. Trust boundary (amendment A3)
The trust boundary is defined in SECURITY.md section 1 and is part of this architecture. Summary: imported images, model outputs, the IR derived from them, and all generated code are untrusted input. The core engine's validated and sanitized handling (decode limits, schema validation, IR validator, confined writer, generator escaping) is the only trusted code path between them. Generated code is never executed automatically; static HTML renders offline with JavaScript disabled (Tier 0); React/Next.js execution requires explicit user action and an isolated boundary, whose Windows mechanism is an open spike (SECURITY section 5.3). Nothing in this architecture presents it as solved.

## 12. Configuration
Layered TOML: built-in defaults < user settings (per-user config dir) < `project.toml` < CLI flags or API arguments. The effective configuration is recorded in the run record, thresholds in `inference_config`, and providers in `producers`. Secrets are never configuration values (SECURITY section 7).

## 13. Observability and performance
- Structured JSON-lines logs per run (`runs/<id>/log.jsonl`) without image or OCR content by default.
- Measurements per EVALUATION section 7: startup, analysis, generation, rendering, evaluation time; peak RAM; accelerator memory where available. A `--profile` flag adds per-stage timings to the report.
- Caching: provider results and expensive artifacts by content-addressed keys; incremental analysis by stage cache keys (PIPELINE section 7).

## 14. Testing architecture
| Layer | What | Where defined |
|---|---|---|
| Unit | geometry, IR, tokens, layout/component inference, generators, metrics | each package |
| Integration | complete pipeline on fixtures | `tests/` |
| Golden/visual | golden IR fixtures, golden file trees, visual regression with pinned renderer | GENERATION section 9, EVALUATION |
| Generator conformance | every adapter passes one shared suite | GENERATION section 9 |
| CLI | exit codes, JSON output, non-interactive behavior | `tests/cli` |
| Desktop | critical user flows on the packaged app | DESKTOP_UX section 2 |
| Security | SECURITY section 9 | `tests/security` |
| Benchmarks | BENCHMARKS tiers | `benchmarks/` |
CI runs on Windows (tier-1) and Linux; steps: lint, type check, unit, schema-drift check, golden, security, smoke benchmark with determinism check, license audit.

## 15. Repository structure (created as code arrives)
```
screen2code/
  packages/{ir,core,cli,vision,reconstruction,generation,rendering,evaluation,server}/
  apps/desktop/                 # Phase 5
  benchmarks/                   # Phase 2
  tools/packaging/              # spike in Phase 1, product in Phase 6
  docs/  tests/  examples/ (when real)  scripts/  .github/
  pyproject.toml (workspace)  package.json (desktop only)
  LICENSE (MIT)  README.md  CONTRIBUTING.md  SECURITY.md  CODE_OF_CONDUCT.md  CHANGELOG.md
```
Directories are not created empty. Open-source hygiene files (issue and PR templates, roadmap link, release workflow) arrive with the phase that needs them (ROADMAP.md).
