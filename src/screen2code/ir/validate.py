"""IR validation: L0 schema, L1 referential, L2 semantic/epistemic, L3 quality (IR_SPEC section 17).

``validate`` never mutates the document. Rules are identified by stable diagnostic codes ``S2C-IR-<rule>``.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any, Iterator

from . import vocab as V
from .diagnostics import Report, pointer
from .schema import IR

JSON = Any
LEAF_KINDS = {"text", "image", "icon", "shape", "instance", "slot", "opaque"}
FORBIDDEN_MEASURE_KEYS = {"node", "nodes", "component", "components", "token", "tokens", "asset", "assets", "role", "layout_mode"}
FACETS = ("structure", "role", "layout", "style", "content")


# ----------------------------------------------------------------------------- helpers shared with producers
def required_facets(node: dict[str, JSON]) -> set[str]:
    """Facets that must carry an inference record because the node populates their fields (R-EPI-3)."""
    need = {"structure"}
    if "role" in node or "affordance" in node:
        need.add("role")
    if any(k in node for k in ("layout", "size", "spacing", "placement", "repeat")):
        need.add("layout")
    text = node.get("text") or {}
    media = node.get("media") or {}
    if "style" in node or "style" in text or "fit" in media:
        need.add("style")
    content = text.get("content")
    if isinstance(content, dict) and "param" not in content:
        need.add("content")
    if media and isinstance(media.get("asset"), str):
        need.add("content")
    if "instance" in node or "opaque" in node:
        need.add("content")
    return need


def _text_values(node: dict[str, JSON]) -> Iterator[tuple[str, dict[str, JSON]]]:
    content = (node.get("text") or {}).get("content")
    if isinstance(content, dict) and "status" in content:
        yield "text/content", content
    for name, p in ((node.get("instance") or {}).get("params") or {}).items():
        if isinstance(p, dict) and "status" in p and "value" in p:
            yield f"instance/params/{name}", p


def derive_status(node: dict[str, JSON]) -> str:
    """Node status is derived (R-EPI-8): opaque, partial, or resolved."""
    if node.get("kind") == "opaque":
        return "opaque"
    inf = node.get("inference", {})
    if any(r.get("basis") == "default" for r in inf.values()):
        return "partial"
    if any(v.get("status") in ("uncertain", "unreadable") for _, v in _text_values(node)):
        return "partial"
    return "resolved"


def derive_completeness(doc: dict[str, JSON], page_id: str) -> str:
    for n in doc["nodes"].values():
        if n["scope"] != page_id:
            continue
        if n["kind"] == "opaque" or any(v.get("status") == "unreadable" for _, v in _text_values(n)):
            return "partial"
    return "complete"


def iter_inference(doc: dict[str, JSON]) -> Iterator[tuple[str, str, dict[str, JSON]]]:
    """Yield (path, claim, record) for every inference record in the document."""
    for nid, n in doc["nodes"].items():
        for f, rec in n.get("inference", {}).items():
            yield pointer("nodes", nid, "inference", f), f, rec
    for sid, r in doc["realizations"].items():
        yield pointer("realizations", sid, "inference"), "realization", r["inference"]
        for nid, e in r["nodes"].items():
            if "inference" in e:
                yield pointer("realizations", sid, "nodes", nid, "inference"), "realization", e["inference"]
    for sid, s in doc["screens"].items():
        yield pointer("screens", sid, "inference"), "mode", s["inference"]
    for mid, m in doc["modes"].items():
        yield pointer("modes", mid, "inference"), "mode", m["inference"]
    for pid, p in doc["pages"].items():
        for bid, b in p.get("breakpoints", {}).items():
            yield pointer("pages", pid, "breakpoints", bid, "inference"), "responsive", b["inference"]
        for i, rs in enumerate(p["responsive"]):
            yield pointer("pages", pid, "responsive", i, "inference"), "responsive", rs["inference"]
        for i, c in enumerate(p.get("constraints", [])):
            yield pointer("pages", pid, "constraints", i, "inference"), "layout", c["inference"]
    for cid, c in doc["components"].items():
        yield pointer("components", cid, "inference"), "component", c["inference"]
    for cat, d in doc["tokens"].items():
        if cat == "scales":
            continue
        for tid, t in d.items():
            for f, rec in t["inference"].items():
                yield pointer("tokens", cat, tid, "inference", f), "token", rec
    for aid, a in doc["assets"].items():
        yield pointer("assets", aid, "inference"), "asset", a["inference"]
    for i, r in enumerate(doc["relations"]):
        yield pointer("relations", i, "inference"), "relation", r["inference"]


def children_of(node: dict[str, JSON]) -> list[str]:
    return list(node.get("children", []))


def token_ids(doc: dict[str, JSON]) -> set[str]:
    out: set[str] = set()
    for cat, d in doc["tokens"].items():
        if cat != "scales":
            out |= set(d)
    return out


def _walk(o: JSON, path: str = "") -> Iterator[tuple[str, JSON]]:
    yield path, o
    if isinstance(o, dict):
        for k, v in o.items():
            yield from _walk(v, f"{path}/{k}")
    elif isinstance(o, list):
        for i, v in enumerate(o):
            yield from _walk(v, f"{path}/{i}")


# ----------------------------------------------------------------------------- L1
def _l1(doc: dict[str, JSON], rep: Report) -> None:
    E = rep.error
    for sec in ("sources", "regions", "evidence", "screens", "modes", "pages", "nodes", "components", "assets", "redactions"):
        for k, v in doc[sec].items():
            if v["id"] != k:
                E("S2C-IR-L1-KEY", pointer(sec, k), f"map key {k!r} != id {v['id']!r}")
    for sec in ("relations", "disputes"):
        c = Counter(x["id"] for x in doc[sec])
        for i, n in c.items():
            if n > 1:
                E("S2C-IR-L1-DUP", f"/{sec}", f"duplicate id {i}")
    src, reg, evd, prd = doc["sources"], doc["regions"], doc["evidence"], doc["producers"]
    for rid, r in reg.items():
        if r["source"] not in src:
            E("S2C-IR-L1-REF", pointer("regions", rid, "source"), f"unknown source {r['source']}")
        else:
            ps, rc = src[r["source"]]["pixel_size"], r["rect"]
            if rc["x"] + rc["w"] > ps["w"] or rc["y"] + rc["h"] > ps["h"]:
                E("S2C-IR-L1-BOUNDS", pointer("regions", rid, "rect"), "region extends outside its source image")
        if r["producer"] not in prd:
            E("S2C-IR-L1-REF", pointer("regions", rid, "producer"), f"unknown producer {r['producer']}")
    for eid, e in evd.items():
        if e["producer"] not in prd:
            E("S2C-IR-L1-REF", pointer("evidence", eid, "producer"), f"unknown producer {e['producer']}")
        for rid in e["regions"]:
            if rid not in reg:
                E("S2C-IR-L1-REF", pointer("evidence", eid, "regions"), f"unknown region {rid}")
    pages, nodes, comps, modes, assets, scr, toks = doc["pages"], doc["nodes"], doc["components"], doc["modes"], doc["assets"], doc["screens"], token_ids(doc)
    for sid, s in scr.items():
        r = s["resolved"]
        for what, ref, tab in (("source", s["source"], src), ("page", r["page"], pages), ("mode", r["mode"], modes)):
            if ref not in tab:
                E("S2C-IR-L1-REF", pointer("screens", sid, what), f"unknown {what} {ref}")
        if r["page"] in pages and r["viewport_class"] not in {c["id"] for c in pages[r["page"]]["viewport_classes"]}:
            E("S2C-IR-L1-REF", pointer("screens", sid, "resolved", "viewport_class"), "viewport class not defined on the page")
    scopes = set(pages) | set(comps)
    parent: dict[str, str] = {}
    for nid, n in nodes.items():
        if n["scope"] not in scopes:
            E("S2C-IR-L1-REF", pointer("nodes", nid, "scope"), f"unknown scope {n['scope']}")
        for c in children_of(n):
            if c not in nodes:
                E("S2C-IR-L1-REF", pointer("nodes", nid, "children"), f"unknown child {c}")
                continue
            if nodes[c]["scope"] != n["scope"]:
                E("S2C-IR-L1-SCOPE", pointer("nodes", nid, "children"), f"child {c} is in scope {nodes[c]['scope']}, parent in {n['scope']}")
            if c in parent:
                E("S2C-IR-L1-PARENT", pointer("nodes", nid, "children"), f"node {c} has more than one parent ({parent[c]}, {nid})")
            parent[c] = nid
    roots = set()
    for pid, p in pages.items():
        roots.add(p["root"])
        if p["root"] not in nodes or nodes[p["root"]]["scope"] != pid:
            E("S2C-IR-L1-REF", pointer("pages", pid, "root"), "page root missing or in another scope")
        ids = [c["id"] for c in p["viewport_classes"]]
        if len(set(ids)) != len(ids):
            E("S2C-IR-L1-DUP", pointer("pages", pid, "viewport_classes"), "duplicate viewport class ids")
        if p["base_class"] not in ids:
            E("S2C-IR-L1-REF", pointer("pages", pid, "base_class"), "unknown base class")
        if "base_basis" in p and (p["base_basis"] not in scr or scr[p["base_basis"]]["resolved"]["page"] != pid):
            E("S2C-IR-L1-REF", pointer("pages", pid, "base_basis"), "base_basis must be a screen of this page")
        for c in p["viewport_classes"]:
            for b in (c["min"], c["max_exclusive"]):
                if isinstance(b, str) and b not in p.get("breakpoints", {}):
                    E("S2C-IR-L1-REF", pointer("pages", pid, "viewport_classes", c["id"]), f"unknown breakpoint {b}")
        for i, rs in enumerate(p["responsive"]):
            if rs["target"] not in nodes or nodes[rs["target"]]["scope"] != pid:
                E("S2C-IR-L1-REF", pointer("pages", pid, "responsive", i, "target"), "target not in this page")
            for w in rs["when"]:
                if w not in ids:
                    E("S2C-IR-L1-REF", pointer("pages", pid, "responsive", i, "when"), f"unknown viewport class {w}")
    for cid, c in comps.items():
        roots.add(c["root"])
        if c["root"] not in nodes or nodes[c["root"]]["scope"] != cid:
            E("S2C-IR-L1-REF", pointer("components", cid, "root"), "component root missing or in another scope")
        for pn, spec in c["params"].items():
            b = spec.get("bind")
            if b and (b["node"] not in nodes or nodes[b["node"]]["scope"] != cid):
                E("S2C-IR-L1-REF", pointer("components", cid, "params", pn, "bind"), "bound node is not in this component")
    # reachability (children + slot_content)
    reach: set[str] = set()
    stack = [r for r in roots if r in nodes]
    while stack:
        x = stack.pop()
        if x in reach:
            continue
        reach.add(x)
        stack += [c for c in children_of(nodes[x]) if c in nodes]
        for lst in ((nodes[x].get("instance") or {}).get("slot_content") or {}).values():
            stack += [c for c in lst if c in nodes]
    for nid in nodes:
        if nid not in reach:
            E("S2C-IR-L1-ORPHAN", pointer("nodes", nid), "node is not reachable from any page or component root (or is part of a cycle)")
    # component graph acyclic
    uses: dict[str, set[str]] = defaultdict(set)
    for nid, n in nodes.items():
        if n["scope"] in comps and "instance" in n and n["instance"]["component"] in comps:
            uses[n["scope"]].add(n["instance"]["component"])
    state: dict[str, int] = {}

    def dfs(c: str) -> bool:
        state[c] = 1
        for d in uses.get(c, ()):
            if state.get(d) == 1 or (d not in state and dfs(d)):
                return True
        state[c] = 2
        return False

    for c in comps:
        if c not in state and dfs(c):
            E("S2C-IR-L1-CYCLE", pointer("components", c), "component definitions are cyclic")
            break
    # references inside nodes
    for nid, n in nodes.items():
        base = pointer("nodes", nid)
        for p, v in _walk(n):
            if isinstance(v, dict) and set(v) >= {"token"} and isinstance(v["token"], str) and v["token"] not in toks:
                E("S2C-IR-L1-REF", base + p, f"unknown token {v['token']}")
        if "instance" in n:
            i = n["instance"]
            if i["component"] not in comps:
                E("S2C-IR-L1-REF", base + "/instance/component", f"unknown component {i['component']}")
            else:
                spec = comps[i["component"]]["params"]
                for pn, pv in (i.get("params") or {}).items():
                    if pn not in spec:
                        E("S2C-IR-L1-PARAM", base + f"/instance/params/{pn}", "parameter not declared by the component")
                    elif spec[pn]["type"] == "asset" and not (isinstance(pv, dict) and pv.get("asset") in assets):
                        E("S2C-IR-L1-REF", base + f"/instance/params/{pn}", "asset parameter must reference a known asset")
                for pn, ps in spec.items():
                    if ps.get("required") and pn not in (i.get("params") or {}) and "default" not in ps:
                        E("S2C-IR-L1-PARAM", base + "/instance/params", f"required parameter {pn!r} missing")
        m = n.get("media")
        if m and isinstance(m["asset"], str) and m["asset"] not in assets:
            E("S2C-IR-L1-REF", base + "/media/asset", f"unknown asset {m['asset']}")
        if "opaque" in n and n["opaque"]["asset"] not in assets:
            E("S2C-IR-L1-REF", base + "/opaque/asset", "unknown asset")
        if "repeat" in n and n["repeat"]["component"] not in comps:
            E("S2C-IR-L1-REF", base + "/repeat/component", "unknown component")
        fill = (n.get("style") or {}).get("fill")
        if fill and fill.get("kind") == "image" and fill["asset"] not in assets:
            E("S2C-IR-L1-REF", base + "/style/fill/asset", "unknown asset")
    # supports / against anywhere outside evidence resolve
    for sec in ("nodes", "realizations", "screens", "modes", "pages", "components", "tokens", "assets", "relations", "disputes"):
        for p, v in _walk(doc[sec], pointer(sec)):
            if isinstance(v, dict):
                for key in ("supports", "against"):
                    if isinstance(v.get(key), list):
                        for ref in v[key]:
                            if ref not in evd:
                                E("S2C-IR-L1-REF", f"{p}/{key}", f"unknown evidence {ref}")
    for aid, a in assets.items():
        o = a.get("origin") or {}
        if "region" in o and o["region"] not in reg:
            E("S2C-IR-L1-REF", pointer("assets", aid, "origin", "region"), "unknown region")
        for m, ref in (a.get("mode_variants") or {}).items():
            if m not in modes or ref not in assets:
                E("S2C-IR-L1-REF", pointer("assets", aid, "mode_variants", m), "unknown mode or asset")
    for cat, d in doc["tokens"].items():
        if cat == "scales":
            for k, ids in d.items():
                for t in ids:
                    if t not in toks:
                        E("S2C-IR-L1-REF", pointer("tokens", "scales", k), f"unknown token {t}")
            continue
        for tid, t in d.items():
            if "aliases_of" in t and t["aliases_of"] not in toks:
                E("S2C-IR-L1-REF", pointer("tokens", cat, tid, "aliases_of"), "unknown token")
            for m in t.get("by_mode", {}):
                if m not in modes:
                    E("S2C-IR-L1-REF", pointer("tokens", cat, tid, "by_mode", m), f"unknown mode {m} (R-MODE-1)")
    for i, r in enumerate(doc["relations"]):
        if r["a"] not in nodes:
            E("S2C-IR-L1-REF", pointer("relations", i, "a"), "unknown node")
        if r["b"] is not None and r["b"] not in nodes and r["b"] not in pages and r["b"] not in comps:
            E("S2C-IR-L1-REF", pointer("relations", i, "b"), "unknown target")
    for i, d in enumerate(doc["disputes"]):
        if d["target"] not in nodes:
            E("S2C-IR-L1-REF", pointer("disputes", i, "target"), "unknown node")
    for sid, r in doc["realizations"].items():
        if sid not in scr:
            E("S2C-IR-L1-REF", pointer("realizations", sid), "unknown screen")
            continue
        for nid, e in r["nodes"].items():
            inst, _, inner = nid.partition("/")  # component-internal observations: <instance id>/<definition node id>
            if inner and not (nodes.get(inst, {}).get("kind") == "instance" and inner in nodes and nodes[inner]["scope"] == nodes[inst]["instance"]["component"]):
                E("S2C-IR-L1-REF", pointer("realizations", sid, "nodes", nid), "internal realization must reference an instance and one of its component's nodes")
            elif not inner and nid not in nodes:
                E("S2C-IR-L1-REF", pointer("realizations", sid, "nodes", nid), "unknown node")
            for rid in e["regions"]:
                if rid not in reg:
                    E("S2C-IR-L1-REF", pointer("realizations", sid, "nodes", nid), f"unknown region {rid}")
                elif reg[rid]["source"] != scr[sid]["source"]:
                    E("S2C-IR-L1-REF", pointer("realizations", sid, "nodes", nid), f"region {rid} belongs to another source")
    for rid, r in doc["redactions"].items():
        if r["producer"] not in prd:
            E("S2C-IR-L1-REF", pointer("redactions", rid, "producer"), "unknown producer")
    for pid, p in prd.items():
        pass


# ----------------------------------------------------------------------------- L2
def _check_record(rep: Report, doc: dict[str, JSON], path: str, claim: str, rec: dict[str, JSON]) -> None:
    evd = doc["evidence"]
    sup = rec["supports"]
    if rec["basis"] == "default" and sup:
        rep.error("S2C-IR-R-EPI-3", path, "basis 'default' must have empty supports")
    if rec["basis"] == "evidence" and not sup:
        rep.error("S2C-IR-R-EPI-3", path, "basis 'evidence' requires non-empty supports")
    if rec["basis"] == "asserted" or rec["calibration"] == "asserted":
        if not (rec["basis"] == "asserted" and rec["calibration"] == "asserted" and rec["confidence"] == 1):
            rep.error("S2C-IR-R-EPI-5", path, "asserted records need basis=asserted, calibration=asserted, confidence=1")
        if not sup or any(evd.get(s, {}).get("kind") != "user_assertion" for s in sup):
            rep.error("S2C-IR-R-EPI-5", path, "asserted values must be supported by user_assertion evidence only")
    allowed = V.ALLOWED_SUPPORTS[claim]
    for s in sup:
        k = evd.get(s, {}).get("kind")
        if k is not None and k not in allowed:
            rep.error("S2C-IR-R-EPI-4", path, f"evidence {s} of kind {k!r} may not support a {claim!r} claim")


def _flex_is_stack(node: dict[str, JSON], nodes: dict[str, JSON]) -> bool:
    f = node["layout"]["flex"]
    if f.get("wrap"):
        return False
    for c in children_of(node):
        fl = (nodes[c].get("placement") or {}).get("flex") or {}
        if fl.get("grow", 0) or fl.get("shrink", 0):
            return False
    return True


def _l2(doc: dict[str, JSON], rep: Report) -> None:
    E, W = rep.error, rep.warn
    nodes, pages, scr, modes, evd = doc["nodes"], doc["pages"], doc["screens"], doc["modes"], doc["evidence"]
    for path, claim, rec in iter_inference(doc):
        _check_record(rep, doc, path, claim, rec)
    # R-EPI-1 / R-EPI-2
    for eid, e in evd.items():
        for p, v in _walk(e["measure"], pointer("evidence", eid, "measure")):
            if isinstance(v, dict) and (set(v) & FORBIDDEN_MEASURE_KEYS):
                E("S2C-IR-R-EPI-1", p, f"observed evidence must not contain structural vocabulary: {sorted(set(v) & FORBIDDEN_MEASURE_KEYS)}")
    for sec in ("nodes", "pages", "components", "tokens", "assets"):
        for p, v in _walk(doc[sec], pointer(sec)):
            if isinstance(v, dict) and set(v) >= {"x", "y", "w", "h"}:
                E("S2C-IR-R-EPI-2", p, "structure sections must not contain pixel rectangles (R-LAYER-1)")
    pstate = doc["project"]["redaction"]["mode"]
    for nid, n in nodes.items():
        base = pointer("nodes", nid)
        kind = n["kind"]
        miss = required_facets(n) - set(n.get("inference", {}))
        if miss:
            E("S2C-IR-R-EPI-3", base + "/inference", f"populated facets without an inference record: {sorted(miss)}")
        if kind in LEAF_KINDS and children_of(n):
            E("S2C-IR-L2-LEAF", base + "/children", f"{kind} nodes cannot have children")
        for field, kinds in (("text", {"text"}), ("media", {"image", "icon"}), ("instance", {"instance"}), ("opaque", {"opaque"})):
            if field in n and kind not in kinds:
                E("S2C-IR-L2-KIND", f"{base}/{field}", f"field {field!r} is not valid on kind {kind!r}")
        for kk, field in (("text", "text"), ("instance", "instance"), ("opaque", "opaque")):
            if kind == kk and field not in n:
                E("S2C-IR-L2-KIND", base, f"kind {kind!r} requires field {field!r}")
        if kind == "image" and "media" not in n:
            E("S2C-IR-L2-KIND", base, "kind 'image' requires field 'media'")
        if n["status"] != derive_status(n):
            E("S2C-IR-R-EPI-8", base + "/status", f"status {n['status']!r} does not match derived {derive_status(n)!r}")
        for where, tv in _text_values(n):
            st, val = tv["status"], tv["value"]
            if st in ("unreadable", "redacted") and val is not None:
                E("S2C-IR-L2-TEXT", f"{base}/{where}", f"status {st!r} requires value null")
            if st in ("verified", "inferred", "uncertain") and val is None:
                E("S2C-IR-L2-TEXT", f"{base}/{where}", f"status {st!r} requires a value")
            if st == "redacted" and pstate == "off":
                E("S2C-IR-L2-REDACT", f"{base}/{where}", "redacted text while project redaction is off")
        lay = n.get("layout")
        if lay:
            mode = lay["mode"]
            for sub in ("stack", "flex", "grid", "overlay", "absolute"):
                if (sub in lay) != (sub == mode):
                    E("S2C-IR-L2-LAYOUT", base + "/layout", f"layout.mode={mode!r} requires exactly the {mode!r} sub-object" if sub == mode or mode == "none" else f"unexpected {sub!r} sub-object for mode {mode!r}")
                    break
            if mode == "flex" and "flex" in lay and _flex_is_stack(n, nodes):
                E("S2C-IR-L2-CANON", base + "/layout", "flex without wrap/grow/shrink must be serialized as stack (canonicalization)")
            if mode == "grid" and "grid" in lay:
                used: dict[tuple[int, int], str] = {}
                ncols = len(lay["grid"]["columns"])
                for c in children_of(n):
                    g = (nodes[c].get("placement") or {}).get("grid")
                    if not g:
                        continue
                    (c0, cs), (r0, rs_) = g.get("col", [1, 1]), g.get("row", [1, 1])
                    if c0 + cs - 1 > ncols:
                        E("S2C-IR-L2-GRID", pointer("nodes", c, "placement"), "explicit column placement exceeds the declared tracks")
                    for cc in range(c0, c0 + cs):
                        for rr in range(r0, r0 + rs_):
                            if (cc, rr) in used:
                                E("S2C-IR-L2-GRID", pointer("nodes", c, "placement"), f"overlaps the explicit placement of {used[(cc, rr)]}")
                            used[(cc, rr)] = c
            if mode == "flex" and "flex" in lay:
                axis = lay["flex"]["axis"]
                for c in children_of(n):
                    sz = (nodes[c].get("size") or {}).get("w" if axis == "horizontal" else "h") or {}
                    if sz.get("kind") == "fill":
                        E("S2C-IR-L2-FLEX", pointer("nodes", c, "size"), "'fill' is not allowed on a flex main axis; use grow")
            for c in children_of(n):
                pl = (nodes[c].get("placement") or {})
                for k in pl:
                    if k != mode:
                        E("S2C-IR-L2-PLACEMENT", pointer("nodes", c, "placement"), f"placement.{k} does not match parent layout mode {mode!r}")
        else:
            for c in children_of(n):
                if nodes[c].get("placement"):
                    E("S2C-IR-L2-PLACEMENT", pointer("nodes", c, "placement"), "parent has no layout; placement is meaningless")
        for ax in ("w", "h"):
            s = (n.get("size") or {}).get(ax)
            if s and s["kind"] == "fixed" and "px" not in s:
                E("S2C-IR-L2-SIZE", f"{base}/size/{ax}", "fixed size requires px")
        if "repeat" in n:
            kids = [nodes[c] for c in children_of(n)]
            if any(not ("instance" in k and k["instance"]["component"] == n["repeat"]["component"]) for k in kids):
                W("S2C-IR-L2-REPEAT", base + "/repeat", "children are not all instances of the repeat component")
    # pages
    for pid, p in pages.items():
        classes = p["viewport_classes"]
        bps = p.get("breakpoints", {})

        def val(b: JSON) -> float | None:
            if isinstance(b, str):
                return float(bps[b]["selected"]) if b in bps else None
            return None if b is None else float(b)

        prev_max = 0.0
        for i, c in enumerate(classes):
            lo, hi = val(c["min"]), val(c["max_exclusive"])
            if lo is None or (i == 0 and lo != 0) or (i > 0 and lo != prev_max):
                E("S2C-IR-L2-VIEWPORT", pointer("pages", pid, "viewport_classes", i), "viewport classes must partition [0, inf) in order")
            if (hi is None) != (i == len(classes) - 1):
                E("S2C-IR-L2-VIEWPORT", pointer("pages", pid, "viewport_classes", i), "only the last class may be unbounded")
            prev_max = hi if hi is not None else prev_max
        widths: dict[str, list[float]] = defaultdict(list)
        for s in scr.values():
            if s["resolved"]["page"] == pid:
                widths[s["resolved"]["viewport_class"]].append(float(s["resolved"]["viewport_width"]))
        for i, c in enumerate(classes):
            for s in scr.values():
                if s["resolved"]["page"] == pid and s["resolved"]["viewport_class"] == c["id"]:
                    lo, hi = val(c["min"]), val(c["max_exclusive"])
                    w = s["resolved"]["viewport_width"]
                    if lo is not None and (w < lo or (hi is not None and w >= hi)):
                        E("S2C-IR-L2-VIEWPORT", pointer("screens", s["id"], "resolved"), f"viewport width {w} lies outside class {c['id']}")
            if i + 1 < len(classes):
                bid = c["max_exclusive"]
                if isinstance(bid, str) and bid in bps:
                    if widths.get(c["id"]) and widths.get(classes[i + 1]["id"]):
                        interval = [max(widths[c["id"]]), min(widths[classes[i + 1]["id"]])]
                        b = bps[bid]
                        if [float(x) for x in b["known_interval"]] != interval:
                            E("S2C-IR-R-EPI-8", pointer("pages", pid, "breakpoints", bid, "known_interval"), f"known_interval {b['known_interval']} != recomputed {interval}")
                        elif not (interval[0] < b["selected"] <= interval[1]):
                            E("S2C-IR-L2-VIEWPORT", pointer("pages", pid, "breakpoints", bid, "selected"), "selected threshold must lie within known_interval")
                    else:
                        W("S2C-IR-L2-VIEWPORT", pointer("pages", pid, "breakpoints", bid), "cannot recompute known_interval: a class has no observing screen")
        for i, rs in enumerate(p["responsive"]):
            tgt = nodes.get(rs["target"], {})
            for j, op in enumerate(rs["patch"]):
                path = pointer("pages", pid, "responsive", i, "patch", j)
                kind = op["op"]
                if kind == "set":
                    pp = op.get("path", "")
                    if "value" not in op or not any(pp == q.rstrip(".") or pp.startswith(q) for q in V.PATCH_SET_PATH_PREFIXES):
                        E("S2C-IR-L2-PATCH", path, f"set path {pp!r} is not in the responsive whitelist or has no value")
                elif kind == "reorder":
                    if op.get("path") != "children" or sorted(op.get("value", [])) != sorted(children_of(tgt)):
                        E("S2C-IR-L2-PATCH", path, "reorder must permute the target's children")
                elif kind == "swap_variant":
                    if "instance" not in tgt:
                        E("S2C-IR-L2-PATCH", path, "swap_variant target must be an instance")
        if p["completeness"]["state"] != derive_completeness(doc, pid):
            E("S2C-IR-R-EPI-8", pointer("pages", pid, "completeness"), f"completeness must be {derive_completeness(doc, pid)!r}")
        # realization coverage
        hidden_by_class: dict[str, set[str]] = defaultdict(set)
        for rs in p["responsive"]:
            if any(o["op"] == "hide" for o in rs["patch"]):
                for w in rs["when"]:
                    hidden_by_class[w].add(rs["target"])
        for sid, s in scr.items():
            if s["resolved"]["page"] != pid or sid not in doc["realizations"]:
                if s["resolved"]["page"] == pid:
                    E("S2C-IR-L2-REALIZE", pointer("realizations", sid), "screen has no realizations")
                continue
            real = doc["realizations"][sid]["nodes"]
            hidden: set[str] = set()
            for h in hidden_by_class.get(s["resolved"]["viewport_class"], ()):
                st = [h]
                while st:
                    x = st.pop()
                    hidden.add(x)
                    st += children_of(nodes.get(x, {}))
            for nid, n in nodes.items():
                if n["scope"] == pid and nid not in real and nid not in hidden:
                    E("S2C-IR-L2-REALIZE", pointer("realizations", sid, "nodes"), f"visible page node {nid} has no realization on screen {sid}")
    # modes and tokens (R-MODE)
    mode_of_source: dict[str, set[str]] = defaultdict(set)
    for s in scr.values():
        mode_of_source[s["source"]].add(s["resolved"]["mode"])
    for cat, d in doc["tokens"].items():
        if cat == "scales":
            continue
        for tid, t in d.items():
            tp = pointer("tokens", cat, tid)
            if ("value" in t) == ("by_mode" in t):
                E("S2C-IR-L2-TOKEN", tp, "exactly one of 'value' or 'by_mode' is required")
            for m, bm in t.get("by_mode", {}).items():
                if not bm["supports"]:
                    E("S2C-IR-R-MODE-2", f"{tp}/by_mode/{m}", "per-mode value needs supporting evidence")
                for s_ in bm["supports"]:
                    e = evd.get(s_)
                    if not e:
                        continue
                    if e["kind"] not in V.ALLOWED_SUPPORTS["token"]:
                        E("S2C-IR-R-EPI-4", f"{tp}/by_mode/{m}", f"evidence {s_} of kind {e['kind']!r} cannot support a token value")
                    srcs = {doc["regions"][r]["source"] for r in e["regions"] if r in doc["regions"]}
                    if e["basis"] != "asserted" and not any(m in mode_of_source.get(sx, set()) for sx in srcs):
                        E("S2C-IR-R-MODE-2", f"{tp}/by_mode/{m}", f"evidence {s_} does not come from a screen resolved to mode {m}")
    # navigation
    for i, r in enumerate(doc["relations"]):
        p = pointer("relations", i)
        if r["kind"] != "navigates_to":
            if "status" in r:
                E("S2C-IR-R-NAV", p, "status is only valid on navigates_to")
            continue
        st = r.get("status")
        kinds = {evd[s]["kind"] for s in r["inference"]["supports"] if s in evd}
        if st is None:
            E("S2C-IR-R-NAV", p, "navigates_to requires a status")
        elif st == "unknown" and r["b"] is not None:
            E("S2C-IR-R-NAV", p, "status 'unknown' requires b = null")
        elif st != "unknown" and r["b"] is None:
            E("S2C-IR-R-NAV", p, f"status {st!r} requires a target")
        if st == "evidenced" and "navigation_cue" not in kinds:
            E("S2C-IR-R-NAV", p, "'evidenced' navigation needs navigation_cue evidence")
        if st == "inferred" and not r["inference"]["supports"]:
            E("S2C-IR-R-NAV", p, "'inferred' navigation needs supporting evidence")
        if st == "user_asserted" and (r["inference"]["calibration"] != "asserted" or "user_assertion" not in kinds):
            E("S2C-IR-R-NAV", p, "'user_asserted' navigation requires an asserted record backed by user_assertion evidence")
        if st in ("inferred", "evidenced", "unknown") and r["inference"]["calibration"] == "asserted":
            E("S2C-IR-R-NAV", p, "navigation cannot be asserted without status 'user_asserted' (no silent promotion)")
    # assets
    for aid, a in doc["assets"].items():
        p, prov, o = pointer("assets", aid), a["provenance"], a.get("origin") or {}
        if prov == "extracted":
            if "content" not in a or not {"region", "fidelity", "resolution_scale", "lossy"} <= set(o):
                E("S2C-IR-L2-ASSET", p, "extracted assets need content and origin{region, fidelity, resolution_scale, lossy}")
            elif o["fidelity"] == "pixel_crop" and o["lossy"] is not True:
                E("S2C-IR-L2-ASSET", p, "a pixel crop is lossy by definition")
        elif prov == "reconstructed":
            if "content" not in a or not {"method", "region"} <= set(o):
                E("S2C-IR-L2-ASSET", p, "reconstructed assets need content and origin{method, region}")
        else:
            if "placeholder" not in a:
                E("S2C-IR-L2-ASSET", p, "placeholder assets need a placeholder descriptor")
            if "content" in a or o:
                E("S2C-IR-L2-ASSET", p, "a placeholder must not carry content bytes or an origin (AS-1)")
        rs = a["rights_status"]
        if rs == "not_applicable" and prov != "placeholder":
            E("S2C-IR-L2-RIGHTS", p, "not_applicable rights are only valid for placeholders")
        if prov == "placeholder" and rs != "not_applicable":
            E("S2C-IR-L2-RIGHTS", p, "placeholders have rights_status not_applicable")
        if rs == "user_declared":
            if "rights" not in a or any(evd.get(s, {}).get("kind") != "user_assertion" for s in a["rights"]["supports"]):
                E("S2C-IR-L2-RIGHTS", p, "user_declared rights need a rights record backed by user_assertion evidence")
        elif "rights" in a:
            E("S2C-IR-L2-RIGHTS", p, "a rights record is only valid with rights_status user_declared")
        for s_ in a["hint"]["supports"]:
            e = evd.get(s_)
            if e and e["kind"] == "asset_candidate":
                m = e["measure"]
                if "aspect" in m and abs(m["aspect"] - a["hint"]["aspect"]) > 0.01:
                    E("S2C-IR-R-EPI-8", p + "/hint/aspect", "hint aspect differs from its supporting evidence")
                if "dominant_color" in m and m["dominant_color"].upper() != a["hint"]["dominant_color"]["hex"]:
                    E("S2C-IR-R-EPI-8", p + "/hint/dominant_color", "hint color differs from its supporting evidence")
    if pstate == "off":
        if doc["redactions"]:
            E("S2C-IR-L2-REDACT", "/redactions", "redaction records exist while project redaction is off")
        if any(s.get("redaction", {}).get("applied") for s in doc["sources"].values()):
            E("S2C-IR-L2-REDACT", "/sources", "source marked redacted while project redaction is off")


# ----------------------------------------------------------------------------- L3
def quality_report(doc: dict[str, JSON]) -> dict[str, JSON]:
    nodes = doc["nodes"]
    cfg = doc["inference_config"]["values"]
    n_abs = sum(1 for n in nodes.values() if (n.get("layout") or {}).get("mode") == "absolute")
    n_layout = sum(1 for n in nodes.values() if n.get("layout"))
    fixed_unsupported = []
    for nid, n in nodes.items():
        sz = n.get("size") or {}
        if any((sz.get(a) or {}).get("kind") == "fixed" for a in ("w", "h")):
            sup = (n.get("inference", {}).get("layout") or {}).get("supports", [])
            if not any(doc["evidence"].get(s, {}).get("kind") in ("size_sample", "asset_candidate") for s in sup):
                fixed_unsupported.append(nid)
    lits: Counter[str] = Counter()
    for n in nodes.values():
        for _, v in _walk(n):
            if isinstance(v, dict) and "literal" in v:
                lits[v["literal"]["hex"]] += 1
    reg_counts = Counter(p for n in nodes.values() for r in n.get("inference", {}).values() if r["basis"] == "default" for p in [r["method"]])
    texts = [tv for n in nodes.values() for _, tv in _text_values(n)]
    return {
        "absolute_ratio": (n_abs / n_layout) if n_layout else 0.0,
        "absolute_ratio_limit": cfg.get("layout.absolute.max_ratio", 0.05),
        "nodes": len(nodes),
        "default_basis_claims": sum(reg_counts.values()),
        "opaque_nodes": sum(1 for n in nodes.values() if n["kind"] == "opaque"),
        "partial_nodes": sum(1 for n in nodes.values() if n["status"] == "partial"),
        "uncertain_text": sum(1 for t in texts if t["status"] == "uncertain"),
        "unreadable_text": sum(1 for t in texts if t["status"] == "unreadable"),
        "contested_disputes": sum(1 for d in doc["disputes"] if d["status"] == "contested"),
        "unknown_rights_assets": sorted(a for a, v in doc["assets"].items() if v["rights_status"] == "unknown"),
        "fixed_sizes_without_support": fixed_unsupported,
        "repeated_literals": sorted(h for h, c in lits.items() if c >= 3),
        "incomplete_mode_tokens": sorted(
            t["id"] for cat, d in doc["tokens"].items() if cat != "scales" for t in d.values() if "by_mode" in t and set(t["by_mode"]) != set(doc["modes"])
        ),
    }


def _l3(doc: dict[str, JSON], rep: Report) -> None:
    q = quality_report(doc)
    if q["absolute_ratio"] > q["absolute_ratio_limit"]:
        rep.warn("S2C-IR-L3-ABSOLUTE", "/nodes", f"absolute layout ratio {q['absolute_ratio']:.2f} exceeds {q['absolute_ratio_limit']}")
    for k, msg in (
        ("fixed_sizes_without_support", "fixed sizes without size evidence"), ("repeated_literals", "literal colors repeated at least 3 times without a token"),
        ("unknown_rights_assets", "assets with unknown rights"), ("incomplete_mode_tokens", "tokens lacking values in some registered modes"),
    ):
        if q[k]:
            rep.warn(f"S2C-IR-L3-{k.upper()}", "/", f"{msg}: {q[k]}") if k != "unknown_rights_assets" else rep.info("S2C-IR-L3-RIGHTS", "/", f"{msg}: {q[k]}")
    for k in ("default_basis_claims", "uncertain_text", "unreadable_text", "contested_disputes", "opaque_nodes"):
        if q[k]:
            rep.info(f"S2C-IR-L3-{k.upper()}", "/", f"{k.replace('_', ' ')}: {q[k]}")


def validate(doc: dict[str, JSON], level: int = 3) -> Report:
    """Validate ``doc`` up to ``level`` (0..3). L1+ run only if L0 passes."""
    rep = Report()
    IR.check(doc, "", rep)
    if level < 1 or not rep.ok:
        return rep
    _l1(doc, rep)
    if level < 2 or not rep.ok:
        return rep
    _l2(doc, rep)
    if level >= 3 and rep.ok:
        _l3(doc, rep)
    return rep
