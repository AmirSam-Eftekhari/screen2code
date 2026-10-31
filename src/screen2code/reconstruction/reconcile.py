"""S7 reconciliation: explicit page grouping, cross-screen node correspondence, viewport classes, responsive patches (PIPELINE 4.7; IR_SPEC 6, 13).

Screens are related only when the user (or a manifest) says they belong to the same page (``page_hint``). Within a group, screens of different
widths are unified into ONE page only if their trees correspond strongly and every difference can be expressed by whitelisted patches (set/hide).
Otherwise they stay separate pages linked by ``possible_responsive_variant_of``; the decision and its reasons are written to the reconciliation report.
"""
from __future__ import annotations

import copy
import difflib
from typing import Any

from ..ir import derive_completeness, derive_id, derive_status
from .structure import rec

JSON = dict[str, Any]
CONVENTION = (480, 600, 640, 768, 900, 1024, 1280)
TOL = 1.5
FOLD_PENALTY = 0.95  # a direct node pair beats a fold when both explain the same content
RESPONSIVE_KINDS = {"alignment", "stack_axis", "grid_fit", "containment", "size_sample"}


def _page_of(doc: JSON) -> str:
    return next(iter(doc["pages"]))


def _screen_of(doc: JSON) -> str:
    return next(iter(doc["screens"]))


def _txt(n: JSON) -> str:
    return " ".join((n["text"]["content"].get("value") or "").lower().split())


def _leaf_ids(doc: JSON, root: str) -> list[str]:
    out, st = [], [root]
    while st:
        x = st.pop()
        n = doc["nodes"][x]
        if n["kind"] in ("text", "image", "opaque"):
            out.append(x)
        st += n.get("children", [])
    return out


def _align(A: JSON, B: JSON, ca: list[str], cb: list[str], memo: dict) -> tuple[float, dict[str, str]]:
    """Order-preserving alignment of two child lists.

    Besides one-to-one pairs, a base wrapper (grid/stack box) may fold onto a run of sibling nodes of the other tree when the other screen has no
    such wrapper (e.g. a 3-column grid that became three stacked cards). Folds are strict: same number of children, every child must match.
    A fold is recorded as ``base_id -> "fold:<run ids joined by |>"`` and materialized by :func:`correspond`.
    """
    n, m = len(ca), len(cb)
    sc = [[_score(A, B, ca[i], cb[j], memo) for j in range(m)] for i in range(n)]
    runs: dict[tuple[int, int], tuple[float, dict[str, str]]] = {}
    for i in range(n):
        na = A["nodes"][ca[i]]
        kids = na.get("children", [])
        mode = (na.get("layout") or {}).get("mode")
        if na["kind"] != "box" or len(kids) < 2 or mode not in ("grid", "stack"):
            continue
        for j in range(m - len(kids) + 1):
            run = cb[j : j + len(kids)]
            tot, mp = _align(A, B, kids, run, memo)
            if len(mp) >= len(kids) and all(k in mp for k in kids) and tot / len(kids) >= 0.5:
                runs[(i, j)] = (FOLD_PENALTY * tot / len(kids), {ca[i]: "fold:" + "|".join(run), **mp})
    dp = [[0.0] * (m + 1) for _ in range(n + 1)]
    bp: list[list[tuple[str, Any]]] = [[("", None)] * (m + 1) for _ in range(n + 1)]
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            best, how = dp[i - 1][j], ("skip_a", None)
            if dp[i][j - 1] > best:
                best, how = dp[i][j - 1], ("skip_b", None)
            v = dp[i - 1][j - 1] + sc[i - 1][j - 1][0]
            if sc[i - 1][j - 1][0] > 0 and v > best:
                best, how = v, ("pair", None)
            for (ri, rj), (rs, _) in runs.items():
                if ri == i - 1 and rj + len(A["nodes"][ca[ri]]["children"]) == j:
                    v = dp[i - 1][rj] + rs
                    if v > best:
                        best, how = v, ("fold", rj)
            dp[i][j], bp[i][j] = best, how
    mapping: dict[str, str] = {}
    i, j = n, m
    while i and j:
        kind, arg = bp[i][j]
        if kind == "pair":
            mapping.update(sc[i - 1][j - 1][1])
            i, j = i - 1, j - 1
        elif kind == "fold":
            mapping.update(runs[(i - 1, arg)][1])
            i, j = i - 1, arg
        elif kind == "skip_a":
            i -= 1
        elif kind == "skip_b":
            j -= 1
        else:
            break
    return dp[n][m], mapping


