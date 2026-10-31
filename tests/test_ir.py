"""IR tests: golden fixture, validation rules (one mutation per rule), canonical determinism, schema drift, migrations."""
from __future__ import annotations

import copy
import json
import re
import unittest
from pathlib import Path

from screen2code.ir import (MigrationError, canonical_dumps, content_hash, derive_id, json_schema, migrate, quality_report, schema_text, validate)

ROOT = Path(__file__).resolve().parent.parent
GOLDEN = ROOT / "tests" / "fixtures" / "golden" / "acme_home.ir.json"


def golden() -> dict:
    return json.loads(GOLDEN.read_text(encoding="utf-8"))


def codes(doc: dict, level: int = 3) -> set[str]:
    return {d.code for d in validate(doc, level).diagnostics if d.severity == "error"}


class GoldenTests(unittest.TestCase):
    def test_golden_validates_cleanly(self) -> None:
        rep = validate(golden())
        self.assertEqual([str(d) for d in rep.errors], [])
        self.assertEqual(rep.warnings, [])

    def test_golden_matches_spec_example(self) -> None:
        spec = (ROOT / "docs" / "IR_SPEC.md").read_text(encoding="utf-8")
        block = re.search(r"## 20\. Complete example.*?```json\n(.*?)\n```", spec, re.S)
        self.assertIsNotNone(block)
        self.assertEqual(json.loads(block.group(1)), golden())  # type: ignore[union-attr]

    def test_quality_report_reflects_example(self) -> None:
        q = quality_report(golden())
        self.assertEqual(q["uncertain_text"], 1)
        self.assertEqual(q["unknown_rights_assets"], ["ast_hero"])
        self.assertEqual(q["absolute_ratio"], 0)


