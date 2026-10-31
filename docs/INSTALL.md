# Installation

Screen2Code runs locally; nothing is uploaded and no model is downloaded automatically.

## Requirements

| Need | Why | Check |
|---|---|---|
| Python 3.11+ | engine | `python --version` |
| Tesseract 5 with English data (`eng`) | default OCR provider | `tesseract --version` |
| Chromium via Playwright | Tier-0 rendering | `python -m playwright install chromium` |
| A sans-serif font set (Liberation Sans recommended) | rendering reference fonts | `screen2code doctor` lists the files used |

Tesseract: Linux `apt install tesseract-ocr`; macOS `brew install tesseract`; Windows: install a Tesseract 5 build (for example the UB-Mannheim installer) and put it on `PATH`.
The Windows steps are documented but have not been verified.

## Install from source

```bash
python -m venv .venv
. .venv/bin/activate            # Windows: .venv\Scripts\activate
pip install -e .
python -m playwright install chromium
screen2code doctor
```

`pip install .` builds a wheel (verified: all subpackages included; the installed CLI runs in a clean environment).
A Windows installer, PyInstaller sidecar, and code signing are **not** built (needs a Windows machine and a signing certificate).

## Desktop app (Windows, Tauri)

**Status: the web UI is built and tested; the Tauri shell has never been compiled.** Nothing below has been run on Windows. A signed installer and a packaged sidecar do not exist.

Prerequisites: Rust (rustup, MSVC toolchain with "Desktop development with C++"), Microsoft WebView2 runtime, Node 20+, Python 3.11+, Tesseract 5, Chromium via Playwright.

```powershell
# 1. engine (inside a venv, as above)
pip install -r requirements-lock.txt; pip install -e . --no-deps; python -m playwright install chromium; screen2code doctor
# 2. UI bundle
npm install --prefix ui; npm run --prefix ui typecheck; python scripts\build_ui.py
# 3. shell: tauri-build on Windows requires icons; generate them from any square PNG, then build
cargo install tauri-cli --version "^2" --locked
cd src-tauri; cargo tauri icon path\to\square.png
cargo tauri dev        # starts `python -m screen2code.server.main` from PATH (activate the venv first)
cargo tauri build      # bundle.active is false: produces the executable, not an installer
```

Expected first-compile work (not yet done): commit the generated `Cargo.lock`; fix any compile error in `src-tauri/src/main.rs`. The shell exposes only `s2c_send`/`s2c_poll` to the web view. A packaged build must set
`S2C_SIDECAR` to a sidecar executable that accepts the argument `serve`; building and signing that executable is not done.

## The browser sandbox

`doctor` reports whether Chromium's own sandbox can start. When it cannot (root in a container is the usual cause) `render`/`run` fail closed with `S2C-RENDER-002`.
Opt in explicitly if you accept that: `screen2code --allow-no-sandbox run ...` or

```toml
# project.toml
[render]
allow_no_sandbox = true
```

JavaScript stays disabled, the network is blocked, and file access is limited to the project directory regardless. The render record documents the choice.

## Models

No model weights are bundled. OCR uses the Tesseract binary. The model store (`screen2code models list|install|verify|remove`) installs from a local file after verifying
the manifest SHA-256 and gating on licence class; non-permissive licences require `--accept-license`. Models live in the per-user data directory
(override with `SCREEN2CODE_MODELS`). No provider currently consumes installed models.

## Tests

```bash
python -m unittest discover -s tests -t .       # 165 tests (UI tests need node + esbuild; they skip with an explicit reason otherwise)
python -m unittest tests.test_ir tests.test_core  # fast, platform-independent subset
```
