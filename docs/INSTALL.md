# Installation

Screen2Code runs locally. It does not automatically upload screenshots or download model weights.

## Requirements

| Requirement | Purpose | Check |
|---|---|---|
| Python 3.11+ | Engine and CLI | `python --version` |
| Tesseract 5 with English data (`eng`) | Default OCR provider | `tesseract --version` |
| Chromium installed by Playwright | Tier-0 rendering | `python -m playwright install chromium` |
| Sans-serif fonts | Reference and generated rendering | `screen2code doctor` |

Install Tesseract separately: Linux `apt install tesseract-ocr`; macOS `brew install tesseract`; Windows use a maintained Tesseract 5 distribution and add its executable to `PATH`.

## Install from source

```bash
python -m venv .venv
# Linux/macOS
. .venv/bin/activate
# Windows PowerShell
.venv\Scripts\Activate.ps1

python -m pip install -r requirements-lock.txt
python -m pip install -e . --no-deps
python -m playwright install chromium
screen2code doctor
```

`pip install -e . --no-deps` is paired with `requirements-lock.txt` so the tested dependency versions are used. For a normal editable install with resolver-selected compatible versions, use `python -m pip install -e .` instead.

## Desktop UI and Tauri shell

The React/TypeScript UI is a web bundle. It talks to the local `screen2code serve` JSON-RPC sidecar.

```bash
npm install --prefix ui
npm run --prefix ui typecheck
python scripts/build_ui.py
python -m unittest tests.test_ui
```

The Tauri 2 shell in `src-tauri/` has been compiled and launched in development mode on the maintainer's Windows machine (`cargo check`, `cargo build`, and `cargo run` succeeded there). This does **not** mean a distributable app is ready.

Current desktop limitations:

- no signed or packaged sidecar executable;
- no Windows installer or auto-updater;
- no code signing;
- no verified clean-machine installation procedure;
- no macOS package;
- no automated packaged-app end-to-end suite.

In development mode, the shell starts `python -m screen2code.server.main` from the environment available to the Tauri process. Activate the Python virtual environment before launching it. A packaged build must supply `S2C_SIDECAR` pointing to a sidecar executable that accepts the `serve` argument; that packaging path is not implemented here.

## Browser sandbox

`screen2code doctor` reports whether Chromium's sandbox can start. Rendering fails closed if it cannot. You may explicitly opt in with `screen2code --allow-no-sandbox run ...` or the corresponding project setting, but the waiver is recorded. JavaScript stays disabled and network requests are blocked either way.

## Models

No model weights are bundled and no remote model provider is currently used by the core pipeline. OCR uses Tesseract. The model store can validate locally supplied model manifests and checksums, but installed model weights are not currently consumed by a provider.

## Tests

```bash
python -m unittest discover -s tests -t .
python -m unittest tests.test_ir tests.test_core
```

Tests that require Chromium, OCR, or Node/React tooling may skip when those prerequisites are absent; each skip should state its reason. A skipped test is not a pass. The supplied source snapshot contains 165 test methods. The maintainer's Windows test history and the independent review environment are described separately in [STATUS.md](STATUS.md).
