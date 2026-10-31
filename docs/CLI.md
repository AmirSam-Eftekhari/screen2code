# CLI reference

Global options: `--json` (machine-readable output; one JSON document per command), `--quiet`, `--debug` (tracebacks), `--allow-no-sandbox`, `--redact-text` (remove recognized text from the IR and exports; text only, see docs/SECURITY.md), `--version`, `-h/--help`.
Progress goes to stderr; results to stdout. No command prompts interactively.

| Command | Purpose |
|---|---|
| `init PATH [--name N]` | create a project directory |
| `import PROJECT IMAGES... [--dpr N] [--viewport-width N] [--page NAME] [--manifest FILE]` | validate and import PNG/JPEG/WebP files (creates the project if missing); `--page`/manifest declare which screenshots belong to one page (WIP, see STATUS) |
| `reconstruct TARGET [--project DIR]` (alias `analyze`) | run S0-S10 and commit `ir/project.ir.json`; TARGET is a project, an image, or a folder of images |
| `generate PROJECT [--target html\|react] [--out DIR] [--asset-policy strict\|default\|permissive]` | generate files from the committed IR |
| `render PROJECT` | render the generated static HTML in Chromium (JS off, offline) |
| `evaluate PROJECT` | compare renders with references; write metrics and artifacts |
| `run TARGET [--project DIR]` | reconstruct + generate + render + evaluate |
| `refine PROJECT [--max-iterations N] [--time-limit S] [--epsilon X] [--apply]` | bounded measured refinement; keeps only measured improvements; `--apply` writes the improved IR (backup kept) |
| `benchmark [--tier smoke\|standard\|full] [--seed N] [--out DIR] [--repeat-check]` | run the synthetic benchmark and write a pinned run record |
| `ir validate FILE [--level 0-3]`, `ir migrate FILE [-o OUT]`, `ir schema` | work with IR documents |
| `doctor` | check Python, Tesseract, Chromium, sandbox, fonts, libraries |
| `models list\|install\|verify\|remove` | local model store |
| `errors` | list the stable error codes |
| `serve` | JSON-RPC sidecar on stdio (used by a desktop client) |

There is deliberately **no command that builds or runs generated code**; React output is generate-only.

## Exit codes

`0` success, `1` general failure, `2` usage error, `3` IR validation failure, `4` provider/model/browser unavailable,
`5` input rejected (limits, content, security), `6` execution refused (reserved), `130` cancelled. With `--json`, errors print `{"error": {"code", "category", "message", "remedy", "details"}}`.

## Example

```bash
screen2code --json --allow-no-sandbox run page.png --project page.s2c > result.json
screen2code ir validate page.s2c/ir/project.ir.json
```
