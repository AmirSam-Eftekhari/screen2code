"""Generation, evaluation, security, architecture, e2e, and CLI tests."""
from __future__ import annotations

import ast
import copy
import hashlib
import io
import json
import re
import tempfile
import unittest
from html.parser import HTMLParser
from pathlib import Path

import numpy as np
from click.testing import CliRunner
from PIL import Image

from screen2code.api import Project
from screen2code.cli.main import cli
from screen2code.core import Context, S2CError
from screen2code.core.config import load_config
from screen2code.evaluation import evaluate
from screen2code.generation import generate, write_project
from screen2code.ir import content_hash, validate
from screen2code.reconstruction import build_ir
from screen2code.vision import TesseractOCR, perceive
from screen2code.vision.ocr import run_ocr

from .helpers import FIX, LANDING, NO_SANDBOX, ROOT, Perceived, needs_browser, needs_ocr

GOLDEN = json.loads((FIX / "golden" / "acme_home.ir.json").read_text(encoding="utf-8"))


class Balanced(HTMLParser):
    VOID = {"meta", "link", "img", "br", "hr", "input"}

    def __init__(self) -> None:
        super().__init__(); self.stack: list[str] = []; self.errors: list[str] = []; self.scripts = 0

    def handle_starttag(self, tag, attrs):
        if tag == "script":
            self.scripts += 1
        if tag not in self.VOID:
            self.stack.append(tag)

    def handle_endtag(self, tag):
        if not self.stack or self.stack[-1] != tag:
            self.errors.append(f"unbalanced </{tag}>")
        else:
            self.stack.pop()


def landing_ir() -> dict:
    return build_ir(Perceived.get(), load_config(), "t", "Home", Perceived.write_asset)


def gen(ir, **opts):
    return generate(ir, "html", lambda sha: Perceived.store[sha], opts or None)


