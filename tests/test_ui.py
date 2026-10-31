"""Desktop UI end-to-end: the built bundle runs in Chromium and talks to a REAL `screen2code.server.main` sidecar process.

The harness stands in for the Tauri shell only: it serves ui/dist over http, provides `window.s2cHost`, and relays framed JSON-RPC to the sidecar.
Nothing is mocked: every number and image the UI shows comes from the sidecar. The harness launches its own Chromium with --no-sandbox because the
sandbox cannot start in this container (a test-environment waiver; the product's own render path records its sandbox state, which the UI displays).
"""
from __future__ import annotations

import http.server
import json
import os
import queue
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
from functools import partial
from pathlib import Path

from .helpers import FIX, ROOT, needs_browser, needs_ocr

SITE = FIX / "site"
sys.path.insert(0, str(ROOT / "scripts"))


def ui_build_ok() -> tuple[bool, str]:
    try:
        import build_ui

        mods = build_ui.node_modules()
        return (build_ui.find_esbuild(mods) is not None and bool(mods) and shutil.which("node") is not None), "node/esbuild/react not found"
    except Exception as e:  # noqa: BLE001
        return False, type(e).__name__


needs_ui_build = unittest.skipUnless(ui_build_ok()[0], "UI toolchain unavailable: " + ui_build_ok()[1])


class Sidecar:
    def __init__(self) -> None:
        env = {**os.environ, "PYTHONPATH": str(ROOT / "src")}
        self.p = subprocess.Popen([sys.executable, "-m", "screen2code.server.main"], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, env=env)
        self.q: queue.Queue[str] = queue.Queue()
        self.lock = threading.Lock()
        self.log: list[str] = []
        threading.Thread(target=self._read, daemon=True).start()

    def _read(self) -> None:
        out = self.p.stdout
        while True:
            length = None
            while True:
                line = out.readline()
                if not line:
                    return
                if not line.strip():
                    break
                if line.lower().startswith(b"content-length:"):
                    length = int(line.split(b":")[1])
            self.q.put(out.read(length).decode("utf-8"))

    def send(self, message: str) -> None:
        body = message.encode("utf-8")
        with self.lock:
            self.log.append(message)
            self.p.stdin.write(b"Content-Length: %d\r\n\r\n" % len(body) + body)
            self.p.stdin.flush()

    def drain(self) -> list[str]:
        out = []
        while True:
            try:
                out.append(self.q.get_nowait())
            except queue.Empty:
                return out

    def close(self) -> None:
        try:
            self.send(json.dumps({"jsonrpc": "2.0", "method": "exit"}))
            self.p.wait(timeout=10)
        except Exception:  # noqa: BLE001
            self.p.kill()
        for f in (self.p.stdin, self.p.stdout):
            try:
                f.close()
            except Exception:  # noqa: BLE001
                pass


class QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *a) -> None:  # noqa: D401
        pass