class RuleTests(unittest.TestCase):
    """Each case breaks exactly one rule and expects that rule's diagnostic code."""

    def expect(self, code: str, mutate, level: int = 3) -> None:
        d = golden()
        mutate(d)
        self.assertIn(code, codes(d, level), msg=f"expected {code}")

    def test_l0_unknown_field(self) -> None:
        self.expect("S2C-IR-L0-UNKNOWN", lambda d: d["nodes"]["nd_root"].update(bogus=1))

    def test_l0_enum_and_range(self) -> None:
        self.expect("S2C-IR-L0-ENUM", lambda d: d["nodes"]["nd_root"].update(kind="div"))
        self.expect("S2C-IR-L0-RANGE", lambda d: d["nodes"]["nd_root"]["inference"]["structure"].update(confidence=1.5))

    def test_l0_absolute_requires_fallback(self) -> None:
        def m(d): d["nodes"]["nd_hero"]["layout"] = {"mode": "absolute", "absolute": {}}
        self.expect("S2C-IR-L0-REQUIRED", m)

    def test_l1_dangling_child_and_two_parents(self) -> None:
        self.expect("S2C-IR-L1-REF", lambda d: d["nodes"]["nd_root"]["children"].append("nd_missing"))
        self.expect("S2C-IR-L1-PARENT", lambda d: d["nodes"]["nd_hero"]["children"].append("nd_himg") or None)

    def test_l1_orphan_and_cycle_free_scope(self) -> None:
        def m(d):
            n = copy.deepcopy(d["nodes"]["nd_h1"]); n["id"] = "nd_orphan"; d["nodes"]["nd_orphan"] = n
        self.expect("S2C-IR-L1-ORPHAN", m)

    def test_l1_unknown_token_asset_component_evidence(self) -> None:
        self.expect("S2C-IR-L1-REF", lambda d: d["nodes"]["nd_root"]["spacing"]["padding"].update(all={"token": "tok_nope"}))
        self.expect("S2C-IR-L1-REF", lambda d: d["nodes"]["nd_himg"]["media"].update(asset="ast_nope"))
        self.expect("S2C-IR-L1-REF", lambda d: d["nodes"]["nd_c1"]["instance"].update(component="cmp_nope"))
        self.expect("S2C-IR-L1-REF", lambda d: d["nodes"]["nd_root"]["inference"]["layout"]["supports"].append("evd_nope"))

    def test_l1_component_cycle(self) -> None:
        def m(d):
            inst = copy.deepcopy(d["nodes"]["nd_c1"]); inst["id"] = "nd_self"; inst["scope"] = "cmp_card"
            inst["instance"]["params"] = {"title": {"value": "x", "status": "verified"}, "image": {"asset": "ast_card_ph"}}
            d["nodes"]["nd_self"] = inst; d["nodes"]["nd_card_root"]["children"].append("nd_self")
        self.expect("S2C-IR-L1-CYCLE", m)

    def test_l1_region_bounds(self) -> None:
        self.expect("S2C-IR-L1-BOUNDS", lambda d: d["regions"]["reg_d_root"]["rect"].update(w=99999))

    def test_epi1_observed_evidence_has_no_structure_vocabulary(self) -> None:
        self.expect("S2C-IR-R-EPI-1", lambda d: d["evidence"]["evd_1"]["measure"].update(node="nd_hero"))

    def test_epi2_no_pixel_rects_in_structure(self) -> None:
        self.expect("S2C-IR-R-EPI-2", lambda d: d["nodes"]["nd_hero"].update(extensions={"x": {"x": 1, "y": 2, "w": 3, "h": 4}}))

    def test_epi3_facet_records(self) -> None:
        self.expect("S2C-IR-R-EPI-3", lambda d: d["nodes"]["nd_hero"]["inference"].pop("layout"))
        self.expect("S2C-IR-R-EPI-3", lambda d: d["nodes"]["nd_hero"]["inference"]["layout"].update(supports=[]))
        self.expect("S2C-IR-R-EPI-3", lambda d: d["nodes"]["nd_h1"]["inference"]["layout"].update(supports=["evd_1"]))  # default must be empty

    def test_epi4_support_kind_compatibility(self) -> None:
        self.expect("S2C-IR-R-EPI-4", lambda d: d["nodes"]["nd_hero"]["inference"]["layout"].update(supports=["evd_6"]))  # text_reading cannot support layout

    def test_epi5_asserted_needs_user_assertion(self) -> None:
        self.expect("S2C-IR-R-EPI-5", lambda d: d["nodes"]["nd_hero"]["inference"]["layout"].update(calibration="asserted", basis="asserted", confidence=1))

    def test_epi8_derived_fields(self) -> None:
        self.expect("S2C-IR-R-EPI-8", lambda d: d["nodes"]["nd_c2"].update(status="resolved"))
        self.expect("S2C-IR-R-EPI-8", lambda d: d["pages"]["pg_home"]["breakpoints"]["bp_1"].update(known_interval=[100, 200]))
        self.expect("S2C-IR-R-EPI-8", lambda d: d["assets"]["ast_hero"]["hint"].update(aspect=2.0))

    def test_layout_rules(self) -> None:
        def flex_as_stack(d):
            lay = d["nodes"]["nd_hero"]["layout"]; lay["mode"] = "flex"; lay["flex"] = lay.pop("stack")
        self.expect("S2C-IR-L2-CANON", flex_as_stack)
        self.expect("S2C-IR-L2-PLACEMENT", lambda d: d["nodes"]["nd_himg"].update(placement={"grid": {"col": [1, 1], "row": [1, 1]}}))
        self.expect("S2C-IR-L2-LAYOUT", lambda d: d["nodes"]["nd_hero"]["layout"].update(grid={"columns": [{"kind": "share", "weight": 1}]}))
        def leaf(d):
            d["nodes"]["nd_hero"]["children"].remove("nd_himg"); d["nodes"]["nd_h1"]["children"] = ["nd_himg"]
        self.expect("S2C-IR-L2-LEAF", leaf)

    def test_grid_overlap_and_bounds(self) -> None:
        def m(d):
            for c in ("nd_c1", "nd_c2"):
                d["nodes"][c]["placement"] = {"grid": {"col": [1, 1], "row": [1, 1]}}
        self.expect("S2C-IR-L2-GRID", m)
        self.expect("S2C-IR-L2-GRID", lambda d: d["nodes"]["nd_c1"].update(placement={"grid": {"col": [3, 2], "row": [1, 1]}}))

    def test_responsive_patch_whitelist(self) -> None:
        self.expect("S2C-IR-L2-PATCH", lambda d: d["pages"]["pg_home"]["responsive"][0]["patch"].append({"op": "set", "path": "kind", "value": "text"}))

    def test_viewport_partition(self) -> None:
        self.expect("S2C-IR-L2-VIEWPORT", lambda d: d["pages"]["pg_home"]["viewport_classes"][0].update(min=5))
        self.expect("S2C-IR-L2-VIEWPORT", lambda d: d["pages"]["pg_home"]["breakpoints"]["bp_1"].update(selected=5000))

    def test_text_status_value(self) -> None:
        self.expect("S2C-IR-L2-TEXT", lambda d: d["nodes"]["nd_h1"]["text"]["content"].update(status="unreadable"))
        self.expect("S2C-IR-L2-REDACT", lambda d: d["nodes"]["nd_h1"]["text"]["content"].update(status="redacted", value=None))

    def test_mode_rules(self) -> None:
        self.expect("S2C-IR-L1-REF", lambda d: d["tokens"]["color"]["tok_bg"]["by_mode"].update(mode_x={"value": {}, "supports": ["evd_12"]}))
        self.expect("S2C-IR-L2-TOKEN", lambda d: d["tokens"]["color"]["tok_bg"].update(value={"space": "srgb", "hex": "#FFFFFF", "alpha": 1}))
        def swap(d): d["tokens"]["color"]["tok_bg"]["by_mode"]["mode_dark"]["supports"] = ["evd_12"]  # light evidence for the dark value
        self.expect("S2C-IR-R-MODE-2", swap)

    def test_realization_coverage(self) -> None:
        self.expect("S2C-IR-L2-REALIZE", lambda d: d["realizations"]["scr_m"]["nodes"].pop("nd_c3"))

    def test_navigation_cannot_be_promoted_silently(self) -> None:
        def rel(status, b="pg_home", cal="heuristic", basis="evidence", sup=("evd_4",)):
            return {"id": "rel_n1", "kind": "navigates_to", "a": "nd_h1", "b": b, "status": status,
                    "inference": {"method": "nav.infer/1", "calibration": cal, "basis": basis, "confidence": 0.5, "supports": list(sup)}}
        self.expect("S2C-IR-R-NAV", lambda d: d["relations"].append(rel("evidenced")))                 # no navigation_cue evidence
        self.expect("S2C-IR-R-NAV", lambda d: d["relations"].append(rel("user_asserted")))              # no user_assertion evidence
        self.expect("S2C-IR-R-NAV", lambda d: d["relations"].append(rel("unknown")))                    # unknown must have no target
        self.expect("S2C-IR-R-NAV", lambda d: d["relations"].append(rel("inferred", cal="asserted", basis="asserted", sup=("evd_4",))))
        d = golden(); d["relations"].append(rel("inferred"))
        self.assertEqual(codes(d), set(), "a well-formed inferred navigation relation is valid")

    def test_asset_provenance_and_rights(self) -> None:
        self.expect("S2C-IR-L2-ASSET", lambda d: d["assets"]["ast_card_ph"].update(content={"ref": "blob:sha256:x", "media_type": "image/png"}))
        self.expect("S2C-IR-L2-ASSET", lambda d: d["assets"]["ast_hero"]["origin"].update(lossy=False))
        self.expect("S2C-IR-L2-RIGHTS", lambda d: d["assets"]["ast_hero"].update(rights_status="user_declared"))
        self.expect("S2C-IR-L2-RIGHTS", lambda d: d["assets"]["ast_hero"].update(rights_status="not_applicable"))

    def test_redaction_off_means_no_redaction_records(self) -> None:
        self.expect("S2C-IR-L2-REDACT", lambda d: d["redactions"].update(rdc_1={"id": "rdc_1", "stage": "post_inference", "target": {"kind": "text"}, "action": "mask",
                                                                                "reason": "user", "producer": "prd_seg", "scrubbed_paths": []}))


