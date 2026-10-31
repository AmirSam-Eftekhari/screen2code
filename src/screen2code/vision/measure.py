"""S3 measurement: deterministic evidence from regions and pixels (PIPELINE section 4.4).

Everything stored in ``evidence`` here is observed (``measured``, or ``reported`` for OCR) and uses no structural vocabulary.
Lengths in measures are design px (source px divided by the screen scale).
"""
from __future__ import annotations

from typing import Any

import numpy as np
from skimage.color import deltaE_ciede2000, rgb2lab

from ..ir import canonical_dumps, derive_id
from .segment import Node, dist, dominant


def hexof(c: tuple[int, int, int]) -> str:
    return "#{:02X}{:02X}{:02X}".format(*c)


def luma(c: tuple[int, int, int]) -> float:
    return (0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]) / 255.0


def contrast_ratio(a: tuple[int, int, int], b: tuple[int, int, int]) -> float:
    def lin(v: int) -> float:
        s = v / 255.0
        return s / 12.92 if s <= 0.03928 else ((s + 0.055) / 1.055) ** 2.4
    la = 0.2126 * lin(a[0]) + 0.7152 * lin(a[1]) + 0.0722 * lin(a[2])
    lb = 0.2126 * lin(b[0]) + 0.7152 * lin(b[1]) + 0.0722 * lin(b[2])
    hi, lo = max(la, lb), min(la, lb)
    return round((hi + 0.05) / (lo + 0.05), 2)


class EvidenceSink:
    def __init__(self, producer: str):
        self.producer = producer
        self.items: dict[str, dict[str, Any]] = {}

    def add(self, kind: str, regions: list[str], measure: dict[str, Any], basis: str = "measured", producer: str | None = None, node: Node | None = None) -> str:
        prod = producer or self.producer
        regs = sorted(set(regions))
        eid = derive_id("evd", kind, basis, prod, ",".join(regs), canonical_dumps(measure))
        self.items.setdefault(eid, {"id": eid, "kind": kind, "basis": basis, "producer": prod, "regions": regs, "measure": measure})
        if node is not None:
            node.notes.setdefault("ev", {}).setdefault(kind, []).append(eid)
        return eid