@needs_ocr
@needs_browser
@needs_ui_build
class UiEndToEnd(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        import build_ui
        from playwright.sync_api import sync_playwright

        cls.dist = build_ui.build()
        cls.httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), partial(QuietHandler, directory=str(cls.dist)))
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()
        cls.tmp = tempfile.TemporaryDirectory()
        cls.side = Sidecar()
        cls.pw = sync_playwright().start()
        cls.browser = cls.pw.chromium.launch(args=["--no-sandbox"])
        cls.page = cls.browser.new_page(viewport={"width": 1400, "height": 900})
        cls.page.set_default_timeout(150_000)
        cls.console: list[str] = []
        cls.page.on("console", lambda m: cls.console.append(f"{m.type}: {m.text}") if m.type in ("error", "warning") else None)
        cls.page.on("pageerror", lambda e: cls.console.append(f"pageerror: {e}"))
        cls.page.on("dialog", lambda d: d.accept())
        cls.page.expose_function("s2cSend", cls.side.send)
        cls.page.expose_function("s2cPoll", cls.side.drain)
        cls.page.add_init_script("window.s2cHost = { send: m => window.s2cSend(m), poll: () => window.s2cPoll() };")
        cls.page.goto(f"http://127.0.0.1:{cls.httpd.server_address[1]}/index.html")

    @classmethod
    def tearDownClass(cls) -> None:
        try:
            cls.page.goto("about:blank")  # stops the UI's polling timer before the browser goes away
        except Exception:  # noqa: BLE001
            pass
        for fn in (cls.page.close, cls.browser.close, cls.pw.stop, cls.side.close, cls.httpd.shutdown, cls.httpd.server_close, cls.tmp.cleanup):
            try:
                fn()
            except Exception:  # noqa: BLE001
                pass

    # helpers
    def nav(self, view: str) -> None:
        self.page.get_by_test_id(f"nav-{view}").click()

    def tid(self, t: str):
        return self.page.get_by_test_id(t)

    def wait_idle(self) -> None:
        self.page.wait_for_function("() => !document.querySelector('[data-testid=task]')")

    def test_full_user_workflow(self) -> None:
        pg = self.page
        self.tid("connection").wait_for()
        pg.wait_for_function("() => document.querySelector('[data-testid=connection]').textContent.startsWith('connected')")

        # -- sandbox waiver is explicit, visible, and a user decision (needed for rendering inside this container)
        self.nav("settings")
        self.tid("waive-sandbox").check()
        self.assertTrue(self.tid("sandbox-banner").is_visible())
        self.assertTrue(self.tid("redact-text").is_visible())
        pg.wait_for_function("() => document.querySelector('[data-testid=config]').textContent.includes('render') || document.querySelector('[data-testid=config]').textContent === '—'")

        # -- project: create, import two screens declared as one page, analyze
        self.nav("project")
        proj = str(Path(self.tmp.name) / "ui-proj")
        self.tid("project-path").fill(proj)
        self.tid("project-create").click()
        self.tid("import-paths").wait_for()
        for img, width in (("home-1000.png", "1000"), ("home-480.png", "480")):
            self.tid("import-paths").fill(str(SITE / img))
            self.tid("import-hint").fill("home")
            self.tid("import-width").fill(width)
            self.tid("import-run").click()
            self.wait_idle()
        pg.wait_for_function("() => document.querySelectorAll('[data-testid=inputs] tbody tr').length === 2")
        self.tid("analyze").click()
        self.tid("task").wait_for()
        self.assertTrue(self.tid("cancel").is_visible())
        self.tid("analysis-done").wait_for()
        self.assertIn("2 screen(s)", self.tid("analysis-done").inner_text())
        self.assertFalse(self.tid("error").count(), "no error banner after a successful analysis")

        # -- regions: the original image with measured rectangles; selecting one shows the node it realizes
        self.nav("regions")
        self.tid("original-image").wait_for()
        n_regions = self.tid("region-rect").count()
        self.assertGreater(n_regions, 10)
        self.assertIn(str(n_regions), self.tid("region-count").inner_text())
        self.tid("region-rect").nth(3).dispatch_event("click")
        detail = self.tid("region-detail").inner_text()
        self.assertIn("basis", detail)
        self.assertIn("measured", detail)

        # -- inspector: tree + provenance (observed vs inferred) for a node
        self.nav("inspector")
        self.assertGreater(self.tid("tree-node").count(), 15)
        self.tid("tree-node").filter(has_text=re.compile(r"^text")).first.click()
        rows = self.tid("provenance").locator("tbody tr")
        self.assertGreaterEqual(rows.count(), 2)
        self.assertRegex(self.tid("provenance").inner_text(), r"(measured|reported|default|heuristic|inferred)")

        # -- design system and reconciliation decision shown to the user
        self.nav("design")
        self.tid("reconciliation").wait_for()
        self.assertIn("unified", self.tid("reconciliation").inner_text())
        self.assertGreater(self.tid("tokens").locator("tbody tr").count(), 2)
        self.assertIn("skipped_responsive", self.tid("near-misses").inner_text())

        # -- generate: files are shown as text only
        self.nav("generate")
        self.tid("generate").click()
        self.tid("generated-files").wait_for()
        self.page.get_by_text("index.html", exact=True).click()
        pg.wait_for_function("() => document.querySelector('[data-testid=file-text]').textContent.toLowerCase().includes('<html')")
        self.assertIn("never executed", pg.locator("p.warn").first.inner_text())
        self.assertEqual(pg.locator("iframe").count(), 0, "generated code is never embedded or run in the UI")

        # -- render + evaluate on the narrow screen (one generated page, media query)
        self.nav("evaluate")
        self.tid("screen-select").select_option(label="home @ 480px")
        self.tid("render-eval").click()
        self.tid("metrics").wait_for()
        self.assertIn("composite", self.tid("metrics").inner_text())
        self.assertIn("OFF", self.tid("sandbox-state").inner_text())
        self.tid("eval-image").wait_for()
        for tab in ("reference", "generated", "overlay", "difference"):
            self.tid(f"tab-{tab}").click()
            self.tid("eval-image").wait_for()
        self.assertTrue(self.tid("worst-nodes").is_visible())

        # -- refine: bounded run, result and history from the sidecar
        self.nav("refine")
        self.tid("refine-iters").fill("1")
        self.tid("refine-run").click()
        self.tid("refine-result").wait_for()
        self.assertIn("stop reason", self.tid("refine-result").inner_text())
        self.assertIn("false", self.tid("refine-result").inner_text().lower().split("applied")[-1])
        self.assertGreaterEqual(self.tid("refine-runs").locator("tbody tr").count(), 1)

        # -- reports
        self.nav("reports")
        self.page.get_by_text("reconciliation.json", exact=True).click()
        pg.wait_for_function("() => document.querySelector('[data-testid=report-text]').textContent.includes('groups')")

        # -- errors are surfaced with their stable code, never swallowed
        self.nav("project")
        self.tid("import-paths").fill(str(Path(self.tmp.name) / "does-not-exist.png"))
        self.tid("import-run").click()
        self.tid("error").wait_for()
        self.assertRegex(self.tid("error").inner_text(), r"S2C-|-32")

        # -- the page itself never failed
        bad = [m for m in self.console if "Content Security Policy" in m or m.startswith("pageerror")]
        self.assertEqual(bad, [], bad)


if __name__ == "__main__":
    unittest.main()