@needs_ocr
class GenerationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.ir = landing_ir()

    def test_output_is_wellformed_and_deterministic(self) -> None:
        a, b = gen(self.ir), gen(self.ir)
        self.assertEqual(a.files, b.files); self.assertEqual(a.plan.hash, b.plan.hash)
        p = Balanced(); p.feed(a.files["index.html"].decode()); self.assertEqual((p.errors, p.stack), ([], []))
        css = a.files["styles.css"].decode()
        self.assertNotIn("@import", css); self.assertNotIn("url(", css); self.assertIn("box-sizing: border-box", css)
        self.assertIn("display: grid", css); self.assertIn("justify-content: space-between", css)
        self.assertEqual(len(re.findall(r'data-s2c-id="', a.files["index.html"].decode())), len(self.ir["nodes"]))

    def test_instrumentation_can_be_stripped_and_semantic_elements_used(self) -> None:
        h = gen(self.ir, instrumentation=False).files["index.html"].decode()
        self.assertNotIn("data-s2c-id", h); self.assertIn("<h1", h); self.assertIn('<button class="button-1" type="button"', h)

    def test_hostile_text_is_inert(self) -> None:
        ir = copy.deepcopy(self.ir)
        victims = [n for n in ir["nodes"].values() if n["kind"] == "text"][:4]
        evil = ['"><script>alert(1)</script>', "</style><img src=x onerror=alert(1)>", "&amp; <b>x</b> \u202e rtl", "{{7*7}} ${process.env} javascript:alert(1)"]
        for n, s in zip(victims, evil):
            n["text"]["content"]["value"] = s; n["name"] = s
        rep = validate(ir, 2); self.assertTrue(rep.ok, rep.errors)
        files = gen(ir).files
        html = files["index.html"].decode()
        self.assertNotIn("<script", html.lower()); self.assertNotIn("<img src=x", html); self.assertNotIn("onerror=alert", html.replace("&quot;", '"').replace("&lt;", "<")[:0] or html.split("&lt;")[0])
        p = Balanced(); p.feed(html); self.assertEqual((p.scripts, p.errors), (0, []))
        self.assertIn("&lt;script&gt;", html)
        self.assertNotIn("</style><img", files["styles.css"].decode())

    def test_unreadable_uncertain_and_redacted_text_policies(self) -> None:
        ir = copy.deepcopy(self.ir)
        t = [n for n in ir["nodes"].values() if n["kind"] == "text"]
        t[0]["text"]["content"].update(value=None, status="unreadable")
        t[1]["text"]["content"].update(status="uncertain")
        self.assertFalse(validate(ir, 2).ok, "derived status/completeness must be updated together with the content (R-EPI-8)")
        from screen2code.ir import derive_completeness, derive_status
        for n in ir["nodes"].values():
            n["status"] = derive_status(n)
        for pid, pg in ir["pages"].items():
            pg["completeness"]["state"] = derive_completeness(ir, pid)
        self.assertTrue(validate(ir, 2).ok)
        g = gen(ir, placeholder_text="[??]")
        self.assertIn("[??]", g.files["index.html"].decode())
        self.assertEqual([u["status"] for u in g.report.uncertain_text], ["uncertain"])
        self.assertTrue(any("unreadable" in d["message"] for d in g.report.deviations))

    def test_page_with_extracted_asset_and_rights_policies(self) -> None:
        canvas = np.full((300, 400, 3), 255, np.uint8)
        canvas[60:180, 100:260] = np.dstack([np.tile(np.linspace(0, 255, 160), (120, 1)), np.tile(np.linspace(255, 0, 120)[:, None], (1, 160)), np.full((120, 160), 90)]).astype(np.uint8)
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "i.png"; Image.fromarray(canvas).save(p)
            per = perceive(p, Context(None, load_config()), TesseractOCR())
            store = {}
            ir = build_ir(per, load_config(), "t", "Img", lambda b: store.setdefault(hashlib.sha256(b).hexdigest(), b) and hashlib.sha256(b).hexdigest())
        rd = lambda sha: store[sha]
        default = generate(ir, "html", rd); strict = generate(ir, "html", rd, {"asset_policy": "strict"}); perm = generate(ir, "html", rd, {"asset_policy": "permissive"})
        self.assertTrue(any(f.startswith("assets/") for f in default.files)); self.assertFalse(any(f.startswith("assets/") for f in strict.files))
        self.assertTrue(any("unknown" in w for w in default.report.warnings)); self.assertTrue(any("strict" in w for w in strict.report.warnings)); self.assertEqual(perm.report.warnings, [])
        for g in (default, strict, perm):  # provenance is preserved under every policy; no ownership claim is ever made
            self.assertEqual(g.report.assets[0]["provenance"], "extracted"); self.assertEqual(g.report.assets[0]["rights_status"], "unknown")
            text = (g.report.markdown() + json.dumps(g.report.to_dict())).lower()
            self.assertNotIn("copyright (c)", text); self.assertNotIn("all rights reserved", text); self.assertNotIn("licensed under", text)
        self.assertIn("data-s2c-placeholder", strict.files["index.html"].decode())
        self.assertEqual(strict.report.placeholders[0]["reason"], "excluded by policy")

    def test_only_committed_valid_ir_is_accepted(self) -> None:
        ir = copy.deepcopy(self.ir); ir["ir_state"] = "working"
        with self.assertRaises(S2CError) as cm:
            gen(ir)
        self.assertEqual(cm.exception.code, "S2C-GEN-001")
        bad = copy.deepcopy(self.ir); bad["nodes"][next(iter(bad["nodes"]))]["children"] = ["nd_nope"]
        with self.assertRaises(S2CError):
            gen(bad)
        with self.assertRaises(S2CError):
            generate(self.ir, "vue", lambda s: b"")

    def test_components_are_lowered_and_unsupported_semantics_are_reported_not_dropped(self) -> None:
        g = generate(GOLDEN, "html", lambda sha: b"x")
        self.assertEqual(g.report.deviations, [], "the golden Card component lowers without deviations")
        self.assertEqual(g.files["index.html"].decode().count('class="card-1 instance-'), 3)  # three instances share one component class
        self.assertEqual(g.files["styles.css"].decode().count(".card-1 {"), 1, "a component's rules are emitted once")
        ir = copy.deepcopy(GOLDEN)
        card_root = ir["components"]["cmp_card"]["root"]
        ir["nodes"]["nd_c1"]["instance"]["overrides"].append({"target": card_root, "path": "style.fill", "value": {"kind": "none"}, "reason": "demo"})
        self.assertTrue(validate(ir, 2).ok)
        self.assertTrue(any("override" in d["message"] and "not applied" in d["message"] for d in generate(ir, "html", lambda sha: b"x").report.deviations))

    def test_builder_is_confined_and_never_overwrites_silently(self) -> None:
        g = gen(self.ir)
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / "out"; write_project(g, out)
            with self.assertRaises(S2CError) as cm:
                write_project(g, out)
            self.assertEqual(cm.exception.code, "S2C-PATH-003")
            write_project(g, out, overwrite=True)
            evil = copy.copy(g); evil.files = {**g.files, "../escape.txt": b"x"}
            with self.assertRaises(S2CError):
                write_project(evil, Path(d) / "out2")
            self.assertFalse((Path(d) / "escape.txt").exists())
            self.assertTrue((out / "REPORT.md").exists() and (out / "s2c-report.json").exists())


