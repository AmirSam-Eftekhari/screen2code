"""Benchmark runner (BENCHMARKS sections 4-7). Composition-level module: it wires corpus, product pipeline, and metrics.

A run is valid only if every pin required by ADR-0001 amendment A1 is recorded. Nothing here is hard-coded per scene.
"""
from __future__ import annotations

import hashlib
import json
import platform
import shutil
import time
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image

from . import __version__
from .api import Project
from .bench.corpus import CATEGORIES, DATASET_VERSION, emit_html, ground_truth, make_scene
from .bench.metrics import bootstrap_ci, score_scene
from .core.errors import S2CError
from .evaluation import image_metrics
from .ir import canonical_dumps, content_hash
from .rendering import render_static, resolve_fonts

JSON = dict[str, Any]
TIERS = {"smoke": 1, "standard": 5, "full": 25}  # scenes per category (initial sizes; recorded in the run)
REQUIRED_PINS = ("dataset_version", "dataset_content_hash", "seeds", "browser", "viewports", "fonts", "providers", "dependencies")
HEADLINE = ("precision", "recall", "recall_text", "recall_container_visible", "recall_container", "recall_image", "text_cer", "text_exact", "font_size_within_1px", "font_size_mae_px", "weight_accuracy",
            "fill_de", "layout_accuracy")


def _versions() -> JSON:
    import click, cv2, playwright, skimage

    from importlib.metadata import version as v

    def ver(n: str) -> str:
        try:
            return v(n)
        except Exception:  # noqa: BLE001
            return "unknown"

    return {"python": platform.python_version(), "platform": platform.platform(), "numpy": np.__version__, "opencv": cv2.__version__, "scikit_image": skimage.__version__,
            "pillow": ver("pillow"), "playwright": ver("playwright"), "click": click.__version__, "screen2code": __version__}


