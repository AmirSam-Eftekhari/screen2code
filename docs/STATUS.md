# Project status and verification

**Status date:** 2026-11-05. This document describes the source snapshot supplied for review, plus the maintainer's subsequent Windows development-shell verification reported in the project conversation. It distinguishes independently rerun checks from maintainer-reported checks.

## Current release stage

Screen2Code is suitable for a **public source-code preview**, not yet a polished binary desktop release. The Python engine, CLI, JSON-RPC sidecar, and React/TypeScript web UI are implemented. The Tauri shell compiled (`cargo check`, `cargo build`) and launched (`cargo run`) on the maintainer's Windows machine. This is development-mode verification only: it does not establish that a clean machine can install or run a packaged application.

## Feature status

| Area | State | Evidence / qualification |
|---|---|---|
| IR 0.1 schema, canonical serialization, content hash, IDs, migration | Implemented | `tests/test_ir.py`; committed schema drift test |
| Validator L0-L3 and epistemic rules | Implemented | Mutation tests and golden fixture |
| Confined workspace, atomic writes, artifact store, config, runner | Implemented | `tests/test_core.py` |
| Screenshot import and validation | Implemented | Import tests; content sniffing and dimension/size limits |
| Region segmentation | Implemented classical baseline | Segmentation tests; not a learned detector |
| OCR | Implemented via Tesseract | Provider-response and timeout tests; requires external Tesseract binary |
| Measurement and structural inference | Implemented | CV measurements, layout fits, tokens and component heuristics |
| HTML/CSS generation | Implemented | Well-formedness, escaping, policy and determinism tests |
| React generation | Experimental, generate-only | No generated React project is built or executed by Screen2Code |
| Multi-screen reconciliation | Implemented with conservative fallback | `tests/test_multiscreen.py`; uncertain screens remain separate |
| Tier-0 rendering | Implemented | Static HTML only, JavaScript off, network blocked, sandbox fail-closed unless explicitly waived |
| Visual evaluation | Implemented | Pixel, SSIM, edge, colour and layout metrics; exclusions reported |
| Synthetic benchmark | Smoke baseline measured | 8 authored scenes; not representative of arbitrary production sites |
| Refinement loop | Implemented | Bounded deterministic rules; IR changes only with explicit `--apply` |
| Text redaction | Implemented, text-only | Recognized text is removed from IR/exports; source screenshot and raster assets remain |
| CLI, Python API, JSON-RPC sidecar | Implemented | CLI, API and protocol tests |
| React/TypeScript desktop web UI | Implemented | `tests/test_ui.py` drives the bundle against a real sidecar |
| Tauri desktop shell | Development-mode Windows launch verified by maintainer | `cargo check`, `cargo build`, `cargo run` reported successful on Windows; no installer or signed sidecar |
| Windows packaged application | Not available | No signed sidecar, installer, update mechanism or packaged-app test suite |
| macOS app | Not verified | No macOS build/test evidence |

## Independent verification of the supplied ZIP

The supplied archive was reviewed in an isolated Linux environment. The following checks were actually completed during this review:

- Python 3.13.5, `PYTHONPATH=src`: **57/57 tests passed** across `tests.test_ir` and `tests.test_core`.
- A full unittest discovery run was attempted. It could not complete within the review time limit; therefore no full-suite pass is claimed.
- Chromium was unavailable in the review environment, so browser/rendering-dependent tests explicitly skipped. React SSR dependencies were also unavailable for the relevant tests.
- Rust/Cargo was unavailable in the review environment, so the Tauri shell was not independently rebuilt here. Its Windows development-mode build/launch status above is based on the maintainer's recorded successful commands.
- No network calls, real generated-project execution, signing, installer build, or production deployment were performed.

The archive contains 165 test methods in the source tree. This count is not the same as a passing-test count; use the commands in [INSTALL.md](INSTALL.md#tests) to verify in a fully provisioned environment.

## Known limitations

- The benchmark corpus contains eight synthetic scenes. The README sample is an authored fixture. These results do not establish real-world reconstruction quality.
- Text geometry uses a typographic cell model; it improves stability but can reduce pixel-level fidelity.
- Fonts are system-dependent. The renderer records resolved font file hashes, but output can differ across machines.
- Invisible wrappers and strict component clustering limit structural recall; near matches may intentionally remain separate.
- React is generate-only. Screen2Code never installs dependencies, builds, or executes generated React/Next.js projects.
- Next.js output, navigation inference, learned detectors/VLM labelling, pre-perception pixel masking, and Tier-1 execution are not implemented.
- Text redaction does not mask screenshot pixels or extracted raster assets.
- Tauri development mode expects a working Python environment and sidecar command. A packaged sidecar and installer are not supplied.
- The Tauri relay now caps inbound/outbound frames at 16 MiB, limits header size and queued responses, rejects malformed UTF-8/framing, and kills/waits for the child process when the shell exits. These changes were statically reviewed but could not be compiled in this Linux review environment because Cargo is unavailable. Treat the shell as development scaffolding until Windows CI compiles it and packaged-app lifecycle tests pass.
- CI workflows are present but have not been observed running successfully in GitHub Actions.

## Before a tagged desktop release

1. Add and validate a packaged sidecar build for each supported OS.
2. Add message-size limits, robust sidecar shutdown/restart and error reporting to the Tauri relay.
3. Build and test a clean Windows installer on a clean Windows VM; document Tesseract and Chromium installation.
4. Add signed binaries if distributing installers broadly; otherwise clearly publish unsigned preview builds.
5. Enable GitHub private vulnerability reporting or publish a monitored security contact before making the repository public.
6. Run the full Linux and Windows CI workflows and publish their results.
7. Add a dependency/SBOM audit and confirm all third-party notices.
