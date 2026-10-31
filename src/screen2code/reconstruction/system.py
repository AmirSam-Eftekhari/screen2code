"""S9 token inference and S8 component inference (PIPELINE sections 4.8-4.9; IR_SPEC sections 11-12, 19A-B).

Tokens are clustered from literals actually present in the IR and supported by the measured evidence cited by the nodes that use them.
Components follow the under-merge rule: a subtree becomes a shared component only if its structure AND style signatures are equal
after masking content, it occurs at least ``component.min_support`` times, and it contains no opaque region. Anything else stays separate.
"""
from __future__ import annotations

import colorsys
import copy
from collections import Counter, defaultdict
from typing import Any

import numpy as np
from skimage.color import deltaE_ciede2000, rgb2lab

from ..ir import derive_id, derive_status, derive_completeness
from ..ir import vocab as V
from .structure import rec

JSON = dict[str, Any]


def _lab(h: str) -> np.ndarray:
    return rgb2lab(np.array([[[int(h[i : i + 2], 16) for i in (1, 3, 5)]]], dtype=np.float64) / 255.0)


def _de(a: str, b: str) -> float:
    return float(deltaE_ciede2000(_lab(a), _lab(b))[0, 0])


def _walk_refs(node: JSON):
    """Yield (container, key) for every {literal: color} / {px: n} slot we may tokenize."""
    st = node.get("style") or {}
    f = st.get("fill")
    if f and f.get("kind") == "solid":
        yield f, "color", "color"
    b = (st.get("border") or {}).get("sides", {}).get("all")
    if b:
        yield b, "color", "color"
        yield b, "width", "border_width"
    t = node.get("text", {}).get("style")
    if t and "family" in t and "color" in t:
        yield t, "color", "color"
    lay = node.get("layout") or {}
    for k in ("stack", "flex"):
        if k in lay and "gap" in lay[k]:
            yield lay[k], "gap", "space"
    if "grid" in lay and "gap" in lay["grid"]:
        for a in ("row", "col"):
            if a in lay["grid"]["gap"]:
                yield lay["grid"]["gap"], a, "space"
    for ins in ("padding", "margin"):
        for side, v in ((node.get("spacing") or {}).get(ins) or {}).items():
            yield node["spacing"][ins], side, "space"
    r = (st.get("radius") or {})
    if "all" in r:
        yield r, "all", "radius"


def _supports(ir: JSON, node: JSON, facet: str, kinds: set[str]) -> list[str]:
    return [e for e in (node["inference"].get(facet) or {}).get("supports", []) if ir["evidence"][e]["kind"] in kinds]


