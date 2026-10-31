"""Perception (S0-S3) and structure (S5/S6/S10) tests on a real screenshot and on adversarial inputs."""
from __future__ import annotations

import io
import json
import tempfile
import unittest
from pathlib import Path

import numpy as np
from PIL import Image

from screen2code.core import S2CError
from screen2code.core.config import load_config
from screen2code.ir import canonical_dumps, content_hash, validate
from screen2code.reconstruction import build_ir
from screen2code.vision import import_image, segment_image

from .helpers import LANDING, Perceived, needs_ocr


class ImportTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup); self.d = Path(self.tmp.name); self.cfg = load_config()

    def save(self, name: str, im: Image.Image, **kw) -> Path:
        p = self.d / name; im.save(p, **kw); return p

    def code(self, p: Path, cfg=None) -> str:
        with self.assertRaises(S2CError) as cm:
            import_image(p, cfg or self.cfg)
        return cm.exception.code

    def test_valid_png_normalized_and_hashed(self) -> None:
        img = import_image(LANDING, self.cfg)
        self.assertEqual((img.pixel_size["w"], img.media_type), (1000, "image/png"))
        self.assertEqual(img.sha256, import_image(LANDING, self.cfg).sha256)
        self.assertEqual(img.rgb.shape, (800, 1000, 3))

    def test_content_not_extension_decides_format(self) -> None:
        p = self.save("really_png.jpg", Image.new("RGB", (20, 20), "red"), format="PNG")
        self.assertEqual(import_image(p, self.cfg).media_type, "image/png")
        (self.d / "x.png").write_text("<svg xmlns='http://www.w3.org/2000/svg'><script>alert(1)</script></svg>")
        self.assertEqual(self.code(self.d / "x.png"), "S2C-IMPORT-003")

    def test_non_accepted_format_animated_and_limits(self) -> None:
        self.assertEqual(self.code(self.save("a.gif", Image.new("P", (10, 10)), format="GIF")), "S2C-IMPORT-001")
        frames = [Image.new("RGB", (10, 10), c) for c in ("red", "blue")]
        p = self.d / "anim.webp"; frames[0].save(p, save_all=True, append_images=frames[1:], format="WEBP")
        self.assertEqual(self.code(p), "S2C-IMPORT-004")
        small = {**self.cfg, "import": {**self.cfg["import"], "max_side_px": 50}}
        self.assertEqual(self.code(self.save("big.png", Image.new("RGB", (60, 10))), small), "S2C-IMPORT-002")
        tiny = {**self.cfg, "import": {**self.cfg["import"], "max_file_mb": 0.0001}}
        self.assertEqual(self.code(self.save("f.png", Image.new("RGB", (300, 300), "white")), tiny), "S2C-IMPORT-002")

    def test_decompression_bomb_rejected_before_decode(self) -> None:
        cfg = {**self.cfg, "import": {**self.cfg["import"], "max_megapixels": 1}}
        self.assertEqual(self.code(self.save("bomb.png", Image.new("1", (4000, 4000))), cfg), "S2C-IMPORT-002")

    def test_alpha_flattened_metadata_stripped(self) -> None:
        im = Image.new("RGBA", (10, 10), (255, 0, 0, 0))
        p = self.save("a.png", im)
        out = import_image(p, self.cfg)
        self.assertEqual(tuple(out.rgb[0, 0]), (255, 255, 255)); self.assertIn("alpha channel flattened onto white", out.warnings)
        exif = Image.new("RGB", (10, 10), "blue"); e = Image.Exif(); e[0x010E] = "secret description"
        p2 = self.d / "e.jpg"; exif.save(p2, exif=e)
        self.assertNotIn(b"secret description", import_image(p2, self.cfg).png)

    def test_truncated_file_is_an_error_not_a_crash(self) -> None:
        data = LANDING.read_bytes()[:500]; p = self.d / "t.png"; p.write_bytes(data)
        self.assertEqual(self.code(p), "S2C-IMPORT-003")


