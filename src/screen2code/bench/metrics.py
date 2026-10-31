"""Structure metrics against synthetic ground truth (EVALUATION section 5): detection, text, typography, colour, layout."""
from __future__ import annotations

import random
from typing import Any

import numpy as np
from skimage.color import deltaE_ciede2000, rgb2lab

JSON = dict[str, Any]
IOU_MIN, IOMIN_TEXT = 0.7, 0.6


def edit_distance(a: str, b: str) -> int:
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def de(hex_a: str, hex_b: str) -> float:
    def lab(h: str) -> np.ndarray:
        return rgb2lab(np.array([[[int(h[i : i + 2], 16) for i in (1, 3, 5)]]], dtype=np.float64) / 255.0)
    return float(deltaE_ciede2000(lab(hex_a), lab(hex_b))[0, 0])


def _iou(a: tuple[float, float, float, float], b: tuple[float, float, float, float], by_min: bool = False) -> float:
    ix = max(0.0, min(a[0] + a[2], b[0] + b[2]) - max(a[0], b[0]))
    iy = max(0.0, min(a[1] + a[3], b[1] + b[3]) - max(a[1], b[1]))
    inter = ix * iy
    denom = min(a[2] * a[3], b[2] * b[3]) if by_min else a[2] * a[3] + b[2] * b[3] - inter
    return inter / denom if denom > 0 else 0.0


def _ir_rects(ir: JSON) -> dict[str, tuple[float, float, float, float]]:
    scr = sorted(ir["screens"])[0]
    s = float(ir["screens"][scr]["resolved"]["scale"])
    out = {}
    for nid, e in ir["realizations"][scr]["nodes"].items():
        rs = [ir["regions"][r]["rect"] for r in e["regions"]]
        x0, y0 = min(r["x"] for r in rs), min(r["y"] for r in rs)
        x1, y1 = max(r["x"] + r["w"] for r in rs), max(r["y"] + r["h"] for r in rs)
        out[nid] = (x0 / s, y0 / s, (x1 - x0) / s, (y1 - y0) / s)
    return out


def _node_of(ir: JSON, key: str) -> JSON:
    return ir["nodes"][key.split("/")[-1]]  # component-internal keys resolve to the definition node


def resolve_type(ir: JSON, style: JSON) -> JSON:
    """Inline type style, or a token reference merged with its overrides."""
    if "token" in style:
        return {**ir["tokens"]["type"][style["token"]]["value"], **style.get("overrides", {})}
    return style


def resolve_hex(ir: JSON, ref: JSON | None) -> str | None:
    """Colour of a ColorRef in the project's default mode (literal, token value, or token by_mode)."""
    if not ref:
        return None
    if "literal" in ref:
        return ref["literal"]["hex"]
    tok = next((d[ref["token"]] for c, d in ir["tokens"].items() if c != "scales" and ref["token"] in d), None)
    if not tok:
        return None
    if "value" in tok:
        return tok["value"].get("hex")
    mode = ir["project"].get("default_mode")
    bm = tok["by_mode"].get(mode) or next(iter(tok["by_mode"].values()))
    return bm["value"].get("hex")


def _text_value(ir: JSON, key: str) -> str:
    """Accepted text of a matched node; for component-internal keys the instance's parameter value."""
    n = _node_of(ir, key)
    content = n["text"]["content"]
    if "param" in content and "/" in key:
        inst = ir["nodes"][key.split("/")[0]]["instance"]["params"]
        return (inst.get(content["param"]) or {}).get("value") or ""
    return content.get("value") or ""


COMPAT = {"text": {"text"}, "image": {"image", "opaque"}, "container": {"box", "shape", "instance"}}


