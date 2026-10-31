"""Public Python API (ARCHITECTURE section 5). The CLI and the desktop server call exactly this layer.

Composition root: it is the only place that wires providers and stages together.
"""
from __future__ import annotations

import copy
import hashlib
import json
import os
import platform
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

import numpy as np
from PIL import Image

from . import __version__
from .core import CancelToken, Context, Event, Project as _Store, S2CError
from .core.providers import REGISTRY
from .core.runner import ProviderCache
from .core.log import JsonLog
from .evaluation import evaluate as _evaluate, refine as _refine, write_artifacts
from .generation import generate as _generate, write_project
from .ir import canonical_dumps, content_hash, derive_id, quality_report, validate
from .reconstruction import build_ir
from .reconstruction.reconcile import reconcile
from .reconstruction.system import infer_components, infer_tokens
from .rendering import render_static, resolve_fonts
from .vision import TesseractOCR, import_image, perceive

JSON = dict[str, Any]
Listener = Callable[[Event], None]
IMAGE_EXT = {".png", ".jpg", ".jpeg", ".webp"}
REGISTRY.register("ocr", "tesseract", lambda **kw: TesseractOCR(lang=kw.get("lang", "eng"), timeout_s=float(kw.get("timeout_s", 30))))


@dataclass
class CommitResult:
    ir_path: Path
    content_hash: str
    nodes: int
    pages: int
    quality: JSON
    diagnostics: list[JSON] = field(default_factory=list)


@dataclass
class RenderResult:
    screenshot: Path
    record: JSON