class SegmentationTests(unittest.TestCase):
    def test_landing_tree(self) -> None:
        root = segment_image(import_image(LANDING, load_config()).rgb)
        top = [(c.kind, c.y, c.h, c.fill) for c in root.children]
        kinds = [k for k, *_ in top]
        self.assertEqual(kinds, ["container", "container", "group", "container"])  # header, hero, card group, footer
        self.assertEqual(top[0][3], (26, 26, 46)); self.assertEqual(top[1][3], (244, 246, 251))
        cards = root.children[2].children
        self.assertEqual(len(cards), 3)
        for c in cards:
            self.assertEqual((c.kind, c.border_w), ("container", 1)); self.assertAlmostEqual(c.radius, 10, delta=2.5)
        btn = [n for n in root.walk() if n.kind == "container" and n.fill == (47, 91, 234)]
        self.assertEqual(len(btn), 1); self.assertAlmostEqual(btn[0].radius, 8, delta=2.5)

    def test_blank_and_noise_inputs_do_not_crash(self) -> None:
        self.assertEqual(segment_image(np.full((50, 80, 3), 255, np.uint8)).children, [])
        rng = np.random.default_rng(0)
        segment_image(rng.integers(0, 255, (120, 160, 3), dtype=np.uint8))  # must terminate


@needs_ocr
class PerceptionTests(unittest.TestCase):
    def test_readings_and_evidence_are_observed_only(self) -> None:
        p = Perceived.get()
        texts = sorted(n.reading["value"] for n in p.root.walk() if n.reading)
        for want in ("Acme Studio", "Build faster", "Get started", "Alpha plan", "Beta plan", "Gamma plan", "Products", "Pricing", "About"):
            self.assertIn(want, texts)
        kinds = {e["kind"] for e in p.evidence.values()}
        self.assertTrue({"text_reading", "color_sample", "text_metrics", "containment", "stack_axis", "alignment", "grid_fit", "repetition", "border_profile", "spacing_sample"} <= kinds)
        for e in p.evidence.values():
            self.assertEqual(e["basis"], "reported" if e["kind"] == "text_reading" else "measured")

    def test_perception_is_deterministic(self) -> None:
        from screen2code.core import Context
        from screen2code.vision import TesseractOCR, perceive

        a, b = Perceived.get(), perceive(LANDING, Context(None, load_config()), TesseractOCR())
        self.assertEqual(canonical_dumps(a.evidence), canonical_dumps(b.evidence)); self.assertEqual(canonical_dumps(a.regions), canonical_dumps(b.regions))


