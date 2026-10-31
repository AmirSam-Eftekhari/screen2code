"""Deterministic, explainable refinement proposals (EVALUATION section 8). Pure functions: report + IR in, patches out.

Every rule corrects a *measured* discrepancy between the rendered box of a node and the box observed in the screenshot. Rules are bounded
(``max_step_px``), never change structure (kind, hierarchy, component identity, layout mode) and never touch asserted values.
"""
from __future__ import annotations

import copy
from typing import Any

from ..ir import derive_id

JSON = dict[str, Any]
RULE_VERSION = 1
TOL_PX = 0.75


def _parents(ir: JSON) -> dict[str, str]:
    return {c: pid for pid, n in ir["nodes"].items() for c in n.get("children", [])}


def _asserted(node: JSON) -> bool:
    return any(r.get("calibration") == "asserted" for r in node.get("inference", {}).values())


def propose(ir: JSON, report: JSON, max_step_px: float = 24.0) -> list[JSON]:
    """Return patches (sorted, deterministic) that address the layout errors in ``report['per_node']``."""
    err = {r["node"]: r for r in report["per_node"] if "dx" in r}
    parents = _parents(ir)
    patches: list[JSON] = []

    def clamp(v: float) -> float:
        return max(-max_step_px, min(max_step_px, v))

    def add(node: str, kind: str, rule: str, **kw: Any) -> None:
        if not _asserted(ir["nodes"][node]):
            patches.append({"node": node, "kind": kind, "rule": rule, **kw, "evidence_of": {k: err[node][k] for k in ("dx", "dy", "dw", "dh") if node in err}})

    for pid in sorted(ir["nodes"]):
        p = ir["nodes"][pid]
        lay = p.get("layout") or {}
        stack = lay.get("stack") or lay.get("flex")
        kids = [c for c in p.get("children", []) if c in err]
        if not stack or len(kids) != len(p.get("children", [])) or not kids:
            continue
        v = stack["axis"] == "vertical"
        pos, size = ("dy", "dh") if v else ("dx", "dw")
        side = "top" if v else "left"
        # first child: its offset from the parent is the parent's leading padding
        if pid in err:
            lead = err[kids[0]][pos] - err[pid][pos]
            if abs(lead) >= TOL_PX and p["kind"] == "box":
                cur = ((p.get("spacing") or {}).get("padding") or {}).get(side, ((p.get("spacing") or {}).get("padding") or {}).get("all", {"px": 0}))
                cur_px = cur.get("px", _token_px(ir, cur))
                add(pid, "padding", "refine.padding/1", side=side, value=round(max(0.0, cur_px - clamp(lead)), 2), previous=cur_px)
        gap_errs = []
        for i in range(1, len(kids)):
            a, b = err[kids[i - 1]], err[kids[i]]
            gap_errs.append((kids[i], b[pos] - a[pos] - a[size]))
        for kid, ge in gap_errs:
            if abs(ge) < TOL_PX:
                continue
            node = ir["nodes"][kid]
            cur = ((node.get("spacing") or {}).get("margin") or {}).get(side, {"px": 0})
            cur_px = cur.get("px", _token_px(ir, cur))
            new = max(0.0, cur_px - clamp(ge))
            if abs(new - cur_px) >= TOL_PX:
                add(kid, "margin", "refine.margin/1", side=side, value=round(new, 2), previous=cur_px)
    for nid, e in sorted(err.items()):
        n = ir["nodes"][nid]
        if n["kind"] == "text" and abs(e["dh"]) >= 1.0:
            st = n["text"]["style"]
            lh = (st.get("overrides", {}).get("line_height") if "token" in st else st.get("line_height")) or {}
            if "px" in lh:
                add(nid, "line_height", "refine.line_height/1", value=round(max(8.0, lh["px"] - clamp(e["dh"])), 2), previous=lh["px"])
        elif n["kind"] == "image" and ((n.get("size") or {}).get("w") or {}).get("kind") == "fixed" and abs(e["dw"]) >= 1.0:
            w = n["size"]["w"]["px"]
            add(nid, "size", "refine.size/1", axis="w", value=round(max(1.0, w - clamp(e["dw"])), 2), previous=w)
    seen: set[tuple] = set()
    out = []
    for p in sorted(patches, key=lambda p: (p["node"], p["kind"], p.get("side", ""), p.get("axis", ""))):
        key = (p["node"], p["kind"], p.get("side"), p.get("axis"))
        if key not in seen:
            seen.add(key)
            out.append(p)
    return out


def _token_px(ir: JSON, dim: JSON) -> float:
    if "px" in dim:
        return float(dim["px"])
    for cat, d in ir["tokens"].items():
        if cat != "scales" and dim.get("token") in d:
            return float(d[dim["token"]]["value"]["px"])
    return 0.0


def apply(ir: JSON, patches: list[JSON], report: JSON, iteration: int, producer_id: str) -> JSON:
    """Return a patched copy of ``ir``. New measured evidence (``layout_residual``) is added; existing evidence is never modified (R-EPI-7)."""
    out = copy.deepcopy(ir)
    out["producers"].setdefault(producer_id, {"class": "classical", "id": "s2c.refine-measure", "version": f"0.{RULE_VERSION}.0"})
    scr = sorted(out["screens"])[0]
    for p in patches:
        n = out["nodes"][p["node"]]
        facet = "style" if p["kind"] == "line_height" else "layout"
        if p["kind"] == "padding":
            n.setdefault("spacing", {}).setdefault("padding", {})
            pad = n["spacing"]["padding"]
            if "all" in pad:  # expand shorthand before editing one side
                allv = pad.pop("all")
                for s in ("top", "right", "bottom", "left"):
                    pad.setdefault(s, allv)
            pad[p["side"]] = {"px": p["value"]}
        elif p["kind"] == "margin":
            n.setdefault("spacing", {}).setdefault("margin", {})[p["side"]] = {"px": p["value"]}
        elif p["kind"] == "size":
            n["size"][p["axis"]] = {**n["size"][p["axis"]], "px": p["value"]}
        elif p["kind"] == "line_height":
            st = n["text"]["style"]
            if "token" in st:
                st.setdefault("overrides", {})["line_height"] = {"px": p["value"]}
            else:
                st["line_height"] = {"px": p["value"]}
        regs = out["realizations"][scr]["nodes"][p["node"]]["regions"]
        measure = {"dx": p["evidence_of"].get("dx"), "dy": p["evidence_of"].get("dy"), "dw": p["evidence_of"].get("dw"), "dh": p["evidence_of"].get("dh"), "iteration": iteration, "unit": "design px (rendered minus observed)"}
        eid = derive_id("evd", "refine", iteration, p["node"], p["kind"], p.get("side", ""), p.get("axis", ""))
        out["evidence"][eid] = {"id": eid, "kind": "layout_residual", "basis": "measured", "producer": producer_id, "regions": sorted(regs), "measure": measure}
        old = n["inference"].get(facet) or {"confidence": 0.5, "supports": []}
        n["inference"][facet] = {"method": p["rule"], "calibration": "heuristic", "basis": "evidence", "confidence": min(old["confidence"], 0.8),
                                 "supports": sorted(set(old.get("supports", []) + [eid]))}
    return out