def infer_tokens(ir: JSON, cfg: JSON) -> JSON:
    """Mutate ``ir``: create tokens for repeated values and replace literals by references. Returns a small summary."""
    th = cfg["thresholds"]
    nodes = ir["nodes"]
    area: dict[str, float] = {}
    scr = {s: r["nodes"] for s, r in ir["realizations"].items()}
    for sid, rn in scr.items():
        for nid, e in rn.items():
            r = ir["regions"][e["regions"][0]]["rect"]
            area[nid] = area.get(nid, 0) + r["w"] * r["h"]
    # ---- colours
    uses: dict[str, list[tuple[str, JSON, str, str]]] = defaultdict(list)  # hex -> [(node id, holder, key, usage)]
    for nid, n in nodes.items():
        for holder, key, cat in _walk_refs(n):
            if cat == "color" and isinstance(holder.get(key), dict) and "literal" in holder[key]:
                usage = "text" if holder is n.get("text", {}).get("style") else "border" if key == "color" and holder is ((n.get("style") or {}).get("border") or {}).get("sides", {}).get("all") else "fill"
                uses[holder[key]["literal"]["hex"]].append((nid, holder, key, usage))
    order = sorted(uses, key=lambda h: (-len(uses[h]), h))
    clusters: list[list[str]] = []
    for h in order:
        for c in clusters:
            if _de(c[0], h) <= th["token.color.merge_delta_e2000"]:
                c.append(h)
                break
        else:
            clusters.append([h])
    made = {"color": 0, "space": 0, "radius": 0, "type": 0, "border_width": 0}
    info: JSON = {"color_clusters": [], "near_miss_colors": []}
    tokens = ir["tokens"]
    taken: set[str] = set()

    def new_token(cat: str, name: str, value: JSON, sup: list[str], conf: float, role: str | None = None) -> str:
        base = name
        k = 2
        while name in taken:
            name = f"{base}-{k}"
            k += 1
        taken.add(name)
        tid = derive_id("tok", cat, name)
        t: JSON = {"id": tid, "name": name, "name_source": "inferred", "value": value, "inference": {"value": rec("token.cluster/1", conf, sup)}}
        if role:
            t["inference"]["role"] = rec("token.role/1", 0.6, sup)
        tokens[cat][tid] = t
        made[cat] += 1
        return tid

    fills = Counter()
    for h, lst in uses.items():
        for nid, holder, key, usage in lst:
            if usage == "fill":
                fills[h] += area.get(nid, 1)
    cl_total = {c[0]: sum(len(uses[h]) for h in c) for c in clusters}
    role_of: dict[str, str] = {}
    fill_clusters = sorted(clusters, key=lambda c: -sum(fills[h] for h in c))
    if fill_clusters and sum(fills[h] for h in fill_clusters[0]):
        role_of[fill_clusters[0][0]] = "background"
    text_cl = sorted(clusters, key=lambda c: -sum(1 for h in c for u in uses[h] if u[3] == "text"))
    if text_cl and any(u[3] == "text" for h in text_cl[0] for u in uses[h]):
        role_of.setdefault(text_cl[0][0], "text")
    border_cl = sorted(clusters, key=lambda c: -sum(1 for h in c for u in uses[h] if u[3] == "border"))
    if border_cl and any(u[3] == "border" for h in border_cl[0] for u in uses[h]):
        role_of.setdefault(border_cl[0][0], "border")
    def sat(h: str) -> float:
        r, g, b = (int(h[i : i + 2], 16) / 255 for i in (1, 3, 5))
        return colorsys.rgb_to_hsv(r, g, b)[1]
    def bright(h: str) -> float:
        return max(int(h[i : i + 2], 16) for i in (1, 3, 5)) / 255
    prim = [c for c in clusters if c[0] not in role_of and any(u[3] == "fill" for h in c for u in uses[h]) and sat(c[0]) >= 0.4 and bright(c[0]) >= 0.45]
    if prim:
        role_of[max(prim, key=lambda c: (cl_total[c[0]], c[0]))[0]] = "primary"
    for c in clusters:
        total = cl_total[c[0]]
        if total < 2:
            continue
        medoid = c[0]
        sup = sorted({e for h in c for nid, *_ in uses[h] for facet in ("style",) for e in _supports(ir, nodes[nid], facet, V.ALLOWED_SUPPORTS["token"])})
        role = role_of.get(medoid)
        tid = new_token("color", f"color/{role}" if role else f"color/{medoid[1:].lower()}", {"space": "srgb", "hex": medoid, "alpha": 1}, sup, 0.8, role)
        pages_of = sorted({nodes[nid]["scope"] for h in c for nid, *_ in uses[h]})
        info["color_clusters"].append({"token": tid, "name": tokens["color"][tid]["name"], "value": medoid, "members": c, "max_delta_e2000": round(max(_de(medoid, h) for h in c), 2), "uses": total, "scopes": pages_of})
        if role:
            tokens["color"][tid]["semantic"] = None
            del tokens["color"][tid]["semantic"]
        for h in c:
            for nid, holder, key, usage in uses[h]:
                holder[key] = {"token": tid}
    # ---- lengths (spacing, radius, border width)
    for cat, tol in (("space", th["token.length.merge_px"]), ("radius", th["token.length.merge_px"]), ("border_width", th["token.length.merge_px"])):
        vals: dict[float, list[tuple[str, JSON, str]]] = defaultdict(list)
        for nid, n in nodes.items():
            for holder, key, c2 in _walk_refs(n):
                d = holder.get(key)
                if c2 == cat and isinstance(d, dict) and "px" in d and d["px"] > 0:
                    vals[round(d["px"], 2)].append((nid, holder, key))
        groups: list[list[float]] = []
        for v in sorted(vals, key=lambda x: (-len(vals[x]), x)):
            for g in groups:
                if abs(g[0] - v) <= tol:
                    g.append(v)
                    break
            else:
                groups.append([v])
        for g in sorted(groups):
            members = [m for v in g for m in vals[v]]
            if len(members) < 2:
                continue
            kinds = {"space": {"spacing_sample"}, "radius": {"border_profile"}, "border_width": {"border_profile"}}[cat]
            facet = "layout" if cat == "space" else "style"
            sup = sorted({e for nid, *_ in members for e in _supports(ir, nodes[nid], facet, kinds)})
            tid = new_token(cat, f"{cat}/{g[0]:g}", {"px": g[0]}, sup, 0.85)
            for nid, holder, key in members:
                holder[key] = {"token": tid}
    tokens["scales"]["space"] = [t["id"] for t in sorted(tokens["space"].values(), key=lambda t: t["value"]["px"])]
    meds = [c[0] for c in clusters]
    for i, a in enumerate(meds):  # values that are close but NOT merged: reported as potential conflicts, never silently merged
        for b in meds[i + 1 :]:
            d = _de(a, b)
            if th["token.color.merge_delta_e2000"] < d <= 3 * th["token.color.merge_delta_e2000"]:
                info["near_miss_colors"].append({"a": a, "b": b, "delta_e2000": round(d, 2), "uses_a": cl_total[a], "uses_b": cl_total[b]})
    # ---- type styles
    groups_t: dict[tuple, list[str]] = defaultdict(list)
    for nid, n in nodes.items():
        st = (n.get("text") or {}).get("style")
        if st and "family" in st:
            groups_t[(st["family"]["generic"], st["size"]["px"], st["weight"], st.get("italic", False))].append(nid)
    for (fam, size, weight, italic), members in sorted(groups_t.items()):
        if len(members) < 2:
            continue
        sup = sorted({e for nid in members for e in _supports(ir, nodes[nid], "style", {"text_metrics"})})
        val = {"family": {"generic": fam, "candidates": [], "status": "guessed"}, "size": {"px": size}, "weight": weight, "italic": italic}
        tid = new_token("type", f"type/{size:g}-{weight}", val, sup, 0.8)
        for nid in members:
            st = nodes[nid]["text"]["style"]
            over = {k: st[k] for k in ("line_height", "color") if k in st}
            nodes[nid]["text"]["style"] = {"token": tid, **({"overrides": over} if over else {})}
    return {"made": made, **info}


