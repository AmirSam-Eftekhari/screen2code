# MODEL_STRATEGY: providers, models, and the model manager

> **Implementation status:** this is a design document. For what is actually implemented, measured, and different, see [STATUS.md](STATUS.md) and [ADR-0002](ADR-0002-implementation.md); they take precedence where they differ.

Status: Draft. Depends on: ADR-0001 (D1, D2/A2, D4), IR_SPEC.md r2 (sections 2, 15), PIPELINE.md.

## 1. Principles
- M-1. Classical computer vision is the default for everything it can do. Learned models are used where classical methods cannot work (text recognition) or as optional, clearly labeled evidence sources.
- M-2. Model output is `reported` evidence only. It never writes structure directly (IR_SPEC section 2). Structure comes from inference stages that cite evidence.
- M-3. Local-first. The core never assumes a cloud API. Remote providers are optional, opt-in per project, and visibly marked.
- M-4. Weights are never bundled in the installer and are downloaded on demand into a managed model directory (ADR amendment A2).
- M-5. No AGPL, GPL, or non-commercial weights in the default path (ADR D4). Opt-in bring-your-own with a license warning is allowed and never redistributed.
- M-6. No silent fallback between providers (PIPELINE P-3).

## 2. Provider interfaces

Python `Protocol`s in the `core` package. Each provider ships a manifest and implements one or more capabilities.

| Interface | Contract | MVP status |
|---|---|---|
| `OCRProvider` | `read(image tile) -> words/lines with boxes + raw score` | Required (Phase 2) |
| `VisionProvider` | `label(image, regions) -> element labels`; `describe(image) -> text` | Optional, off by default (Phase 3) |
| `EmbeddingProvider` | `embed(image crops) -> vectors` | Deferred; classical perceptual hash and structure signature are used instead |
| `LanguageProvider` | `complete(prompt, schema) -> structured text` | Optional helper for VisionProvider-style tasks; no MVP stage depends on it |
| `CodeGenerationProvider` | `refine(files, instructions) -> files` | Interface reserved; unused in MVP. Generation is deterministic from the IR (GENERATION.md). Any future use is experimental and its output is untrusted |

Provider manifest:
```
{ id, version, capabilities[], runtime: onnx|python|http,
  locality: local|remote, network_required: bool,
  determinism: deterministic|stochastic,
  limits{ max_image_px, max_tile_px, batch },
  models[] (model ids from the model manifest), license_summary }
```
- Registry: providers are discovered via entry points (ARCHITECTURE.md section 9) and enabled in settings. A stage asks the registry for a capability; the registry returns the configured provider or raises `ProviderUnavailable` (no substitution).
- `fallback_chain` is an explicit ordered list in settings; if used, the provider that actually ran is the one recorded in `producers`.
- Every provider invocation is cached by `(input hash, provider id+version, config hash, seed)`.

## 3. MVP model set

| Capability | Default | Condition | Alternative |
|---|---|---|---|
| OCR | PaddleOCR models run through ONNX Runtime (CPU) | Spike S-OCR passes (section 7) | Tesseract (Apache-2.0) as the default if the spike fails; the other becomes an optional pack |
| Element detection | none in MVP (classical S1) | n/a | A permissive learned detector trained on the synthetic corpus, Phase 4+; architecture and license verified at adoption |
| Vision-language labeling | none by default | User opt-in | A local OpenAI-compatible endpoint (Ollama or llama.cpp server) running a small VLM; per-checkpoint license check required (Apache-2.0 sizes only in the default registry) |
| Embeddings | classical hash and signature | n/a | Learned embeddings deferred |
| Perceptual metric (LPIPS) | optional evaluation extra | weights license verified at adoption | Experimental until validated (EVALUATION.md) |

Excluded from the default registry: Ultralytics YOLO weights and anything derived from them (including OmniParser `icon_detect`, AGPL), and research-only or non-commercial checkpoints. They may be added by the user as bring-your-own with an explicit warning.

