"""The IR 0.1 shapes. Single source of truth for L0 validation and the committed JSON Schema."""
from __future__ import annotations

import json
import sys
from typing import Any

from . import vocab as V
from .shapes import Any_, Arr, Bool, Const, MapOf, Null, Num, Obj, OneOf, Shape, Str

ID = Str(r"^[a-z]+_[a-z0-9_]+$")


def _idp(prefix: str) -> Str:
    return Str(rf"^{prefix}_[a-z0-9_]+$")


def _key(prefix: str) -> str:
    return rf"^{prefix}_[a-z0-9_]+$"


Dim = OneOf(Obj({"px": Num()}, ["px"]), Obj({"token": ID}, ["token"]))
ColorValue = Obj({"space": Const("srgb"), "hex": Str(r"^#[0-9A-F]{6}$"), "alpha": Num(0, 1)}, ["space", "hex", "alpha"])
ColorRef = OneOf(Obj({"token": ID}, ["token"]), Obj({"literal": ColorValue}, ["literal"]))
EnumStr = lambda vals: Str(enum=tuple(vals))  # noqa: E731

InferenceRecord = Obj(
    {
        "method": Str(r"^[a-z0-9_.]+/[0-9]+$"),
        "calibration": EnumStr(V.CALIBRATION),
        "basis": EnumStr(V.BASIS),
        "confidence": Num(0, 1),
        "supports": Arr(ID),
        "against": Arr(ID),
    },
    ["method", "calibration", "basis", "confidence", "supports"],
)

Region = Obj(
    {
        "id": _idp("reg"), "source": _idp("src"),
        "rect": Obj({"x": Num(0, integer=True), "y": Num(0, integer=True), "w": Num(1, integer=True), "h": Num(1, integer=True)}, ["x", "y", "w", "h"]),
        "basis": EnumStr(["measured", "reported"]), "producer": _idp("prd"), "redacted": _idp("rdc"),
    },
    ["id", "source", "rect", "basis", "producer"],
)
Evidence = Obj(
    {
        "id": _idp("evd"), "kind": EnumStr(V.EVIDENCE_KINDS), "basis": EnumStr(V.EVIDENCE_BASIS),
        "producer": _idp("prd"), "regions": Arr(_idp("reg")), "measure": Obj({}, extra=True),
    },
    ["id", "kind", "basis", "producer", "regions", "measure"],
)
Source = Obj(
    {
        "id": _idp("src"), "media_type": EnumStr(["image/png", "image/jpeg", "image/webp"]), "sha256": Str(min_length=1),
        "pixel_size": Obj({"w": Num(1, integer=True), "h": Num(1, integer=True)}, ["w", "h"]),
        "declared": Obj({"device_pixel_ratio": Num(0.5, 8), "viewport_width": Num(1), "mode": ID, "state": ID, "page_hint": Str()}),
        "redaction": Obj({"applied": Bool(), "redaction_ids": Arr(_idp("rdc"))}, ["applied"]),
    },
    ["id", "media_type", "sha256", "pixel_size"],
)
Screen = Obj(
    {
        "id": _idp("scr"), "source": _idp("src"),
        "resolved": Obj({"page": _idp("pg"), "viewport_width": Num(1), "scale": Num(0.5, 8), "viewport_class": _idp("vc"), "mode": _idp("mode"), "state": ID},
                        ["page", "viewport_width", "scale", "viewport_class", "mode"]),
        "origin": MapOf(EnumStr(V.ORIGIN)), "inference": InferenceRecord,
    },
    ["id", "source", "resolved", "origin", "inference"],
)
Mode = Obj({"id": _idp("mode"), "name": Str(), "kind": EnumStr(V.MODE_KINDS), "inference": InferenceRecord}, ["id", "name", "kind", "inference"])

