# Screen2Code 0.1 — public source preview

This is an early public-source preview of the Screen2Code engine and desktop UI code. It is not a stable binary desktop release.

## Included

- Python engine, CLI and Python API.
- Versioned interface representation (IR), schema, validator and migration support.
- Screenshot import, classical computer-vision segmentation, Tesseract OCR and evidence-linked measurement.
- HTML/CSS generation and experimental generate-only React output.
- Multi-screen responsive reconciliation with explicit fallback when evidence is insufficient.
- Tier-0 static rendering (JavaScript disabled, network blocked) and visual evaluation.
- Bounded, measured refinement; explicit `--apply` required to modify committed IR.
- Text-only redaction; source pixels and raster assets are retained.
- JSON-RPC sidecar and React/TypeScript web UI.
- Tauri desktop shell that has been compiled and launched in Windows development mode by the maintainer.

## Not included / not promised

- No Windows installer, signed executable, packaged sidecar, auto-updater or macOS application.
- No automatic build or execution of generated React/Next.js projects.
- No Next.js target, navigation inference, learned detector/VLM pipeline or pre-perception pixel masking.
- No production guarantee for arbitrary websites; the committed benchmark is synthetic and small.

## Security and privacy

Screen2Code treats screenshots, IR data, provider output and generated code as untrusted. It validates imports and IR, confines project writes, renders static HTML with JavaScript disabled and network blocked, and does not execute generated projects. Text redaction does not erase text visible in source screenshots or raster assets. Read [docs/SECURITY.md](docs/SECURITY.md) before handling sensitive material.

## Verification

The exact checks performed on the supplied archive are recorded in [docs/STATUS.md](docs/STATUS.md). The independent review passed 57 core/IR tests; full-suite execution did not complete in the review environment, and Chromium-dependent tests could not run there. The maintainer separately verified the Tauri development shell on Windows. Do not interpret these results as a full release qualification.