class CanonicalTests(unittest.TestCase):
    def test_canonical_is_order_independent_and_stable(self) -> None:
        a = {"b": 1, "a": [1.0, 2.5, {"z": 0.1 + 0.2, "y": None}]}
        b = {"a": [1, 2.5, {"y": None, "z": 0.3}], "b": 1}
        self.assertEqual(canonical_dumps(a), canonical_dumps(b))
        self.assertEqual(canonical_dumps(a), '{"a":[1,2.5,{"y":null,"z":0.3}],"b":1}')

    def test_nan_rejected(self) -> None:
        with self.assertRaises(ValueError):
            canonical_dumps({"a": float("nan")})

    def test_content_hash_ignores_meta_only(self) -> None:
        d = golden(); h = content_hash(d)
        d["meta"]["created_at"] = "2030-01-01T00:00:00Z"
        self.assertEqual(h, content_hash(d))
        d["project"]["name"] = "Other"
        self.assertNotEqual(h, content_hash(d))

    def test_derive_id_deterministic(self) -> None:
        self.assertEqual(derive_id("nd", "a", 1), derive_id("nd", "a", 1))
        self.assertNotEqual(derive_id("nd", "a", 1), derive_id("nd", "a", 2))
        self.assertRegex(derive_id("nd", "x"), r"^nd_[a-z2-7]{16}$")

    def test_golden_roundtrip_hash_stable(self) -> None:
        d = golden()
        again = json.loads(canonical_dumps(d))
        self.assertEqual(content_hash(d), content_hash(again))


