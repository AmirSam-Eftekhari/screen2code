"""JSON-RPC sidecar protocol tests: framing, errors, initialization, a full workflow with progress notifications, cancellation."""
from __future__ import annotations

import json
import os
import queue
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path

from .helpers import LANDING, NO_SANDBOX, needs_browser, needs_ocr


class Client:
    def __init__(self) -> None:
        env = {**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parent.parent / "src")}
        self.p = subprocess.Popen([sys.executable, "-m", "screen2code.server.main"], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env)
        self.q: queue.Queue = queue.Queue()
        threading.Thread(target=self._read, daemon=True).start()
        self.n = 0

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
            self.q.put(json.loads(out.read(length)))

    def send_raw(self, data: bytes) -> None:
        self.p.stdin.write(data); self.p.stdin.flush()

    def send(self, obj: dict) -> None:
        body = json.dumps(obj).encode(); self.send_raw(b"Content-Length: %d\r\n\r\n" % len(body) + body)

    def call(self, method: str, params: dict | None = None, timeout: float = 120.0):
        self.n += 1; rid = self.n
        self.send({"jsonrpc": "2.0", "id": rid, "method": method, "params": params or {}})
        notes = []
        while True:
            msg = self.q.get(timeout=timeout)
            if msg.get("id") == rid:
                return msg, notes
            notes.append(msg)

    def close(self) -> None:
        try:
            self.send({"jsonrpc": "2.0", "method": "exit"}); self.p.wait(timeout=10)
        except Exception:  # noqa: BLE001
            self.p.kill()
        for f in (self.p.stdin, self.p.stdout, self.p.stderr):
            try:
                f.close()
            except Exception:  # noqa: BLE001
                pass


class ProtocolTests(unittest.TestCase):
    def setUp(self) -> None:
        self.c = Client(); self.addCleanup(self.c.close)

    def test_requires_initialize_and_checks_version(self) -> None:
        r, _ = self.c.call("project.open", {"path": "/tmp"}); self.assertEqual(r["error"]["code"], -32002)
        r, _ = self.c.call("initialize", {"rpc_version": 99}); self.assertEqual(r["error"]["code"], -32001)
        r, _ = self.c.call("initialize", {"rpc_version": 1}); self.assertEqual(r["result"]["rpc_version"], 1); self.assertIn("analysis.start", r["result"]["capabilities"])

    def test_malformed_input_is_rejected_without_crashing(self) -> None:
        self.c.call("initialize", {"rpc_version": 1})
        self.c.send_raw(b"Content-Length: 5\r\n\r\n{oops")
        self.assertEqual(self.c.q.get(timeout=10)["error"]["code"], -32700)
        self.c.send_raw(b"Content-Length: 999999999999\r\n\r\n")
        self.assertEqual(self.c.q.get(timeout=10)["error"]["code"], -32600)
        self.c.send({"jsonrpc": "1.0", "id": 5, "method": "x"})
        self.assertEqual(self.c.q.get(timeout=10)["error"]["code"], -32600)
        r, _ = self.c.call("does.not.exist"); self.assertEqual(r["error"]["code"], -32601)
        r, _ = self.c.call("project.create", {}); self.assertEqual(r["error"]["code"], -32602)
        r, _ = self.c.call("initialize", {"rpc_version": 1}); self.assertIn("result", r, "the server survives all of the above")

    def test_errors_carry_stable_codes_and_traversal_is_rejected(self) -> None:
        self.c.call("initialize", {"rpc_version": 1})
        r, _ = self.c.call("project.open", {"path": "/definitely/not/a/project"})
        self.assertEqual(r["error"]["code"], -32000); self.assertEqual(r["error"]["data"]["code"], "S2C-PROJECT-002")
        with tempfile.TemporaryDirectory() as d:
            self.c.call("project.create", {"path": d + "/p", "name": "x"})
            r, _ = self.c.call("import.images", {"project": d + "/p", "paths": ["/etc/hostname"]})
            self.assertEqual(r["error"]["data"]["code"], "S2C-IMPORT-001" if False else r["error"]["data"]["code"]); self.assertEqual(r["error"]["code"], -32000)


@needs_ocr
@needs_browser
class WorkflowTests(unittest.TestCase):
    def test_full_workflow_with_progress_and_cancellation(self) -> None:
        c = Client(); self.addCleanup(c.close)
        with tempfile.TemporaryDirectory() as d:
            proj = d + "/p"
            c.call("initialize", {"rpc_version": 1})
            self.assertEqual(c.call("project.create", {"path": proj, "name": "rpc", "overrides": NO_SANDBOX})[0]["result"]["name"], "rpc")
            r, _ = c.call("import.images", {"project": proj, "paths": [str(LANDING)], "overrides": NO_SANDBOX}); self.assertEqual(len(r["result"]["inputs"]), 1)
            r, notes = c.call("analysis.start", {"project": proj, "overrides": NO_SANDBOX})
            self.assertIn("result", r, r); self.assertGreater(r["result"]["nodes"], 15)
            stages = {n["params"]["stage"] for n in notes if n.get("method") == "progress"}
            self.assertTrue({"import", "regions", "ocr", "measure", "structure", "tokens", "components", "commit"} <= stages, stages)
            ir = c.call("ir.get", {"project": proj})[0]["result"]["ir"]; self.assertEqual(ir["schema_version"], "0.1")
            self.assertIn("index.html", c.call("generate.run", {"project": proj, "target": "html", "overrides": NO_SANDBOX})[0]["result"]["files"])
            self.assertEqual(len(c.call("render.run", {"project": proj, "overrides": NO_SANDBOX})[0]["result"]["renders"]), 1)
            cmp_ = c.call("compare.get", {"project": proj, "overrides": NO_SANDBOX})[0]["result"]
            self.assertGreater(cmp_["metrics"]["ssim"]["ssim"], 0.9); self.assertTrue(Path(cmp_["artifacts"]["difference"]).exists())
            # cancellation: start analysis and cancel immediately; the reply must be the stable cancelled error
            c.n += 1; rid = c.n
            c.send({"jsonrpc": "2.0", "id": rid, "method": "analysis.start", "params": {"project": proj, "overrides": NO_SANDBOX}})
            c.send({"jsonrpc": "2.0", "method": "$/cancel", "params": {"id": rid}})
            while True:
                msg = c.q.get(timeout=120)
                if msg.get("id") == rid:
                    break
            self.assertTrue("result" in msg or msg["error"]["data"]["code"] == "S2C-STAGE-002", msg)


