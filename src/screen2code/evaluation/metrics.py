"""Visual evaluation (EVALUATION sections 2-6): an extensible metric vector, never a single score.

Implemented: Pixel, SSIM, Edge, Color, Layout, MissingElement, plus a Composite whose weights are recorded.
Not implemented (reported as unavailable, never faked): Typography, Perceptual (LPIPS), Responsive, Theme.
"""
from __future__ import annotations

import json
import platform
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

import cv2
import numpy as np
import skimage
from PIL import Image
from skimage.color import deltaE_ciede2000, rgb2lab
from skimage.metrics import structural_similarity

from ..ir import content_hash

JSON = dict[str, Any]
PIXEL_TOL = 24
EDGE_TOL_PX = 2
COMPOSITE_WEIGHTS = {"ssim": 0.3, "edge_f1": 0.2, "layout_mean_iou": 0.3, "pixel_match": 0.2}
UNAVAILABLE = {
    "typography": "not implemented: needs rendered text metrics and an OCR comparison (EVALUATION.md 4); reported as unavailable",
    "perceptual_lpips": "not implemented: requires LPIPS weights through the model manager",
    "responsive": "not implemented in this release (multi-viewport evaluation)",
    "theme": "not implemented in this release (per-mode evaluation)",
}


@dataclass
class EvalContext:
    ref: np.ndarray  # H x W x 3 uint8 (reference, design-aligned)
    gen: np.ndarray  # same shape (generated, padded/cropped to the reference)
    ir: JSON
    screen_id: str
    scale: float
    boxes: dict[str, dict[str, float]]  # rendered node boxes in CSS px
    mask: np.ndarray  # True where pixels are excluded from masked variants
    exclusions: JSON = field(default_factory=dict)
    cache: dict[str, Any] = field(default_factory=dict)


class Metric(Protocol):
    name: str
    version: str

    def compute(self, c: EvalContext) -> JSON: ...


def _gray(a: np.ndarray) -> np.ndarray:
    return cv2.cvtColor(a, cv2.COLOR_RGB2GRAY)


class PixelMetric:
    name, version = "pixel", "1"

    def compute(self, c: EvalContext) -> JSON:
        d = np.abs(c.ref.astype(np.int16) - c.gen.astype(np.int16))
        bad = d.max(axis=2) > PIXEL_TOL
        keep = ~c.mask
        out = {"mae": round(float(d.mean() / 255.0), 5), "mismatch_fraction": round(float(bad.mean()), 5), "pixel_match": round(float(1.0 - bad.mean()), 5)}
        if c.mask.any():
            out["masked"] = {"mae": round(float(d[keep].mean() / 255.0), 5), "mismatch_fraction": round(float(bad[keep].mean()), 5)}
        c.cache["diff"] = d
        return out


class SSIMMetric:
    name, version = "ssim", "1"

    def compute(self, c: EvalContext) -> JSON:
        score, smap = structural_similarity(_gray(c.ref), _gray(c.gen), full=True, data_range=255)
        c.cache["ssim_map"] = smap
        out = {"ssim": round(float(score), 5)}
        if c.mask.any():
            out["masked"] = {"ssim": round(float(smap[~c.mask].mean()), 5)}
        return out


class EdgeMetric:
    name, version = "edge", "1"

    def compute(self, c: EvalContext) -> JSON:
        er = cv2.Canny(_gray(c.ref), 50, 150) > 0
        eg = cv2.Canny(_gray(c.gen), 50, 150) > 0
        k = cv2.getStructuringElement(cv2.MORPH_RECT, (2 * EDGE_TOL_PX + 1, 2 * EDGE_TOL_PX + 1))
        dr, dg = cv2.dilate(er.astype(np.uint8), k) > 0, cv2.dilate(eg.astype(np.uint8), k) > 0
        prec = float((eg & dr).sum() / max(1, eg.sum()))
        rec = float((er & dg).sum() / max(1, er.sum()))
        f1 = 0.0 if prec + rec == 0 else 2 * prec * rec / (prec + rec)
        return {"edge_precision": round(prec, 4), "edge_recall": round(rec, 4), "edge_f1": round(f1, 4), "tolerance_px": EDGE_TOL_PX}


def _mode_color(a: np.ndarray) -> tuple[int, int, int]:
    flat = a.reshape(-1, 3).astype(np.uint32)
    key = (flat[:, 0] << 16) | (flat[:, 1] << 8) | flat[:, 2]
    vals, counts = np.unique(key, return_counts=True)
    v = int(vals[counts.argmax()])
    return (v >> 16) & 255, (v >> 8) & 255, v & 255


