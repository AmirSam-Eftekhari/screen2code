"""React adapter tests. Generated components are verified by server-side rendering with tsx in THIS TEST HARNESS ONLY.

Screen2Code itself never builds or executes generated code (SECURITY section 5); here the inputs are our own fixtures inside a temporary
directory in the test environment. A Vite build and TypeScript type-check are NOT verified (no network, no @types/react offline).
"""
from __future__ import annotations

import copy
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from screen2code.generation import generate, write_project
from screen2code.ir import derive_completeness, derive_status, validate

from .helpers import FIX, Perceived, needs_ocr

GOLDEN = json.loads((FIX / "golden" / "acme_home.ir.json").read_text(encoding="utf-8"))
NODE_PATH = subprocess.run(["npm", "root", "-g"], capture_output=True, text=True).stdout.strip() if shutil.which("npm") else ""
HAVE_SSR = bool(shutil.which("tsx") and NODE_PATH and (Path(NODE_PATH) / "react-dom").is_dir())
needs_ssr = unittest.skipUnless(HAVE_SSR, "tsx/react/react-dom not available for server-side rendering")


def ssr(files: dict[str, bytes], page: str, d: Path) -> str:
    out = d / "app"
    from screen2code.generation import Generated  # noqa: F401
    for rel, data in files.items():
        p = out / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
    os.symlink(NODE_PATH, out / "node_modules")  # ESM resolution ignores NODE_PATH; link the globally installed react/react-dom (test harness only)
    (out / "render.tsx").write_text(f'import React from "react";\nimport {{ renderToStaticMarkup }} from "react-dom/server";\nimport {{ {page} }} from "./src/pages/{page}";\nprocess.stdout.write(renderToStaticMarkup(<{page} />));\n')
    r = subprocess.run(["tsx", str(out / "render.tsx")], capture_output=True, text=True, timeout=120, env={**os.environ, "NODE_PATH": NODE_PATH}, cwd=out)
    assert r.returncode == 0, r.stderr
    return r.stdout


class ReactStructureTests(unittest.TestCase):
    def test_project_layout_pins_and_typed_components(self) -> None:
        g = generate(GOLDEN, "react", lambda s: b"x")
        self.assertTrue({"package.json", "tsconfig.json", "index.html", "src/App.tsx", "src/main.tsx", "src/styles.css", "src/pages/Home.tsx", "src/components/ProductCard.tsx"} <= set(g.files))
        pkg = json.loads(g.files["package.json"]); self.assertTrue(all(v[0].isdigit() for v in {**pkg["dependencies"], **pkg["devDependencies"]}.values()), "exact pins only")
        card = g.files["src/components/ProductCard.tsx"].decode()
        self.assertIn("export type ProductCardProps", card); self.assertIn("title: string", card); self.assertIn("image: string | null", card)
        self.assertNotIn("dangerouslySetInnerHTML", "".join(b.decode(errors="ignore") for p, b in g.files.items() if p.endswith(".tsx")))
        self.assertTrue(any("generate-only" in w for w in g.report.warnings))

    def test_write_is_confined(self) -> None:
        g = generate(GOLDEN, "react", lambda s: b"x")
        with tempfile.TemporaryDirectory() as d:
            write_project(g, Path(d) / "out"); self.assertTrue((Path(d) / "out" / "src" / "pages" / "Home.tsx").exists())


@needs_ssr
class ReactRenderTests(unittest.TestCase):
    def test_golden_renders_with_components_and_params(self) -> None:
        g = generate(GOLDEN, "react", lambda s: b"x", {"instrumentation": False})
        with tempfile.TemporaryDirectory() as d:
            html = ssr(g.files, "Home", Path(d))
        self.assertIn("Summer essentials", html)
        for t in ("Canvas tote", "Linen shirt", "Wool beanie"):
            self.assertIn(t, html)
        self.assertEqual(html.count('class="card-1 instance-'), 3)
        self.assertEqual(html.count("data-s2c-placeholder"), 3)

    def test_hostile_text_is_escaped_by_react(self) -> None:
        ir = copy.deepcopy(GOLDEN)
        ir["nodes"]["nd_h1"]["text"]["content"]["value"] = '</p><script>alert(1)</script>"{x}'
        ir["nodes"]["nd_c1"]["instance"]["params"]["title"]["value"] = "<img src=x onerror=alert(1)>"
        self.assertTrue(validate(ir, 2).ok)
        with tempfile.TemporaryDirectory() as d:
            html = ssr(generate(ir, "react", lambda s: b"x").files, "Home", Path(d))
        self.assertNotIn("<script", html); self.assertNotIn("<img src=x", html); self.assertIn("&lt;script&gt;", html)

    @needs_ocr
    def test_reconstructed_landing_page_renders(self) -> None:
        import hashlib

        from screen2code.core.config import load_config
        from screen2code.reconstruction import build_ir
        from screen2code.reconstruction.system import infer_components, infer_tokens

        cfg = load_config()
        ir = build_ir(Perceived.get(), cfg, "t", "Landing", Perceived.write_asset)
        import copy as c
        ir = c.deepcopy(ir); infer_tokens(ir, cfg); infer_components(ir, cfg)
        self.assertTrue(validate(ir, 2).ok)
        g = generate(ir, "react", lambda sha: Perceived.store[sha], {"instrumentation": False})
        with tempfile.TemporaryDirectory() as d:
            html = ssr(g.files, "Landing", Path(d))
        for t in ("Acme Studio", "Build faster", "Get started", "Alpha plan", "Beta plan", "Gamma plan"):
            self.assertIn(t, html)


if __name__ == "__main__":
    unittest.main()