def run_benchmark(tier: str, seed: int, out_dir: Path, overrides: JSON | None = None, *, repeat_check: bool = False, categories: tuple[str, ...] = CATEGORIES) -> JSON:
    if tier not in TIERS:
        raise S2CError("S2C-CONFIG-001", f"unknown tier {tier!r}", f"choose one of {sorted(TIERS)}")
    t0 = time.perf_counter()
    out_dir.mkdir(parents=True, exist_ok=True)
    overrides = overrides or {}
    rcfg = {**{"allow_no_sandbox": False, "browsers_path": ""}, **overrides.get("render", {})}
    scenes = [make_scene(c, seed * 1000 + i) for c in categories for i in range(TIERS[tier])]
    work = out_dir / "scenes"
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir()
    results, browser, viewports, hashes, rec_fonts, prov = [], "", {}, {}, {}, {}
    for sc in scenes:
        d = work / sc.id
        d.mkdir()
        html_path = d / "gt.html"
        html_path.write_text(emit_html(sc), encoding="utf-8")
        gt = ground_truth(sc)
        hashes[sc.id] = hashlib.sha256((html_path.read_text() + json.dumps(gt, sort_keys=True)).encode()).hexdigest()
        rr = render_static(html_path, d, d / "gt.png", viewport_width=sc.width, allow_no_sandbox=rcfg["allow_no_sandbox"], browsers_path=rcfg["browsers_path"])
        browser, rec_fonts = rr.browser, rr.fonts
        viewports[sc.id] = {"width": sc.width, "scale": 1.0, "pixel_size": rr.pixel_size}
        proj = Project.create(d / "project", sc.id, overrides=overrides)
        proj.import_images([d / "gt.png"], {"device_pixel_ratio": 1.0, "page_hint": sc.id})
        ts = time.perf_counter()
        proj.run()
        ir = proj.ir
        scr = sorted(ir["screens"])[0]
        ev = json.loads((proj.root / "evaluations" / scr / "report.json").read_text())
        rec = json.loads((proj.root / "runs" / "reconstruct-latest.json").read_text())
        prov = rec["pins"]["ocr"]
        structure = score_scene(gt, rr.boxes, ir)
        ref = proj.reference_rgb(ir["sources"][ir["screens"][scr]["source"]]["sha256"])
        baselines = {"blank_page": image_metrics(ref, np.full_like(ref, 255)), "single_image": image_metrics(ref, ref.copy()), "single_image_structure": {"ir_nodes": 1, "recall": 0.0, "note": "one <img> element; no text, regions, or layout"}}
        row = {"scene": sc.id, "category": sc.category, "theme": sc.theme, "ir_hash": content_hash(ir), "seconds": round(time.perf_counter() - ts, 2), "structure": structure,
               "visual": {k: ev["metrics"][k] for k in ("pixel", "ssim", "edge", "layout", "composite")}, "baselines": baselines}
        if repeat_check:
            p2 = Project.create(d / "project_repeat", sc.id, overrides=overrides)
            p2.import_images([d / "gt.png"], {"device_pixel_ratio": 1.0, "page_hint": sc.id})
            row["deterministic"] = p2.reconstruct().content_hash == row["ir_hash"]
        results.append(row)
    pins = {"dataset_version": DATASET_VERSION, "dataset_content_hash": hashlib.sha256(canonical_dumps(hashes).encode()).hexdigest(), "seeds": {"corpus_seed": seed, "scene_seeds": {s.id: s.seed for s in scenes}},
            "browser": browser, "viewports": viewports, "fonts": rec_fonts, "providers": prov, "dependencies": _versions(), "tier": tier, "scenes_per_category": TIERS[tier],
            "sandbox": {"chromium_sandbox": not rcfg["allow_no_sandbox"]}, "redaction_profile_hash": None}
    missing = [k for k in REQUIRED_PINS if not pins.get(k)]
    agg: JSON = {}
    for key in HEADLINE:
        vals = [r["structure"][key] for r in results if r["structure"].get(key) is not None]
        agg[key] = {"mean": round(float(np.mean(vals)), 4), "ci95": bootstrap_ci(vals, seed), "n": len(vals)} if vals else None
    vis = {}
    for key, getter in (("ssim", lambda r: r["visual"]["ssim"]["ssim"]), ("edge_f1", lambda r: r["visual"]["edge"]["edge_f1"]), ("pixel_mismatch", lambda r: r["visual"]["pixel"]["mismatch_fraction"]),
                        ("layout_mean_iou", lambda r: r["visual"]["layout"]["layout_mean_iou"]), ("composite", lambda r: r["visual"]["composite"]["composite"])):
        vals = [getter(r) for r in results if getter(r) is not None]
        vis[key] = {"mean": round(float(np.mean(vals)), 4), "ci95": bootstrap_ci(vals, seed), "n": len(vals)}
    base = {"blank_page": {k: round(float(np.mean([r["baselines"]["blank_page"][m][f] for r in results])), 4) for k, (m, f) in {"ssim": ("ssim", "ssim"), "edge_f1": ("edge", "edge_f1"), "pixel_mismatch": ("pixel", "mismatch_fraction")}.items()},
            "single_image": {k: round(float(np.mean([r["baselines"]["single_image"][m][f] for r in results])), 4) for k, (m, f) in {"ssim": ("ssim", "ssim"), "edge_f1": ("edge", "edge_f1"), "pixel_mismatch": ("pixel", "mismatch_fraction")}.items()} | {"structure_recall": 0.0}}
    by_cat = {c: {"scenes": sum(1 for r in results if r["category"] == c), "ssim": round(float(np.mean([r["visual"]["ssim"]["ssim"] for r in results if r["category"] == c])), 4),
                  "recall": round(float(np.mean([r["structure"]["recall"] for r in results if r["category"] == c])), 4), "text_cer": _m([r["structure"]["text_cer"] for r in results if r["category"] == c])} for c in categories}
    run = {"run_id": f"{tier}-seed{seed}-{content_hash({'p': pins})[7:19]}", "valid": not missing, "missing_pins": missing, "pins": pins, "seconds": round(time.perf_counter() - t0, 1), "structure": agg, "visual": vis,
           "baselines": base, "by_category": by_cat, "scenes": results,
           "determinism": {"checked": repeat_check, "all_identical": all(r.get("deterministic", True) for r in results) if repeat_check else None},
           "limitations": ["synthetic scenes are cleaner and more regular than real sites; results do not predict real-world performance",
                           "scenes use the same font family as the generation font policy, so typography results are optimistic",
                           "the corpus emitter is independent of the product generator, but both run in the same Chromium and font environment"]}
    (out_dir / "run.json").write_text(json.dumps(run, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    (out_dir / "summary.md").write_text(summary_md(run), encoding="utf-8")
    return run


def _m(v: list[Any]) -> float | None:
    v = [x for x in v if x is not None]
    return round(float(np.mean(v)), 4) if v else None


def summary_md(r: JSON) -> str:
    L = [f"# Benchmark run `{r['run_id']}`", "", f"- valid: **{r['valid']}**" + (f" (missing pins: {r['missing_pins']})" if r["missing_pins"] else ""), f"- dataset {r['pins']['dataset_version']} / tier {r['pins']['tier']} / scenes {len(r['scenes'])} / seed {r['pins']['seeds']['corpus_seed']}",
         f"- browser: {r['pins']['browser']}  (chromium sandbox: {r['pins']['sandbox']['chromium_sandbox']})", f"- OCR: {r['pins']['providers']}", f"- duration: {r['seconds']} s", "", "## Structure metrics vs ground truth (mean, 95% bootstrap CI)", "", "| metric | mean | CI95 | n |", "|---|---|---|---|"]
    L += [f"| {k} | {v['mean']} | {v['ci95']} | {v['n']} |" for k, v in r["structure"].items() if v]
    L += ["", "## Visual metrics (pipeline output vs reference)", "", "| metric | mean | CI95 |", "|---|---|---|"] + [f"| {k} | {v['mean']} | {v['ci95']} |" for k, v in r["visual"].items()]
    L += ["", "## Baselines (why pixel metrics alone are insufficient)", "", "| baseline | SSIM | edge F1 | pixel mismatch | structure recall |", "|---|---|---|---|---|"]
    b = r["baselines"]
    L += [f"| blank page | {b['blank_page']['ssim']} | {b['blank_page']['edge_f1']} | {b['blank_page']['pixel_mismatch']} | 0.0 |", f"| single `<img>` of the screenshot | {b['single_image']['ssim']} | {b['single_image']['edge_f1']} | {b['single_image']['pixel_mismatch']} | {b['single_image']['structure_recall']} |",
          f"| **Screen2Code** | {r['visual']['ssim']['mean']} | {r['visual']['edge_f1']['mean']} | {r['visual']['pixel_mismatch']['mean']} | {r['structure']['recall']['mean']} |"]
    L += ["", "## By category", "", "| category | scenes | SSIM | recall | text CER |", "|---|---|---|---|---|"] + [f"| {c} | {v['scenes']} | {v['ssim']} | {v['recall']} | {v['text_cer']} |" for c, v in r["by_category"].items()]
    L += ["", "## Determinism", "", f"- repeat check: {r['determinism']}", "", "## Limitations", ""] + [f"- {x}" for x in r["limitations"]]
    return "\n".join(L) + "\n"