@needs_ocr
class ReconstructionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.cfg = load_config()
        cls.ir = build_ir(Perceived.get(), cls.cfg, "t", "Home", Perceived.write_asset)

    def nodes(self, kind: str | None = None):
        return [n for n in self.ir["nodes"].values() if kind is None or n["kind"] == kind]

    def test_valid_through_l3_and_deterministic(self) -> None:
        self.assertTrue(validate(self.ir, 3).ok)
        again = build_ir(Perceived.get(), self.cfg, "t", "Home", Perceived.write_asset)
        self.assertEqual(content_hash(self.ir), content_hash(again)); self.assertEqual(canonical_dumps(self.ir), canonical_dumps(again))

    def test_layout_decisions(self) -> None:
        root = self.ir["nodes"][self.ir["pages"][next(iter(self.ir["pages"]))]["root"]]
        self.assertEqual((root["layout"]["mode"], root["layout"]["stack"]["axis"]), ("stack", "vertical"))
        grids = [n for n in self.nodes("box") if n.get("layout", {}).get("mode") == "grid"]
        self.assertEqual(len(grids), 1); self.assertEqual(len(grids[0]["layout"]["grid"]["columns"]), 3)
        self.assertTrue(all(c["kind"] == "share" for c in grids[0]["layout"]["grid"]["columns"]))
        self.assertEqual(sum(1 for n in self.nodes() if n.get("layout", {}).get("mode") == "absolute"), 0)
        space_between = [n for n in self.nodes("box") if n.get("layout", {}).get("stack", {}).get("distribute") == "space-between"]
        self.assertEqual(len(space_between), 1, "the header row is justified space-between")

    def test_text_typography_estimates(self) -> None:
        by = {n["text"]["content"]["value"]: n for n in self.nodes("text")}
        truth = {"Acme Studio": (22, 700), "Build faster": (40, 700), "Get started": (16, 400), "Alpha plan": (20, 700), "For small teams": (14, 400), "Products": (15, 400)}
        for text, (size, weight) in truth.items():
            st = by[text]["text"]["style"]
            self.assertAlmostEqual(st["size"]["px"], size, delta=2, msg=text); self.assertEqual(st["weight"], weight, msg=text)

    def test_roles_and_heading_levels(self) -> None:
        self.assertEqual(sum(1 for n in self.nodes() if n.get("role") == "button"), 1)
        self.assertEqual(sum(1 for n in self.nodes() if n.get("role") == "card"), 3)
        heads = [n for n in self.nodes("text") if n.get("role") == "heading"]
        self.assertEqual([(h["text"]["content"]["value"], h["text"]["heading_level"]) for h in heads], [("Build faster", 1)], "conservative rule: >= 1.5x median size or >= 24px")

    def test_epistemic_separation_and_honest_uncertainty(self) -> None:
        for n in self.nodes():
            self.assertNotIn("rect", json.dumps({k: v for k, v in n.items() if k != "inference"}), "no pixel rectangles in structure")
            for f, rec in n["inference"].items():
                self.assertEqual(rec["calibration"], "heuristic")
                self.assertEqual(rec["basis"] == "default", not rec["supports"])
        self.assertTrue(all(a["rights_status"] in ("unknown", "not_applicable") for a in self.ir["assets"].values()))

    def test_every_page_node_is_realized_by_a_measured_region(self) -> None:
        real = next(iter(self.ir["realizations"].values()))["nodes"]
        self.assertEqual(set(real), set(self.ir["nodes"]))
        for e in real.values():
            for r in e["regions"]:
                self.assertEqual(self.ir["regions"][r]["basis"], "measured")


@needs_ocr
class ImageNodeTests(unittest.TestCase):
    def test_images_become_extracted_assets_with_unknown_rights(self) -> None:
        from screen2code.core import Context
        from screen2code.vision import TesseractOCR, perceive

        rng = np.random.default_rng(3)
        canvas = np.full((300, 400, 3), 255, np.uint8)
        gradient = np.dstack([np.tile(np.linspace(0, 255, 160), (120, 1)), np.tile(np.linspace(255, 0, 120)[:, None], (1, 160)), np.full((120, 160), 90)]).astype(np.uint8)
        canvas[60:180, 100:260] = gradient
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "img.png"; Image.fromarray(canvas).save(p)
            cfg = load_config()
            per = perceive(p, Context(None, cfg), TesseractOCR())
            saved = {}
            ir = build_ir(per, cfg, "t", "Img", lambda b: saved.setdefault(__import__("hashlib").sha256(b).hexdigest(), b) and __import__("hashlib").sha256(b).hexdigest())
        imgs = [n for n in ir["nodes"].values() if n["kind"] == "image"]
        self.assertEqual(len(imgs), 1)
        a = ir["assets"][imgs[0]["media"]["asset"]]
        self.assertEqual((a["provenance"], a["rights_status"], a["origin"]["fidelity"], a["origin"]["lossy"]), ("extracted", "unknown", "pixel_crop", True))
        self.assertTrue(validate(ir, 2).ok)


if __name__ == "__main__":
    unittest.main()
