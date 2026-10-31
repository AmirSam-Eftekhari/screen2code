"""Core tests: workspace confinement (security), storage, config, runner, models, logging."""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
import unittest
from pathlib import Path

from screen2code.core import (CancelToken, Context, Project, S2CError, Workspace, check_no_case_collisions, run_stages, sanitize_name)
from screen2code.core.config import load_config
from screen2code.core.log import JsonLog, scrub
from screen2code.core.models import ModelManifest, ModelStore
from screen2code.core.providers import Registry
from screen2code.core.runner import ProviderCache


class WorkspaceSecurityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.ws = Workspace(Path(self.tmp.name) / "proj"); self.ws.root.mkdir()

    def code(self, rel: str) -> str:
        with self.assertRaises(S2CError) as cm:
            self.ws.resolve(rel)
        return cm.exception.code

    def test_traversal_and_absolute_rejected(self) -> None:
        for bad in ("../x", "a/../../x", "/etc/passwd", "\\windows\\x", "C:/x", "C:x", "\\\\server\\share\\x", "a/../.."):
            self.assertIn(self.code(bad), ("S2C-PATH-001", "S2C-PATH-002"), bad)

    def test_forbidden_components(self) -> None:
        for bad in ("CON", "nul.txt", "a/PRN", "COM1.png", "file.", "file ", "a:b", "f\x00x", "a/./b", "", "x" * 300, "ads.txt:stream", "q?.png"):
            self.assertIn(self.code(bad), ("S2C-PATH-001", "S2C-PATH-002"), repr(bad))

    def test_valid_paths_resolve_inside(self) -> None:
        p = self.ws.resolve("a/b/c.txt")
        self.assertTrue(str(p).startswith(str(self.ws.root)))

    def test_symlink_escape_rejected(self) -> None:
        outside = Path(self.tmp.name) / "outside"; outside.mkdir()
        try:
            os.symlink(outside, self.ws.root / "link")
        except OSError:
            self.skipTest("symlinks unavailable")
        self.assertEqual(self.code("link/secret.txt"), "S2C-PATH-001")

    def test_atomic_write_no_overwrite_without_flag(self) -> None:
        self.ws.write_text("f.txt", "one")
        with self.assertRaises(S2CError) as cm:
            self.ws.write_text("f.txt", "two")
        self.assertEqual(cm.exception.code, "S2C-PATH-003")
        self.assertEqual(self.ws.read_bytes("f.txt"), b"one")
        self.ws.write_text("f.txt", "two", overwrite=True)
        self.assertEqual(self.ws.read_bytes("f.txt"), b"two")
        self.assertEqual([p.name for p in self.ws.root.iterdir() if p.name.startswith(".s2c-tmp")], [])

    def test_case_collisions(self) -> None:
        with self.assertRaises(S2CError):
            check_no_case_collisions(["Hero.png", "hero.PNG"])
        check_no_case_collisions(["a.png", "b.png"])

    def test_sanitize_name_never_returns_reserved_or_traversal(self) -> None:
        for raw in ("../../etc/passwd", "CON", "", "héllo wörld", "<script>"):
            n = sanitize_name(raw)
            self.assertNotIn("/", n); self.assertNotIn("..", n); self.assertNotIn(n.upper(), ("CON", ""))


class ProjectTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)

    def test_create_open_and_layout(self) -> None:
        p = Project.create(Path(self.tmp.name) / "p", 'My "quoted" project')
        self.assertEqual(Project.open(p.root).name, 'My "quoted" project')
        for d in ("ir", "assets", "artifacts", "cache", "runs"):
            self.assertTrue((p.root / d).is_dir())
        with self.assertRaises(S2CError):
            Project.create(p.root, "again")

    def test_open_rejects_non_project(self) -> None:
        with self.assertRaises(S2CError) as cm:
            Project.open(self.tmp.name)
        self.assertEqual(cm.exception.code, "S2C-PROJECT-002")

    def test_single_writer_lock_and_stale_recovery(self) -> None:
        p = Project.create(Path(self.tmp.name) / "p", "x")
        (p.root / ".lock").write_text(json.dumps({"pid": 4_000_000, "t": 0}))  # stale: no such pid
        with p:
            self.assertTrue((p.root / ".lock").exists())
        self.assertFalse((p.root / ".lock").exists())
        (p.root / ".lock").write_text(json.dumps({"pid": os.getppid(), "t": 0}))  # live foreign process
        with self.assertRaises(S2CError) as cm:
            p.acquire()
        self.assertEqual(cm.exception.code, "S2C-PROJECT-001")

    def test_artifact_store_is_content_addressed_and_detects_corruption(self) -> None:
        p = Project.create(Path(self.tmp.name) / "p", "x")
        k = p.artifacts.put(b"hello", ".bin")
        self.assertEqual(k, hashlib.sha256(b"hello").hexdigest())
        self.assertEqual(p.artifacts.get(k, ".bin"), b"hello")
        p.artifacts.path(k, ".bin").write_bytes(b"tampered")
        with self.assertRaises(S2CError):
            p.artifacts.get(k, ".bin")
        with self.assertRaises(S2CError):
            p.artifacts.path("../../etc/passwd")


