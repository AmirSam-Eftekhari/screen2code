# ADR-0001: Phase 0 pre-coding decisions

> **Implementation status:** this is a design document. For what is actually implemented, measured, and different, see [STATUS.md](STATUS.md) and [ADR-0002](ADR-0002-implementation.md); they take precedence where they differ.

Status: APPROVED WITH AMENDMENTS (maintainer, 2026-10-08) - see section 5; amendments override conflicting text in D2, D5, D6
Date: 2026-10-08
Supersedes: none

## 0. Method and limits of the scan

Sources checked on 2026-10-08: the abi/screenshot-to-code repository and its reviews, OmniParser model-license notices, PaddleOCR docs and model cards, PyInstaller issue tracker and Windows-sidecar reports, Qwen3-VL / Holo2 model cards, and the Design2Code / UIBenchKit material.

NOT re-checked in this pass (verify before the PRD is final): commercial products (v0, Locofy, Builder.io, Figma Make), Playwright, Tauri, OpenCV, Pydantic, LPIPS, Tesseract, RT-DETR license texts. Statements about those come from prior knowledge, not this scan.

Per-checkpoint licenses must be read from each model card at adoption time. "Most sizes are Apache-2.0" is not a sufficient license check.

## 1. Scan findings that drive the decisions

- abi/screenshot-to-code is MIT, covers HTML/Tailwind/CSS, React, Vue, Bootstrap and Ionic, and adds screenshot, Figma and screen-recording input. Its README recommends Gemini for best quality (asset extraction) and says the Ollama path gives poor results. Architecture is LLM-centric; no explicit IR or render-score loop was evident from the README. Differentiation (IR, multi-screen design system, measured verification, local-first) still stands. Do not copy its code or architecture.
- OmniParser V2: `icon_detect` weights are AGPL (inherited from YOLO); captioning models are MIT.
- PaddleOCR is Apache-2.0. It needs PaddlePaddle, with separate CPU/GPU wheels and driver minimums on Windows, plus a special wheel for NVIDIA 50-series on Windows. ONNX conversions of its models exist (Apache-2.0).
- PyInstaller bundles are a known antivirus false-positive source on Windows. `--onefile` also extracts on every launch. Nuitka sidecars have been reported flagged as well. PyTorch/TensorFlow bundles commonly reach 0.5-1.5 GB before exclusions.
- Qwen3-VL is reported Apache-2.0 for most sizes. Holo2-30B-A3B is research-only (non-commercial) while its 4B/8B siblings are Apache-2.0.
- Design2Code: 484 real webpages, ODC-By, research-oriented; human judgments diverged from automatic metrics. UIBenchKit (arXiv 2605.13141, May 2026) is a unified harness worth studying for our benchmark runner.

## 2. Decisions

### D1. Core language: Python core, thin TypeScript shell
Decision: Python 3.11+ core engine; Tauri/React is a client only.
Why: CV/OCR/ML ecosystem, Playwright, scikit-image/OpenCV all first-class. Rust-core would cost the ecosystem for no v1 benefit.
Consequence: packaging is the main cost (D2). Rust is allowed later for hot paths behind the same interfaces.

### D2. Windows sidecar packaging
Decision:
- Windows is a tier-1 platform from day one (CI on windows-latest, path/long-path tests).
- Dev: `uv`-managed venv. Release: Tauri launches a Python sidecar built as `--onedir` (not `--onefile`), code-signed, communicating over stdio JSON-RPC.
- Heavy weights are never bundled. Model packs are downloaded on demand into a user data dir with hash verification.
- Prefer ONNX Runtime for detector/OCR inference to avoid shipping PyTorch/PaddlePaddle in the installer.
- Spike gate (before Phase 1 exit): confirm Paddle OCR models run acceptably through ONNX Runtime on CPU on Windows; otherwise default OCR = Tesseract and PaddleOCR becomes an optional pack.
- Evaluate Nuitka only after a measured comparison. Plan to submit false-positive reports per release and sign every artifact.

### D3. IR vocabulary (principles; full spec in IR_SPEC.md)
Decision:
- Closed core node vocabulary, extensible via namespaced extensions, versioned with `schema_version` and migrations.
- Layout intent is an enum: `stack_h`, `stack_v`, `grid`, `flow`, `overlay`, `absolute` (fallback only; must carry a reason and low confidence, and counts against a "layout quality" metric).
- Every node carries: stable id, type, source region(s), confidence, evidence list (only signals actually computed), and token references instead of raw values where a token exists.
- Components and instances are separate from nodes; variants are explicit props.
- Asset provenance is an enum: `extracted | reconstructed | placeholder`.