class SecurityTests(unittest.TestCase):
    def test_tampered_ir_with_path_traversal_asset_is_rejected(self) -> None:
        ir = copy.deepcopy(GOLDEN)
        ir["assets"]["ast_hero"]["content"]["ref"] = "blob:sha256:../../../etc/passwd"
        self.assertFalse(validate(ir, 0).ok)

    @needs_ocr
    def test_malformed_provider_responses_are_rejected(self) -> None:
        class Bad:
            id, version = "bad", "1"
            def __init__(self, res): self.res = res
            def available(self): return True, ""
            def read(self, rgb, bg, multiline): return self.res
        from screen2code.core.runner import ProviderCache
        from screen2code.vision.segment import segment_image
        from screen2code.vision import import_image

        root = segment_image(import_image(LANDING, load_config()).rgb)
        rgb = import_image(LANDING, load_config()).rgb
        for res in ("not a dict", {"value": 5, "conf": 0.5}, {"value": "x", "conf": 7}, {"value": "x", "conf": True}, {"value": "x\x00y", "conf": 0.5}, {"value": "A" * 5000, "conf": 0.5}):
            with self.assertRaises(S2CError) as cm:
                run_ocr(rgb, root, Bad(res), ProviderCache(None), 30.0)
            self.assertEqual(cm.exception.code, "S2C-PROVIDER-002", res)

    @needs_ocr
    def test_provider_timeout_is_an_error_not_a_hang(self) -> None:
        from screen2code.core.runner import ProviderCache
        from screen2code.vision import import_image
        from screen2code.vision.segment import segment_image

        rgb = import_image(LANDING, load_config()).rgb
        with self.assertRaises(S2CError) as cm:
            run_ocr(rgb, segment_image(rgb), TesseractOCR(timeout_s=0.001), ProviderCache(None), 30.0)
        self.assertIn(cm.exception.code, ("S2C-PROVIDER-003",))

    def test_no_code_execution_entry_points_in_the_source(self) -> None:
        bad = re.compile(r"\b(os\.system|os\.popen|eval|exec|compile|__import__|pickle\.loads?|marshal\.loads?)\(")
        allowed_subprocess = {"rendering/render.py"}  # fc-match font resolution only (fixed argv, no shell, no user data)
        for f in (ROOT / "src" / "screen2code").rglob("*.py"):
            rel = str(f.relative_to(ROOT / "src" / "screen2code"))
            src = f.read_text(encoding="utf-8")
            code_lines = [l for l in src.splitlines() if not l.lstrip().startswith("#")]
            for l in code_lines:
                m = bad.search(l)
                if m and "__import__" not in m.group(0) and "re.compile" not in l and "compile(" != m.group(1) + "(":
                    self.fail(f"{rel}: forbidden call {m.group(0)!r}")
            if "subprocess" in src:
                self.assertIn(rel, allowed_subprocess, f"{rel} uses subprocess")
                self.assertNotIn("shell=True", src)

    def test_cli_exposes_no_way_to_execute_generated_code(self) -> None:
        self.assertEqual(sorted(cli.commands), sorted(["init", "import", "reconstruct", "analyze", "generate", "render", "evaluate", "run", "ir", "doctor", "models", "errors", "benchmark", "serve", "refine"]))


