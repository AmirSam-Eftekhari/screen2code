# Screen2Code

**See it. Understand it. Rebuild it.**

Screen2Code is an open-source UI reverse-engineering tool. From screenshots it infers an explicit, evidence-aware, framework-independent
description of the interface (the *IR*), generates an editable project from it, renders that project in a locked-down Chromium, and
measures the result against the reference. It is **not** "image → LLM → HTML": perception is classical computer vision plus OCR, and every
inferred property keeps a pointer to the measurements that support it. *Pixels are observations. Structure is an inference.*

| Reference screenshot | Generated, rendered | Overlay | Difference |
|---|---|---|---|
| ![reference](docs/assets/landing-reference.png) | ![generated](docs/assets/landing-generated.png) | ![overlay](docs/assets/landing-overlay.png) | ![difference](docs/assets/landing-difference.png) |

*Real output of `screen2code run tests/fixtures/landing.png` (a page we authored). Measured: SSIM 0.923, edge F1 0.882, layout IoU 0.878, 18/18 nodes matched.*

```text
Reference screenshots -> Screen2Code -> editable HTML/CSS or React project -> visual comparison + metrics
```

## Status (read this first)

**0.1 release candidate** (package version `0.1.0.dev0`). Authoritative details: [docs/STATUS.md](docs/STATUS.md) and [RELEASE_NOTES.md](RELEASE_NOTES.md).

| | |
|---|---|
| **Implemented and tested** | single- and multi-screenshot reconstruction (design tokens, shared components, responsive unification of one page shown at several widths, explicit fallback with recorded reasons); versioned IR with validator; HTML/CSS and React generation; Tier-0 rendering (JS off, offline, fail-closed sandbox); visual evaluation; measured refinement loop; text redaction; reproducible synthetic benchmark; CLI; Python API; JSON-RPC sidecar; desktop UI (web bundle) tested end to end against the real sidecar |
| **Experimental** | React target (generate-only); token/component heuristics; typographic cell model; component inference skips responsively-patched subtrees (reported) |
| **Built but NOT verified** | the Tauri desktop shell (`src-tauri/`): never compiled; no installer, no signed Windows sidecar. See [docs/INSTALL.md](docs/INSTALL.md#desktop-app-windows-tauri) |
| **Not implemented** | Next.js target; pre-perception pixel masking; navigation inference; learned detectors / VLMs; remote model providers |
| **Unsupported** | SVG/video/animated input; executing generated code |

Measured so far: [benchmarks/baselines/smoke-seed1.summary.md](benchmarks/baselines/smoke-seed1.summary.md) (8 synthetic scenes; read its limitations: synthetic scenes are cleaner than real sites and do not predict real-world performance).

## Quick start

Requirements: Python 3.11+, the Tesseract binary with English data, and Chromium (via Playwright). Details: [docs/INSTALL.md](docs/INSTALL.md).

```bash
python -m venv .venv && . .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements-lock.txt && pip install -e . --no-deps   # or: pip install -e .
python -m playwright install chromium
screen2code doctor
screen2code run tests/fixtures/landing.png --project demo.s2c
```

If `doctor` reports the browser sandbox as unavailable (for example as root in a container), rendering **fails closed** until you explicitly opt in with
`screen2code --allow-no-sandbox run ...`. JavaScript stays disabled and the network blocked either way. Everything above was run on Linux; Windows is **not verified**.

Outputs land in the project directory: `ir/project.ir.json`, `exports/html/` (generated project and `REPORT.md`), `renders/`, `evaluations/<screen>/` (reference, generated, overlay, difference, `report.json`, `REPORT.md`).

Several screenshots of one page at different widths: `screen2code import demo.s2c home-1000.png --page home --viewport-width 1000` (repeat per width), then `screen2code reconstruct demo.s2c`.
Remove recognized text from the IR and exports with `screen2code --redact-text reconstruct ...` (text only; see Security below).

**Desktop UI (web bundle, runs against the real sidecar):**

```bash
npm install --prefix ui && npm run --prefix ui typecheck && python scripts/build_ui.py     # writes ui/dist
python -m unittest tests.test_ui                                                         # drives the bundle against a real `screen2code serve`
```

The sidecar is `screen2code serve` (JSON-RPC over stdio, Content-Length framed). The Tauri shell that hosts the bundle is unverified; see INSTALL.

## Documentation

[CLI reference](docs/CLI.md) · [Python API](docs/PYTHON_API.md) · [IR specification](docs/IR_SPEC.md) · [Architecture](docs/ARCHITECTURE.md) · [Security model](docs/SECURITY.md) ·
[Benchmarks](docs/BENCHMARKS.md) · [Status and deviations](docs/STATUS.md) · [ADR-0002](docs/ADR-0002-implementation.md) · [Contributing](CONTRIBUTING.md)

## Security in one paragraph

Screenshots, model output, the IR, and generated code are untrusted. Writes are confined to project directories; imports are limited and content-validated;
static HTML is rendered offline with JavaScript disabled; Screen2Code never builds or executes generated projects, and has no command that does.
There is no telemetry and nothing is uploaded. Text redaction (`--redact-text`) removes recognized text from the IR and exports but does **not** mask pixels: the screenshot and extracted image assets stay in the project folder, so it does not make a project safe to share. See [docs/SECURITY.md](docs/SECURITY.md).

## License

MIT. Third-party notices: [THIRD_PARTY_LICENSES.md](THIRD_PARTY_LICENSES.md).
