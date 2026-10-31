"""Rendering tests against the real Chromium: Tier 0 restrictions are verified, not assumed."""
from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from PIL import Image

from screen2code.core import S2CError
from screen2code.rendering import render_static

BP = os.environ.get("PLAYWRIGHT_BROWSERS_PATH", "")
OPT = {"allow_no_sandbox": True, "browsers_path": BP}  # root-in-container sandbox: explicit opt-in, recorded in the render record

PAGE = """<!doctype html><html><body style="margin:0;background:#fff">
<div data-s2c-id="nd_a" style="position:absolute;left:10px;top:20px;width:100px;height:50px;background:#f00"></div>
<div data-s2c-id="nd_b" style="position:absolute;left:30px;top:100px;width:40px;height:300px;background:#00f"></div>
<script>document.body.style.background='#0f0'</script>
<img src="http://example.invalid/x.png" width="5" height="5">
<img src="file:///etc/hostname" width="5" height="5">
</body></html>"""


class RenderTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name); (self.root / "p.html").write_text(PAGE)

    def test_tier0_restrictions_hold(self) -> None:
        rec = render_static(self.root / "p.html", self.root, self.root / "out.png", viewport_width=200, **OPT)
        im = Image.open(self.root / "out.png").convert("RGB")
        self.assertEqual(im.getpixel((190, 5)), (255, 255, 255), "inline script must NOT have run (JavaScript disabled)")
        self.assertEqual(im.getpixel((50, 40)), (255, 0, 0))
        self.assertFalse(rec.javascript_enabled); self.assertTrue(rec.offline)
        self.assertTrue(any("example.invalid" in u for u in rec.blocked_requests), rec.blocked_requests)
        self.assertTrue(any("etc/hostname" in u for u in rec.blocked_requests), "file access outside the project must be blocked")
        self.assertIn("Chromium sandbox disabled", " ".join(rec.warnings)); self.assertFalse(rec.chromium_sandbox)

    def test_full_page_size_and_boxes_without_page_script(self) -> None:
        rec = render_static(self.root / "p.html", self.root, self.root / "o.png", viewport_width=200, **OPT)
        self.assertEqual(rec.pixel_size["w"], 200); self.assertGreaterEqual(rec.pixel_size["h"], 400)
        self.assertEqual(rec.boxes["nd_a"], {"x": 10.0, "y": 20.0, "w": 100.0, "h": 50.0})
        self.assertEqual(rec.boxes["nd_b"], {"x": 30.0, "y": 100.0, "w": 40.0, "h": 300.0})

    def test_device_scale_factor(self) -> None:
        rec = render_static(self.root / "p.html", self.root, self.root / "o2.png", viewport_width=200, scale=2.0, **OPT)
        self.assertEqual(rec.pixel_size["w"], 400); self.assertEqual(rec.boxes["nd_a"]["w"], 100.0, "boxes stay in CSS px")

    def test_same_render_is_byte_identical(self) -> None:
        for n in ("a", "b"):
            render_static(self.root / "p.html", self.root, self.root / f"{n}.png", viewport_width=200, **OPT)
        self.assertEqual((self.root / "a.png").read_bytes(), (self.root / "b.png").read_bytes())

    def test_html_outside_project_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as other:
            (Path(other) / "x.html").write_text("<p>x</p>")
            with self.assertRaises(S2CError) as cm:
                render_static(Path(other) / "x.html", self.root, self.root / "x.png", viewport_width=100, **OPT)
            self.assertEqual(cm.exception.code, "S2C-PATH-001")

    def test_sandbox_default_fails_closed_or_runs_with_sandbox(self) -> None:
        try:
            rec = render_static(self.root / "p.html", self.root, self.root / "s.png", viewport_width=100, browsers_path=BP)
            self.assertTrue(rec.chromium_sandbox)
        except S2CError as e:  # expected where the sandbox cannot start (e.g. root in a container)
            self.assertEqual(e.code, "S2C-RENDER-002")


if __name__ == "__main__":
    unittest.main()
