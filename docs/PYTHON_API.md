# Python API

`screen2code.api.Project` is the same layer the CLI and the sidecar call.

```python
from screen2code.api import Project

project = Project.create("demo.s2c", "demo", overrides={"render": {"allow_no_sandbox": True}})  # sandbox opt-in is explicit
project.import_images(["landing.png"], {"device_pixel_ratio": 1.0})
commit = project.reconstruct(listener=lambda ev: print(ev.stage, ev.status))   # -> CommitResult(ir_path, content_hash, nodes, pages, quality)
project.generate("html")                       # or "react" (generate-only)
project.render()                               # Tier-0 render of every screen
report = project.evaluate()                    # metrics + artifact paths
print(report["metrics"]["ssim"], report["artifacts"]["difference"])
```

| Member | Notes |
|---|---|
| `Project.create/open/open_or_create(path, ...)` | typed errors are `S2CError` with stable `code`, `category`, `remedy` |
| `import_images(paths, declared=None)` | declared metadata (`device_pixel_ratio`, `viewport_width`, `page_hint`) is recorded as asserted |
| `reconstruct(listener=None, cancel=None)` / `analyze` | `CancelToken().cancel()` stops between stages and recognition calls |
| `ir` | the committed IR as a dict (validated) |
| `generate(target, out=None, options=None, overwrite=True)` | options: `asset_policy`, `navigation_policy`, `placeholder_text`, `instrumentation` |
| `render(...)`, `evaluate(screen=None)`, `run()` | |

The IR utilities are in `screen2code.ir`: `validate(doc, level)`, `canonical_dumps`, `content_hash`, `derive_id`, `migrate`, `quality_report`, `json_schema`.
API stability: 0.x, no compatibility guarantee (docs/IR_SPEC.md section 4.1).
