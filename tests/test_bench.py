"""Benchmark corpus, structure metrics, and runner tests."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from screen2code.bench.corpus import CATEGORIES, emit_html, ground_truth, make_scene
from screen2code.bench.metrics import bootstrap_ci, edit_distance, score_scene

from .helpers import FIX, NO_SANDBOX, needs_browser, needs_ocr

GOLDEN = json.loads((FIX / "golden" / "acme_home.ir.json").read_text(encoding="utf-8"))


class CorpusTests(unittest.TestCase):
    def test_same_seed_same_scene_different_seed_differs(self) -> None:
        for c in CATEGORIES:
            a, b, other = make_scene(c, 7), make_scene(c, 7), make_scene(c, 8)
            self.assertEqual(emit_html(a), emit_html(b)); self.assertEqual(ground_truth(a), ground_truth(b))
        self.assertNotEqual(emit_html(make_scene("landing", 1)), emit_html(make_scene("landing", 2)))

    def test_ground_truth_is_complete_and_ids_unique(self) -> None:
        for c in CATEGORIES:
            s = make_scene(c, 3); gt = ground_truth(s)
            ids = [g["id"] for g in gt]
            self.assertEqual(len(ids), len(set(ids)))
            for g in gt:
                if g["kind"] == "text":
                    self.assertTrue(g["text"] and g["font_size"] > 0 and g["weight"] in (400, 700))
                self.assertIn("visible", g) if g["kind"] == "container" else None
            self.assertTrue(f'data-s2c-id="{ids[-1]}"' in emit_html(s))

    def test_emitter_escapes_text(self) -> None:
        s = make_scene("typography", 1); s.root.children[0].children[0].text = "<b>x</b> & y"
        self.assertIn("&lt;b&gt;x&lt;/b&gt; &amp; y", emit_html(s))


class MetricTests(unittest.TestCase):
    def test_edit_distance_and_bootstrap(self) -> None:
        self.assertEqual((edit_distance("kitten", "sitting"), edit_distance("", "ab"), edit_distance("a", "a")), (3, 2, 0))
        self.assertEqual(bootstrap_ci([0.1, 0.2, 0.3, 0.4], 5), bootstrap_ci([0.1, 0.2, 0.3, 0.4], 5))
        lo, hi = bootstrap_ci([0.5] * 5, 1); self.assertEqual((lo, hi), (0.5, 0.5))

    def test_perfect_and_degraded_scoring_against_ground_truth(self) -> None:
        ir = GOLDEN
        scr = "scr_d"
        real = ir["realizations"][scr]["nodes"]
        gt, boxes = [], {}
        for nid, e in real.items():
            n = ir["nodes"][nid]; r = ir["regions"][e["regions"][0]]["rect"]
            boxes[nid] = {"x": float(r["x"]), "y": float(r["y"]), "w": float(r["w"]), "h": float(r["h"])}
            if n["kind"] == "text":
                st = ir["tokens"]["type"][n["text"]["style"]["token"]]["value"]
                gt.append({"id": nid, "kind": "text", "text": n["text"]["content"]["value"], "font_size": st["size"]["px"], "weight": st["weight"], "color": "#111827"})
            elif n["kind"] == "image":
                gt.append({"id": nid, "kind": "image"})
            else:
                gt.append({"id": nid, "kind": "container", "layout": "none", "fill": None, "radius": 0.0, "visible": False})
        perfect = score_scene(gt, boxes, ir)
        self.assertEqual((perfect["recall"], perfect["text_cer"], perfect["font_size_mae_px"], perfect["weight_accuracy"]), (1.0, 0.0, 0.0, 1.0))
        bad = [dict(g, text="zzzz" if g["kind"] == "text" else None) if g["kind"] == "text" else g for g in gt]
        self.assertGreater(score_scene(bad, boxes, ir)["text_cer"], 0.9)
        far = {k: {**v, "x": v["x"] + 5000} for k, v in boxes.items()}
        self.assertEqual(score_scene(gt, far, ir)["recall"], 0.0)


@needs_ocr
@needs_browser
class RunnerTests(unittest.TestCase):
    def test_runner_records_pins_and_is_deterministic(self) -> None:
        from screen2code.benchmark import REQUIRED_PINS, run_benchmark

        with tempfile.TemporaryDirectory() as d:
            run = run_benchmark("smoke", 2, Path(d) / "r", NO_SANDBOX, repeat_check=True, categories=("typography",))
            self.assertTrue(run["valid"], run["missing_pins"])
            for k in REQUIRED_PINS:
                self.assertTrue(run["pins"][k], k)
            self.assertEqual(run["pins"]["dataset_version"], "0.1.0"); self.assertIn("tesseract", run["pins"]["providers"]["version"])
            self.assertTrue(run["determinism"]["all_identical"])
            self.assertGreater(run["structure"]["recall_text"]["mean"], 0.8)
            self.assertEqual(run["baselines"]["single_image"]["structure_recall"], 0.0)
            self.assertTrue((Path(d) / "r" / "summary.md").exists())
            again = run_benchmark("smoke", 2, Path(d) / "r2", NO_SANDBOX, categories=("typography",))
            self.assertEqual(run["pins"]["dataset_content_hash"], again["pins"]["dataset_content_hash"])
            self.assertEqual(run["scenes"][0]["ir_hash"], again["scenes"][0]["ir_hash"])

    def test_unknown_tier_is_rejected(self) -> None:
        from screen2code.benchmark import run_benchmark
        from screen2code.core import S2CError

        with self.assertRaises(S2CError):
            run_benchmark("huge", 1, Path("/tmp/never"))


if __name__ == "__main__":
    unittest.main()