class Project:
    """A Screen2Code project on disk."""

    def __init__(self, store: _Store, overrides: JSON | None = None):
        self.store = store
        self.root = store.root
        self.overrides = overrides or {}

    # -- lifecycle
    @classmethod
    def create(cls, path: str | os.PathLike[str], name: str | None = None, overrides: JSON | None = None) -> "Project":
        return cls(_Store.create(path, name or Path(path).name or "project"), overrides)

    @classmethod
    def open(cls, path: str | os.PathLike[str], overrides: JSON | None = None) -> "Project":
        return cls(_Store.open(path), overrides)

    @classmethod
    def open_or_create(cls, path: str | os.PathLike[str], name: str | None = None, overrides: JSON | None = None) -> "Project":
        return cls(_Store.open_or_create(path, name), overrides)

    @property
    def name(self) -> str:
        return self.store.name

    @property
    def cfg(self) -> JSON:
        return self.store.config(self.overrides)

    def _ctx(self, listener: Listener | None, cancel: CancelToken | None, run: str) -> Context:
        return Context(self.store, self.cfg, JsonLog(self.root / "runs" / run / "log.jsonl"), cancel or CancelToken(), listener, ProviderCache(self.store))

    # -- S0: import
    def import_images(self, paths: list[str | os.PathLike[str]] | str | os.PathLike[str], declared: JSON | None = None) -> list[JSON]:
        items = [Path(paths)] if isinstance(paths, (str, os.PathLike)) else [Path(p) for p in paths]
        files: list[Path] = []
        for p in items:
            files += sorted(q for q in p.iterdir() if q.suffix.lower() in IMAGE_EXT) if p.is_dir() else [p]
        if not files:
            raise S2CError("S2C-IMPORT-001", "no importable images found", "supply PNG, JPEG, or WebP files")
        with self.store:
            inputs = self._inputs()
            for f in files:
                img = import_image(f, self.cfg, {**(declared or {}), **({"page_hint": f.stem} if "page_hint" not in (declared or {}) else {})})
                self.store.artifacts.put(img.png, ".png")
                inputs = [i for i in inputs if i["sha256"] != img.sha256] + [{"name": img.name, "sha256": img.sha256, "declared": img.declared, "media_type": img.media_type, "pixel_size": img.pixel_size, "warnings": img.warnings}]
            self.store.write_json("ir/inputs.json", sorted(inputs, key=lambda i: (i["name"], i["sha256"])))
        return self._inputs()

    def import_manifest(self, manifest: str | os.PathLike[str]) -> list[JSON]:
        """Import screenshots listed in a TOML manifest: ``[[screen]] file, page, viewport_width, device_pixel_ratio``. Relationships are explicit, never guessed."""
        import tomllib

        mp = Path(manifest)
        data = tomllib.loads(mp.read_text(encoding="utf-8"))
        screens = data.get("screen")
        if not isinstance(screens, list) or not screens:
            raise S2CError("S2C-CONFIG-001", "manifest needs at least one [[screen]] table")
        out: list[JSON] = []
        for s in screens:
            if not isinstance(s, dict) or not isinstance(s.get("file"), str):
                raise S2CError("S2C-CONFIG-001", "each [[screen]] needs a 'file'")
            declared = {k: s[k] for k in ("viewport_width", "device_pixel_ratio") if k in s}
            if "page" in s:
                declared["page_hint"] = str(s["page"])
            out = self.import_images([mp.parent / s["file"]], declared)
        return out

    def _inputs(self) -> list[JSON]:
        return self.store.read_json("ir/inputs.json") if self.store.exists("ir/inputs.json") else []

    def reference_rgb(self, sha: str) -> np.ndarray:
        with Image.open(self.store.artifacts.path(sha, ".png")) as im:
            return np.asarray(im.convert("RGB")).copy()

    # -- S0-S10
    def reconstruct(self, *, listener: Listener | None = None, cancel: CancelToken | None = None, ocr: str | None = None) -> CommitResult:
        t0 = time.perf_counter()
        inputs = self._inputs()
        if not inputs:
            raise S2CError("S2C-IMPORT-001", "the project has no imported screenshots", "import images first")
        ctx = self._ctx(listener, cancel, f"reconstruct-{int(time.time())}")
        cfg = ctx.cfg
        provider = REGISTRY.get("ocr", ocr or cfg["ocr"]["provider"], lang=cfg["ocr"]["lang"], timeout_s=cfg["ocr"]["timeout_s"])

        def write_asset(data: bytes) -> str:
            sha = hashlib.sha256(data).hexdigest()
            if not self.store.exists(f"assets/{sha}.png"):
                self.store.ws.write_bytes(f"assets/{sha}.png", data)
            return sha

        docs = []
        with self.store:
            for inp in inputs:
                ctx.cancel.check()
                p = perceive(self.store.artifacts.path(inp["sha256"], ".png"), ctx, provider, inp["declared"])
                ctx.emit("structure", "running")
                docs.append(build_ir(p, cfg, self.name, inp["declared"].get("page_hint") or Path(inp["name"]).stem, write_asset))
                ctx.emit("structure", "done", 1.0)
            ctx.emit("reconcile", "running")
            page_docs, rec_report = reconcile(docs, cfg)
            ir = merge_irs(page_docs)
            ctx.emit("reconcile", "done", 1.0)
            ctx.emit("tokens", "running")
            tok_report = infer_tokens(ir, cfg)
            ctx.emit("tokens", "done", 1.0)
            ctx.emit("components", "running")
            comp_report = infer_components(ir, cfg)
            ctx.emit("components", "done", 1.0)
            self.store.write_json("ir/reconciliation.json", {"pages": rec_report, "tokens": tok_report, "components": comp_report})
            ctx.emit("commit", "running")
            rep = validate(ir, 3)
            if not rep.ok:
                raise S2CError("S2C-IR-INVALID", f"the reconstructed IR failed validation ({len(rep.errors)} errors)", details={"diagnostics": [d.to_dict() for d in rep.errors[:20]]})
            path = self.store.ws.write_text("ir/project.ir.json", canonical_dumps(ir) + "\n", overwrite=True)
            ctx.emit("commit", "done", 1.0)
            self._run_record(ctx, "reconstruct", time.perf_counter() - t0, provider)
        return CommitResult(path, content_hash(ir), len(ir["nodes"]), len(ir["pages"]), quality_report(ir), [d.to_dict() for d in rep.diagnostics])

    analyze = reconstruct  # the working IR is committed only if it validates; there is no separate unvalidated state in this release

    @property
    def ir(self) -> JSON:
        if not self.store.exists("ir/project.ir.json"):
            raise S2CError("S2C-GEN-001", "the project has no committed IR", "run reconstruct first")
        return self.store.read_json("ir/project.ir.json")

    # -- S11-S12
    def generate(self, target: str = "html", out: str | os.PathLike[str] | None = None, options: JSON | None = None, *, overwrite: bool = True) -> JSON:
        ir = self.ir
        cfg = self.cfg
        opts = {"asset_policy": cfg["policy"]["asset_rights"], "navigation_policy": cfg["policy"]["navigation"], "placeholder_text": cfg["policy"]["placeholder_text"], **(options or {})}
        gen = _generate(ir, target, lambda sha: self.store.ws.read_bytes(f"assets/{sha}.png"), opts)
        out_dir = Path(out) if out else self.root / "exports" / target
        with self.store:
            self.store.write_json(f"plans/{gen.plan.hash}.plan.json", gen.plan.to_dict())
            written = write_project(gen, out_dir, overwrite=overwrite)
        return {"out": str(out_dir), "files": sorted(gen.files), "report": gen.report.to_dict(), "plan_hash": gen.plan.hash}

    # -- S13
    def render(self, target: str = "html", out_dir: str | os.PathLike[str] | None = None, screen: str | None = None) -> RenderResult:
        ir = self.ir
        cfg = self.cfg
        exp = Path(out_dir) if out_dir else self.root / "exports" / target
        scr = screen or sorted(ir["screens"])[0]
        s = ir["screens"][scr]["resolved"]
        page_file = "index.html"
        pages = sorted(ir["pages"], key=lambda p: ir["pages"][p]["name"])
        if s["page"] != pages[0]:
            from .generation.common import make_plan

            page_file = make_plan(ir, target).pages[s["page"]]
        png = self.root / "renders" / f"{scr}.png"
        rr = cfg["render"]
        rec = render_static(exp / page_file, exp, png, viewport_width=int(round(s["viewport_width"])), scale=float(s["scale"]), allow_no_sandbox=bool(rr["allow_no_sandbox"]),
                            browsers_path=rr["browsers_path"], timeout_s=float(rr["timeout_s"]))
        self.store.write_json(f"renders/{scr}.render.json", rec.to_dict())
        return RenderResult(png, rec.to_dict())

    # -- S14
    def evaluate(self, screen: str | None = None) -> JSON:
        ir = self.ir
        scr = screen or sorted(ir["screens"])[0]
        sha = ir["sources"][ir["screens"][scr]["source"]]["sha256"]
        rec = self.store.read_json(f"renders/{scr}.render.json")
        report, images = _evaluate(self.reference_rgb(sha), self.root / "renders" / f"{scr}.png", ir, scr, rec)
        out = self.root / "evaluations" / f"{scr}"
        paths = write_artifacts(report, images, out)
        report["artifacts"] = {k: str(v) for k, v in paths.items()}
        return report

    # -- S15 refinement
    def _trial(self, ir: JSON, trial_dir: Path, scr: str) -> tuple[JSON, JSON]:
        """Generate, render, and evaluate ``ir`` into ``trial_dir`` with the same code paths as the normal workflow."""
        cfg = self.cfg
        opts = {"asset_policy": cfg["policy"]["asset_rights"], "navigation_policy": cfg["policy"]["navigation"], "placeholder_text": cfg["policy"]["placeholder_text"]}
        gen = _generate(ir, "html", lambda sha: self.store.ws.read_bytes(f"assets/{sha}.png"), opts)
        exp = trial_dir / "exports"
        write_project(gen, exp, overwrite=True)
        s = ir["screens"][scr]["resolved"]
        rr = cfg["render"]
        rec = render_static(exp / gen.plan.pages[s["page"]], exp, trial_dir / "render.png", viewport_width=int(round(s["viewport_width"])), scale=float(s["scale"]),
                            allow_no_sandbox=bool(rr["allow_no_sandbox"]), browsers_path=rr["browsers_path"], timeout_s=float(rr["timeout_s"]))
        sha = ir["sources"][ir["screens"][scr]["source"]]["sha256"]
        report, images = _evaluate(self.reference_rgb(sha), trial_dir / "render.png", ir, scr, rec.to_dict())
        write_artifacts(report, images, trial_dir / "evaluation")
        (trial_dir / "render.json").write_text(json.dumps(rec.to_dict(), indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return report, rec.to_dict()

    @staticmethod
    def _tracked(report: JSON) -> JSON:
        m = report["metrics"]
        return {"composite": m["composite"]["composite"], **m["composite"]["members"]}

    def refine(self, *, screen: str | None = None, max_iterations: int | None = None, time_limit_s: float = 300.0, epsilon: float = 0.002, tolerance: float = 0.01,
               apply: bool = False, listener: Listener | None = None, cancel: CancelToken | None = None) -> JSON:
        """Closed-loop refinement: render -> evaluate -> deterministic IR adjustments -> re-render -> compare. Never modifies the committed IR unless ``apply``.

        An iteration is kept only if the composite improves by at least ``epsilon`` and no tracked metric drops by more than ``tolerance``.
        """
        t0 = time.perf_counter()
        ir0 = self.ir
        cfg = self.cfg
        limit = int(max_iterations if max_iterations is not None else cfg["thresholds"]["refine.max_iterations"])
        scr = screen or sorted(ir0["screens"])[0]
        base = self.root / "refinements"
        base.mkdir(exist_ok=True)
        n_run = 1 + sum(1 for q in base.iterdir() if q.is_dir() and q.name.startswith("run-"))
        run_dir = base / f"run-{n_run:03d}"
        run_dir.mkdir()
        (run_dir / "initial.ir.json").write_text(canonical_dumps(ir0) + "\n", encoding="utf-8")  # immutable record of the starting point
        config = {"screen": scr, "max_iterations": limit, "time_limit_s": time_limit_s, "epsilon": epsilon, "tolerance": tolerance, "max_step_px": 24.0, "rules": "refine/1"}
        producer = derive_id("prd", "s2c.refine-measure", "0.1.0")
        cancel = cancel or CancelToken()

        def emit(stage: str, status: str, msg: str = "") -> None:
            if listener:
                listener(Event(stage, status, 0.0, msg))

        emit("refine-0", "running")
        report, _ = self._trial(ir0, run_dir / "iter-000", scr)
        (run_dir / "iter-000" / "ir.json").write_text(canonical_dumps(ir0) + "\n", encoding="utf-8")
        best_ir, best_report, best_n = ir0, report, 0
        history = [{"iteration": 0, "accepted": True, "patches": 0, "metrics": self._tracked(report), "reason": "initial state"}]
        stop = "iteration limit reached"
        for n in range(1, limit + 1):
            cancel.check()
            if time.perf_counter() - t0 > time_limit_s:
                stop = "time limit reached"
                break
            patches = _refine.propose(best_ir, best_report, config["max_step_px"])
            if not patches:
                stop = "no justified adjustment remains"
                break
            emit(f"refine-{n}", "running", f"{len(patches)} adjustments")
            cand = _refine.apply(best_ir, patches, best_report, n, producer)
            rep = validate(cand, 2)
            d = run_dir / f"iter-{n:03d}"
            d.mkdir()
            (d / "patches.json").write_text(json.dumps(patches, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            if not rep.ok:  # a proposal that breaks validation is a bug in the rules; record and stop rather than continue
                history.append({"iteration": n, "accepted": False, "patches": len(patches), "reason": "proposal failed IR validation", "diagnostics": [x.to_dict() for x in rep.errors[:5]]})
                stop = "a proposal failed IR validation (refinement bug)"
                break
            new_report, _ = self._trial(cand, d, scr)
            (d / "ir.json").write_text(canonical_dumps(cand) + "\n", encoding="utf-8")
            before, after = self._tracked(best_report), self._tracked(new_report)
            degraded = sorted(k for k in before if k != "composite" and after[k] < before[k] - tolerance)
            ok = after["composite"] >= before["composite"] + epsilon and not degraded
            history.append({"iteration": n, "accepted": ok, "patches": len(patches), "metrics": after, "delta_composite": round(after["composite"] - before["composite"], 5),
                            "reason": "improved" if ok else ("a tracked metric degraded: " + ", ".join(degraded) if degraded else "composite did not improve by epsilon")})
            if not ok:
                stop = f"quality stopped improving (iteration {n} rejected)"
                break
            best_ir, best_report, best_n = cand, new_report, n
        initial_m, final_m = self._tracked(report), self._tracked(best_report)
        improved = final_m["composite"] > initial_m["composite"] and best_n > 0
        (run_dir / "best.ir.json").write_text(canonical_dumps(best_ir) + "\n", encoding="utf-8")
        result = {"run": str(run_dir), "config": config, "initial_ir_hash": content_hash(ir0), "best_ir_hash": content_hash(best_ir), "best_iteration": best_n, "improved": improved,
                  "stop_reason": stop, "before": initial_m, "after": final_m, "iterations": history, "applied": False, "seconds": round(time.perf_counter() - t0, 2),
                  "note": "metrics are measured on the render of this screen against its screenshot; they do not by themselves establish fidelity on other inputs"}
        if apply and improved:
            with self.store:
                bak = self.root / "ir" / f"project.ir.json.bak-{content_hash(ir0)[7:19]}"
                self.store.ws.write_text(f"ir/{bak.name}", canonical_dumps(ir0) + "\n", overwrite=True)
                self.store.ws.write_text("ir/project.ir.json", canonical_dumps(best_ir) + "\n", overwrite=True)
            result["applied"] = True
            result["backup"] = str(bak)
        (run_dir / "run.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        emit("refine", "done", stop)
        return result

    def run(self, *, target: str = "html", listener: Listener | None = None) -> JSON:
        """Convenience: reconstruct, generate, render, evaluate (every screen)."""
        c = self.reconstruct(listener=listener)
        g = self.generate(target)
        evals = {}
        for scr in sorted(self.ir["screens"]):
            self.render(target, screen=scr)
            evals[scr] = self.evaluate(scr)
        return {"commit": {"hash": c.content_hash, "nodes": c.nodes, "pages": c.pages}, "generation": {"files": g["files"], "plan_hash": g["plan_hash"]}, "evaluation": evals}

    def _run_record(self, ctx: Context, command: str, seconds: float, provider: Any) -> None:
        import cv2, skimage

        rec = {
            "command": command, "version": __version__, "durations": {**ctx.timings, "total_s": round(seconds, 3)},
            "pins": {"python": platform.python_version(), "platform": platform.platform(), "numpy": np.__version__, "opencv": cv2.__version__, "scikit_image": skimage.__version__,
                     "ocr": {"id": provider.id, "version": provider.version, "lang": getattr(provider, "lang", None)}, "fonts": resolve_fonts(), "thresholds": ctx.cfg["thresholds"]},
            "ocr_cache": {"hits": ctx.cache.hits, "misses": ctx.cache.misses},
        }
        self.store.write_json(f"runs/{command}-latest.json", rec)


def merge_irs(docs: list[JSON]) -> JSON:
    """Combine single-screen IRs into one multi-page IR. Pages stay independent: no cross-screen inference in this release."""
    out = copy.deepcopy(docs[0])
    for d in docs[1:]:
        for sec in ("producers", "sources", "regions", "evidence", "screens", "modes", "pages", "nodes", "realizations", "components", "assets", "redactions"):
            for k, v in d[sec].items():
                out[sec].setdefault(k, copy.deepcopy(v))
        out["relations"] += d["relations"]
        out["disputes"] += d["disputes"]
    return out


__all__ = ["Project", "CommitResult", "RenderResult", "merge_irs", "REGISTRY"]