def score_scene(gt: list[JSON], boxes: dict[str, JSON], ir: JSON) -> JSON:
    rects = _ir_rects(ir)
    cands = []
    for g in gt:
        b = boxes.get(g["id"])
        if not b:
            continue
        gb = (b["x"], b["y"], b["w"], b["h"])
        for nid, r in rects.items():
            if _node_of(ir, nid)["kind"] not in COMPAT[g["kind"]]:
                continue
            by_min = g["kind"] == "text"
            sc = _iou(gb, r, by_min)
            if sc >= (IOMIN_TEXT if by_min else IOU_MIN):
                cands.append((sc, g["id"], nid))
    cands.sort(key=lambda t: (-t[0], t[1], t[2]))
    gmatch: dict[str, str] = {}
    used: set[str] = set()
    for sc, gid, nid in cands:
        if gid not in gmatch and nid not in used:
            gmatch[gid] = nid
            used.add(nid)
    byk = {k: [g for g in gt if g["kind"] == k] for k in COMPAT}
    out: JSON = {"ir_nodes": len(rects), "gt_elements": len(gt), "matched": len(gmatch)}
    out["precision"] = round(len(used) / max(1, len(rects)), 4)
    out["recall"] = round(len(gmatch) / max(1, len(gt)), 4)
    for k, lst in byk.items():
        if k == "container":
            vis = [g for g in lst if g.get("visible")]
            out["recall_container_visible"] = round(sum(1 for g in vis if g["id"] in gmatch) / len(vis), 4) if vis else None
        out[f"recall_{k}"] = round(sum(1 for g in lst if g["id"] in gmatch) / len(lst), 4) if lst else None
    cer, exact, size_err, size_ok, weight_ok, tcol = [], [], [], [], [], []
    for g in byk["text"]:
        nid = gmatch.get(g["id"])
        if not nid:
            continue
        n = _node_of(ir, nid)
        val = _text_value(ir, nid)
        cer.append(edit_distance(g["text"], val) / max(1, len(g["text"])))
        exact.append(val == g["text"])
        st = resolve_type(ir, n["text"]["style"])
        size_err.append(abs(st["size"]["px"] - g["font_size"]))
        size_ok.append(abs(st["size"]["px"] - g["font_size"]) <= 1.0)
        weight_ok.append(st["weight"] == g["weight"])
        hx = resolve_hex(ir, st.get("color"))
        if hx:
            tcol.append(de(g["color"], hx))
    fills, radii, lay_ok = [], [], []
    for g in byk["container"]:
        nid = gmatch.get(g["id"])
        if not nid:
            continue
        n = _node_of(ir, nid)
        f = (n.get("style") or {}).get("fill")
        hx = resolve_hex(ir, f["color"]) if f and f["kind"] == "solid" else None
        if g.get("fill") and hx:
            fills.append(de(g["fill"], hx))
        if g.get("fill"):
            rad = ((n.get("style") or {}).get("radius") or {}).get("all", {"px": 0.0})
            if "token" in rad:
                rad = next(d[rad["token"]]["value"] for c, d in ir["tokens"].items() if c != "scales" and rad["token"] in d)
            radii.append(abs(rad.get("px", 0.0) - g["radius"]))
        nk = [c for c in gt if False]
        if g["layout"] in ("flex", "grid") and len(n.get("children", [])) >= 2:
            lay = (n.get("layout") or {})
            mode = lay.get("mode")
            if g["layout"] == "grid":
                lay_ok.append(mode == "grid" and len(lay["grid"]["columns"]) == g.get("columns"))
            else:
                ax = (lay.get("stack") or lay.get("flex") or {}).get("axis")
                lay_ok.append(mode in ("stack", "flex") and ax == ("horizontal" if g["axis"] == "row" else "vertical"))
    mean = lambda v: round(float(np.mean(v)), 4) if v else None  # noqa: E731
    out.update(text_cer=mean(cer), text_exact=mean(exact), font_size_mae_px=mean(size_err), font_size_within_1px=mean(size_ok), weight_accuracy=mean(weight_ok), text_color_de=mean(tcol),
               fill_de=mean(fills), radius_mae_px=mean(radii), layout_accuracy=mean(lay_ok), text_matched=len(cer), layout_checked=len(lay_ok))
    return out


def bootstrap_ci(values: list[float], seed: int = 0, n: int = 1000) -> tuple[float, float]:
    rng = random.Random(seed)
    v = [x for x in values if x is not None]
    if not v:
        return (float("nan"), float("nan"))
    means = sorted(sum(rng.choice(v) for _ in v) / len(v) for _ in range(n))
    return round(means[int(0.025 * n)], 4), round(means[int(0.975 * n)], 4)
