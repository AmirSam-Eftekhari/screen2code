"""Multi-screen reconstruction: explicit page declaration, responsive unification, honest fallback, shared tokens/components, determinism, rendering.

Fixtures are authored by this project (tests/fixtures/site): Home (responsive, 1000 + 480), Products (shares header/footer/cards, one deliberately different
button colour and a similar-but-different "featured" card), Contact (unrelated).
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from screen2code.api import Project
from screen2code.ir import content_hash, validate
from screen2code.reconstruction import reconcile as R

from .helpers import FIX, NO_SANDBOX, needs_browser, needs_ocr

SITE = FIX / "site"


def build_site(tmp: Path, name: str) -> Project:
    p = Project.create(tmp / f"{name}.s2c", name, NO_SANDBOX)
    p.import_images([SITE / "home-1000.png"], {"page_hint": "home", "viewport_width": 1000})
    p.import_images([SITE / "home-480.png"], {"page_hint": "home", "viewport_width": 480})
    p.import_images([SITE / "products-1000.png"], {"page_hint": "products", "viewport_width": 1000})
    p.import_images([SITE / "contact-1000.png"], {"page_hint": "contact", "viewport_width": 1000})
    p.reconstruct()
    return p


@needs_ocr
class SiteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._tmp = tempfile.TemporaryDirectory()
        cls.tmp = Path(cls._tmp.name)
        cls.p = build_site(cls.tmp, "site")
        cls.ir = cls.p.ir
        cls.rep = json.loads((cls.p.root / "ir" / "reconciliation.json").read_text(encoding="utf-8"))
        cls.page = {pg["name"]: (pid, pg) for pid, pg in cls.ir["pages"].items()}

    @classmethod
    def tearDownClass(cls) -> None:
        cls._tmp.cleanup()

    def page_texts(self, pid: str) -> set[str]:
        """Visible text of a page: text nodes plus the parameters of component instances (their texts live in the instance)."""
        out = {n["text"]["content"]["value"] for n in self.ir["nodes"].values() if n["kind"] == "text" and n["scope"] == pid}
        for n in self.ir["nodes"].values():
            if n["kind"] == "instance" and n["scope"] == pid:
                out |= {v["value"] for v in n["instance"]["params"].values()}
        return out

    # -- unification of the responsive pair
    def test_responsive_pair_becomes_one_page_with_two_screens(self) -> None:
        self.assertEqual(sorted(self.page), ["contact", "home", "products"])
        home_id, home = self.page["home"]
        widths = sorted(s["resolved"]["viewport_width"] for s in self.ir["screens"].values() if s["resolved"]["page"] == home_id)
        self.assertEqual(widths, [480.0, 1000.0])
        self.assertEqual(len(home["viewport_classes"]), 2)
        group = next(g for g in self.rep["pages"]["groups"] if g["page"] == "home")
        self.assertEqual(group["decision"], "unified")
        self.assertGreaterEqual(group["unified"][0]["confidence"], 0.7)
        self.assertEqual(self.ir["relations"], [], "unified screens are one page: no 'possible variant' relation is needed")
        self.assertTrue(validate(self.ir, 3).ok)

    def test_breakpoint_is_an_interval_with_a_basis_never_observed(self) -> None:
        _, home = self.page["home"]
        (bp,) = home["breakpoints"].values()
        self.assertEqual(bp["known_interval"], [480, 1000])
        self.assertEqual(bp["basis"], "convention_snap")
        self.assertTrue(480 < bp["selected"] <= 1000)
        self.assertNotIn("measured", json.dumps(bp["inference"]["basis"]))

    def test_responsive_patches_are_whitelisted_and_cover_the_grid_to_one_column_change(self) -> None:
        _, home = self.page["home"]
        self.assertGreaterEqual(len(home["responsive"]), 3)
        ops = {op["op"] for rs in home["responsive"] for op in rs["patch"]}
        self.assertLessEqual(ops, {"set", "hide"})
        cols = [op for rs in home["responsive"] for op in rs["patch"] if op.get("path") == "layout.grid.columns"]
        self.assertEqual(cols[0]["value"], [{"kind": "share", "weight": 1}])
        # the folded wrapper is explicit inferred structure, not a measured claim
        grid = self.ir["nodes"][next(rs["target"] for rs in home["responsive"] if any(o.get("path") == "layout.grid.columns" for o in rs["patch"]))]
        self.assertEqual(grid["layout"]["mode"], "grid")

    def test_unified_page_keeps_every_text_of_both_screens(self) -> None:
        texts = self.page_texts(self.page["home"][0])
        for t in ("Acme Studio", "Build faster", "Alpha plan", "Beta plan", "Gamma plan", "Copyright 2026 Acme Studio"):
            self.assertIn(t, texts)

    # -- other pages stay separate and keep their own content
    def test_unrelated_contact_page_is_not_merged_and_keeps_its_content(self) -> None:
        cid, contact = self.page["contact"]
        self.assertEqual(len(contact["viewport_classes"]), 1)
        self.assertEqual(contact["responsive"], [])
        self.assertFalse(self.page_texts(cid) & {"Alpha plan", "Beta plan", "Gamma plan", "Add to cart"})
        inst = [n for n in self.ir["nodes"].values() if n["kind"] == "instance" and n["scope"] == cid]
        self.assertEqual(inst, [], "nothing on the unrelated page is claimed as a shared component")

    def test_per_page_differences_are_preserved(self) -> None:
        self.assertIn("Add to cart", self.page_texts(self.page["products"][0]))
        self.assertNotIn("Add to cart", self.page_texts(self.page["home"][0]))

    # -- tokens and components across pages
    def test_tokens_are_shared_across_pages(self) -> None:
        pages = {pid: name for name, (pid, _) in self.page.items()}
        shared = [c for c in self.rep["tokens"]["color_clusters"] if {pages[s] for s in c["scopes"]} >= {"home", "products"}]
        self.assertGreaterEqual(len(shared), 2, "colours used on both Home and Products are bound to one token each")
        self.assertTrue(any(c["value"] == "#1A1A2E" for c in shared))

    def test_deliberate_inconsistency_is_reported_not_hidden(self) -> None:
        near = [c for c in self.rep["tokens"]["color_clusters"] if {"#3060EA", "#2F5BEA"} <= set(c["members"])]
        self.assertEqual(len(near), 1, "the two blues are clustered AND both observed values are listed")
        self.assertGreater(near[0]["max_delta_e2000"], 0)
        # token binding does not erase the observations: both literals remain in measured evidence
        observed = {cl["hex"] for e in self.ir["evidence"].values() if e["kind"] == "color_sample" for cl in e["measure"]["clusters"]}
        self.assertTrue({"#3060EA", "#2F5BEA"} <= observed)

    def test_featured_card_is_similar_but_not_merged(self) -> None:
        near = self.rep["components"]["near_misses"]
        self.assertTrue(any(m["structure_equal"] and "not merged" in m["decision"] for m in near), "a structurally equal but differently styled card is reported as a near miss")
        pid, _ = self.page["products"]
        by_comp: dict[str, list[str]] = {}
        for n in self.ir["nodes"].values():
            if n["kind"] == "instance" and n["scope"] == pid:
                by_comp.setdefault(n["instance"]["component"], []).append(n["id"])
        self.assertTrue(by_comp, "plain Products cards are component instances")
        counts = sorted(len(v) for v in by_comp.values())
        self.assertEqual(counts[-1], 2, "the featured card is not folded into the two plain cards")

    def test_responsive_subtrees_are_not_componentized_and_the_report_says_why(self) -> None:
        skipped = self.rep["components"]["skipped_responsive"]
        self.assertTrue(skipped)
        self.assertTrue(all(s["page"] == "home" and "responsive" in s["reason"] for s in skipped))

    def test_deterministic_output(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            again = build_site(Path(d), "site")
            self.assertEqual(content_hash(again.ir), content_hash(self.ir))
            self.assertEqual(again.ir["pages"].keys(), self.ir["pages"].keys())

    # -- generation and rendering
    def test_generated_html_has_a_media_query_derived_from_the_breakpoint(self) -> None:
        out = self.tmp / "gen"
        g = self.p.generate("html", out)
        css = (Path(g["out"]) / "styles.css").read_text(encoding="utf-8")
        _, home = self.page["home"]
        (bp,) = home["breakpoints"].values()
        queries = [ln for ln in css.splitlines() if ln.startswith("@media")]
        self.assertEqual(len(queries), 1)
        self.assertIn(f"max-width: {bp['selected'] - 0.02}px", queries[0])
        self.assertEqual(g["report"].get("deviations", []), [])

    @needs_browser
    def test_unified_home_renders_sensibly_at_both_widths(self) -> None:
        self.p.generate("html")
        home_id, _ = self.page["home"]
        got = {}
        for scr, s in self.ir["screens"].items():
            if s["resolved"]["page"] != home_id:
                continue
            self.p.render("html", screen=scr)
            m = self.p.evaluate(scr)["metrics"]
            got[int(s["resolved"]["viewport_width"])] = m["composite"]["composite"]
            self.assertGreater(m["ssim"]["ssim"], 0.8)
        self.assertEqual(sorted(got), [480, 1000])
        # measured here: 0.905 (480) and 0.933 (1000); the floor leaves room for platform font differences
        self.assertGreater(got[480], 0.85)
        self.assertGreater(got[1000], 0.88)


@needs_ocr
class FallbackTests(unittest.TestCase):
    def test_unrelated_screens_declared_as_one_page_stay_separate_with_reasons(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            p = Project.create(Path(d) / "fb.s2c", "fb", NO_SANDBOX)
            p.import_images([SITE / "home-1000.png"], {"page_hint": "home", "viewport_width": 1000})
            p.import_images([SITE / "contact-1000.png"], {"page_hint": "home", "viewport_width": 500})
            p.reconstruct()
            rep = json.loads((p.root / "ir" / "reconciliation.json").read_text(encoding="utf-8"))
            (group,) = rep["pages"]["groups"]
            self.assertEqual(group["decision"], "separate")
            reasons = " ".join(group["separate"][0]["reasons"])
            self.assertIn("below", reasons)
            self.assertIn("absent from the base screen", reasons)
            ir = p.ir
            self.assertEqual(len(ir["pages"]), 2)
            self.assertEqual([r["kind"] for r in ir["relations"]], ["possible_responsive_variant_of"])
            self.assertLess(ir["relations"][0]["inference"]["confidence"], 0.5)

    def test_same_width_screens_are_never_treated_as_responsive_variants(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            p = Project.create(Path(d) / "sw.s2c", "sw", NO_SANDBOX)
            p.import_images([SITE / "home-1000.png"], {"page_hint": "home", "viewport_width": 1000})
            p.import_images([SITE / "products-1000.png"], {"page_hint": "home", "viewport_width": 1000})
            p.reconstruct()
            rep = json.loads((p.root / "ir" / "reconciliation.json").read_text(encoding="utf-8"))
            self.assertIn("same viewport width", rep["pages"]["groups"][0]["separate"][0]["reason"])
            self.assertEqual(len(p.ir["pages"]), 2)


class MatcherUnitTests(unittest.TestCase):
    def doc(self, nested: bool) -> dict:
        def text(i: str, v: str) -> dict:
            return {"id": i, "kind": "text", "scope": "pg", "text": {"content": {"value": v}}}

        def box(i: str, kids: list[str], layout: dict) -> dict:
            return {"id": i, "kind": "box", "scope": "pg", "children": kids, "layout": layout}

        grid = {"mode": "grid", "grid": {"columns": [{"kind": "share", "weight": 1}] * 2}}
        stack = {"mode": "stack", "stack": {"axis": "vertical"}}
        nodes = {"t1": text("t1", "alpha"), "t2": text("t2", "beta")}
        if nested:
            nodes.update(c1=box("c1", ["t1"], stack), c2=box("c2", ["t2"], stack), g=box("g", ["c1", "c2"], grid), root=box("root", ["g"], stack))
        else:
            nodes.update(c1=box("c1", ["t1"], stack), c2=box("c2", ["t2"], stack), root=box("root", ["c1", "c2"], stack))
        return {"pages": {"pg": {"root": "root"}}, "nodes": nodes, "screens": {"s": {"resolved": {"viewport_width": 1000 if nested else 480}}},
                "regions": {}, "realizations": {"s": {"nodes": {}}}}

    def test_a_wrapper_folds_onto_a_run_of_siblings_with_an_explicit_synthetic_group(self) -> None:
        a, b = self.doc(True), self.doc(False)
        c = R.correspond(a, b)
        self.assertEqual(c["confidence"], 1.0)
        self.assertEqual(len(c["folds"]), 1)
        wrapper = c["other"]["nodes"][c["mapping"]["g"]]
        self.assertEqual(wrapper["children"], ["c1", "c2"])
        self.assertEqual(wrapper["layout"]["mode"], "grid")
        self.assertEqual(c["other"]["nodes"]["root"]["children"], [c["mapping"]["g"]])
        self.assertEqual(b["nodes"]["root"]["children"], ["c1", "c2"], "the input document is not modified")

    def test_no_fold_when_a_child_has_no_counterpart(self) -> None:
        a, b = self.doc(True), self.doc(False)
        b["nodes"]["t2"]["text"]["content"]["value"] = "something else entirely"
        c = R.correspond(a, b)
        self.assertEqual(c["folds"], [])
        self.assertLess(c["confidence"], 1.0)


if __name__ == "__main__":
    unittest.main()
