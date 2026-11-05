# Security policy

## Reporting a vulnerability

Please do **not** open a public issue for a vulnerability. Use the repository's private vulnerability reporting (GitHub **Security → Advisories → Report a vulnerability**). **Before making the repository public, the maintainer must enable private vulnerability reporting in GitHub repository settings and ensure that at least one maintainer monitors incoming reports.** No security contact address is configured in this source tree; do not publish until the private reporting channel is enabled.

## Scope and model

The engineering security model is [docs/SECURITY.md](docs/SECURITY.md). Summary of what the code enforces today (each item has tests):

- screenshots, model/provider output, the IR and generated code are untrusted; the IR is validated before any generation;
- imports are content-sniffed (not extension-trusted), size/dimension/megapixel limited, animated and SVG inputs rejected, metadata stripped;
- all writes go through a confined workspace (traversal, drive/UNC paths, reserved Windows names, symlink escape, case collisions rejected; no silent overwrite);
- rendering is Tier 0 only: JavaScript disabled, network blocked, file reads limited to the project; the Chromium sandbox is required unless explicitly waived and recorded;
- no code path builds or executes generated code; there is no isolation mechanism for doing so, and none is claimed;
- provider responses are schema-checked; logs scrub secrets and omit image/OCR content; no telemetry; nothing is uploaded.

Not covered: generated projects (including the React target) are never built or run by Screen2Code; running them is your decision and risk. Installed plugins/providers run as trusted code.
