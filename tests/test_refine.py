"""Refinement tests: proposal rules (pure), the closed loop on a deliberately imperfect fixture, limits, traceability, determinism."""
from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path

from screen2code.api import Project
from screen2code.core import CancelToken, S2CError
from screen2code.evaluation import refine as R
from screen2code.ir import canonical_dumps, content_hash, validate

from .helpers import FIX, LANDING, NO_SANDBOX, needs_browser, needs_ocr

GOLDEN = json.loads((FIX / "golden" / "acme_home.ir.json").read_text(encoding="utf-8"))


class ProposalTests(unittest.TestCase):
    def report(self, **per: dict) -> dict:
        return {"per_node": [{"node": k, **v} for k, v in per.items()]}

    def test_gap_error_becomes_a_bounded_margin_patch(self) -> None:
        ir = copy.deepcopy(GOLDEN)
        root = ir["nodes"]["nd_root"]  # vertical stack: nd_hero then nd_grid
        rep = self.report(nd_root=dict(dx=0, dy=0, dw=0, dh=0), nd_hero=dict(dx=0, dy=0, dw=0, dh=0), nd_grid=dict(dx=0, dy=10, dw=0, dh=0))
        ir["nodes"]["nd_grid"].setdefault("spacing", {})["margin"] = {"top": {"px": 30}}
        patches = R.propose(ir, rep)
        grid = [p for p in patches if p["node"] == "nd_grid"]
        self.assertEqual((grid[0]["kind"], grid[0]["side"], grid[0]["previous"], grid[0]["value"]), ("margin", "top", 30, 20.0))
        huge = self.report(nd_root=dict(dx=0, dy=0, dw=0, dh=0), nd_hero=dict(dx=0, dy=0, dw=0, dh=0), nd_grid=dict(dx=0, dy=500, dw=0, dh=0))
        self.assertGreaterEqual([p for p in R.propose(ir, huge) if p["node"] == "nd_grid"][0]["value"], 30 - 24, "a single step is bounded")

    def test_no_error_no_patch_and_asserted_values_are_untouchable(self) -> None:
        ir = copy.deepcopy(GOLDEN)
        zero = self.report(nd_root=dict(dx=0, dy=0, dw=0, dh=0), nd_hero=dict(dx=0, dy=0, dw=0, dh=0), nd_grid=dict(dx=0, dy=0.3, dw=0, dh=0.2))
        self.assertEqual(R.propose(ir, zero), [])
        ir["nodes"]["nd_grid"]["inference"]["layout"].update(calibration="asserted", basis="asserted", confidence=1)
        off = self.report(nd_root=dict(dx=0, dy=0, dw=0, dh=0), nd_hero=dict(dx=0, dy=0, dw=0, dh=0), nd_grid=dict(dx=0, dy=9, dw=0, dh=0))
        self.assertEqual([p for p in R.propose(ir, off) if p["node"] == "nd_grid"], [])

    def test_apply_adds_measured_evidence_without_touching_existing_evidence(self) -> None:
        ir = copy.deepcopy(GOLDEN)
        ir["nodes"]["nd_grid"].setdefault("spacing", {})["margin"] = {"top": {"px": 30}}
        rep = self.report(nd_root=dict(dx=0, dy=0, dw=0, dh=0), nd_hero=dict(dx=0, dy=0, dw=0, dh=0), nd_grid=dict(dx=0, dy=10, dw=0, dh=0))
        before = copy.deepcopy(ir["evidence"])
        out = R.apply(ir, R.propose(ir, rep), rep, 1, "prd_refine")
        for k, v in before.items():
            self.assertEqual(out["evidence"][k], v)
        new = [e for k, e in out["evidence"].items() if k not in before]
        self.assertEqual([e["kind"] for e in new], ["layout_residual"]); self.assertEqual(new[0]["basis"], "measured")
        self.assertEqual(out["nodes"]["nd_grid"]["inference"]["layout"]["method"], "refine.margin/1")
        self.assertEqual(ir["nodes"]["nd_grid"]["spacing"]["margin"]["top"]["px"], 30, "the input IR is never mutated")
        self.assertTrue(validate(out, 2).ok, [str(d) for d in validate(out, 2).errors])