### D4. Model and dependency license policy
Decision:
- Repo is MIT. Default install and default model packs: only OSI-permissive licenses (MIT, BSD, Apache-2.0), checked per checkpoint.
- AGPL/GPL/research-only/non-commercial weights (Ultralytics YOLO and derivatives including OmniParser `icon_detect`; Holo2-30B-A3B) are excluded from the default path and not redistributed. A user may opt in to bring their own, with an explicit license warning in CLI and UI.
- Default detection: classical CV plus a permissive detector trained by us on synthetic data (see D5). Candidate architectures need license verification before adoption.
- Local VLM default candidates: Qwen3-VL small sizes via an OpenAI-compatible local endpoint (Ollama/llama.cpp), subject to per-checkpoint license check.
- A `THIRD_PARTY_LICENSES` file and a CI license-audit job are required before first release.

### D5. Benchmark and training data
Decision:
- Primary: a synthetic corpus we generate by rendering our own templates and permissively licensed pages, with DOM ground truth for regions, text, tokens and components. Fully reproducible from a seed.
- Secondary: Design2Code via a fetch script; do not vendor its screenshots in the repo. Check its ODC-By and source-page terms before any redistribution or use for training.
- No third-party screenshots committed. Every fixture carries a license record.
- Report metrics per category with versions and seeds; no number appears in docs unless produced by a CI-reproducible run.
- Study UIBenchKit's harness design; verify its license before borrowing anything.

### D6. Rendering and execution sandbox
Decision (tiered):
- Tier 0 (default, automatic): render static HTML/CSS with JavaScript disabled, a fresh Chromium profile, all network requests aborted, file access limited to the project directory.
- Tier 1 (React/Next.js): the generator emits only dependencies from a pinned allowlist template with a lockfile, so no arbitrary installs. Build and run happen only on explicit user action, inside a container or equivalent isolation, offline after the pinned install.
- Never auto-run generated code. Sanitize SVG, reject path traversal on every write, and treat model output as untrusted data.
- Open item: define the Windows isolation story (Docker Desktop/WSL2 vs other) after testing; until then Tier 1 is labeled experimental.

## 3. Consequences for the docs
- IR_SPEC.md depends on D1 and D3 only; it can start now.
- SECURITY.md depends on D6; MODEL_STRATEGY.md on D4; BENCHMARKS.md on D5; PIPELINE/ARCHITECTURE on D1 and D2.

## 4. Deferred (safe to postpone)
Video input, Vue adapter, plugin system, Docker image, GPU tuning, release automation, Nuitka evaluation.

## 5. Amendments (maintainer decision, 2026-10-08)

These override any conflicting text in D2, D5 and D6 above. D3's layout enum (`stack_h`, `stack_v`, `grid`, `flow`, `overlay`, `absolute`) is superseded by IR_SPEC.md (`stack`, `flex`, `grid`, `overlay`, `absolute`; no `flow`).

### A1. Benchmark architecture
- The primary benchmark is a reproducible synthetic/procedural corpus with known ground truth. It must not depend on any third-party dataset.
- Design2Code and other real-world licensed datasets are secondary sources only. They are never a dependency of the benchmark system: the benchmark runs and reports fully without them.
- Every benchmark run must record and pin, at minimum: dataset version, seed, browser/renderer version, viewport, fonts, model/provider configuration, and relevant dependency versions. A run missing any of these is not a valid result and must not be published.

### A2. Packaging
- Initial strategy: a signed Windows `--onedir` sidecar.
- PyInstaller is NOT an architectural dependency. Packaging sits behind a packaging/build abstraction so the tool can be replaced (for example by Nuitka or another bundler) without touching engine code.
- Model weights are never bundled into the installer. Models are downloaded on demand into a managed model directory.
- Model metadata must include: version, source, license information, and integrity/checksum information. A model without complete metadata is not installable.

### A3. Generated-code execution and the trust boundary
- All generated code is UNTRUSTED INPUT.
- Generated projects are never executed automatically.
- Static HTML rendering may run offline with JavaScript disabled.
- React/Next.js builds or execution require explicit user action and must run inside an isolated execution boundary.
- The exact Windows isolation mechanism is an OPEN SPIKE. It is not solved and must not be presented as solved in any document, UI string or release note.
- ARCHITECTURE.md must document this as an explicit trust boundary: imported images, model outputs, the IR derived from them, and all generated code sit on the untrusted side; only the core engine's validated, sanitized handling of them is trusted.