class SchemaTests(unittest.TestCase):
    def test_committed_schema_matches_shapes(self) -> None:
        committed = (ROOT / "schema" / "ir-0.1.schema.json").read_text(encoding="utf-8")
        self.assertEqual(committed, schema_text(), "schema drift: run `python -m screen2code.ir.schema > schema/ir-0.1.schema.json`")

    def test_schema_is_valid_json_with_draft(self) -> None:
        s = json_schema()
        self.assertEqual(s["$schema"], "https://json-schema.org/draft/2020-12/schema")
        self.assertIn("nodes", s["properties"])


class MigrationTests(unittest.TestCase):
    def test_same_version_is_identity_copy(self) -> None:
        d = golden(); out, chain = migrate(d)
        self.assertEqual(out, d); self.assertIsNot(out, d); self.assertEqual(chain, ["0.1"])

    def test_chain_applies_and_records_lineage(self) -> None:
        def m0(doc):
            doc = copy.deepcopy(doc); doc["schema_version"] = "0.1"; return doc
        d = golden(); d["schema_version"] = "0.0"
        out, chain = migrate(d, registry={"0.0": ("0.1", m0)})
        self.assertEqual(chain, ["0.0", "0.1"]); self.assertEqual(out["lineage"]["migrated_from"], ["0.0"])
        self.assertEqual(d["schema_version"], "0.0", "input must not be mutated")

    def test_unknown_version_and_bad_migration_fail(self) -> None:
        d = golden(); d["schema_version"] = "9.9"
        with self.assertRaises(MigrationError):
            migrate(d)
        d["schema_version"] = "0.0"
        with self.assertRaises(MigrationError):
            migrate(d, registry={"0.0": ("0.1", lambda x: x)})  # forgot to bump the version


if __name__ == "__main__":
    unittest.main()
