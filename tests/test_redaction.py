"""Optional auditable redaction (IR_SPEC section 16): text never enters the IR, evidence, names, generated code or ids; records and counted exclusions exist."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from screen2code.api import Project
from screen2code.ir import content_hash, validate

from .helpers import FIX, LANDING, NO_SANDBOX, needs_browser, needs_ocr

SITE = FIX / "site"
REDACT = {**NO_SANDBOX, "privacy": {"redact_text": True}}


def texts_of(ir: dict) -> set[str]:
    out = set()
    for n in ir["nodes"].values():
        if n["kind"] == "text":
            out.add(n["text"]["content"].get("value"))
        elif n["kind"] == "instance":
            out |= {v["value"] for v in n["instance"]["params"].values() if isinstance(v, dict) and isinstance(v.get("value"), str)}
    return {t for t in out if isinstance(t, str) and t}


@needs_ocr
class RedactionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._tmp = tempfile.TemporaryDirectory()
        d = Path(cls._tmp.name)
        cls.plain = Project.create(d / "plain.s2c", "r", NO_SANDBOX)
        cls.plain.import_images([LANDING], {})
        cls.plain.reconstruct()
        cls.red = Project.create(d / "red.s2c", "r", REDACT)
        cls.red.import_images([LANDING], {})
        cls.red.reconstruct()
        # whole recognized strings (and long words): short English words such as "plan" or "from" legitimately occur in schema keys and report boilerplate
        cls.secrets = {t.replace("\n", " ") for t in texts_of(cls.plain.ir) if len(t) >= 6} | {w for t in texts_of(cls.plain.ir) for w in t.split() if len(w) >= 8 and w.isalpha()}

    @classmethod
    def tearDownClass(cls) -> None:
        cls._tmp.cleanup()

    def test_default_is_off_and_nothing_is_recorded(self) -> None:
        ir = self.plain.ir
        self.assertEqual(ir["project"]["redaction"], {"mode": "off"})
        self.assertEqual(ir["redactions"], {})

    def test_redacted_ir_is_valid_and_records_every_text(self) -> None:
        ir = self.red.ir
        self.assertTrue(validate(ir, 3).ok)
        proj = ir["project"]["redaction"]
        self.assertEqual((proj["mode"], proj["stage"], proj["artifacts"], proj["keep_original_digest"]), ("on", "post_inference", "retained", False))
        text_nodes = [n for n in ir["nodes"].values() if n["kind"] == "text" and "value" in n["text"]["content"]]
        self.assertGreater(len(text_nodes), 3)
        for n in text_nodes:
            c = n["text"]["content"]
            self.assertEqual((c["status"], c["value"]), ("redacted", None))
            self.assertIn(c["redaction"], ir["redactions"])
            self.assertNotIn("name", n, "no name is derived from redacted text")
        # audit integrity: every record points at an existing node, and every redacted text value (node or instance parameter) has its record
        for rid, r in ir["redactions"].items():
            self.assertIn(r["target"]["ref"], ir["nodes"], rid)
        used = {n["text"]["content"]["redaction"] for n in text_nodes} | {v["redaction"] for n in ir["nodes"].values() if n["kind"] == "instance" for v in n["instance"]["params"].values() if isinstance(v, dict) and v.get("redaction")}
        self.assertEqual(used, set(ir["redactions"]))
        rec = next(iter(ir["redactions"].values()))
        self.assertEqual((rec["action"], rec["reason"], rec["rule_id"]), ("replace_text", "rule", "redact-all-text/1"))
        self.assertTrue(rec["scrubbed_paths"])

    def test_no_recognized_word_survives_anywhere_in_the_ir_or_exports(self) -> None:
        self.assertGreater(len(self.secrets), 3)
        blob = json.dumps(self.red.ir).lower()
        for f in (self.red.root / "ir").rglob("*.json"):
            blob += f.read_text(encoding="utf-8").lower()
        g = self.red.generate("html")
        for f in Path(g["out"]).rglob("*"):
            if f.is_file() and f.suffix in (".html", ".css", ".json", ".md"):
                blob += f.read_text(encoding="utf-8").lower()
        leaked = sorted(w for w in self.secrets if w.lower() in blob)
        self.assertEqual(leaked, [])

    def test_profile_hash_changes_comparability(self) -> None:
        a, b = self.plain.ir, self.red.ir
        self.assertNotEqual(content_hash(a), content_hash(b))
        self.assertNotEqual(a["inference_config"]["config_hash"], b["inference_config"]["config_hash"])
        self.assertEqual(b["inference_config"]["values"]["redaction.profile_hash"], b["project"]["redaction"]["profile_hash"])
        self.assertNotIn("redaction.profile_hash", a["inference_config"]["values"])

    def test_geometry_and_structure_are_preserved(self) -> None:
        # component inference may group differently once text no longer distinguishes elements, so compare what redaction must not change: measured regions
        rects = lambda ir: sorted((r["rect"]["x"], r["rect"]["y"], r["rect"]["w"], r["rect"]["h"]) for r in ir["regions"].values())  # noqa: E731
        self.assertEqual(rects(self.red.ir), rects(self.plain.ir))

    @needs_browser
    def test_evaluation_reports_redacted_regions_as_a_counted_exclusion(self) -> None:
        self.red.generate("html")
        scr = sorted(self.red.ir["screens"])[0]
        self.red.render("html", screen=scr)
        ev = self.red.evaluate(scr)
        ex = ev["exclusions"]
        self.assertGreater(len(ex["redacted_regions"]), 5)
        self.assertGreater(ex["excluded_area_fraction"], 0)

    def test_cli_flag_redacts(self) -> None:
        from click.testing import CliRunner

        from screen2code.cli.main import cli

        with tempfile.TemporaryDirectory() as d:
            proj = str(Path(d) / "c.s2c")
            for args in (["init", proj], ["import", proj, str(LANDING)], ["reconstruct", proj]):
                r = CliRunner().invoke(cli, ["--quiet", "--redact-text", *args])
                self.assertEqual(r.exit_code, 0, r.output)
            ir = Project.open(Path(proj)).ir
            self.assertEqual(ir["project"]["redaction"]["mode"], "on")

    def test_multi_page_project_with_redaction_stays_valid_and_leak_free(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            p = Project.create(Path(d) / "s.s2c", "s", REDACT)
            p.import_images([SITE / "home-1000.png"], {"page_hint": "home", "viewport_width": 1000})
            p.import_images([SITE / "home-480.png"], {"page_hint": "home", "viewport_width": 480})
            p.import_images([SITE / "contact-1000.png"], {"page_hint": "contact", "viewport_width": 1000})
            p.reconstruct()
            ir = p.ir
            self.assertTrue(validate(ir, 3).ok)
            self.assertEqual(len(ir["pages"]), 2)
            blob = json.dumps(ir).lower()
            for w in ("acme studio", "alpha plan", "beta plan", "gamma plan", "build faster", "copyright 2026"):
                self.assertNotIn(w, blob)


if __name__ == "__main__":
    unittest.main()