def _realized_rects(c: EvalContext) -> dict[str, tuple[float, float, float, float]]:
    """Observed rectangles in design px per page node, from the IR's realizations."""
    out = {}
    real = c.ir["realizations"].get(c.screen_id, {"nodes": {}})["nodes"]
    for nid, e in real.items():
        if "/" in nid:  # component-internal observations have no rendered box of their own
            continue
        rs = [c.ir["regions"][r]["rect"] for r in e["regions"]]
        x0 = min(r["x"] for r in rs); y0 = min(r["y"] for r in rs)
        x1 = max(r["x"] + r["w"] for r in rs); y1 = max(r["y"] + r["h"] for r in rs)
        out[nid] = (x0 / c.scale, y0 / c.scale, (x1 - x0) / c.scale, (y1 - y0) / c.scale)
    return out


class ColorMetric:
    name, version = "color", "1"

    def compute(self, c: EvalContext) -> JSON:
        errs: dict[str, float] = {}
        for nid, (x, y, w, h) in _realized_rects(c).items():
            X, Y, W, H = (int(round(v * c.scale)) for v in (x, y, w, h))
            if W < 2 or H < 2:
                continue
            a, b = _mode_color(c.ref[Y : Y + H, X : X + W]), _mode_color(c.gen[Y : Y + H, X : X + W])
            la, lb = rgb2lab(np.array([[a]], dtype=np.float64) / 255.0), rgb2lab(np.array([[b]], dtype=np.float64) / 255.0)
            errs[nid] = round(float(deltaE_ciede2000(la, lb)[0, 0]), 3)
        c.cache["color_errs"] = errs
        vals = list(errs.values())
        return {"mean_delta_e2000": round(float(np.mean(vals)), 3) if vals else None, "max_delta_e2000": round(float(max(vals)), 3) if vals else None, "regions": len(vals)}


class LayoutMetric:
    name, version = "layout", "1"

    def compute(self, c: EvalContext) -> JSON:
        rects = _realized_rects(c)
        per: dict[str, JSON] = {}
        missing: list[str] = []
        for nid, (x, y, w, h) in rects.items():
            b = c.boxes.get(nid)
            if not b:
                missing.append(nid)
                continue
            ix = max(0.0, min(x + w, b["x"] + b["w"]) - max(x, b["x"]))
            iy = max(0.0, min(y + h, b["y"] + b["h"]) - max(y, b["y"]))
            inter = ix * iy
            union = w * h + b["w"] * b["h"] - inter
            iou = inter / union if union > 0 else 0.0
            per[nid] = {"iou": round(iou, 4), "dx": round(b["x"] - x, 2), "dy": round(b["y"] - y, 2), "dw": round(b["w"] - w, 2), "dh": round(b["h"] - h, 2)}
            if iou < 0.1:
                missing.append(nid)
        c.cache["layout_per_node"] = per
        ious = [v["iou"] for v in per.values()]
        pos = [abs(v["dx"]) + abs(v["dy"]) for v in per.values()]
        return {"layout_mean_iou": round(float(np.mean(ious)), 4) if ious else None, "layout_min_iou": round(float(min(ious)), 4) if ious else None,
                "mean_position_error_px": round(float(np.mean(pos)), 3) if pos else None, "matched_nodes": len(per), "expected_nodes": len(rects), "missing_nodes": sorted(set(missing))}


class MissingElementMetric:
    name, version = "missing_elements", "1"

    def compute(self, c: EvalContext) -> JSON:
        rects = _realized_rects(c)
        missing = sorted(n for n in rects if n not in c.boxes or c.cache.get("layout_per_node", {}).get(n, {"iou": 0})["iou"] < 0.1)
        opaque = sorted(n for n in rects if c.ir["nodes"][n]["kind"] == "opaque")
        return {"missing": missing, "missing_count": len(missing), "opaque_regions": opaque}


DEFAULT_METRICS: list[Metric] = [PixelMetric(), SSIMMetric(), EdgeMetric(), ColorMetric(), LayoutMetric(), MissingElementMetric()]


def align(ref: np.ndarray, gen: np.ndarray, pad_rgb: tuple[int, int, int]) -> tuple[np.ndarray, JSON]:
    """Pad/crop ``gen`` to the reference extent (policy recorded; mismatch reported, never hidden)."""
    H, W = ref.shape[:2]
    gh, gw = gen.shape[:2]
    out = np.empty_like(ref)
    out[:] = np.array(pad_rgb, dtype=np.uint8)
    h, w = min(H, gh), min(W, gw)
    out[:h, :w] = gen[:h, :w]
    return out, {"reference": [W, H], "generated": [gw, gh], "policy": "pad with the page background / crop to the reference extent", "size_mismatch": (gw, gh) != (W, H)}


