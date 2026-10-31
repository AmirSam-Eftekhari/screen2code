"""Project builder: confined, atomic writes of the generated file tree plus report files (SECURITY section 3)."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Callable

from ..core.errors import S2CError
from ..core.workspace import Workspace
from ..ir import content_hash
from .common import JSON, Generated, Plan, Report, make_plan, require_committed
from .html import HtmlAdapter
from .react import ReactAdapter

ADAPTERS = {"html": HtmlAdapter, "react": ReactAdapter}


def generate(ir: JSON, target: str, read_asset: Callable[[str], bytes], options: JSON | None = None) -> Generated:
    """Pure: committed IR -> file tree + report. No filesystem access."""
    require_committed(ir)
    if target not in ADAPTERS:
        raise S2CError("S2C-GEN-001", f"target {target!r} is not available", f"available: {sorted(ADAPTERS)}")
    plan = make_plan(ir, target, options)
    report = Report(ir_hash=content_hash(ir), plan_hash=plan.hash, target=target)
    files = ADAPTERS[target]().emit(ir, plan, read_asset, report)
    report.files = {p: hashlib.sha256(b).hexdigest() for p, b in sorted(files.items())}
    return Generated(files, report, plan)


def write_project(gen: Generated, out_dir: Path, *, overwrite: bool = False) -> list[Path]:
    """Write ``gen`` under ``out_dir`` through a confined Workspace. Refuses to overwrite unless explicitly allowed."""
    out_dir.mkdir(parents=True, exist_ok=True)
    ws = Workspace(out_dir)
    written = []
    for rel, data in sorted(gen.files.items()):
        written.append(ws.write_bytes(rel, data, overwrite=overwrite))
    written.append(ws.write_text("s2c-report.json", json.dumps(gen.report.to_dict(), indent=2, sort_keys=True) + "\n", overwrite=overwrite))
    written.append(ws.write_text("REPORT.md", gen.report.markdown() + "\n", overwrite=overwrite))
    return written