def _score(A: JSON, B: JSON, a: str, b: str, memo: dict) -> tuple[float, dict[str, str]]:
    key = (a, b)
    if key in memo:
        return memo[key]
    na, nb = A["nodes"][a], B["nodes"][b]
    ka, kb = na["kind"], nb["kind"]
    res: tuple[float, dict[str, str]] = (0.0, {})
    if ka == "text" and kb == "text":
        s = difflib.SequenceMatcher(None, _txt(na), _txt(nb)).ratio()
        res = (s, {a: b}) if s >= 0.8 else (0.0, {})
    elif ka in ("image", "opaque") and kb in ("image", "opaque"):
        res = (0.9, {a: b})
    elif ka in ("box", "shape") and kb in ("box", "shape"):
        ca, cb = na.get("children", []), nb.get("children", [])
        if not ca and not cb:
            res = (0.5, {a: b})
        elif ca and cb:
            total, mp = _align(A, B, ca, cb, memo)
            if total > 0:
                res = (0.4 + 0.6 * total / max(len(ca), len(cb)), {a: b, **mp})
    memo[key] = res
    return res


def _mtop(n: JSON) -> float:
    return float(((n.get("spacing") or {}).get("margin") or {}).get("top", {}).get("px", 0.0))


def _set_mtop(n: JSON, v: float) -> None:
    sp = n.setdefault("spacing", {})
    mg = sp.setdefault("margin", {})
    if v > 0.5:
        mg["top"] = {"px": round(v, 2)}
    else:
        mg.pop("top", None)
    if not mg:
        sp.pop("margin")
    if not sp:
        n.pop("spacing")


def _fold_spacing(B2: JSON, A: JSON, a: str, wid: str, run: list[str], mapping: dict[str, str], layout: JSON) -> None:
    """Express the run's vertical spacing the way the base wrapper does: the first item's margin belongs to the wrapper, the smallest
    margin between items becomes the wrapper's gap, and grid items stretch in their single track (width taken from the base counterpart when the
    measured widths agree). Only inferred layout fields of the copy are changed; measured evidence is untouched."""
    wrap, kids = B2["nodes"][wid], [B2["nodes"][x] for x in run]
    if len(kids) > 1:
        gap = min(_mtop(k) for k in kids[1:])
        if layout["mode"] == "grid":
            layout["grid"]["gap"]["row"] = {"px": round(gap, 2)}
        else:
            layout["stack"]["gap"] = {"px": round(gap, 2)}
        for k in kids[1:]:
            _set_mtop(k, _mtop(k) - gap)
    first = _mtop(kids[0])
    _set_mtop(kids[0], 0.0)
    if first > 0.5:
        wrap["spacing"] = {"margin": {"top": {"px": round(first, 2)}}}
    if layout["mode"] == "grid":
        scr = _screen_of(B2)
        widths = [B2["regions"][B2["realizations"][scr]["nodes"][x]["regions"][0]]["rect"]["w"] for x in run if B2["realizations"][scr]["nodes"].get(x, {}).get("regions")]
        for bk in A["nodes"][a].get("children", []):
            rk = mapping.get(bk)
            if rk in B2["nodes"] and not B2["nodes"][rk].get("size", {}).get("w") and (A["nodes"][bk].get("size") or {}).get("w"):
                if widths and max(widths) - min(widths) <= TOL:
                    B2["nodes"][rk].setdefault("size", {})["w"] = copy.deepcopy(A["nodes"][bk]["size"]["w"])