PatchOp = Obj({"op": EnumStr(["set", "hide", "reorder", "swap_variant"]), "path": Str(), "value": Any_()}, ["op"])
Page = Obj(
    {
        "id": _idp("pg"), "name": Str(), "name_source": EnumStr(["inferred", "user"]), "root": _idp("nd"),
        "viewport_classes": Arr(Obj({"id": _idp("vc"), "min": OneOf(Num(0), Str()), "max_exclusive": OneOf(Num(), Str(), Null())}, ["id", "min", "max_exclusive"]), 1),
        "breakpoints": MapOf(Obj({"known_interval": Arr(Num(), 2, 2), "selected": Num(), "basis": EnumStr(V.BREAKPOINT_BASIS), "inference": InferenceRecord},
                                 ["known_interval", "selected", "basis", "inference"]), _key("bp")),
        "base_class": _idp("vc"), "base_basis": _idp("scr"),
        "responsive": Arr(Obj({"id": _idp("rs"), "target": _idp("nd"), "when": Arr(_idp("vc")), "patch": Arr(PatchOp, 1), "inference": InferenceRecord},
                              ["id", "target", "when", "patch", "inference"])),
        "states": Arr(Obj({"id": ID, "name": Str()}, ["id"])),
        "constraints": Arr(Obj({"id": ID, "kind": EnumStr(["align", "same_size", "same_spacing", "aspect"]), "nodes": Arr(_idp("nd")),
                                "axis": Str(), "edge": Str(), "tolerance_px": Num(0), "inference": InferenceRecord}, ["id", "kind", "nodes", "inference"])),
        "completeness": Obj({"state": EnumStr(["complete", "partial"])}, ["state"]),
    },
    ["id", "name", "name_source", "root", "viewport_classes", "base_class", "responsive", "states", "completeness"],
)