# ----------------------------------------------------------------------------- components
STRIP = ("id", "scope", "children", "inference", "status")


def _round2(v: float) -> float:
    return round(v / 2) * 2


def _sig(ir: JSON, nid: str, top: bool = False) -> tuple | None:
    n = ir["nodes"][nid]
    if n["kind"] in ("opaque", "instance", "slot"):
        return None
    base: dict[str, Any] = {k: v for k, v in n.items() if k not in STRIP and k not in ("name", "name_source")}
    if top:
        for k in ("size", "placement"):
            base.pop(k, None)
        sp = dict(base.get("spacing") or {})
        sp.pop("margin", None)
        base["spacing"] = sp or None
    if n["kind"] == "text":
        t = copy.deepcopy(base["text"])
        t["content"] = "param"
        st = t["style"]
        if "token" in st:  # line height is derived from each instance's observed ink height: content-dependent, so not part of identity
            st["overrides"] = {k: v for k, v in st.get("overrides", {}).items() if k != "line_height"}
        else:
            st.pop("line_height", None)
        base["text"] = t
    if n["kind"] == "image":
        base["media"] = {**base["media"], "asset": "param"}
        sz = base.get("size") or {}
        base["size"] = {k: ({**v, "px": _round2(v["px"])} if isinstance(v, dict) and "px" in v else v) for k, v in sz.items()}
    kids = []
    for c in n.get("children", []):
        s = _sig(ir, c)
        if s is None:
            return None
        kids.append(s)
    return (repr(sorted((k, repr(v)) for k, v in base.items())), tuple(kids))


def _lh(style: JSON) -> JSON | None:
    return style.get("line_height") or style.get("overrides", {}).get("line_height")


def _ssig(ir: JSON, nid: str) -> tuple:
    n = ir["nodes"][nid]
    lay = n.get("layout") or {}
    return (n["kind"], n.get("role"), lay.get("mode"), (lay.get("stack") or lay.get("flex") or {}).get("axis"), tuple(_ssig(ir, c) for c in n.get("children", []) if c in ir["nodes"]))


def _count(ir: JSON, nid: str) -> int:
    return 1 + sum(_count(ir, c) for c in ir["nodes"][nid].get("children", []))


def _subtree(ir: JSON, nid: str) -> list[str]:
    out = [nid]
    for c in ir["nodes"].get(nid, {}).get("children", []):
        if c in ir["nodes"]:
            out += _subtree(ir, c)
    return out