def _fold_nodes(A: JSON, B: JSON, mapping: dict[str, str]) -> tuple[JSON, dict[str, str]]:
    """Materialize folds on a copy of ``B``: each run of siblings gets an explicit inferred wrapper that mirrors the base wrapper's layout mode.

    The wrapper is structure inferred at reconciliation time (basis ``default``, no evidence of its own); its children and their measured evidence are untouched.
    """
    folds = {a: b for a, b in mapping.items() if b.startswith("fold:")}
    if not folds:
        return B, mapping
    B2 = copy.deepcopy(B)
    pid = _page_of(B2)
    scr = _screen_of(B2)
    mapping = dict(mapping)
    parent_of = {c: p for p, n in B2["nodes"].items() for c in n.get("children", [])}
    for a, token in sorted(folds.items()):
        run = token[len("fold:"):].split("|")
        wid = derive_id("nd", "fold", *run)
        parent = B2["nodes"][parent_of[run[0]]]
        kids = parent["children"]
        k0 = kids.index(run[0])
        parent["children"] = kids[:k0] + [wid] + kids[k0 + len(run):]
        base_layout = A["nodes"][a]["layout"]
        if base_layout["mode"] == "grid":
            layout: JSON = {"mode": "grid", "grid": {"columns": [{"kind": "share", "weight": 1}], "gap": {"row": {"px": 0.0}, "col": {"px": 0.0}}, "flow": "row"}}
        else:
            layout = {"mode": "stack", "stack": {"axis": "vertical", "gap": {"px": 0.0}, "align": "stretch", "distribute": "start"}}
        # width: fill when the run spans (nearly) the whole parent content box, otherwise the measured union width
        rects = [B2["regions"][r]["rect"] for x in run for r in B2["realizations"][scr]["nodes"].get(x, {}).get("regions", [])]
        prects = [B2["regions"][r]["rect"] for r in B2["realizations"][scr]["nodes"].get(parent["id"], {}).get("regions", [])]
        size: JSON = {}
        if rects and prects:
            uw = max(r["x"] + r["w"] for r in rects) - min(r["x"] for r in rects)
            size["w"] = {"kind": "fill"} if uw >= 0.85 * prects[0]["w"] else {"kind": "fixed", "px": float(uw)}
        B2["nodes"][wid] = {"id": wid, "kind": "box", "scope": pid, "children": list(run), "status": "resolved", "layout": layout, "size": size,
                            "inference": {"layout": rec("reconcile.fold/1", 0.6, [], basis="default"), "size": rec("reconcile.fold/1", 0.6, [], basis="default")},
                            "origin": {"layout": "inferred", "size": "inferred"}, "role": "group"}
        _fold_spacing(B2, A, a, wid, run, mapping, layout)
        # the wrapper is realized by its children's measured regions; no region is invented for it
        B2["realizations"][scr]["nodes"][wid] = {"regions": [r for x in run for r in B2["realizations"][scr]["nodes"].get(x, {}).get("regions", [])]}
        mapping[a] = wid
    return B2, mapping


def correspond(A: JSON, B: JSON) -> JSON:
    ra, rb = A["pages"][_page_of(A)]["root"], B["pages"][_page_of(B)]["root"]
    score, mapping = _score(A, B, ra, rb, {})
    la, lb = _leaf_ids(A, ra), _leaf_ids(B, rb)
    inv = {b: a for a, b in mapping.items() if not b.startswith("fold:")}
    matched_b = [x for x in lb if x in inv]
    B2, mapping = _fold_nodes(A, B, mapping)
    unmatched_a = [x for x in A["nodes"] if x not in mapping and A["nodes"][x]["scope"] == _page_of(A)]
    return {"mapping": mapping, "other": B2, "folds": sorted(a for a, b in mapping.items() if b.startswith("nd_") and b in B2["nodes"] and b not in B["nodes"]),
            "confidence": round(len(matched_b) / max(len(la), len(lb), 1), 3), "unmatched_b_leaves": [x for x in lb if x not in inv],
            "unmatched_a": unmatched_a, "score": round(score, 3)}


def _px(d: JSON | None) -> float:
    return float((d or {}).get("px", 0.0))


