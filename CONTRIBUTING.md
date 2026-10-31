# Contributing

1. Read [docs/STATUS.md](docs/STATUS.md) and [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md). The IR boundary (docs/IR_SPEC.md) is the core rule: observed data and inferred data live in different sections and never mix.
2. Set up: see [docs/INSTALL.md](docs/INSTALL.md). Run `python -m unittest discover -s tests -t .` before opening a pull request.
3. Every behaviour change needs a test; do not weaken an assertion to make a build green. Anything that touches the IR schema must update `docs/IR_SPEC.md`, the golden fixture
   (`tests/fixtures/golden/`), and the committed schema (`python -m screen2code.ir.schema > schema/ir-0.1.schema.json`).
4. Keep the dependency graph (ADR-0002) and the security rules: no code that executes generated output, no network access in the engine, all file writes through `Workspace`.
5. Do not claim a feature in docs unless it is implemented and tested; mark experimental features as such.
6. New dependencies and model checkpoints need their exact source, licence, and redistribution terms recorded in `THIRD_PARTY_LICENSES.md`. No AGPL or research-only models in the default path.
