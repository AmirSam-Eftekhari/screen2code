"""S5 structure inference + S6 assets + S10 commit for a single screen (PIPELINE sections 4.5, 4.6, 4.10).

Reads the observed layer (regions, evidence) and writes the inferred layer (nodes, realizations, assets) with an
inference record per facet. Heuristics are deliberately simple and labelled ``heuristic``; nothing here is a probability.
"""
from __future__ import annotations

import io
import re
from typing import Any, Callable

from PIL import Image

from .. import __version__
from ..core.errors import S2CError
from ..ir import canonical_dumps, content_hash, derive_completeness, derive_id, derive_status, sha256_hex, validate
from ..ir import vocab as V
from ..vision.measure import hexof
from ..vision.perceive import REDACT_PLACEHOLDER, REDACT_VERSION, Perception
from ..vision.segment import Node

JSON = dict[str, Any]
from ..vision.typography import ASC, ASC_H, DESC, DESC_H, X_H  # noqa: E402,F401  ink extents in em for Liberation Sans-like faces (heuristic)
BOLD_STROKE_EM = 0.124  # heuristic weight threshold on stroke width / font size (regular ~0.10-0.12, bold ~0.13-0.15 em on Liberation Sans)

# Documented rule priors (heuristic scores, NOT probabilities); each is combined with measured quantities where possible.
PRIOR = {"structure": 0.9, "role": 0.7, "layout": 0.85, "style": 0.8, "asset": 0.6, "realize": 0.95}


def rec(method: str, conf: float, supports: list[str], basis: str | None = None) -> JSON:
    b = basis or ("evidence" if supports else "default")
    return {"method": method, "calibration": "heuristic", "basis": b, "confidence": round(max(0.0, min(1.0, conf)), 3), "supports": sorted(set(supports)) if b == "evidence" else []}


def lit(hexv: str) -> JSON:
    return {"literal": {"space": "srgb", "hex": hexv, "alpha": 1}}


def px(v: float) -> JSON:
    return {"px": round(float(v), 2)}


def parent_is_root_page(n: Node) -> bool:
    return n.notes.get("is_root", False)