def build_mask(ir: JSON, screen_id: str, scale: float, shape: tuple[int, int]) -> tuple[np.ndarray, JSON]:
    """Regions excluded from masked pixel variants: placeholder-rendered images, opaque regions (counted, never silent)."""
    mask = np.zeros(shape, dtype=bool)
    ex: JSON = {"placeholder_regions": [], "opaque_regions": [], "redacted_regions": [], "excluded_area_fraction": 0.0}
    real = ir["realizations"].get(screen_id, {"nodes": {}})["nodes"]
    for nid, e in real.items():
        n = ir["nodes"][nid.split("/")[-1]]
        aid = (n.get("media") or n.get("opaque") or {}).get("asset")
        asset = ir["assets"].get(aid) if isinstance(aid, str) else None
        kind = "opaque_regions" if n["kind"] == "opaque" else "placeholder_regions" if asset and asset["provenance"] == "placeholder" else None
        if kind is None and n["kind"] == "instance":  # coarse: the whole instance is excluded when any asset parameter is a placeholder
            for pv in (n["instance"].get("params") or {}).values():
                a2 = ir["assets"].get(pv.get("asset")) if isinstance(pv, dict) else None
                if a2 and a2["provenance"] == "placeholder":
                    kind = "placeholder_regions"
        for rid in e["regions"]:
            if ir["regions"][rid].get("redacted"):
                ex["redacted_regions"].append(rid)
                kind = "redacted_regions"
            if kind:
                r = ir["regions"][rid]["rect"]
                mask[r["y"] : r["y"] + r["h"], r["x"] : r["x"] + r["w"]] = True
                ex[kind].append(nid)
    ex["excluded_area_fraction"] = round(float(mask.mean()), 5)
    return mask, ex


def image_metrics(ref: np.ndarray, gen: np.ndarray) -> JSON:
    """Image-only metrics (no IR): used for baselines and the standalone comparison of two images."""
    ctx = EvalContext(ref, gen, {}, "", 1.0, {}, np.zeros(ref.shape[:2], dtype=bool))
    return {m.name: m.compute(ctx) for m in (PixelMetric(), SSIMMetric(), EdgeMetric())}


def composite(values: JSON) -> JSON:
    parts = {"ssim": values["ssim"]["ssim"], "edge_f1": values["edge"]["edge_f1"], "layout_mean_iou": values["layout"]["layout_mean_iou"] or 0.0, "pixel_match": values["pixel"]["pixel_match"]}
    score = sum(COMPOSITE_WEIGHTS[k] * parts[k] for k in COMPOSITE_WEIGHTS)
    return {"composite": round(score, 5), "weights": COMPOSITE_WEIGHTS, "members": parts, "note": "convenience aggregate; always read the full metric vector"}