def _spread(rgb: np.ndarray, rect: tuple[int, int, int, int], mode: tuple[int, int, int]) -> float:
    x, y, w, h = rect
    reg = rgb[y : y + h, x : x + w].reshape(-1, 3)
    near = reg[np.abs(reg.astype(np.int16) - np.array(mode, dtype=np.int16)).max(axis=1) <= 24]
    if len(near) == 0:
        return 0.0
    if len(near) > 3000:
        near = near[:: len(near) // 3000]
    lab = rgb2lab(near.reshape(1, -1, 3).astype(np.float64) / 255.0)
    ref = rgb2lab(np.array(mode, dtype=np.float64).reshape(1, 1, 3) / 255.0)
    return round(float(np.percentile(deltaE_ciede2000(lab, np.broadcast_to(ref, lab.shape)), 90)), 2)


def _stroke_width(alpha: np.ndarray) -> float:
    """Mean stroke width in source px: ink mass divided by skeleton length (scale-free weight cue)."""
    from skimage.morphology import skeletonize

    core = alpha > 0.5
    if core.sum() < 4:
        return 0.0
    skel = int(skeletonize(core).sum())
    return float(alpha.sum()) / max(1, skel)


def _ink(rgb: np.ndarray, n: Node) -> tuple[np.ndarray, tuple[int, int, int]]:
    reg = rgb[n.y : n.y + n.h, n.x : n.x + n.w]
    mask = np.abs(reg.astype(np.int16) - np.array(n.fill, dtype=np.int16)).max(axis=2) > 24
    if not mask.any():
        return mask, n.fill
    d = np.abs(reg.astype(np.int16) - np.array(n.fill, dtype=np.int16)).sum(axis=2)
    k = max(1, int(mask.sum() * 0.1))
    far = reg[mask][np.argsort(-d[mask])[:k]]
    return mask, tuple(int(v) for v in np.median(far, axis=0))  # type: ignore[return-value]


def _overlap(a: Node, b: Node) -> float:
    ix = max(0, min(a.x + a.w, b.x + b.w) - max(a.x, b.x))
    iy = max(0, min(a.y + a.h, b.y + b.h) - max(a.y, b.y))
    return ix * iy / max(1, min(a.w * a.h, b.w * b.h))


def _sig(n: Node) -> tuple[Any, ...]:
    kids = sorted(n.children, key=lambda c: (c.y, c.x))
    rel = [((c.x - n.x) / max(1, n.w), (c.y - n.y) / max(1, n.h), c.w / max(1, n.w), c.h / max(1, n.h)) for c in kids]
    return (n.w, n.h, n.kind, len(kids), rel)


def _similarity(a: Node, b: Node) -> float:
    sa, sb = _sig(a), _sig(b)
    if sa[2] != sb[2] or sa[3] != sb[3]:
        return 0.0
    parts = [abs(sa[0] - sb[0]) / max(sa[0], sb[0]), abs(sa[1] - sb[1]) / max(sa[1], sb[1])]
    for r1, r2 in zip(sa[4], sb[4]):
        parts.append(sum(abs(p - q) for p, q in zip(r1, r2)) / 4.0)
    return round(max(0.0, 1.0 - float(np.mean(parts))), 3)


def _cluster(vals: list[float], tol: float) -> list[list[int]]:
    order = sorted(range(len(vals)), key=lambda i: vals[i])
    groups: list[list[int]] = []
    for i in order:
        if groups and vals[i] - vals[groups[-1][-1]] <= tol:
            groups[-1].append(i)
        else:
            groups.append([i])
    return groups


def measure_tree(rgb: np.ndarray, root: Node, sink: EvidenceSink, scale: float, tol_px: float = 2.0) -> None:
    s = scale
    d = lambda v: round(v / s, 2)  # noqa: E731 - source px -> design px
    H, W = rgb.shape[:2]
    sink.add("luminance_profile", [root.rid], {"mean_luma": round(float(rgb.mean(axis=2).mean() / 255.0), 3)}, node=root)
    for n in root.walk():
        rid = n.rid
        if n.kind in ("container", "group"):
            if n.kind == "container":
                clusters = [{"hex": hexof(n.fill), "usage": "area_fill", "n_px": int(n.w * n.h), "spread_de2000": _spread(rgb, n.rect, n.fill)}]
                if n.border_rgb:
                    clusters.append({"hex": hexof(n.border_rgb), "usage": "border", "n_px": int(2 * (n.w + n.h) * n.border_w), "spread_de2000": 0.0})
                sink.add("color_sample", [rid], {"clusters": clusters}, node=n)
                if n.border_w or n.radius:
                    sink.add("border_profile", [rid], {"corner_radius_px": d(n.radius), "border_width_px": d(n.border_w)}, node=n)
            kids = n.children
            bw = n.border_w
            ix, iy, iw, ih = n.x + bw, n.y + bw, n.w - 2 * bw, n.h - 2 * bw
            if kids:
                regs = [rid] + [k.rid for k in kids]
                ov = max((_overlap(a, b) for i, a in enumerate(kids) for b in kids[i + 1 :]), default=0.0)
                sink.add("containment", regs, {"children": len(kids), "max_overlap_ratio": round(ov, 3)}, node=n)
                left = min(k.x for k in kids) - ix
                top = min(k.y for k in kids) - iy
                right = ix + iw - max(k.x + k.w for k in kids)
                bottom = iy + ih - max(k.y + k.h for k in kids)
                samples = {"padding_px": {"top": d(top), "right": d(right), "bottom": d(bottom), "left": d(left)}}
                fills = [{"region": k.rid, "axis": ax, "extent_ratio_of_container": round(k_ext / ext, 3), "extent_px": d(k_ext)}
                         for k in kids for ax, k_ext, ext in (("x", k.w, iw), ("y", k.h, ih)) if ext > 0]
                sink.add("size_sample", [rid] + [k.rid for k in kids], {"items": fills}, node=n)
            if len(kids) >= 2:
                for axis in ("horizontal", "vertical"):
                    srt = sorted(kids, key=(lambda k: (k.x, k.y)) if axis == "horizontal" else (lambda k: (k.y, k.x)))
                    ok, gaps = 0, []
                    for a, b in zip(srt, srt[1:]):
                        if axis == "horizontal":
                            gap = b.x - (a.x + a.w)
                            ov = max(0, min(a.y + a.h, b.y + b.h) - max(a.y, b.y)) / max(1, min(a.h, b.h))
                        else:
                            gap = b.y - (a.y + a.h)
                            ov = max(0, min(a.x + a.w, b.x + b.w) - max(a.x, b.x)) / max(1, min(a.w, b.w))
                        if gap >= -1 and ov >= 0.3:
                            ok += 1
                        gaps.append(d(gap))
                    cons = round(ok / (len(srt) - 1), 3)
                    sink.add("stack_axis", [rid] + [k.rid for k in srt], {"axis": axis, "order_consistency": cons, "gap_samples_px": gaps}, node=n)
                    if cons == 1.0:
                        if axis == "horizontal":
                            e = {"start": [k.y for k in srt], "center": [k.y + k.h / 2 for k in srt], "end": [k.y + k.h for k in srt]}
                        else:
                            e = {"start": [k.x for k in srt], "center": [k.x + k.w / 2 for k in srt], "end": [k.x + k.w for k in srt]}
                        edge = min(e, key=lambda k: max(e[k]) - min(e[k]))
                        sink.add("alignment", [k.rid for k in srt], {"axis": "y" if axis == "horizontal" else "x", "edge": edge, "residual_px": d(max(e[edge]) - min(e[edge])), "n": len(srt)}, node=n)
                cols = _cluster([k.x for k in kids], tol_px * s * 1.5)
                rows = _cluster([k.y for k in kids], tol_px * s * 1.5)
                cell: dict[tuple[int, int], int] = {}
                for ci, cg in enumerate(cols):
                    for i in cg:
                        for ri, rg in enumerate(rows):
                            if i in rg:
                                cell[(ci, ri)] = cell.get((ci, ri), 0) + 1
                if len(cols) >= 2 and all(v == 1 for v in cell.values()) and len(cell) == len(cols) * len(rows):  # full lattice only
                    cw = [max(kids[i].w for i in cg) for cg in cols]
                    cx = [min(kids[i].x for i in cg) for cg in cols]
                    gaps_c = [cx[j + 1] - (cx[j] + cw[j]) for j in range(len(cols) - 1)]
                    rh = [max(kids[i].h for i in rg) for rg in rows]
                    ry = [min(kids[i].y for i in rg) for rg in rows]
                    gaps_r = [ry[j + 1] - (ry[j] + rh[j]) for j in range(len(rows) - 1)]
                    res = max([abs(g - float(np.mean(gaps_c))) for g in gaps_c] + [max(max(kids[i].x for i in cg) - min(kids[i].x for i in cg) for cg in cols)])
                    sink.add("grid_fit", regs, {"columns": len(cols), "rows": len(rows), "track_widths_px": [d(v) for v in cw], "row_heights_px": [d(v) for v in rh],
                                                "col_gap_px": d(float(np.mean(gaps_c))), "row_gap_px": d(float(np.mean(gaps_r))) if gaps_r else 0.0,
                                                "residual_px": d(res), "equal_widths": max(cw) - min(cw) <= tol_px * s}, node=n)
                # repetition among siblings
                groups: list[list[Node]] = []
                for k in kids:
                    for g in groups:
                        if _similarity(g[0], k) >= 0.75:
                            g.append(k)
                            break
                    else:
                        groups.append([k])
                for g in groups:
                    if len(g) >= 2 and g[0].kind in ("container", "image"):
                        sim = min(_similarity(a, b) for i, a in enumerate(g) for b in g[i + 1 :])
                        ax = "x" if len({k.y for k in g}) == 1 else "y" if len({k.x for k in g}) == 1 else "mixed"
                        eid = sink.add("repetition", [k.rid for k in g], {"similarity": sim, "count": len(g), "axis": ax}, node=n)
                        for k in g:
                            k.notes.setdefault("ev", {}).setdefault("repetition", []).append(eid)
            if len(kids) >= 2 and not any(n.notes.get("ev", {}).get(k) for k in ("grid_fit",)):
                cons = [sink.items[e]["measure"]["order_consistency"] for e in n.notes.get("ev", {}).get("stack_axis", [])]
                if not cons or max(cons) < 1.0:
                    ov2 = max((_overlap(a, b) for i, a in enumerate(kids) for b in kids[i + 1 :]), default=0.0)
                    sink.add("layout_residual", [rid] + [k.rid for k in kids], {"explained_by": "none", "children": len(kids), "max_overlap_ratio": round(ov2, 3),
                                                                              "best_order_consistency": max(cons) if cons else 0.0}, node=n)
            if kids:
                sink.add("spacing_sample", [rid] + [k.rid for k in kids], samples, node=n)
            if n is not root and len(kids) == 1 and kids[0].reading and bw == 0:
                k = kids[0]
                cx_off = abs((k.x + k.w / 2) - (n.x + n.w / 2)) / s
                cy_off = abs((k.y + k.h / 2) - (n.y + n.h / 2)) / s
                _, ink = _ink(rgb, k)
                sink.add("affordance_cue", [rid, k.rid], {"filled": True, "text_centered": bool(cx_off <= 3 and cy_off <= 3), "corner_radius_px": d(n.radius),
                                                          "contrast_ratio": contrast_ratio(n.fill, ink)}, node=n)
        elif n.kind == "image":
            dc, _ = dominant(rgb[n.y : n.y + n.h, n.x : n.x + n.w])
            sink.add("asset_candidate", [rid], {"occluded_ratio": 0.0, "overlaid_text": False, "aspect": round(n.w / n.h, 3), "dominant_color": hexof(dc),
                                                "resolution_scale": round(1.0 / s, 3)}, node=n)
        else:  # leaf
            if n.reading:
                mask, ink = _ink(rgb, n)
                if mask.any():
                    rows = mask.sum(axis=1)
                    nz = np.nonzero(rows)[0]
                    top, bot = int(nz[0]), int(nz[-1])
                    dense = np.nonzero(rows >= 0.5 * rows.max())[0]
                    base, xtop = int(dense[-1]), int(dense[0])
                    reg = rgb[n.y : n.y + n.h, n.x : n.x + n.w].astype(np.float64)
                    full = float(np.abs(np.array(ink, dtype=np.float64) - np.array(n.fill, dtype=np.float64)).sum()) or 1.0
                    alpha = np.clip(np.abs(reg - np.array(n.fill, dtype=np.float64)).sum(axis=2) / full, 0.0, 1.0)  # per-pixel ink coverage
                    sink.add("text_metrics", [rid], {"items": [{"region": rid, "ink_height_px": d(bot - top + 1), "baseline_offset_px": d(base - top), "x_top_offset_px": d(xtop - top),
                                                                "line_height_px": d(n.h), "stroke_ratio": round(float(alpha.sum()) / max(1, alpha.size), 3), "stroke_width_px": d(_stroke_width(alpha)),
                                                                "ink_hex": hexof(ink)}]}, node=n)
                    sink.add("color_sample", [rid], {"clusters": [{"hex": hexof(ink), "usage": "text", "n_px": int(mask.sum()), "spread_de2000": 0.0}]}, node=n)
            elif n.w > 3 and n.h > 3:
                dc, _ = dominant(rgb[n.y : n.y + n.h, n.x : n.x + n.w])
                sink.add("color_sample", [rid], {"clusters": [{"hex": hexof(dc), "usage": "area_fill", "n_px": int(n.w * n.h), "spread_de2000": 0.0}]}, node=n)
                if n.w >= 8 and n.h >= 8:
                    sink.add("asset_candidate", [rid], {"occluded_ratio": 0.0, "overlaid_text": False, "aspect": round(n.w / n.h, 3), "dominant_color": hexof(dc),
                                                        "resolution_scale": round(1.0 / s, 3)}, node=n)