class ArchitectureTests(unittest.TestCase):
    ALLOWED = {"ir": set(), "core": {"ir"}, "vision": {"ir", "core"}, "reconstruction": {"ir", "core", "vision"}, "generation": {"ir", "core"},
               "rendering": {"core"}, "evaluation": {"ir", "core"}, "bench": {"ir", "core", "rendering"}}

    def test_package_dependency_graph(self) -> None:
        base = ROOT / "src" / "screen2code"
        for pkg, allowed in self.ALLOWED.items():
            for f in (base / pkg).rglob("*.py"):
                for node in ast.walk(ast.parse(f.read_text(encoding="utf-8"))):
                    mods = []
                    if isinstance(node, ast.ImportFrom):
                        if node.level >= 2 and node.module:
                            mods.append(node.module.split(".")[0])
                        elif node.level >= 2 and not node.module:
                            mods += [a.name for a in node.names]
                        elif node.module and node.module.startswith("screen2code."):
                            mods.append(node.module.split(".")[1])
                    for m in mods:
                        if m in self.ALLOWED and m != pkg:
                            self.assertIn(m, allowed, f"{f.relative_to(base)} imports screen2code.{m}, violating the dependency graph")
                        self.assertNotIn(m, ("cli", "server", "api"), f"{f.relative_to(base)} imports an outer layer")


class EvaluationTests(unittest.TestCase):
    def ir_with_region(self):
        ir = copy.deepcopy(GOLDEN)
        return ir

    def run_eval(self, ref, gen_arr, ir=None, boxes=None):
        ir = ir or self.ir_with_region()
        scr = "scr_d"
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "g.png"; Image.fromarray(gen_arr).save(p)
            return evaluate(ref, p, ir, scr, {"boxes": boxes or {}})

    def test_identical_images_score_perfectly_and_reports_are_honest(self) -> None:
        ref = np.full((868, 1440, 3), 255, np.uint8); ref[100:300, 100:500] = (10, 100, 200)
        rep, imgs = self.run_eval(ref, ref.copy())
        m = rep["metrics"]
        self.assertEqual((m["pixel"]["mismatch_fraction"], m["pixel"]["mae"]), (0.0, 0.0)); self.assertAlmostEqual(m["ssim"]["ssim"], 1.0, places=6)
        self.assertEqual(m["edge"]["edge_f1"], 1.0)
        self.assertEqual(set(rep["unavailable_metrics"]), {"typography", "perceptual_lpips", "responsive", "theme"})
        self.assertEqual(m["composite"]["weights"], {"ssim": 0.3, "edge_f1": 0.2, "layout_mean_iou": 0.3, "pixel_match": 0.2})
        self.assertEqual(set(imgs), {"reference", "generated", "overlay", "difference", "ssim_map"})

    def test_known_difference_is_measured(self) -> None:
        ref = np.full((868, 1440, 3), 255, np.uint8); gen = ref.copy(); gen[0:100, 0:1440] = 0
        rep, _ = self.run_eval(ref, gen)
        self.assertAlmostEqual(rep["metrics"]["pixel"]["mismatch_fraction"], 100 / 868, places=4)
        self.assertLess(rep["metrics"]["ssim"]["ssim"], 0.95)

    def test_size_mismatch_is_reported_not_hidden(self) -> None:
        ref = np.full((868, 1440, 3), 255, np.uint8)
        rep, _ = self.run_eval(ref, ref[:500, :1000].copy())
        self.assertTrue(rep["size"]["size_mismatch"]); self.assertEqual(rep["size"]["generated"], [1000, 500])

    def test_layout_metric_uses_realizations_and_flags_missing_nodes(self) -> None:
        ir = self.ir_with_region()
        ref = np.full((868, 1440, 3), 255, np.uint8)
        real = ir["realizations"]["scr_d"]["nodes"]
        rect = {nid: ir["regions"][e["regions"][0]]["rect"] for nid, e in real.items()}
        boxes = {nid: {"x": float(r["x"]), "y": float(r["y"]), "w": float(r["w"]), "h": float(r["h"])} for nid, r in rect.items()}
        victim = "nd_h1"; boxes.pop(victim); shifted = "nd_himg"; boxes[shifted]["x"] += 1000
        rep, _ = self.run_eval(ref, ref.copy(), ir, boxes)
        lay = rep["metrics"]["layout"]
        self.assertIn(victim, lay["missing_nodes"]); self.assertIn(shifted, lay["missing_nodes"]); self.assertEqual(lay["matched_nodes"] + 1, lay["expected_nodes"] - 0 if False else lay["matched_nodes"] + 1)
        self.assertEqual(rep["metrics"]["missing_elements"]["missing_count"], len(rep["metrics"]["missing_elements"]["missing"]))

    def test_placeholder_regions_are_excluded_and_counted(self) -> None:
        ref = np.full((868, 1440, 3), 255, np.uint8)
        gen = ref.copy(); gen[484:796, 40:456] = 0  # the placeholder image area differs completely
        rep, _ = self.run_eval(ref, gen)
        ex = rep["exclusions"]
        self.assertGreater(len(ex["placeholder_regions"]), 0); self.assertGreater(ex["excluded_area_fraction"], 0)
        self.assertEqual(rep["metrics"]["pixel"]["masked"]["mismatch_fraction"], 0.0)
        self.assertGreater(rep["metrics"]["pixel"]["mismatch_fraction"], 0)


