# Screen2Code 0.1 release candidate: release notes

Scope is frozen. This candidate is a working Python engine, CLI, JSON-RPC sidecar, and a desktop UI web bundle. It is **not** a verified desktop application release.

## What works (verified by the automated tests in this repository)

- Screenshot to IR to HTML/CSS (and generate-only React), rendered in locked-down Chromium and measured against the reference (SSIM, edge F1, layout IoU, composite) with overlay and difference images.
- Several screenshots of one page at different widths become one page with responsive patches and one `@media` rule; when screens cannot be matched they stay separate and the reasons are recorded.
- Design tokens and shared components across pages, with near misses (similar but not merged) reported, not hidden.
- Measured refinement loop (`screen2code refine`), never applied to the IR unless asked.
- Text redaction (`--redact-text`, UI Settings): recognized text is removed from the IR, evidence, names and exports; records are auditable; evaluation counts redacted regions as an exclusion.
- JSON-RPC sidecar (`screen2code serve`) and a React UI that talks to it; the UI test drives the built bundle in Chromium against a real sidecar process.

## Security posture

Screenshots, the IR and generated code are untrusted. Generated code is never built or executed by Screen2Code. Rendering is offline with JavaScript disabled, and **fails closed** when Chromium's sandbox cannot start;
the explicit opt-in (`--allow-no-sandbox`, or the Settings checkbox) is recorded on every render and shown in the UI. The sidecar validates parameters, confines reads and exports to the project, and scrubs secrets from settings and errors.
Redaction covers recognized text only. **The screenshot and extracted raster assets remain on disk; a redacted project is not safe to share by that alone.**

## Verification results (Linux, Python 3.12.3, Node with esbuild 0.27.7, TypeScript 6.0.3)

See the final delivery message and `docs/STATUS.md`. The suite: `python -W error::ResourceWarning -m unittest discover -s tests -t .`.

## Known limitations and external platform gaps

- Windows and Tauri: the shell in `src-tauri/` has never been compiled (no Rust toolchain was available); no icons, no `Cargo.lock`, no installer, no signed sidecar. Windows is unverified for the whole project. Steps: docs/INSTALL.md.
- The UI is type-checked against a hand-written subset of React's types (offline). With network, `npm install --prefix ui` provides the real `@types/react`; this was not run.
- CI workflows were never executed.
- Header/footer shared across responsive pages are not componentized (reported as skipped); one fixture page (Contact) scores low (composite 0.60).
- Benchmarks are synthetic (8 scenes) and do not predict real-world quality. Sandbox-less rendering was used in this environment for every measured render.
- Not implemented: Next.js, pixel masking, navigation inference, learned detectors, remote providers.