@needs_ocr
@needs_browser
class LoopTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.tmp = tempfile.TemporaryDirectory(); cls.addClassCleanup(cls.tmp.cleanup)
        cls.dir = Path(cls.tmp.name)

    def project(self, name: str, perturb: bool) -> Project:
        p = Project.create(self.dir / name, "refine-fixture", overrides=NO_SANDBOX)  # same project name: it is part of the IR content
        p.import_images([LANDING]); p.reconstruct()
        if perturb:
            ir = p.ir
            kids = ir["nodes"][ir["pages"][sorted(ir["pages"])[0]]["root"]]["children"]
            for k in kids[1:3]:
                cur = ir["nodes"][k].get("spacing", {}).get("margin", {}).get("top", {}).get("px", 0)
                ir["nodes"][k].setdefault("spacing", {}).setdefault("margin", {})["top"] = {"px": cur + 18}
            p.store.ws.write_text("ir/project.ir.json", canonical_dumps(ir) + "\n", overwrite=True)
            self.assertTrue(validate(p.ir, 2).ok)
        return p

    def test_refinement_improves_an_imperfect_fixture_without_degrading_other_metrics(self) -> None:
        p = self.project("bad", True)
        original = content_hash(p.ir)
        r = p.refine(max_iterations=4)
        self.assertTrue(r["improved"], r["iterations"])
        self.assertGreater(r["after"]["composite"] - r["before"]["composite"], 0.05)
        for k in ("ssim", "edge_f1", "layout_mean_iou", "pixel_match"):
            self.assertGreaterEqual(r["after"][k], r["before"][k] - 0.01, f"{k} must not degrade")
        self.assertIn(r["stop_reason"], ("no justified adjustment remains", "quality stopped improving (iteration 2 rejected)", "iteration limit reached"))
        run = Path(r["run"])
        for f in ("initial.ir.json", "best.ir.json", "run.json", "iter-000/evaluation/report.json", "iter-000/render.png", "iter-001/patches.json", "iter-001/ir.json", "iter-001/evaluation/difference.png"):
            self.assertTrue((run / f).exists(), f)
        self.assertEqual(content_hash(json.loads((run / "initial.ir.json").read_text())), original, "immutable record of the starting point")
        self.assertEqual(content_hash(p.ir), original, "the committed IR is unchanged without --apply")
        self.assertFalse(r["applied"])
        patches = json.loads((run / "iter-001" / "patches.json").read_text())
        self.assertTrue(all(x["rule"].startswith("refine.") and "evidence_of" in x for x in patches), "every change is explainable and traceable")

    def test_apply_backs_up_and_keeps_the_ir_valid(self) -> None:
        p = self.project("apply", True)
        original = content_hash(p.ir)
        r = p.refine(max_iterations=3, apply=True)
        self.assertTrue(r["applied"]); self.assertTrue(Path(r["backup"]).exists())
        self.assertEqual(content_hash(json.loads(Path(r["backup"]).read_text())), original)
        self.assertNotEqual(content_hash(p.ir), original); self.assertTrue(validate(p.ir, 3).ok)

    def test_runs_are_deterministic(self) -> None:
        a, b = self.project("det-a", True), self.project("det-b", True)
        ra, rb = a.refine(max_iterations=3), b.refine(max_iterations=3)
        self.assertEqual(ra["best_ir_hash"], rb["best_ir_hash"]); self.assertEqual(ra["after"], rb["after"])
        self.assertEqual([h["patches"] for h in ra["iterations"]], [h["patches"] for h in rb["iterations"]])

    def test_already_good_input_is_not_degraded_and_limits_are_respected(self) -> None:
        p = self.project("good", False)
        r = p.refine(max_iterations=1)
        self.assertGreaterEqual(r["after"]["composite"], r["before"]["composite"] - 1e-9)
        self.assertLessEqual(len(r["iterations"]), 2)
        for k in ("ssim", "edge_f1", "layout_mean_iou", "pixel_match"):
            self.assertGreaterEqual(r["after"][k], r["before"][k] - 0.01)
        t = p.refine(max_iterations=5, time_limit_s=0.0)
        self.assertEqual(t["stop_reason"], "time limit reached"); self.assertFalse(t["improved"])

    def test_cancellation_is_an_error_not_a_partial_success(self) -> None:
        p = self.project("cancel", True)
        tok = CancelToken(); tok.cancel()
        with self.assertRaises(S2CError) as cm:
            p.refine(cancel=tok)
        self.assertEqual(cm.exception.code, "S2C-STAGE-002")

    def test_cli_refine_command(self) -> None:
        from click.testing import CliRunner

        from screen2code.cli.main import cli

        p = self.project("cli", True)
        res = CliRunner().invoke(cli, ["--json", "--allow-no-sandbox", "refine", str(p.root), "--max-iterations", "2"])
        self.assertEqual(res.exit_code, 0, res.stderr); out = json.loads(res.stdout)
        self.assertTrue(out["improved"]); self.assertIn("composite", out["before"])


if __name__ == "__main__":
    unittest.main()