def _diff(a: JSON, b: JSON) -> list[JSON] | None:
    """Patch ops turning base node ``a`` into ``b``; None when the difference cannot be expressed (mode change)."""
    ops: list[JSON] = []
    la, lb = a.get("layout") or {}, b.get("layout") or {}
    if (la.get("mode") or "none") != (lb.get("mode") or "none"):
        return None
    mode = la.get("mode")
    if mode in ("stack", "flex"):
        sa, sb = la[mode], lb[mode]
        for f in ("axis", "align", "distribute"):
            if sa.get(f) != sb.get(f):
                ops.append({"op": "set", "path": f"layout.{mode}.{f}", "value": sb.get(f, "start" if f != "axis" else "vertical")})
        if abs(_px(sa.get("gap")) - _px(sb.get("gap"))) > TOL:
            ops.append({"op": "set", "path": f"layout.{mode}.gap", "value": sb.get("gap", {"px": 0})})
    elif mode == "grid":
        ga, gb = la["grid"], lb["grid"]
        if ga["columns"] != gb["columns"]:
            ops.append({"op": "set", "path": "layout.grid.columns", "value": gb["columns"]})
        if any(abs(_px(ga.get("gap", {}).get(k)) - _px(gb.get("gap", {}).get(k))) > TOL for k in ("row", "col")):
            ops.append({"op": "set", "path": "layout.grid.gap", "value": gb.get("gap", {})})
    for ax in ("w", "h"):
        sa, sb = (a.get("size") or {}).get(ax), (b.get("size") or {}).get(ax)
        if (sa or {}).get("kind") != (sb or {}).get("kind") or abs(_px(sa) - _px(sb)) > TOL:
            ops.append({"op": "set", "path": f"size.{ax}", "value": sb or {"kind": "hug"}})
    for k in ("padding", "margin"):
        pa, pb = (a.get("spacing") or {}).get(k) or {}, (b.get("spacing") or {}).get(k) or {}
        if any(abs(_px(pa.get(s)) - _px(pb.get(s))) > TOL for s in ("top", "right", "bottom", "left")):
            ops.append({"op": "set", "path": f"spacing.{k}", "value": pb})
    if a["kind"] == "text":
        ta, tb = a["text"]["style"], b["text"]["style"]
        if abs(ta["size"]["px"] - tb["size"]["px"]) >= 1 or ta["weight"] != tb["weight"]:
            ops.append({"op": "set", "path": "text.style", "value": tb})
    return ops


def _width(doc: JSON) -> float:
    return float(doc["screens"][_screen_of(doc)]["resolved"]["viewport_width"])


def _select(lo: float, hi: float) -> tuple[int, str]:
    for c in CONVENTION:
        if lo < c <= hi:
            return c, "convention_snap"
    return int(round((lo + hi) / 2)), "interval_midpoint"


def unify(base: JSON, others: list[tuple[JSON, JSON]]) -> JSON:
    """Merge ``others`` [(doc, correspondence)] into ``base`` as additional screens of the base page. Mutates ``base``."""
    pid, bscr = _page_of(base), _screen_of(base)
    entries = sorted([(_width(base), base, None)] + [(_width(d), d, c) for d, c in others], key=lambda t: t[0])
    page = base["pages"][pid]
    vcs = {w: derive_id("vc", pid, w) for w, *_ in entries}
    bps: JSON = {}
    classes: list[JSON] = []
    for i, (w, d, c) in enumerate(entries):
        lo = classes[-1]["max_exclusive"] if classes else 0
        hi: Any = None
        if i + 1 < len(entries):
            sel, basis = _select(w, entries[i + 1][0])
            bid = derive_id("bp", pid, w, entries[i + 1][0])
            bps[bid] = {"known_interval": [w, entries[i + 1][0]], "selected": sel, "basis": basis, "inference": rec("breakpoint.select/1", 0.5, [], basis="default")}
            hi = bid
        classes.append({"id": vcs[w], "min": lo, "max_exclusive": hi})
    page["viewport_classes"], page["breakpoints"] = classes, bps
    base["screens"][bscr]["resolved"]["viewport_class"] = vcs[_width(base)]
    page["base_class"], page["base_basis"] = vcs[_width(base)], bscr
    rules: dict[tuple[str, str], JSON] = {}
    for d, c in others:
        scr, opid = _screen_of(d), _page_of(d)
        mapping = c["mapping"]
        for sec in ("producers", "sources", "regions", "evidence", "modes", "assets"):
            for k, v in d[sec].items():
                base[sec].setdefault(k, copy.deepcopy(v))
        s = copy.deepcopy(d["screens"][scr])
        s["resolved"].update(page=pid, viewport_class=vcs[_width(d)])
        s["origin"].update(page="declared", viewport_class="inferred")
        base["screens"][scr] = s
        real = d["realizations"][scr]
        nodes_real = {a: copy.deepcopy(real["nodes"][b]) for a, b in mapping.items() if b in real["nodes"]}
        base["realizations"][scr] = {"inference": copy.deepcopy(real["inference"]), "nodes": nodes_real}
        # hidden: base nodes without a counterpart (top-most only; their subtrees are hidden with them)
        hidden = [x for x in c["unmatched_a"] if not any(x in base["nodes"][p].get("children", []) for p in c["unmatched_a"])]
        for h in hidden:
            rules[(h, vcs[_width(d)])] = {"op": "hide", "node": h, "a": base["nodes"][h], "b": None}
        for a, b in mapping.items():
            ops = _diff(base["nodes"][a], d["nodes"][b])
            if ops:
                rules[(a, vcs[_width(d)])] = {"ops": ops, "node": a, "a": base["nodes"][a], "b": d["nodes"][b], "conf": c["confidence"]}
    for (nid, vc), r in sorted(rules.items()):
        sup = sorted({e for n in (r["a"], r["b"]) if n for f in ("layout", "style") for e in (n["inference"].get(f) or {}).get("supports", []) if base["evidence"].get(e, {}).get("kind") in RESPONSIVE_KINDS})
        patch = [{"op": "hide"}] if r.get("op") == "hide" else r["ops"]
        page["responsive"].append({"id": derive_id("rs", nid, vc), "target": nid, "when": [vc], "patch": patch,
                                   "inference": rec("responsive.diff/1", r.get("conf", 0.7), sup)})
    page["responsive"].sort(key=lambda r: r["id"])
    # the other documents' own pages/nodes are subsumed
    return base