def evaluate(reference_rgb: np.ndarray, generated_png: Path, ir: JSON, screen_id: str, render: JSON | None, *, ocr_free: bool = True, top_k: int = 5) -> tuple[JSON, JSON]:
    """Return (report, images). ``images`` maps artifact names to RGB arrays for the caller to write."""
    scale = float(ir["screens"][screen_id]["resolved"]["scale"])
    with Image.open(generated_png) as im:
        gen = np.asarray(im.convert("RGB")).copy()
    root = ir["nodes"][ir["pages"][ir["screens"][screen_id]["resolved"]["page"]]["root"]]
    fill = (root.get("style") or {}).get("fill")
    hexv = fill["color"]["literal"]["hex"] if fill and fill["kind"] == "solid" and "literal" in fill["color"] else "#FFFFFF"
    pad = (int(hexv[1:3], 16), int(hexv[3:5], 16), int(hexv[5:7], 16))
    aligned, size_info = align(reference_rgb, gen, pad)
    mask, exclusions = build_mask(ir, screen_id, scale, reference_rgb.shape[:2])
    ctx = EvalContext(reference_rgb, aligned, ir, screen_id, scale, (render or {}).get("boxes", {}), mask, exclusions)
    values: JSON = {}
    for m in DEFAULT_METRICS:
        values[m.name] = m.compute(ctx)
    values["composite"] = composite(values)
    d = ctx.cache["diff"].max(axis=2)
    per_node = []
    for nid, (x, y, w, h) in _realized_rects(ctx).items():
        X, Y, W, H = (int(round(v * scale)) for v in (x, y, w, h))
        region = d[Y : Y + H, X : X + W]
        if region.size:
            per_node.append({"node": nid, "kind": ir["nodes"][nid]["kind"], "mismatch_fraction": round(float((region > PIXEL_TOL).mean()), 4),
                             **ctx.cache.get("layout_per_node", {}).get(nid, {}), "delta_e2000": ctx.cache.get("color_errs", {}).get(nid)})
    per_node.sort(key=lambda r: (-r["mismatch_fraction"], r["node"]))
    heat = cv2.applyColorMap(np.clip(d * 4, 0, 255).astype(np.uint8), cv2.COLORMAP_INFERNO)[..., ::-1]
    overlay = (0.5 * reference_rgb + 0.5 * aligned).astype(np.uint8)
    smap = np.clip(ctx.cache["ssim_map"] * 255, 0, 255).astype(np.uint8)
    report: JSON = {
        "schema_version": "0.1", "kind": "visual", "ir_content_hash": content_hash(ir), "screen": screen_id,
        "reference_sha256": _sha(reference_rgb), "generated_sha256": _sha(aligned), "size": size_info, "metrics": values, "worst_nodes": per_node[:top_k], "per_node": per_node,
        "exclusions": exclusions, "unavailable_metrics": UNAVAILABLE,
        "render": {k: v for k, v in (render or {}).items() if k != "boxes"},
        "environment": {"python": platform.python_version(), "numpy": np.__version__, "scikit_image": skimage.__version__, "opencv": cv2.__version__, "pixel_tolerance": PIXEL_TOL, "edge_tolerance_px": EDGE_TOL_PX},
    }
    return report, {"reference": reference_rgb, "generated": aligned, "overlay": overlay, "difference": heat.copy(), "ssim_map": np.stack([smap] * 3, axis=2)}


def _sha(a: np.ndarray) -> str:
    import hashlib

    return hashlib.sha256(a.tobytes() + str(a.shape).encode()).hexdigest()


def report_markdown(r: JSON) -> str:
    m = r["metrics"]
    L = ["# Screen2Code evaluation report", "", f"- IR content hash: `{r['ir_content_hash']}`", f"- Reference: {r['size']['reference']}  Generated: {r['size']['generated']}  (size mismatch: {r['size']['size_mismatch']})", ""]
    L += ["| metric | value |", "|---|---|"]
    L += [f"| pixel mismatch fraction (tol {r['environment']['pixel_tolerance']}) | {m['pixel']['mismatch_fraction']} |", f"| pixel MAE (0..1) | {m['pixel']['mae']} |", f"| SSIM | {m['ssim']['ssim']} |",
          f"| edge F1 (tol {r['environment']['edge_tolerance_px']}px) | {m['edge']['edge_f1']} |", f"| mean CIEDE2000 (regions) | {m['color']['mean_delta_e2000']} |",
          f"| layout mean IoU | {m['layout']['layout_mean_iou']} |", f"| mean position error px | {m['layout']['mean_position_error_px']} |", f"| missing nodes | {m['missing_elements']['missing_count']} |",
          f"| composite (weights recorded) | {m['composite']['composite']} |", ""]
    L += ["## Worst regions", ""] + [f"- `{w['node']}` ({w['kind']}): mismatch {w['mismatch_fraction']}" + (f", IoU {w['iou']}" if "iou" in w else "") for w in r["worst_nodes"]]
    ex = r["exclusions"]
    L += ["", "## Exclusions (counted, never silent)", "", f"- placeholder regions: {len(ex['placeholder_regions'])}, opaque: {len(ex['opaque_regions'])}, redacted: {len(ex['redacted_regions'])}, area fraction {ex['excluded_area_fraction']}"]
    L += ["", "## Unavailable metrics", ""] + [f"- {k}: {v}" for k, v in r["unavailable_metrics"].items()]
    return "\n".join(L) + "\n"


def write_artifacts(report: JSON, images: JSON, out_dir: Path) -> dict[str, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = {}
    for name, arr in images.items():
        p = out_dir / f"{name}.png"
        Image.fromarray(arr).save(p)
        paths[name] = p
    (out_dir / "report.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (out_dir / "REPORT.md").write_text(report_markdown(report), encoding="utf-8")
    paths["report"], paths["markdown"] = out_dir / "report.json", out_dir / "REPORT.md"
    return paths