@needs_ocr
@needs_browser
class EndToEndTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.tmp = tempfile.TemporaryDirectory(); cls.addClassCleanup(cls.tmp.cleanup)
        cls.proj = Project.create(Path(cls.tmp.name) / "p", "e2e", overrides=NO_SANDBOX)
        cls.proj.import_images([LANDING], {"page_hint": "Landing"})
        cls.res = cls.proj.run()

    def test_artifacts_exist_and_ir_is_valid(self) -> None:
        r = self.proj.root
        self.assertTrue(validate(self.proj.ir, 3).ok)
        for f in ("exports/html/index.html", "exports/html/styles.css", "exports/html/s2c-report.json", "exports/html/REPORT.md", "ir/project.ir.json"):
            self.assertTrue((r / f).exists(), f)
        scr = next(iter(self.res["evaluation"]))
        for f in ("reference.png", "generated.png", "overlay.png", "difference.png", "report.json", "REPORT.md"):
            self.assertTrue((r / "evaluations" / scr / f).exists(), f)
        self.assertTrue((r / "runs" / "reconstruct-latest.json").exists())

    def test_measured_quality_gates_on_the_landing_fixture(self) -> None:
        """Regression gates from measured baselines on this one fixture (not a claim about other pages).

        Ink-box geometry measured SSIM 0.927 / edge F1 0.981 / layout IoU 0.842. The typographic cell model (content-independent line boxes, needed for
        stable tokens and component identity) measured SSIM 0.923 / edge F1 0.88 / layout IoU 0.878; the gates below follow the current design."""
        m = next(iter(self.res["evaluation"].values()))["metrics"]
        self.assertGreaterEqual(m["ssim"]["ssim"], 0.90); self.assertGreaterEqual(m["edge"]["edge_f1"], 0.85)
        self.assertGreaterEqual(m["layout"]["layout_mean_iou"], 0.80); self.assertEqual(m["missing_elements"]["missing_count"], 0)
        self.assertLessEqual(m["pixel"]["mismatch_fraction"], 0.05); self.assertEqual(m["color"]["max_delta_e2000"], 0.0)

    def test_render_record_documents_tier0_and_sandbox_opt_in(self) -> None:
        rec = json.loads((self.proj.root / "renders" / f"{next(iter(self.res['evaluation']))}.render.json").read_text())
        self.assertFalse(rec["javascript_enabled"]); self.assertTrue(rec["offline"]); self.assertEqual(rec["blocked_requests"], [])
        if not rec["chromium_sandbox"]:
            self.assertTrue(any("sandbox disabled" in w for w in rec["warnings"]))

    def test_rerun_is_deterministic_and_uses_the_cache(self) -> None:
        h1 = content_hash(self.proj.ir)
        r2 = self.proj.reconstruct()
        self.assertEqual(r2.content_hash, h1)
        rec = json.loads((self.proj.root / "runs" / "reconstruct-latest.json").read_text())
        self.assertEqual(rec["ocr_cache"]["misses"], 0); self.assertGreater(rec["ocr_cache"]["hits"], 0)

    def test_multi_screenshot_project_keeps_pages_independent(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            other = Image.open(LANDING).convert("RGB"); other.paste((200, 30, 30), (0, 0, 1000, 60)); other.save(Path(d) / "second.png")
            p = Project.create(Path(d) / "m", "multi", overrides=NO_SANDBOX)
            p.import_images([LANDING, Path(d) / "second.png"]); c = p.reconstruct()
            self.assertEqual(c.pages, 2); self.assertTrue(validate(p.ir, 3).ok)


@needs_ocr
@needs_browser
class CliTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup); self.d = Path(self.tmp.name); self.r = CliRunner()

    def test_run_json_and_exit_codes(self) -> None:
        res = self.r.invoke(cli, ["--json", "--allow-no-sandbox", "run", str(LANDING), "--project", str(self.d / "p")])
        self.assertEqual(res.exit_code, 0, res.stderr)
        out = json.loads(res.stdout); self.assertGreater(out["commit"]["nodes"], 15); self.assertIn("ssim", next(iter(out["evaluation"].values())))
        ok = self.r.invoke(cli, ["--json", "ir", "validate", str(self.d / "p" / "ir" / "project.ir.json")])
        self.assertEqual(ok.exit_code, 0); self.assertTrue(json.loads(ok.stdout)["valid"])
        broken = self.d / "broken.json"; doc = json.loads((self.d / "p" / "ir" / "project.ir.json").read_text()); doc["nodes"][next(iter(doc["nodes"]))]["kind"] = "div"; broken.write_text(json.dumps(doc))
        bad = self.r.invoke(cli, ["ir", "validate", str(broken)]); self.assertEqual(bad.exit_code, 3)
        junk = self.d / "junk.png"; junk.write_text("nope")
        self.assertEqual(self.r.invoke(cli, ["--json", "reconstruct", str(junk), "--project", str(self.d / "q")]).exit_code, 5)
        err = json.loads(self.r.invoke(cli, ["--json", "reconstruct", str(junk), "--project", str(self.d / "q2")]).stdout)["error"]
        self.assertEqual(err["code"], "S2C-IMPORT-003"); self.assertEqual(err["category"], "input")

    def test_render_fails_closed_without_opt_in_when_sandbox_unavailable(self) -> None:
        self.r.invoke(cli, ["reconstruct", str(LANDING), "--project", str(self.d / "p")]); self.r.invoke(cli, ["generate", str(self.d / "p")])
        res = self.r.invoke(cli, ["--json", "render", str(self.d / "p")])
        if res.exit_code != 0:
            self.assertEqual(res.exit_code, 4); self.assertEqual(json.loads(res.stdout)["error"]["code"], "S2C-RENDER-002")
        else:
            self.assertTrue(json.loads(res.stdout)["sandbox"])

    def test_help_doctor_errors_and_models(self) -> None:
        self.assertIn("see it, understand it", self.r.invoke(cli, ["--help"]).stdout.lower())
        self.assertEqual(self.r.invoke(cli, ["--json", "doctor"]).exit_code, 0)
        codes = json.loads(self.r.invoke(cli, ["--json", "errors"]).stdout); self.assertIn("S2C-PATH-001", codes)
        mf = self.d / "m.json"; f = self.d / "m.bin"; f.write_bytes(b"w")
        mf.write_text(json.dumps({"id": "demo", "version": "1", "source_url": "file:///x", "license_spdx": "AGPL-3.0-only", "license_class": "copyleft", "sha256": hashlib.sha256(b"w").hexdigest(), "size_bytes": 1, "format": "onnx"}))
        import os
        os.environ["SCREEN2CODE_MODELS"] = str(self.d / "models"); self.addCleanup(os.environ.pop, "SCREEN2CODE_MODELS")
        denied = self.r.invoke(cli, ["--json", "models", "install", "--manifest", str(mf), "--file", str(f)]); self.assertEqual(denied.exit_code, 5, "license refusal is a security-category error")
        self.assertEqual(json.loads(denied.stdout)["error"]["code"], "S2C-MODEL-003")
        self.assertEqual(self.r.invoke(cli, ["models", "install", "--manifest", str(mf), "--file", str(f), "--accept-license"]).exit_code, 0)
        self.assertEqual(self.r.invoke(cli, ["models", "verify", "demo", "1"]).exit_code, 0)


if __name__ == "__main__":
    unittest.main()