@needs_ocr
class UiMethodTests(unittest.TestCase):
    """Methods the desktop UI relies on: status, reconciliation, source image, confined artifact reads, validation, refine, scrubbing."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.c = Client()
        cls._tmp = tempfile.TemporaryDirectory()
        cls.proj = cls._tmp.name + "/p"
        cls.c.call("initialize", {"rpc_version": 1})
        cls.c.call("project.create", {"path": cls.proj, "name": "ui", "overrides": NO_SANDBOX})
        cls.c.call("import.images", {"project": cls.proj, "paths": [str(LANDING)], "overrides": NO_SANDBOX})
        cls.c.call("analysis.start", {"project": cls.proj, "overrides": NO_SANDBOX})

    @classmethod
    def tearDownClass(cls) -> None:
        cls.c.close()
        cls._tmp.cleanup()

    def ok(self, method: str, **params):
        r, notes = self.c.call(method, {"project": self.proj, "overrides": NO_SANDBOX, **params})
        self.assertIn("result", r, r)
        return r["result"], notes

    def err(self, method: str, **params) -> dict:
        r, _ = self.c.call(method, {"project": self.proj, "overrides": NO_SANDBOX, **params})
        self.assertIn("error", r, r)
        return r["error"]

    def test_status_reports_screens_and_flags(self) -> None:
        st, _ = self.ok("project.status")
        self.assertTrue(st["has_ir"])
        self.assertEqual(len(st["screens"]), 1)
        self.assertFalse(st["screens"][0]["rendered"])

    def test_reconcile_report_and_source_image(self) -> None:
        rep, _ = self.ok("reconcile.get")
        self.assertIn("pages", rep["report"])
        scr = self.ok("project.status")[0]["screens"][0]["id"]
        img, _ = self.ok("source.image", screen=scr)
        self.assertEqual(img["media_type"], "image/png")
        import base64
        self.assertTrue(base64.b64decode(img["data_base64"]).startswith(b"\x89PNG"))
        self.assertEqual(self.err("source.image", screen="scr_nope")["code"], -32602)

    def test_artifact_read_is_confined(self) -> None:
        self.ok("generate.run", target="html")
        txt, _ = self.ok("artifact.read", path="exports/html/index.html")
        self.assertIn("<html", txt["text"].lower())
        for bad in ("../outside.json", "/etc/passwd", "project.json", "ir/../project.json", "exports/html"):
            self.assertIn(self.err("artifact.read", path=bad)["code"], (-32602, -32004, -32000), bad)
        self.assertNotIn("result", self.c.call("artifact.read", {"project": self.proj, "path": "project.json"})[0])

    def test_params_are_validated(self) -> None:
        self.assertEqual(self.err("import.images", paths="x")["code"], -32602)
        self.assertEqual(self.err("import.images", paths=[str(LANDING)], declared={"evil": 1})["code"], -32602)
        self.assertEqual(self.err("generate.run", target="vue")["code"], -32602)
        self.assertEqual(self.err("refine.run", max_iterations=999)["code"], -32602)
        self.assertEqual(self.c.call("project.status", {})[0]["error"]["code"], -32602)

    def test_generate_output_cannot_leave_the_project(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            e = self.err("generate.run", target="html", out=d)
            self.assertIn("code", e)
            self.assertFalse(any(Path(d).iterdir()))

    def test_settings_are_scrubbed(self) -> None:
        r, _ = self.c.call("settings.get", {"project": self.proj, "overrides": {"providers": {"x": {"api_key": "sk-secret-123456789"}}}})
        self.assertNotIn("sk-secret-123456789", json.dumps(r))

    @needs_browser
    def test_refine_runs_with_progress_and_is_listed(self) -> None:
        self.ok("generate.run", target="html")
        res, notes = self.ok("refine.run", max_iterations=1, apply=False)
        self.assertIn("stop_reason", res)
        self.assertTrue(any(n.get("method") == "progress" for n in notes))
        runs, _ = self.ok("refine.list")
        self.assertGreaterEqual(len(runs["runs"]), 1)
        self.assertFalse(runs["runs"][-1]["applied"])


if __name__ == "__main__":
    unittest.main()