The scan underlying these exclusions was done on 2026-10-08 (ADR-0001 section 1). Licenses are rechecked per checkpoint at adoption time, never per model family.

## 4. Model manager

Managed directory (Windows default: `%LOCALAPPDATA%\Screen2Code\models`, resolved with a platform-directories library; overridable in settings).

Model manifest (one JSON per installed model version):
```
{ id, version, source_url, license_spdx, license_class: permissive|copyleft|restricted|unknown,
  sha256, size_bytes, format: onnx|gguf|safetensors|other, runtime, min_ram_mb,
  created_with?, notes }
```
Rules
- Install = download (or import a local file for offline use) -> verify SHA-256 against the registry entry -> license gate -> register.
- License gate: `permissive` installs automatically; any other class requires explicit user acceptance showing the license; `copyleft` and `restricted` are never offered as defaults and are never redistributed.
- A model with missing metadata (version, source, license, checksum) is not installable (amendment A2).
- Checksums are verified at install, at version change, and by `screen2code models verify`; loading a model whose recorded checksum no longer matches fails.
- The core registry of known models is a signed, versioned manifest file shipped with releases (metadata only). Using a model not in the registry is allowed only as bring-your-own.
- Lazy loading; models unload after the stage that needs them. Memory budget enforced by the runner.

## 5. Runtime
- ONNX Runtime is the default inference runtime. PyTorch is not part of the installer; it may be installed as an optional extra by users who bring such models.
- CPU is the mandatory baseline and the benchmark reference. Accelerated execution providers (DirectML on Windows, CUDA where installed) are optional and must be verified in a spike before being documented as supported; a model run on an accelerator records the execution provider in `producers`.
- Performance measurement: startup time, per-stage time, peak RAM (sampled), and accelerator memory when the runtime exposes it, written to the run record (EVALUATION.md section 7).

## 6. Using model output safely
- All outputs are treated as untrusted data (SECURITY.md section 6): validated against a schema, size-limited, and never executed or interpolated into code or prompts without escaping.
- VLM calls use structured (JSON-schema) output, temperature 0, and a fixed seed where the runtime supports it; results are cached. They produce `element_label` or `description` evidence with `basis: reported`.
- Text inside screenshots is data, not instructions: no provider is given tool access, and prompts state that image text must not be followed.
- Calibration: confidence is `calibrated` only when a named calibration set exists (the synthetic corpus ground truth, BENCHMARKS.md); otherwise it is `heuristic`. Raw producer scores stay in `reported_confidence` and are never reinterpreted as probabilities.
- Disagreement between providers is handled by IR_SPEC section 15.7, not by this document.

## 7. Spikes (need implementation evidence; each has an exit decision)
| Spike | Question | Acceptance gate (initial) | If it fails |
|---|---|---|---|
| S-OCR | Do PaddleOCR ONNX models run acceptably on Windows CPU? | Runs without PaddlePaddle; on the synthetic smoke corpus text recall is at least that of Tesseract; latency on a 1440x900 image is within the budget set in the run record | Default to Tesseract |
| S-VLM | Does a small local VLM add useful `element_label` evidence? | Role accuracy on synthetic ground truth improves over rule-only S5 without raising absolute fallback ratio | Keep S4 off |
| S-ACCEL | Is DirectML/CUDA worth supporting? | Measured speedup on S-OCR with identical outputs within tolerance | CPU only |

Gates are initial values to be set once the first baseline run exists; no gate is claimed as met today.

## 8. Training our own models (Phase 4+, optional)
The synthetic corpus (BENCHMARKS.md) supplies labeled regions and structure under our own license. Any trained model ships with a model card (data provenance, version, license, checksum) and goes through the same manager. Real-world secondary datasets are evaluation-only unless their terms explicitly allow training.

## 9. Privacy
No telemetry. Remote providers: off by default; enabling one shows exactly what is sent; with pre-perception redaction on, only masked images are sent; API keys live in the OS credential store (SECURITY.md section 7) and never in project files, the IR, logs, or reports.