class ConfigTests(unittest.TestCase):
    def test_layering_and_validation(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / "project.toml").write_text('[policy]\nasset_rights = "strict"\n[thresholds]\n"align.tolerance_px" = 3.0\n')
            cfg = load_config(root, overrides={"ocr": {"lang": "eng"}})
            self.assertEqual(cfg["policy"]["asset_rights"], "strict")
            self.assertEqual(cfg["policy"]["navigation"], "asserted_only")
            self.assertEqual(cfg["thresholds"]["align.tolerance_px"], 3.0)
            self.assertEqual(cfg["thresholds"]["component.min_support"], 2)
            (root / "project.toml").write_text('[policy]\nasset_rights = "bogus"\n')
            with self.assertRaises(S2CError):
                load_config(root)
            (root / "project.toml").write_text("not = [valid")
            with self.assertRaises(S2CError):
                load_config(root)


class RunnerTests(unittest.TestCase):
    class Ok:
        name, version = "ok", "1"
        def run(self, ctx, state): state["n"] = state.get("n", 0) + 1

    class Boom:
        name, version = "boom", "1"
        def run(self, ctx, state): raise ValueError("kaput")

    class Cancels:
        name, version = "c", "1"
        def run(self, ctx, state): ctx.cancel.cancel(); ctx.cancel.check()

    def test_events_timings_and_error_wrapping(self) -> None:
        evs = []
        ctx = Context(None, {}, listener=evs.append)
        state = run_stages([self.Ok(), self.Ok()], ctx, {})
        self.assertEqual(state["n"], 2)
        self.assertEqual([(e.stage, e.status) for e in evs], [("ok", "running"), ("ok", "done"), ("ok", "running"), ("ok", "done")])
        with self.assertRaises(S2CError) as cm:
            run_stages([self.Boom()], Context(None, {}), {})
        self.assertEqual(cm.exception.code, "S2C-STAGE-001"); self.assertIn("kaput", str(cm.exception))

    def test_cancellation_stops_pipeline(self) -> None:
        ctx = Context(None, {}); st = {}
        with self.assertRaises(S2CError) as cm:
            run_stages([self.Cancels(), self.Ok()], ctx, st)
        self.assertEqual(cm.exception.code, "S2C-STAGE-002"); self.assertNotIn("n", st)

    def test_provider_cache_roundtrip(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            c = ProviderCache(Project.create(Path(d) / "p", "x"))
            k = ProviderCache.key("ocr", "v1", "abc")
            self.assertIsNone(c.get(k)); c.put(k, {"words": [1]}); self.assertEqual(c.get(k), {"words": [1]})
            self.assertEqual((c.hits, c.misses), (1, 1))


class ProviderRegistryTests(unittest.TestCase):
    def test_no_silent_fallback(self) -> None:
        class Down:
            def available(self): return False, "not installed"
        r = Registry(); r.register("ocr", "a", Down)
        with self.assertRaises(S2CError) as cm:
            r.get("ocr", "a")
        self.assertEqual(cm.exception.code, "S2C-PROVIDER-001"); self.assertIn("not installed", str(cm.exception))
        with self.assertRaises(S2CError):
            r.get("ocr", "missing")


class ModelStoreTests(unittest.TestCase):
    def manifest(self, data: bytes, **kw) -> ModelManifest:
        d = dict(id="demo", version="1.0", source_url="file:///x", license_spdx="Apache-2.0", license_class="permissive",
                 sha256=hashlib.sha256(data).hexdigest(), size_bytes=len(data), format="onnx")
        d.update(kw); return ModelManifest.from_dict(d)

    def test_install_verify_remove_and_tamper_detection(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            src = Path(d) / "m.onnx"; src.write_bytes(b"weights"); store = ModelStore(Path(d) / "models")
            dest = store.install_from_file(self.manifest(b"weights"), src)
            self.assertTrue(store.verify("demo", "1.0")); self.assertEqual(len(store.list()), 1)
            dest.write_bytes(b"evil")
            with self.assertRaises(S2CError) as cm:
                store.verify("demo", "1.0")
            self.assertEqual(cm.exception.code, "S2C-MODEL-002")
            store.remove("demo", "1.0"); self.assertEqual(store.list(), [])

    def test_checksum_mismatch_stores_nothing(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            src = Path(d) / "m.onnx"; src.write_bytes(b"weights"); store = ModelStore(Path(d) / "models")
            with self.assertRaises(S2CError):
                store.install_from_file(self.manifest(b"other"), src)
            self.assertFalse((Path(d) / "models").exists() and any((Path(d) / "models").rglob("*.onnx")))

    def test_license_gate_and_incomplete_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            src = Path(d) / "m.bin"; src.write_bytes(b"w"); store = ModelStore(Path(d) / "models")
            m = self.manifest(b"w", license_spdx="AGPL-3.0-only", license_class="copyleft")
            with self.assertRaises(S2CError) as cm:
                store.install_from_file(m, src)
            self.assertEqual(cm.exception.code, "S2C-MODEL-003")
            store.install_from_file(m, src, accept_license=True)
            with self.assertRaises(S2CError):
                ModelManifest.from_dict({"id": "x", "version": "1"})
            with self.assertRaises(S2CError):
                store._dir("../evil", "1")


class LogTests(unittest.TestCase):
    def test_scrubs_secrets_and_content(self) -> None:
        s = scrub({"api_key_header": "Authorization: Bearer abc", "text": "private ocr", "msg": 'token="s3cr3t" ok', "n": {"image": b"x"}})
        self.assertNotIn("private ocr", json.dumps(s, default=str)); self.assertNotIn("s3cr3t", json.dumps(s, default=str))
        with tempfile.TemporaryDirectory() as d:
            log = JsonLog(Path(d) / "x.jsonl"); log.event("e", password="hunter2", n=1)
            rec = json.loads((Path(d) / "x.jsonl").read_text()); self.assertNotIn("hunter2", json.dumps(rec)); self.assertEqual(rec["n"], 1)


if __name__ == "__main__":
    unittest.main()
