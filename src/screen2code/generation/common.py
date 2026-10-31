"""Shared generation machinery: plan, escaping, token/colour/length lowering, report (GENERATION sections 1, 4, 7, 9)."""
from __future__ import annotations

import hashlib
import html as _html
import json
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Protocol

from ..core.errors import S2CError
from ..core.workspace import check_no_case_collisions, sanitize_name
from ..ir import canonical_dumps, content_hash, validate

JSON = dict[str, Any]
ADAPTER_VERSION = "0.1.0"
FONT_STACKS = {  # font_policy: generic family -> stack (resolved concrete fonts are recorded by the renderer)
    "sans": '"Liberation Sans", "Noto Sans", "DejaVu Sans", Arial, sans-serif',
    "serif": '"Liberation Serif", "Noto Serif", "DejaVu Serif", Georgia, serif',
    "mono": '"Liberation Mono", "Noto Sans Mono", "DejaVu Sans Mono", monospace',
    "display": '"Liberation Sans", "DejaVu Sans", sans-serif',
    "unknown": '"Liberation Sans", "DejaVu Sans", sans-serif',
}


def esc(s: str) -> str:
    return _html.escape(s, quote=True)


def num(v: float) -> str:
    s = f"{float(v):.2f}".rstrip("0").rstrip(".")
    return s if s not in ("", "-0") else "0"


def css_px(v: float) -> str:
    return "0" if abs(v) < 1e-9 else f"{num(v)}px"


@dataclass
class Plan:
    target: str
    options: JSON
    names: dict[str, str] = field(default_factory=dict)  # node id -> class/component name
    pages: dict[str, str] = field(default_factory=dict)  # page id -> file name
    ir_hash: str = ""

    def to_dict(self) -> JSON:
        return {"target": self.target, "adapter_version": ADAPTER_VERSION, "ir_hash": self.ir_hash, "options": self.options, "names": self.names, "pages": self.pages}

    @property
    def hash(self) -> str:
        return hashlib.sha256(canonical_dumps(self.to_dict()).encode()).hexdigest()


DEFAULT_OPTIONS: JSON = {
    "asset_policy": "default", "navigation_policy": "asserted_only", "placeholder_text": "[unreadable text]",
    "instrumentation": True, "theme_mechanism": "prefers_color_scheme", "breakpoint_direction": "mobile_first",
}


@dataclass
class Report:
    ir_hash: str
    plan_hash: str = ""
    target: str = ""
    files: dict[str, str] = field(default_factory=dict)
    assets: list[JSON] = field(default_factory=list)
    uncertain_text: list[JSON] = field(default_factory=list)
    placeholders: list[JSON] = field(default_factory=list)
    fallbacks: list[JSON] = field(default_factory=list)
    deviations: list[JSON] = field(default_factory=list)
    navigation: list[JSON] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def deviate(self, node: str, message: str) -> None:
        self.deviations.append({"node": node, "message": message})

    def to_dict(self) -> JSON:
        return {k: getattr(self, k) for k in ("ir_hash", "plan_hash", "target", "files", "assets", "uncertain_text", "placeholders", "fallbacks", "deviations", "navigation", "warnings")}

    def markdown(self) -> str:
        L = [f"# Screen2Code generation report", "", f"- Target: `{self.target}`", f"- IR content hash: `{self.ir_hash}`", f"- Plan hash: `{self.plan_hash}`", ""]
        def sec(title: str, rows: list[str]) -> None:
            L.append(f"## {title}")
            L.extend(rows or ["_none_"])
            L.append("")
        sec("Assets (provenance)", [f"- `{a['id']}`: {a['provenance']}, rights_status={a['rights_status']}, policy applied: {a['policy_applied']}" + (f", origin region {a['origin_region']}" if a.get("origin_region") else "") + (", lossy pixel crop" if a.get("lossy") else "") for a in self.assets])
        L.insert(-1, "Screen2Code makes no ownership or licensing claim about extracted assets; `rights_status: unknown` means the rights holder is unknown.")
        sec("Uncertain text (verify manually)", [f"- `{u['node']}`: {u['value']!r} ({u['status']})" for u in self.uncertain_text])
        sec("Placeholders", [f"- `{p['asset']}` ({p['reason']})" for p in self.placeholders])
        sec("Layout fallbacks", [f"- `{f['node']}`: {f['mode']} ({f['reason']})" for f in self.fallbacks])
        sec("Deviations from the IR", [f"- `{d['node']}`: {d['message']}" for d in self.deviations])
        sec("Navigation relations (not emitted as behavior)", [f"- {n['a']} -> {n['b']} [{n['status']}]" for n in self.navigation])
        sec("Warnings", [f"- {w}" for w in self.warnings])
        return "\n".join(L)


@dataclass
class Generated:
    files: dict[str, bytes]
    report: Report
    plan: Plan


class FrameworkAdapter(Protocol):
    id: str

    def emit(self, ir: JSON, plan: Plan, read_asset: Callable[[str], bytes], report: Report) -> dict[str, bytes]: ...


def require_committed(ir: JSON) -> None:
    if ir.get("ir_state") != "committed":
        raise S2CError("S2C-GEN-001", "the generator only accepts committed IR", "run reconstruct first")
    rep = validate(ir, 2)
    if not rep.ok:
        raise S2CError("S2C-GEN-001", f"IR is invalid ({len(rep.errors)} errors)", details={"diagnostics": [d.to_dict() for d in rep.errors[:10]]})


def make_plan(ir: JSON, target: str, options: JSON | None = None) -> Plan:
    opts = {**DEFAULT_OPTIONS, **(options or {})}
    if opts["asset_policy"] not in ("strict", "default", "permissive") or opts["navigation_policy"] not in ("asserted_only", "evidenced_and_asserted"):
        raise S2CError("S2C-CONFIG-001", "invalid asset_policy or navigation_policy")
    plan = Plan(target, opts, ir_hash=content_hash(ir))
    counters: dict[str, int] = {}
    used: set[str] = set()
    for nid in _doc_order(ir):
        n = ir["nodes"][nid]
        base = sanitize_name(n.get("role") or n["kind"], "node").lower()
        counters[base] = counters.get(base, 0) + 1
        plan.names[nid] = f"{base}-{counters[base]}"
        used.add(plan.names[nid])
    files: list[str] = []
    for i, pid in enumerate(sorted(ir["pages"], key=lambda p: ir["pages"][p]["name"])):
        name = "index.html" if i == 0 else sanitize_name(ir["pages"][pid]["name"], "page").lower() + ".html"
        plan.pages[pid] = name
        files.append(name)
    check_no_case_collisions(files + ["styles.css", "s2c-report.json", "REPORT.md"])
    return plan


def _doc_order(ir: JSON) -> list[str]:
    out: list[str] = []
    for pid in sorted(ir["pages"], key=lambda p: ir["pages"][p]["name"]):
        st = [ir["pages"][pid]["root"]]
        while st:
            x = st.pop()
            out.append(x)
            st += list(reversed(ir["nodes"][x].get("children", [])))
    for cid in sorted(ir["components"]):
        st = [ir["components"][cid]["root"]]
        while st:
            x = st.pop()
            out.append(x)
            st += list(reversed(ir["nodes"][x].get("children", [])))
    return out
