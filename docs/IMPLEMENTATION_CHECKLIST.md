# Implementation checklist

Legend: [x] done and tested, [~] partial/experimental, [ ] not done.

- [x] Foundation: repo, MIT license, uv-free setuptools packaging, unittest suite, CI definitions (not executed here), IR schema/validator/canonical/migrations, golden fixture
- [x] Core: confined workspace, artifact store, config, error registry, runner, provider registry, model store, scrubbing log
- [x] Vertical slice: screenshot -> perception -> IR -> HTML/CSS -> Chromium render -> evaluation report (real input, real browser, real metrics)
- [x] Perception: limits, content sniffing, regions, OCR, measurement, evidence
- [~] Reconstruction: layout, spacing, typography estimates, roles, assets; tokens and components (heuristic); multi-screen = independent pages
- [ ] Cross-screen reconciliation, responsive rules, theme-mode pairing
- [x] Generation: HTML/CSS with component reuse; [~] React (generate-only, SSR-verified); [ ] Next.js
- [x] Rendering + evaluation: Tier-0 renderer, six metrics + composite, exclusions, artifacts
- [ ] Refinement loop
- [x] CLI, Python API, JSON-RPC sidecar
- [ ] Desktop application (toolchain unavailable)
- [x] Security: path confinement, import validation, offline JS-off rendering, no execution entry points, response validation, secret scrubbing, tests
- [x] Benchmark: corpus, structure metrics, runner, pins, determinism check, baseline recorded
- [x] Wheel build verified; [ ] Windows installer / signing
- [x] Documentation: README, STATUS, ADR-0002, INSTALL, CLI, PYTHON_API; [ ] screenshots of a desktop app (none exists)