def reconcile(docs: list[JSON], cfg: JSON) -> tuple[list[JSON], JSON]:
    """Group single-screen IRs by declared page hint; unify responsive groups when evidence allows. Returns (page documents, report)."""
    thr = float(cfg["thresholds"]["screen.correspondence.min"])
    groups: dict[str, list[JSON]] = {}
    order: list[str] = []
    for d in docs:
        hint = next(iter(d["sources"].values())).get("declared", {}).get("page_hint") or d["pages"][_page_of(d)]["name"]
        groups.setdefault(hint, []).append(d)
        order.append(hint) if hint not in order else None
    out: list[JSON] = []
    report: JSON = {"groups": [], "thresholds": {"screen.correspondence.min": thr}}
    for hint in order:
        g = sorted(groups[hint], key=lambda d: -_width(d))
        entry: JSON = {"page": hint, "screens": [_screen_of(d) for d in g], "widths": [_width(d) for d in g]}
        if len(g) == 1:
            entry.update(decision="single", reason="one screenshot declared for this page")
            out.append(g[0])
        else:
            base, rest = g[0], g[1:]
            ok: list[tuple[JSON, JSON]] = []
            sep: list[JSON] = []
            for d in rest:
                if abs(_width(d) - _width(base)) < 1:
                    sep.append(d)
                    entry.setdefault("separate", []).append({"screen": _screen_of(d), "reason": "same viewport width as the base screen: cannot be a responsive variant (re-capture or theme pairing is not inferred)"})
                    continue
                c = correspond(base, d)
                d = c["other"]
                info = {"screen": _screen_of(d), "confidence": c["confidence"], "tree_score": c["score"], "unmatched_in_other": len(c["unmatched_b_leaves"]), "base_nodes_without_counterpart": len(c["unmatched_a"])}
                ops_ok = all(_diff(base["nodes"][a], d["nodes"][b]) is not None for a, b in c["mapping"].items())
                reasons = []
                if c["confidence"] < thr:
                    reasons.append(f"correspondence {c['confidence']} below {thr}")
                if c["unmatched_b_leaves"]:
                    reasons.append("the other screen has content absent from the base screen (not representable by set/hide patches)")
                if not ops_ok:
                    reasons.append("a layout mode differs between matched nodes (not representable by patches)")
                if reasons:
                    info["reasons"] = reasons
                    entry.setdefault("separate", []).append(info)
                    sep.append(d)
                else:
                    ok.append((d, c))
                    entry.setdefault("unified", []).append(info)
            if ok:
                out.append(unify(base, ok))
                entry["decision"] = "unified"
            else:
                out.append(base)
                entry["decision"] = "separate"
            for d in sep:
                # keep as its own page; relate it to the base page without asserting equivalence
                pg = d["pages"][_page_of(d)]
                pg["name"] = f"{pg['name']} ({int(_width(d))}px)"
                d["relations"].append({"id": derive_id("rel", _page_of(d), _page_of(base)), "kind": "possible_responsive_variant_of", "a": pg["root"], "b": base["pages"][_page_of(base)]["root"],
                                       "inference": rec("reconcile.group/1", 0.4, [], basis="default")})
                out.append(d)
        report["groups"].append(entry)
    return out, report
