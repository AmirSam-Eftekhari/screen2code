# DESKTOP_UX: the desktop application

> **Implementation status (2026-11-05):** The React + TypeScript web bundle is implemented and tested against the real JSON-RPC sidecar. The Tauri 2 shell has been compiled and launched in Windows development mode by the maintainer. This document remains the intended UX/design specification; it is not proof that every design detail is implemented. Packaged-app tests, native dialogs, credential-store integration, installer and signed sidecar are not available. See [STATUS.md](STATUS.md).

> Where this design differs from current behaviour, [STATUS.md](STATUS.md) and [ADR-0002](ADR-0002-implementation.md) describe the implemented state.

## 1. Principles
- U-1. The desktop contains no business logic. It displays and edits state held by the core engine through RPC.
- U-2. It shows only what the pipeline actually produced. No decorative or invented explanations.
- U-3. Observed and inferred information are visibly different everywhere they appear.
- U-4. Serious engineering-tool feel: dark by default, clear hierarchy, subtle motion, no gratuitous gradients or glow.
- U-5. Honest states: partial, uncertain, unavailable, and experimental are labelled, never hidden.
- U-6. Edits are first-class and reversible.

## 2. Stack
Tauri 2 with a React + TypeScript frontend. The Rust layer currently supervises a Python sidecar and exposes a narrow command surface to the webview. Native dialogs, OS credential-store bridge, custom project file protocol, and production-grade packaged sidecar management remain future work. The UI bundle is built with esbuild; the desktop shell uses WebView2 on Windows.

## 3. Information architecture

| View | Purpose | Current status |
|---|---|---|
| Home | New/Open project, recent projects, examples | Implemented in web UI |
| Import | Add screenshots, group screens and set viewport metadata | Implemented in web UI |
| Analysis | Stage progress, cancellation and diagnostics | Implemented in web UI |
| Workspace | Regions, tree and inspector with provenance | Implemented in web UI |
| Compare | Reference, generated, overlay, difference and metrics | Implemented in web UI |
| Export | Generate target and inspect output files | Implemented in web UI; output is shown as text, not executed |
| Settings | Privacy and render policy controls | Partial; no native credential store |

## 4. Security boundary
The UI communicates with the local sidecar; it does not receive a general shell or filesystem API. The sidecar validates RPC parameters and confines project operations. Generated HTML is rendered under the Tier-0 policy described in [SECURITY.md](SECURITY.md). The current Tauri relay is development scaffolding and still needs bounded message framing, robust child-process shutdown, and packaged-sidecar hardening before a production desktop release.

## 5. Not yet delivered
- Native file dialogs and a custom file protocol.
- OS credential-store integration.
- Packaged and signed sidecar executable.
- Windows installer, updater and macOS package.
- Automated end-to-end tests against the packaged desktop application.