Track = Obj({"kind": EnumStr(V.TRACK_KINDS), "px": Num(0), "weight": Num(0), "min": Dim, "max": Dim}, ["kind"])
StackLayout = Obj({"axis": EnumStr(["horizontal", "vertical"]), "gap": Dim, "align": EnumStr(V.ALIGN), "distribute": EnumStr(V.DISTRIBUTE)}, ["axis"])
FlexLayout = Obj({**StackLayout.props, "wrap": Bool(), "row_gap": Dim}, ["axis"])
Layout = Obj(
    {
        "mode": EnumStr(V.LAYOUT_MODES), "stack": StackLayout, "flex": FlexLayout,
        "grid": Obj({"columns": Arr(Track, 1), "rows": Arr(Track), "gap": Obj({"row": Dim, "col": Dim}), "flow": EnumStr(["row", "column"]),
                     "align_items": EnumStr(V.ALIGN), "justify_items": EnumStr(V.ALIGN)}, ["columns"]),
        "overlay": Obj({"reason": EnumStr(V.OVERLAY_REASONS)}, ["reason"]),
        "absolute": Obj({"fallback": Obj({"reason": EnumStr(V.ABSOLUTE_REASONS), "supports": Arr(ID)}, ["reason", "supports"])}, ["fallback"]),
    },
    ["mode"],
)
Size1D = Obj({"kind": EnumStr(V.SIZE_KINDS), "px": Num(0), "portion": Num(0), "min": Dim, "max": Dim}, ["kind"])
Insets = Obj({"all": Dim, "top": Dim, "right": Dim, "bottom": Dim, "left": Dim})
Placement = Obj(
    {
        "grid": Obj({"col": Arr(Num(1, integer=True), 2, 2), "row": Arr(Num(1, integer=True), 2, 2)}),
        "flex": Obj({"grow": Num(0), "shrink": Num(0), "basis": OneOf(Dim, Str(enum=("hug",)))}),
        "overlay": Obj({"base": Bool(), "anchor": Obj({"ref": Str(), "h": EnumStr(["start", "center", "end"]), "v": EnumStr(["start", "center", "end"]), "inside": Bool()}),
                        "offset": Obj({"x": Dim, "y": Dim}), "z": Num(integer=True)}),
        "absolute": Obj({"left": Dim, "top": Dim, "right": Dim, "bottom": Dim}),
    }
)
Fill = OneOf(
    Obj({"kind": Const("none")}, ["kind"]),
    Obj({"kind": Const("solid"), "color": ColorRef}, ["kind", "color"]),
    Obj({"kind": Const("gradient"), "type": EnumStr(["linear", "radial"]), "angle": Num(), "estimated": Bool(),
         "stops": Arr(Obj({"pos": Num(0, 1), "color": ColorRef}, ["pos", "color"]), 2)}, ["kind", "type", "stops", "estimated"]),
    Obj({"kind": Const("image"), "asset": ID, "fit": EnumStr(V.FILL_FIT), "position": Str()}, ["kind", "asset", "fit"]),
)
Side = Obj({"width": Dim, "style": EnumStr(["solid", "dashed", "dotted"]), "color": ColorRef}, ["width", "style", "color"])
Style = Obj(
    {
        "fill": Fill,
        "border": Obj({"sides": Obj({"all": Side, "top": Side, "right": Side, "bottom": Side, "left": Side})}, ["sides"]),
        "radius": Obj({"all": Dim, "tl": Dim, "tr": Dim, "br": Dim, "bl": Dim, "pill": Bool()}),
        "shadows": Arr(Obj({"x": Dim, "y": Dim, "blur": Dim, "spread": Dim, "color": ColorRef, "inset": Bool(), "estimated": Const(True)}, ["x", "y", "blur", "color", "estimated"])),
        "opacity": Num(0, 1), "clip": EnumStr(V.CLIP),
    }
)
TypeStyle = Obj(
    {
        "family": Obj({"generic": EnumStr(["sans", "serif", "mono", "display", "unknown"]), "candidates": Arr(Str()), "status": EnumStr(["guessed", "matched"])}, ["generic", "status"]),
        "size": Dim, "weight": Num(100, 900, integer=True), "italic": Bool(),
        "line_height": OneOf(Obj({"ratio": Num(0)}, ["ratio"]), Obj({"px": Num(0)}, ["px"])),
        "letter_spacing": Obj({"size_ratio": Num()}, ["size_ratio"]), "align": EnumStr(["left", "center", "right", "justify"]),
        "transform": EnumStr(["none", "uppercase", "lowercase", "capitalize"]), "decoration": EnumStr(["none", "underline", "line-through"]), "color": ColorRef,
    },
    ["family", "size", "weight"],
)
TextValue = Obj(
    {
        "value": OneOf(Str(), Null()), "status": EnumStr(V.TEXT_STATUS),
        "alternatives": Arr(Obj({"value": Str(), "confidence": Num(0, 1), "supports": Arr(ID)}, ["value", "confidence", "supports"]), 0, 3),
        "replacement": Obj({"kind": Const("class_label"), "label": Str()}, ["kind", "label"]), "redaction": _idp("rdc"),
    },
    ["value", "status"],
)
Param = Obj({"param": Str(min_length=1)}, ["param"])
TextShape = Obj(
    {
        "content": OneOf(TextValue, Param),
        "runs": Arr(Obj({"range": Arr(Num(0, integer=True), 2, 2), "style_overrides": Obj({}, extra=True), "link": Bool()}, ["range"])),
        "style": OneOf(Obj({"token": ID, "overrides": Obj({}, extra=True)}, ["token"]), TypeStyle),
        "heading_level": Num(1, 6, integer=True), "lang": Str(), "dir": EnumStr(["ltr", "rtl"]),
        "truncation": Obj({"mode": EnumStr(["wrap", "ellipsis"]), "max_lines": Num(1, integer=True)}, ["mode"]),
    },
    ["content", "style"],
)
Facets = Obj({f: InferenceRecord for f in ("structure", "role", "layout", "style", "content")}, ["structure"])
Node = Obj(
    {
        "id": _idp("nd"), "kind": EnumStr(V.NODE_KINDS), "role": EnumStr(V.ROLES), "name": Str(), "name_source": EnumStr(["inferred", "user"]),
        "scope": ID, "children": Arr(_idp("nd")), "layout": Layout, "size": Obj({"w": Size1D, "h": Size1D, "aspect": Num(0)}),
        "spacing": Obj({"padding": Insets, "margin": Insets}), "placement": Placement,
        "repeat": Obj({"component": _idp("cmp"), "count": Num(0, integer=True), "count_semantics": EnumStr(["fixed", "dynamic", "unknown"])}, ["component", "count", "count_semantics"]),
        "style": Style, "text": TextShape,
        "media": Obj({"asset": OneOf(_idp("ast"), Param), "fit": EnumStr(V.FILL_FIT)}, ["asset"]),
        "instance": Obj({"component": _idp("cmp"), "variant": MapOf(Str()), "params": MapOf(Any_()), "slot_content": MapOf(Arr(_idp("nd"))),
                         "overrides": Arr(Obj({"target": ID, "path": Str(), "value": Any_(), "reason": Str()}, ["target", "path"]))}, ["component"]),
        "opaque": Obj({"asset": _idp("ast")}, ["asset"]),
        "affordance": Obj({"kind": EnumStr(["clickable", "editable", "toggle", "scrollable", "none"]), "purpose": EnumStr(["navigation_like", "action_like", "unknown"])}, ["kind"]),
        "presence": Arr(ID), "status": EnumStr(V.STATUS), "inference": Facets, "extensions": Obj({}, extra=True),
    },
    ["id", "kind", "scope", "status", "inference"],
)
Token = Obj(
    {
        "id": _idp("tok"), "name": Str(min_length=1), "name_source": EnumStr(["inferred", "user"]), "value": Any_(),
        "by_mode": MapOf(Obj({"value": Any_(), "supports": Arr(ID)}, ["value", "supports"]), _key("mode")),
        "aliases_of": _idp("tok"), "inference": MapOf(InferenceRecord),
    },
    ["id", "name", "name_source", "inference"],
)
_tokcat = MapOf(Token, _key("tok"))
Tokens = Obj({c: _tokcat for c in ("color", "type", "space", "radius", "border_width", "shadow", "opacity")} | {"scales": MapOf(Arr(_idp("tok")))})
Asset = Obj(
    {
        "id": _idp("ast"), "kind": EnumStr(V.ASSET_KINDS), "provenance": EnumStr(V.PROVENANCE),
        "content": Obj({"ref": Str(r"^blob:sha256:[A-Za-z0-9_-]+$"), "media_type": Str(), "intrinsic": Obj({"w": Num(1, integer=True), "h": Num(1, integer=True)}, ["w", "h"])}, ["ref", "media_type"]),
        "origin": Obj({"region": _idp("reg"), "method": Obj({"name": Str(), "version": Str()}, ["name", "version"]), "fidelity": EnumStr(["pixel_crop", "original_bytes"]),
                       "resolution_scale": Num(0), "lossy": Bool()}),
        "placeholder": Obj({"reason": EnumStr(V.PLACEHOLDER_REASONS), "kind": EnumStr(V.PLACEHOLDER_KINDS)}, ["reason", "kind"]),
        "hint": Obj({"aspect": Num(0), "dominant_color": ColorValue, "supports": Arr(ID)}, ["aspect", "dominant_color", "supports"]),
        "rights_status": EnumStr(V.RIGHTS_STATUS),
        "rights": Obj({"holder": Str(), "license": Str(), "declared_by": Const("user"), "supports": Arr(ID, 1)}, ["declared_by", "supports"]),
        "mode_variants": MapOf(_idp("ast"), _key("mode")), "inference": InferenceRecord,
    },
    ["id", "kind", "provenance", "hint", "rights_status", "inference"],
)
Component = Obj(
    {
        "id": _idp("cmp"), "name": Str(min_length=1), "name_source": EnumStr(["inferred", "user"]), "category": EnumStr(["ui", "layout"]), "root": _idp("nd"),
        "params": MapOf(Obj({"type": EnumStr(["text", "bool", "enum", "number", "asset", "slot"]), "required": Bool(), "default": Any_(),
                             "bind": Obj({"node": _idp("nd"), "field": Str()}, ["node", "field"])}, ["type", "required"])),
        "slots": MapOf(Obj({"accepts": EnumStr(["any", "text", "media"]), "optional": Bool()}, ["accepts", "optional"])),
        "variants": Obj({"axes": Arr(Obj({"id": Str(), "kind": EnumStr(["style", "visual_state"]), "values": Arr(Str(), 1)}, ["id", "kind", "values"])),
                         "patches": MapOf(Arr(Obj({"op": EnumStr(["set", "hide"]), "target": _idp("nd"), "path": Str(), "value": Any_()}, ["op", "target"])))}, ["axes", "patches"]),
        "inference": InferenceRecord,
    },
    ["id", "name", "name_source", "category", "root", "params", "slots", "variants", "inference"],
)
Relation = Obj({"id": _idp("rel"), "kind": EnumStr(V.RELATION_KINDS), "a": ID, "b": OneOf(ID, Null()), "status": EnumStr(V.NAV_STATUS), "inference": InferenceRecord}, ["id", "kind", "a", "b", "inference"])
Dispute = Obj(
    {"id": _idp("dsp"), "target": ID, "field": Str(), "kind": Str(), "selected": Obj({"value": Any_()}, ["value"]),
     "alternatives": Arr(Obj({"value": Any_(), "producers": Arr(_idp("prd")), "supports": Arr(ID)}, ["value", "producers", "supports"])),
     "resolution": EnumStr(["user", "geometric_consistency", "weighted_vote", "tie_break", "unresolved"]), "status": EnumStr(["contested", "resolved"])},
    ["id", "target", "field", "kind", "selected", "alternatives", "resolution", "status"],
)
Redaction = Obj(
    {"id": _idp("rdc"), "stage": EnumStr(["pre_perception", "post_inference"]), "target": Obj({"kind": EnumStr(["region", "text", "asset"]), "ref": Str(), "field": Str()}, ["kind"]),
     "action": EnumStr(["mask", "replace_text", "remove"]), "replacement": Obj({"kind": Const("class_label"), "label": Str()}, ["kind", "label"]),
     "reason": EnumStr(["rule", "user"]), "rule_id": Str(), "producer": _idp("prd"), "scrubbed_paths": Arr(Str())},
    ["id", "stage", "target", "action", "reason", "producer", "scrubbed_paths"],
)
Project = Obj(
    {"id": _idp("prj"), "name": Str(min_length=1), "name_source": EnumStr(["inferred", "user"]), "default_mode": _idp("mode"),
     "redaction": Obj({"mode": EnumStr(["off", "on"]), "profile_id": Str(), "profile_hash": Str(), "stage": EnumStr(["pre_perception", "post_inference", "both"]),
                       "artifacts": EnumStr(["purged", "retained", "redacted"]), "keep_original_digest": Bool()}, ["mode"])},
    ["id", "name", "name_source", "redaction"],
)
Producer = Obj({"class": EnumStr(V.PRODUCER_CLASS), "id": Str(min_length=1), "version": Str(min_length=1), "config_hash": Str(), "artifact_ref": Str(),
                "execution_provider": Str()}, ["class", "id", "version"])