def _retarget_redactions(ir: JSON) -> None:
    """Component inference replaces member subtrees by instances; a redaction record must keep pointing at an existing location (its text now lives in an instance parameter)."""
    nodes = ir["nodes"]
    where: dict[str, tuple[str, str]] = {}
    for nid, n in nodes.items():
        if n["kind"] == "instance":
            for pn, v in n["instance"]["params"].items():
                if isinstance(v, dict) and v.get("redaction"):
                    where[v["redaction"]] = (nid, f"instance.params.{pn}")
    for rid, r in list(ir["redactions"].items()):
        ref = r["target"].get("ref")
        if ref in nodes:
            continue
        if rid in where:
            r["target"]["ref"], r["target"]["field"] = where[rid]
        else:  # no location left in the IR: the record would dangle, so it is dropped together with its region mark
            del ir["redactions"][rid]
            for reg in ir["regions"].values():
                if reg.get("redacted") == rid:
                    reg.pop("redacted")


def infer_components(ir: JSON, cfg: JSON) -> JSON:
    th = cfg["thresholds"]
    min_support = int(th["component.min_support"])
    nodes, pages = ir["nodes"], ir["pages"]
    roots = {p["root"] for p in pages.values()}
    patched = {rs["target"] for p in pages.values() for rs in p["responsive"]}  # responsive variation is not modelled at component level
    skipped: list[str] = []
    cand: dict[tuple, list[str]] = defaultdict(list)
    by_struct: dict[tuple, list[tuple[str, tuple]]] = defaultdict(list)
    for pid in sorted(pages):
        stack = [pages[pid]["root"]]
        while stack:
            nid = stack.pop()
            n = nodes[nid]
            stack += list(reversed(n.get("children", [])))
            if nid in roots or n["kind"] != "box" or not n.get("children") or _count(ir, nid) < 3:
                continue
            if patched & set(_subtree(ir, nid)):
                skipped.append(nid)
                continue
            s = _sig(ir, nid, True)
            if s:
                cand[s].append(nid)
                by_struct[_ssig(ir, nid)].append((nid, s))
    chosen: list[tuple[tuple, list[str]]] = sorted(((s, m) for s, m in cand.items() if len(m) >= min_support), key=lambda sm: (-_count(ir, sm[1][0]), sm[1][0]))
    claimed: set[str] = set()
    made = 0
    names: Counter[str] = Counter()
    for sig, members in chosen:
        members = [m for m in members if m in nodes and not (set(_subtree(ir, m)) & claimed)]
        if len(members) < min_support:
            continue
        first = nodes[members[0]]
        cid = derive_id("cmp", members[0])
        base = {"button": "Button", "card": "Card"}.get(first.get("role", ""), "Block")
        names[base] += 1
        cname = base if names[base] == 1 else f"{base}{names[base]}"
        rep_ev = sorted({e for m in members for f in ("role", "structure") for e in (nodes[m]["inference"].get(f) or {}).get("supports", []) if ir["evidence"][e]["kind"] == "repetition"})
        # definition: clone the first member's subtree into component scope
        idmap: dict[str, str] = {}
        params: dict[str, JSON] = {}
        order = _subtree(ir, members[0])
        counters = Counter()
        pname: dict[str, str] = {}
        for old in order:
            idmap[old] = derive_id("nd", cid, old)
            n = nodes[old]
            if n["kind"] == "text":
                counters["text"] += 1
                pname[old] = f"text{counters['text']}"
                params[pname[old]] = {"type": "text", "required": True, "bind": {"node": idmap[old], "field": "text.content"}}
            elif n["kind"] == "image":
                counters["image"] += 1
                pname[old] = f"image{counters['image']}"
                params[pname[old]] = {"type": "asset", "required": True, "bind": {"node": idmap[old], "field": "media.asset"}}
        for old in order:
            c = copy.deepcopy(nodes[old])
            c["id"], c["scope"] = idmap[old], cid
            if "children" in c:
                c["children"] = [idmap[x] for x in c["children"]]
            if old == members[0]:
                for k in ("size", "placement"):
                    c.pop(k, None)
                sp = c.get("spacing") or {}
                sp.pop("margin", None)
                if sp:
                    c["spacing"] = sp
                else:
                    c.pop("spacing", None)
                c["inference"].pop("layout", None) if not any(k in c for k in ("layout", "size", "spacing", "placement", "repeat")) else None
            if c["kind"] == "text":
                c["text"]["content"] = {"param": pname[old]}
                c["inference"].pop("content", None)
            if c["kind"] == "image":
                c["media"]["asset"] = {"param": pname[old]}
                c["inference"].pop("content", None)
            c["status"] = derive_status(c)
            nodes[idmap[old]] = c
        ir["components"][cid] = {"id": cid, "name": cname, "name_source": "inferred", "category": "ui", "root": idmap[members[0]], "params": params, "slots": {}, "variants": {"axes": [], "patches": {}},
                                 "inference": rec("component.cluster/1", 0.7, rep_ev)}
        # replace every member by an instance (keeping its id, size, placement, margin and realization)
        for m in members:
            n = nodes[m]
            values: JSON = {}
            ev_content: list[str] = []
            walk = _subtree(ir, m) if m != members[0] else order
            t_i = i_i = 0
            for x in walk:
                xn = nodes[x] if x in nodes else None
                if xn is None:
                    continue
                if xn["kind"] == "text":
                    t_i += 1
                    values[f"text{t_i}"] = xn["text"]["content"]
                    ev_content += (xn["inference"].get("content") or {}).get("supports", [])
                elif xn["kind"] == "image":
                    i_i += 1
                    values[f"image{i_i}"] = {"asset": xn["media"]["asset"]}
                    ev_content += (xn["inference"].get("content") or {}).get("supports", [])
            keep = {k: n[k] for k in ("id", "scope", "size", "placement") if k in n}
            if (n.get("spacing") or {}).get("margin"):
                keep["spacing"] = {"margin": n["spacing"]["margin"]}
            layout_rec = n["inference"].get("layout") if any(k in keep for k in ("size", "placement", "spacing")) else None
            for ox, x in zip(order, walk):  # keep what was observed: component-internal realizations are keyed <instance>/<definition node>
                if x == m:
                    continue
                for r in ir["realizations"].values():
                    e = r["nodes"].pop(x, None)
                    if e:
                        r["nodes"][f"{m}/{idmap[ox]}"] = e
                nodes.pop(x, None)
            overrides = []
            if m != members[0]:
                for dx, x in zip([o for o in order if nodes.get(idmap[o], {}).get("kind") == "text"], [w for w in walk if w in nodes and nodes[w]["kind"] == "text"]):
                    a = _lh(nodes[idmap[dx]]["text"]["style"])
                    b = _lh(nodes[x]["text"]["style"])
                    if b and a != b:
                        overrides.append({"target": idmap[dx], "path": "text.style.line_height", "value": b, "reason": "line box derived from this instance's observed ink height"})
            nodes[m] = {**keep, "kind": "instance", "instance": {"component": cid, "variant": {}, "params": values, "overrides": overrides}, "status": "resolved",
                        "inference": {"structure": rec("component.cluster/1", 0.7, rep_ev), "content": rec("text.accept/1", 0.8, [e for e in ev_content if ir["evidence"][e]["kind"] in V.ALLOWED_SUPPORTS["content"]])}}
            if layout_rec:
                nodes[m]["inference"]["layout"] = layout_rec
            nodes[m]["status"] = derive_status(nodes[m])
            claimed |= set(walk)
            # a parent grid/list of instances is a repeated collection
        parents = {c: pid for pid, pn in nodes.items() for c in pn.get("children", [])}
        for par in {parents.get(m) for m in members if parents.get(m)}:
            kids = [nodes[c] for c in nodes[par].get("children", [])]
            if len(kids) >= 2 and all(k["kind"] == "instance" and k["instance"]["component"] == cid for k in kids):
                nodes[par]["repeat"] = {"component": cid, "count": len(kids), "count_semantics": "dynamic"}
                nodes[par]["inference"].setdefault("layout", rec("layout.grid/1", 0.85, rep_ev))
        made += 1
    for pid in pages:
        pages[pid]["completeness"]["state"] = derive_completeness(ir, pid)
    near = []
    for ss, lst in sorted(by_struct.items(), key=lambda kv: repr(kv[0])):
        full = {}
        for nid, s in lst:
            if nid in nodes:
                full.setdefault(s, []).append(nid)
        if len(full) >= 2:
            firsts = [v[0] for v in full.values()]
            diffs = sorted({k for a in firsts[1:] for k in ("style", "layout", "size", "spacing") if (nodes[firsts[0]].get(k) if firsts[0] in nodes else None) != (nodes[a].get(k) if a in nodes else None)})
            near.append({"structure_equal": True, "variants": [{"nodes": v[:4], "count": len(v)} for v in full.values()], "differing_root_fields": diffs,
                         "decision": "not merged: styles or sizes differ (under-merge rule); a user may merge them"})
    _retarget_redactions(ir)
    skipped_set = set(skipped)
    top = [x for x in skipped if not any(x in nodes[q].get("children", []) for q in skipped_set)]
    return {"components": made, "near_misses": near,
            "skipped_responsive": [{"node": x, "page": pages[nodes[x]["scope"]]["name"], "reason": "subtree touched by a responsive patch; responsive variation is not modelled at component level, so it is not a component candidate"} for x in sorted(top)]}