class Builder:
    def __init__(self, p: Perception, cfg: JSON, write_asset: Callable[[bytes], str]):
        self.p, self.cfg, self.write_asset = p, cfg, write_asset
        self.s = p.scale
        self.th = cfg["thresholds"]
        self.nodes: dict[str, JSON] = {}
        self.assets: dict[str, JSON] = {}
        self.real: dict[str, JSON] = {}
        self.sizes: list[float] = []
        self.heading_ids: list[tuple[float, str]] = []
        self.redactions: dict[str, JSON] = {}

    # -- helpers
    def d(self, v: float) -> float:
        return round(v / self.s, 2)

    def evi(self, n: Node, kinds: tuple[str, ...]) -> list[str]:
        out: list[str] = []
        for k in kinds:
            out += n.notes.get("ev", {}).get(k, [])
        return out

    def ev(self, eid: str) -> JSON:
        return self.p.evidence[eid]["measure"]

    def nid(self, n: Node) -> str:
        return derive_id("nd", n.rid)

    # -- asset (S6)
    def make_asset(self, n: Node, kind_hint: str) -> str:
        ids = n.notes.get("ev", {}).get("asset_candidate", [])
        aid = derive_id("ast", n.rid)
        ev = self.ev(ids[0]) if ids else None
        too_small = self.d(n.w) < self.th["asset.extract.min_size_px"] or self.d(n.h) < self.th["asset.extract.min_size_px"]
        dom = ev["dominant_color"] if ev else hexof(n.fill)
        hint = {"aspect": round(n.w / n.h, 3), "dominant_color": {"space": "srgb", "hex": dom.upper(), "alpha": 1}, "supports": ids}
        if ev:
            hint["aspect"] = ev["aspect"]
        a: JSON = {"id": aid, "kind": kind_hint, "hint": hint, "inference": rec("asset.classify/1", PRIOR["asset"], ids)}
        if too_small or not ids:
            a.update(provenance="placeholder", placeholder={"reason": "too_small" if too_small else "unrecoverable", "kind": "flat"}, rights_status="not_applicable")
        else:
            crop = self.p.image.rgb[n.y : n.y + n.h, n.x : n.x + n.w]
            buf = io.BytesIO()
            Image.fromarray(crop).save(buf, format="PNG")
            sha = self.write_asset(buf.getvalue())
            a.update(provenance="extracted", content={"ref": f"blob:sha256:{sha}", "media_type": "image/png", "intrinsic": {"w": n.w, "h": n.h}},
                     origin={"region": n.rid, "fidelity": "pixel_crop", "resolution_scale": self.s, "lossy": True}, rights_status="unknown")
        self.assets[aid] = a
        return aid

    # -- text style heuristics
    def text_style(self, n: Node) -> tuple[JSON, float, list[str]]:
        tm_ids = n.notes.get("ev", {}).get("text_metrics", [])
        cs_ids = [e for e in n.notes.get("ev", {}).get("color_sample", [])]
        item = self.ev(tm_ids[0])["items"][0] if tm_ids else None
        text = n.reading["value"] if n.reading else ""
        lines = max(1, text.count("\n") + 1)
        has_asc, has_desc = any(c in ASC for c in text), any(c in DESC for c in text)
        top = ASC_H if has_asc else X_H
        bot = DESC_H if has_desc else 0.0
        ink_h = (item["ink_height_px"] / lines) if item else self.d(n.h) / lines
        size = max(8.0, round(ink_h / (top + bot)))
        weight = 700 if item and item.get("stroke_width_px", 0) / size >= BOLD_STROKE_EM else 400
        color = hexv = (item or {}).get("ink_hex", "#000000")
        style = {"family": {"generic": "sans", "candidates": [], "status": "guessed"}, "size": px(size), "weight": weight, "italic": False,
                 "line_height": {"px": round(self.d(n.h) / lines, 2)}, "color": lit(color)}
        return style, size, tm_ids + cs_ids

    def redact_text(self, rid: str, nid: str, n: Node) -> None:
        eids = n.notes.get("ev", {}).get("text_reading", [])
        paths = [f"/evidence/{e}/measure/readings/{i}/value" for e in eids for i, r in enumerate(self.p.evidence[e]["measure"]["readings"]) if r["region"] == n.rid]
        prd = derive_id("prd", "s2c.redact", REDACT_VERSION)
        self.p.regions[n.rid]["redacted"] = rid
        self.redactions[rid] = {"id": rid, "stage": "post_inference", "target": {"kind": "text", "ref": nid, "field": "text.content"}, "action": "replace_text", "reason": "rule",
                                "rule_id": REDACT_RULE, "producer": prd, "scrubbed_paths": paths}

    # -- node construction
    def build(self, n: Node, parent: Node | None) -> str:
        nid = self.nid(n)
        node: JSON = {"id": nid, "kind": "box", "scope": self.page_id, "children": [], "status": "resolved", "inference": {}}
        inf = node["inference"]
        node_sup = lambda kinds: self.evi(n, kinds)  # noqa: E731
        if n.kind in ("container", "group"):
            self.layout(n, node)
            kids = [self.build(c, n) for c in n.children]
            node["children"] = kids
            if parent is None or n.kind == "group":
                pass
            if n.kind == "container":
                style: JSON = {"fill": {"kind": "solid", "color": lit(hexof(n.fill))}}
                if n.border_w and n.border_rgb:
                    style["border"] = {"sides": {"all": {"width": px(self.d(n.border_w)), "style": "solid", "color": lit(hexof(n.border_rgb))}}}
                if n.radius:
                    style["radius"] = {"all": px(self.d(n.radius))}
                node["style"] = style
                inf["style"] = rec("style.box/1", PRIOR["style"], node_sup(("color_sample", "border_profile")))
            sup = node_sup(("containment",)) or node_sup(("size_sample", "spacing_sample"))
            inf["structure"] = rec("tree.build/1", PRIOR["structure"], sup)
            self.role_for_container(n, node)
        elif n.kind == "image":
            node["kind"] = "image"
            aid = self.make_asset(n, "raster")
            node["media"] = {"asset": aid, "fit": "cover"}
            node["size"] = {"w": {"kind": "fixed", "px": self.d(n.w)}, "h": {"kind": "hug"}, "aspect": round(n.w / n.h, 3)}
            ac = node_sup(("asset_candidate",))
            inf["structure"] = rec("tree.build/1", PRIOR["structure"], ac)
            inf["layout"] = rec("layout.size/1", PRIOR["layout"], ac)
            inf["style"] = rec("style.media/1", PRIOR["style"], ac)
            inf["content"] = rec("asset.bind/1", PRIOR["asset"], ac)
        elif n.reading:
            node["kind"] = "text"
            style, size, sup = self.text_style(n)
            text = n.reading["value"]
            conf = n.reading["conf"]
            status = "inferred" if conf >= self.th["text.status.uncertain_below"] else "uncertain"
            if n.notes.get("redacted"):
                rid = derive_id("rdc", "text", self.p.source_id, n.rid, REDACT_RULE)
                node["text"] = {"content": {"value": None, "status": "redacted", "redaction": rid}, "style": style}  # no name is derived from redacted text
                self.redact_text(rid, nid, n)
            else:
                node["text"] = {"content": {"value": text, "status": status}, "style": style}
                node["name"] = re.sub(r"\s+", " ", text)[:40]
                node["name_source"] = "inferred"
            if text.count("\n"):
                node["text"]["truncation"] = {"mode": "wrap"}
            self.sizes.append(size)
            self.heading_ids.append((size, nid))
            tr = node_sup(("text_reading",))
            inf["structure"] = rec("tree.build/1", PRIOR["structure"], tr)
            inf["style"] = rec("style.text/1", PRIOR["style"], [e for e in sup if self.p.evidence[e]["kind"] in ("text_metrics", "color_sample")])
            inf["content"] = rec("text.accept/1", conf, tr)
        else:  # non-text leaf: icon/logo/decoration
            big = self.d(n.w) >= self.th["asset.extract.min_size_px"] and self.d(n.h) >= self.th["asset.extract.min_size_px"]
            ac = node_sup(("asset_candidate",))
            if big and ac:
                node["kind"] = "opaque"
                aid = self.make_asset(n, "icon" if max(n.w, n.h) <= 96 else "illustration")
                node["opaque"] = {"asset": aid}
                node["name"] = "Unrecognized graphic"
                node["name_source"] = "inferred"
                inf["structure"] = rec("tree.build/1", 0.5, ac)
                inf["content"] = rec("asset.bind/1", PRIOR["asset"], ac)
            else:
                node["kind"] = "shape" if min(n.w, n.h) > 3 else "box"
                node["style"] = {"fill": {"kind": "solid", "color": lit(hexof(n.fill if n.kind == "container" else self.dominant_leaf(n)))}}
                node["size"] = {"w": {"kind": "fixed", "px": self.d(n.w)}, "h": {"kind": "fixed", "px": self.d(n.h)}}
                if node["kind"] == "box":
                    node["role"] = "separator"
                inf["structure"] = rec("tree.build/1", 0.5, ac)
                inf["style"] = rec("style.fill/1", PRIOR["style"], node_sup(("color_sample",)))
                inf["layout"] = rec("layout.size/1", PRIOR["layout"], ac)
                if "role" in node:
                    inf["role"] = rec("role.classify/1", 0.5, [])
        if not node["children"]:
            del node["children"]
        self.nodes[nid] = node
        self.real[nid] = {"regions": [n.rid]}
        return nid

    def dominant_leaf(self, n: Node) -> tuple[int, int, int]:
        from ..vision.segment import dominant

        return dominant(self.p.image.rgb[n.y : n.y + n.h, n.x : n.x + n.w])[0]

    def role_for_container(self, n: Node, node: JSON) -> None:
        inf = node["inference"]
        ac = n.notes.get("ev", {}).get("affordance_cue", [])
        if ac:
            m = self.ev(ac[0])
            if m["text_centered"] and m["contrast_ratio"] >= 3.0 and n.radius > 0 and n.w >= n.h:
                node["role"] = "button"
                node["affordance"] = {"kind": "clickable", "purpose": "action_like"}
                inf["role"] = rec("role.classify/1", 0.6, ac)
                return
        rp = n.notes.get("ev", {}).get("repetition", [])
        if rp and n.kind == "container":
            node["role"] = "card"
            inf["role"] = rec("role.classify/1", 0.5, rp)

    # -- layout inference (the decision; the measurements are evidence)
    def layout(self, n: Node, node: JSON) -> None:
        kids, inf = n.children, node["inference"]
        evs = n.notes.get("ev", {})
        tol = self.th["align.tolerance_px"]
        bw = n.border_w
        ix, iy, iw, ih = n.x + bw, n.y + bw, n.w - 2 * bw, n.h - 2 * bw
        if not kids:
            return
        # copy: evidence is observed data and must never be modified by inference (R-EPI-7)
        pad = dict(self.ev(evs["spacing_sample"][0])["padding_px"]) if evs.get("spacing_sample") else {"top": 0, "right": 0, "bottom": 0, "left": 0}
        sup_base = [e for k in ("spacing_sample", "size_sample", "containment") for e in evs.get(k, [])]
        # a lattice is a grid only if it is genuinely two-dimensional or its single row has equal-width columns; otherwise it is a stack
        grid = [e for e in evs.get("grid_fit", []) if self.ev(e)["columns"] >= 2 and self.ev(e)["residual_px"] <= tol * 1.5 and (self.ev(e)["rows"] >= 2 or self.ev(e)["equal_widths"])]
        axes = [(self.ev(e), e) for e in evs.get("stack_axis", []) if self.ev(e)["order_consistency"] == 1.0]
        sizes = {it["region"]: it for it in (self.ev(evs["size_sample"][0])["items"] if evs.get("size_sample") else []) for _ in [0]}
        # index size items by (region, axis)
        sz = {(it["region"], it["axis"]): it for it in (self.ev(evs["size_sample"][0])["items"] if evs.get("size_sample") else [])}
        spacing: JSON = {}
        node_layout: JSON
        if len(kids) == 1 and not grid:
            k = kids[0]
            axis = "vertical"
            left, right = pad["left"], pad["right"]
            horiz = "center" if abs(left - right) <= tol and left > tol * 2 and k.kind != "leaf" or (abs(left - right) <= tol and left > 8) else "start"
            node_layout = {"mode": "stack", "stack": {"axis": axis, "gap": px(0), "align": horiz, "distribute": "start"}}
            lay_sup = sup_base
        elif grid:
            g = self.ev(grid[0])
            cols = [{"kind": "share", "weight": 1}] * g["columns"] if g["equal_widths"] else [{"kind": "fixed", "px": w} for w in g["track_widths_px"]]
            node_layout = {"mode": "grid", "grid": {"columns": list(cols), "gap": {"row": px(g["row_gap_px"]), "col": px(g["col_gap_px"])}, "flow": "row"}}
            lay_sup = sup_base + grid
        elif axes:
            m, eid = axes[0]
            axis = m["axis"]
            gaps = m["gap_samples_px"]
            uniform = (max(gaps) - min(gaps)) <= self.th["gap.uniform_tolerance_px"]
            main_pad = (pad["left"], pad["right"]) if axis == "horizontal" else (pad["top"], pad["bottom"])
            sym = abs(main_pad[0] - main_pad[1]) <= tol
            ext = (iw if axis == "horizontal" else ih) / self.s
            margins: dict[str, float] = {}
            if uniform and len(kids) >= 3 or (uniform and len(kids) == 2 and not (sym and main_pad[0] < 0.12 * ext and gaps[0] > 2 * max(main_pad[0], 1))):
                gap, dist = round(sum(gaps) / len(gaps), 2), "start"
            elif sym and main_pad[0] < 0.12 * ext and len(kids) == 2:
                gap, dist = 0, "space-between"
            else:  # irregular spacing: smallest gap on the container, the deviations as per-child margins (IR_SPEC 9.3)
                gap, dist = round(min(gaps), 2), "start"
                n.children = sorted(kids, key=(lambda k: (k.x, k.y)) if axis == "horizontal" else (lambda k: (k.y, k.x)))
                for i, k in enumerate(n.children[1:]):
                    if gaps[i] - gap > 0.5:
                        margins[k.rid] = round(gaps[i] - gap, 2)
            al = [self.ev(e) for e in evs.get("alignment", []) if self.ev(e)["axis"] == ("y" if axis == "horizontal" else "x")]
            cross_total = (ih if axis == "horizontal" else iw) / self.s
            fills = all(sz.get((k.rid, "y" if axis == "horizontal" else "x"), {}).get("extent_ratio_of_container", 0) >= 0.98 for k in kids)
            align = "stretch" if fills else (al[0]["edge"] if al and al[0]["residual_px"] <= tol else "start")
            node_layout = {"mode": "stack", "stack": {"axis": axis, "gap": px(gap), "align": align, "distribute": dist}}
            lay_sup = sup_base + [eid] + evs.get("alignment", [])
        else:
            lr = evs.get("layout_residual", [])
            node_layout = {"mode": "absolute", "absolute": {"fallback": {"reason": "insufficient_evidence" if not lr else "irregular_scatter", "supports": lr}}}
            lay_sup = sup_base + lr
            spacing.pop("padding", None)
        # cross-axis slack is not padding: with start/end alignment the container's extent comes from its parent, so mirror the measured side
        if node_layout["mode"] == "stack":
            s_ = node_layout["stack"]
            cross = ("left", "right") if s_["axis"] == "vertical" else ("top", "bottom")
            if s_.get("align") == "start":
                pad[cross[1]] = pad[cross[0]]
            elif s_.get("align") == "end":
                pad[cross[0]] = pad[cross[1]]
        if parent_is_root_page(n):  # the page root fills the viewport: space below the last section is empty canvas, not padding
            pad["bottom"] = 0.0
        if node_layout["mode"] != "absolute" and any(v > 0.5 for v in pad.values()):
            spacing["padding"] = {k: px(v) for k, v in pad.items() if v > 0.5}
        node["layout"] = node_layout
        if axes and not grid and len(kids) >= 2:
            n.children = sorted(n.children, key=(lambda k: (k.x, k.y)) if axes[0][0]["axis"] == "horizontal" else (lambda k: (k.y, k.x)))
        mode = node_layout["mode"]
        conf = 0.9 if mode != "absolute" else 0.3
        inf["layout"] = rec(f"layout.{mode}/1", conf, [e for e in lay_sup if self.p.evidence[e]["kind"] in V.ALLOWED_SUPPORTS["layout"]])
        # children sizing and placement
        for k in kids:
            kn = self.pending_child(k)
            kn["size"], kn["spacing"], kn["placement"] = {}, {}, {}
        node["_child_ctx"] = {"margins": locals().get("margins", {}), "mode": mode, "node_layout": node_layout, "sz": sz, "iw": iw, "ih": ih, "ix": ix, "iy": iy, "tol": tol}
        if spacing:
            node["spacing"] = spacing

    def pending_child(self, k: Node) -> JSON:
        return k.notes.setdefault("_pending", {})

    def finalize_children(self) -> None:
        """Apply parent-driven sizing/placement to children now that every node exists."""
        for n in self.order:
            nid = self.nid(n)
            node = self.nodes[nid]
            ctx = node.pop("_child_ctx", None)
            if not ctx:
                continue
            mode, lay, sz, tol = ctx["mode"], ctx["node_layout"], ctx["sz"], ctx["tol"]
            for k in n.children:
                kn = self.nodes[self.nid(k)]
                axis = lay["stack"]["axis"] if mode == "stack" else None
                ratio = lambda a: sz.get((k.rid, a), {}).get("extent_ratio_of_container", 0.0)  # noqa: E731
                size: JSON = {}
                kid_sup = [e for e in n.notes.get("ev", {}).get("size_sample", [])]
                if k.rid in ctx["margins"]:
                    kn.setdefault("spacing", {})["margin"] = {("top" if axis == "vertical" else "left"): px(ctx["margins"][k.rid])}
                    kid_sup += n.notes.get("ev", {}).get("stack_axis", []) + n.notes.get("ev", {}).get("spacing_sample", [])
                if mode == "absolute":
                    kn["placement"] = {"absolute": {"left": px(self.d(k.x - ctx["ix"])), "top": px(self.d(k.y - ctx["iy"]))}}
                    size = {"w": {"kind": "fixed", "px": self.d(k.w)}, "h": {"kind": "fixed", "px": self.d(k.h)}}
                elif mode == "grid":
                    if k.kind in ("container", "group"):
                        size["w"] = {"kind": "fill"}
                else:
                    cross = "x" if axis == "vertical" else "y"
                    if ratio(cross) >= 0.98 and k.kind != "leaf":
                        size["w" if axis == "vertical" else "h"] = {"kind": "fill"}
                    elif k.kind in ("group", "container") and not (k.kind == "container" and k.children) and False:
                        pass
                    elif axis == "vertical" and k.kind == "group" and k.children and self.nodes[self.nid(k)].get("layout", {}).get("mode") == "grid":
                        size["w"] = {"kind": "fixed", "px": self.d(k.w)}
                    elif axis == "horizontal" and k.kind == "group" and self.nodes[self.nid(k)].get("layout", {}).get("mode") == "grid":
                        size["w"] = {"kind": "fixed", "px": self.d(k.w)}
                    main = "w" if axis == "horizontal" else "h"
                    if len(n.children) == 1 and ratio("x" if axis == "horizontal" else "y") >= 0.98 and k.kind != "leaf":
                        size[main] = {"kind": "fill"}
                if size and (size.get("w", {}).get("kind") == "fixed" or size.get("h", {}).get("kind") == "fixed"):
                    kid_sup += n.notes.get("ev", {}).get("grid_fit", [])
                if kn.get("spacing") and "layout" not in kn["inference"]:
                    kn["inference"]["layout"] = rec("layout.size/1", 0.85, [e for e in kid_sup if self.p.evidence[e]["kind"] in V.ALLOWED_SUPPORTS["layout"]])
                if size:
                    kn["size"] = {**kn.get("size", {}), **size} if kn.get("size") else size
                    prior = kn["inference"].get("layout")
                    sups = sorted(set((prior or {}).get("supports", []) + kid_sup + n.notes.get("ev", {}).get("layout_residual", [])))
                    sups = [e for e in sups if self.p.evidence[e]["kind"] in V.ALLOWED_SUPPORTS["layout"]]
                    kn["inference"]["layout"] = rec("layout.size/1", 0.85, sups)
                for f in ("size", "spacing", "placement"):
                    if kn.get(f) == {}:
                        kn.pop(f)
                if kn.get("placement") and "layout" not in kn["inference"]:
                    kn["inference"]["layout"] = rec("layout.size/1", 0.85, n.notes.get("ev", {}).get("layout_residual", []))
            k_nodes = None

    def run(self, root: Node, page_id: str) -> str:
        self.page_id = page_id
        root.notes["is_root"] = True
        self.order: list[Node] = list(root.walk())
        rid = self.build(root, None)
        self.finalize_children()
        return rid

    def finish_roles(self) -> None:
        if len(self.sizes) < 2:
            return
        med = sorted(self.sizes)[len(self.sizes) // 2]
        heads = sorted({s for s, _ in self.heading_ids if s >= max(24.0, 1.5 * med)}, reverse=True)
        for size, nid in self.heading_ids:
            if size in heads:
                node = self.nodes[nid]
                node["role"] = "heading"
                node["text"]["heading_level"] = min(heads.index(size) + 1, 6)
                tm = [e for e in self.p.evidence if self.p.evidence[e]["kind"] == "text_metrics" and self.nodes[nid] is node and self.nodes_region(nid) in self.p.evidence[e]["regions"]]
                node["inference"]["role"] = rec("role.classify/1", 0.6, tm)

    def nodes_region(self, nid: str) -> str:
        return self.real[nid]["regions"][0]


REDACT_RULE = "redact-all-text/1"


def build_ir(p: Perception, cfg: JSON, project_name: str, page_name: str, write_asset: Callable[[bytes], str], *, config_extra: JSON | None = None) -> JSON:
    """Assemble and validate a committed single-screen IR from a Perception."""
    sha = p.image.sha256
    src_id, scr_id, pg_id = p.source_id, derive_id("scr", sha), derive_id("pg", sha)
    vc_id, prj_id = derive_id("vc", sha), derive_id("prj", sha, project_name)
    b = Builder(p, cfg, write_asset)
    root_id = b.run(p.root, pg_id)
    b.finish_roles()
    for nid, node in b.nodes.items():
        node["status"] = derive_status(node)
    lum_ids = p.root.notes.get("ev", {}).get("luminance_profile", [])
    luma = p.evidence[lum_ids[0]]["measure"]["mean_luma"] if lum_ids else 1.0
    mkind = "light" if luma >= 0.5 else "dark"
    mode_id = derive_id("mode", mkind)
    root_ev = p.root.notes.get("ev", {}).get("containment", [])
    values = {k: v for k, v in cfg["thresholds"].items()}
    values["heuristics.font_metrics_em"] = [ASC_H, X_H, DESC_H]
    values["heuristics.bold_stroke_em"] = BOLD_STROKE_EM
    redacting = bool(cfg.get("privacy", {}).get("redact_text"))
    profile_hash = "sha256:" + sha256_hex(canonical_dumps({"rule": REDACT_RULE, "replacement": REDACT_PLACEHOLDER, "stage": "post_inference"}).encode())
    if redacting:  # the profile hash is part of inference_config, hence of content_hash: redacted and unredacted runs are never silently comparable
        values["redaction.profile_id"], values["redaction.profile_hash"] = REDACT_RULE, profile_hash
    icfg = {"config_hash": "sha256:" + sha256_hex(canonical_dumps(values).encode()), "values": values}
    vw = float(p.image.declared["viewport_width"]) if p.image.declared.get("viewport_width") else round(p.image.pixel_size["w"] / p.scale, 2)
    declared = {k: v for k, v in p.image.declared.items() if k in ("device_pixel_ratio", "viewport_width", "mode", "state", "page_hint")}
    doc: JSON = {
        "schema_version": V.SCHEMA_VERSION, "ir_state": "committed", "extensions_used": [], "extensions_required": [],
        "meta": {"created_by": f"screen2code {__version__}"},
        "project": {"id": prj_id, "name": project_name, "name_source": "user", "default_mode": mode_id, "redaction": ({"mode": "on", "profile_id": REDACT_RULE, "profile_hash": profile_hash, "stage": "post_inference", "artifacts": "retained", "keep_original_digest": False} if redacting else {"mode": "off"})},
        "inference_config": icfg, "producers": p.producers,
        "sources": {src_id: {"id": src_id, "media_type": p.image.media_type, "sha256": sha, "pixel_size": p.image.pixel_size, **({"declared": declared} if declared else {})}},
        "regions": p.regions, "evidence": p.evidence,
        "screens": {scr_id: {"id": scr_id, "source": src_id,
                             "resolved": {"page": pg_id, "viewport_width": vw, "scale": p.scale, "viewport_class": vc_id, "mode": mode_id},
                             "origin": {"page": "declared" if p.image.declared.get("page_hint") else "inferred", "viewport_width": "declared" if p.image.declared.get("viewport_width") or p.scale_origin == "declared" else "assumed", "scale": p.scale_origin,
                                        "viewport_class": "inferred", "mode": "inferred"},
                             "inference": rec("screen.resolve/1", 0.9, lum_ids)}},
        "modes": {mode_id: {"id": mode_id, "name": mkind.capitalize(), "kind": mkind, "inference": rec("mode.detect/1", 0.9, lum_ids)}},
        "pages": {pg_id: {"id": pg_id, "name": page_name, "name_source": "inferred", "root": root_id,
                          "viewport_classes": [{"id": vc_id, "min": 0, "max_exclusive": None}], "base_class": vc_id, "base_basis": scr_id,
                          "responsive": [], "states": [], "constraints": [], "completeness": {"state": "complete"}}},
        "nodes": b.nodes,
        "realizations": {scr_id: {"inference": rec("realize.match/1", PRIOR["realize"], root_ev), "nodes": b.real}},
        "components": {}, "tokens": {"color": {}, "type": {}, "space": {}, "radius": {}, "border_width": {}, "shadow": {}, "opacity": {}, "scales": {}},
        "assets": b.assets, "relations": [], "disputes": [], "redactions": b.redactions,
        "lineage": {"tombstones": [], "counter": 0, "migrated_from": [], "repairs": []},
    }
    doc["pages"][pg_id]["completeness"]["state"] = derive_completeness(doc, pg_id)
    rep = validate(doc, 2)
    if not rep.ok:
        raise S2CError("S2C-IR-INVALID", f"reconstruction produced an invalid IR ({len(rep.errors)} errors)", "this is a Screen2Code bug; please report it",
                       {"diagnostics": [d.to_dict() for d in rep.errors[:20]]})
    return doc


__all__ = ["build_ir", "Builder", "content_hash"]