IR = Obj(
    {
        "schema_version": Const(V.SCHEMA_VERSION), "ir_state": EnumStr(["working", "committed"]),
        "extensions_used": Arr(Str()), "extensions_required": Arr(Str()), "meta": Obj({}, extra=True),
        "project": Project, "inference_config": Obj({"config_hash": Str(min_length=1), "values": Obj({}, extra=True)}, ["config_hash", "values"]),
        "producers": MapOf(Producer, _key("prd")),
        "sources": MapOf(Source, _key("src")), "regions": MapOf(Region, _key("reg")), "evidence": MapOf(Evidence, _key("evd")),
        "screens": MapOf(Screen, _key("scr")), "modes": MapOf(Mode, _key("mode")), "pages": MapOf(Page, _key("pg")),
        "nodes": MapOf(Node, _key("nd")),
        "realizations": MapOf(Obj({"inference": InferenceRecord, "nodes": MapOf(Obj({"regions": Arr(_idp("reg"), 1), "inference": InferenceRecord}, ["regions"]))}, ["inference", "nodes"]), _key("scr")),
        "components": MapOf(Component, _key("cmp")), "tokens": Tokens, "assets": MapOf(Asset, _key("ast")),
        "relations": Arr(Relation), "disputes": Arr(Dispute), "redactions": MapOf(Redaction, _key("rdc")),
        "lineage": Obj({"tombstones": Arr(Obj({"id": ID, "reason": Str()}, ["id"])), "counter": Num(0, integer=True), "migrated_from": Arr(Str()),
                        "repairs": Arr(Obj({}, extra=True))}, ["tombstones", "counter", "migrated_from", "repairs"]),
    },
    ["schema_version", "ir_state", "extensions_used", "extensions_required", "project", "inference_config", "producers", "sources", "regions", "evidence",
     "screens", "modes", "pages", "nodes", "realizations", "components", "tokens", "assets", "relations", "disputes", "redactions", "lineage"],
)


def json_schema() -> dict[str, Any]:
    s = IR.schema()
    return {"$schema": "https://json-schema.org/draft/2020-12/schema", "$id": "https://screen2code.dev/schema/ir-0.1.schema.json",
            "title": "Screen2Code UI IR 0.1", **s}


def schema_text() -> str:
    return json.dumps(json_schema(), indent=2, sort_keys=True) + "\n"


if __name__ == "__main__":
    sys.stdout.write(schema_text())
