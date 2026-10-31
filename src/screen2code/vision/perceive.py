"""S0-S3 orchestration: image -> regions (observed) + evidence (observed). No structure is inferred here."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

from ..core.runner import Context
from ..ir import derive_id
from .importer import ImportedImage, import_image
from .measure import EvidenceSink, measure_tree
from .ocr import OCRProvider, run_ocr
from .segment import Node, segment_image
from .typography import cell_for

SEG_VERSION, MEASURE_VERSION = "0.1.0", "0.1.0"


REDACT_VERSION = "1"
REDACT_PLACEHOLDER = "[redacted]"


def redacted_value(text: str) -> str:
    """Replacement that keeps only the line count (layout needs it); no length, no characters, no hash of the original."""
    return "\n".join(REDACT_PLACEHOLDER for _ in text.split("\n"))


@dataclass
class Perception:
    image: ImportedImage
    source_id: str
    root: Node
    regions: dict[str, dict[str, Any]]
    evidence: dict[str, dict[str, Any]]
    producers: dict[str, dict[str, Any]]
    scale: float
    scale_origin: str
    ocr_calls: int = 0
    warnings: list[str] = field(default_factory=list)


def perceive(path: Path, ctx: Context, ocr: OCRProvider, declared: dict[str, Any] | None = None) -> Perception:
    cfg = ctx.cfg
    ctx.emit("import", "running")
    img = import_image(path, cfg, declared)
    src_id = derive_id("src", img.sha256)
    scale = float(img.declared.get("device_pixel_ratio", 1.0))
    ctx.emit("import", "done", 1.0)

    ctx.emit("regions", "running")
    root = segment_image(img.rgb)
    ctx.emit("ocr", "running")
    calls = run_ocr(img.rgb, root, ocr, ctx.cache, float(cfg["ocr"]["min_conf"]), ctx.cancel)
    ctx.emit("ocr", "done", 1.0, f"{calls} recognition calls")
    for n in root.walk():  # text leaves become nominal line boxes (see vision/typography.py)
        if n.reading:
            cell = cell_for(img.rgb, n.rect, n.fill, n.reading["value"], scale)
            if cell:
                x, y, w, h = cell
                y = max(0, y)
                h = min(h, img.rgb.shape[0] - y)
                n.notes["ink_rect"] = n.rect
                n.x, n.y, n.w, n.h = x, y, w, h
    def refit(n: Node) -> None:  # group boxes are unions of their children: recompute after text leaves became line-box cells
        for c in n.children:
            refit(c)
        if n.kind == "group" and n.children:
            x0 = min(c.x for c in n.children); y0 = min(c.y for c in n.children)
            x1 = max(c.x + c.w for c in n.children); y1 = max(c.y + c.h for c in n.children)
            n.x, n.y, n.w, n.h = x0, y0, x1 - x0, y1 - y0

    refit(root)
    seg_prod = derive_id("prd", "s2c.region-segmenter", SEG_VERSION)
    meas_prod = derive_id("prd", "s2c.measure", MEASURE_VERSION)
    ocr_prod = derive_id("prd", ocr.id, ocr.version)
    producers = {
        seg_prod: {"class": "classical", "id": "s2c.region-segmenter", "version": SEG_VERSION},
        meas_prod: {"class": "classical", "id": "s2c.measure", "version": MEASURE_VERSION},
        ocr_prod: {"class": "model", "id": ocr.id, "version": ocr.version},
    }
    regions: dict[str, dict[str, Any]] = {}

    def assign(n: Node, path: tuple[int, ...]) -> None:
        n.rid = derive_id("reg", img.sha256, n.x, n.y, n.w, n.h, path)
        regions[n.rid] = {"id": n.rid, "source": src_id, "rect": {"x": n.x, "y": n.y, "w": n.w, "h": n.h}, "basis": "measured", "producer": seg_prod}
        for i, c in enumerate(n.children):
            assign(c, path + (i,))

    assign(root, ())
    ctx.emit("regions", "done", 1.0)

    ctx.emit("measure", "running")
    sink = EvidenceSink(meas_prod)
    redact = bool(cfg.get("privacy", {}).get("redact_text"))
    # redaction (IR_SPEC section 16): evidence is built from the placeholder, never from the recognized text, so no evidence copy or content-derived id exists
    readings = [{"region": n.rid, "value": redacted_value(n.reading["value"]) if redact else n.reading["value"], "reported_confidence": n.reading["conf"]} for n in root.walk() if n.reading]
    if readings:
        eid = sink.add("text_reading", [r["region"] for r in readings], {"readings": readings}, basis="reported", producer=ocr_prod)
        for n in root.walk():
            if n.reading:
                n.notes.setdefault("ev", {}).setdefault("text_reading", []).append(eid)
    measure_tree(img.rgb, root, sink, scale, float(cfg["thresholds"]["align.tolerance_px"]))  # measurement needs the real text (font fitting); it stores none of it
    if redact:
        for n in root.walk():
            if n.reading:
                n.reading = {"value": redacted_value(n.reading["value"]), "conf": n.reading["conf"]}
                n.notes["redacted"] = True
        producers[derive_id("prd", "s2c.redact", REDACT_VERSION)] = {"class": "classical", "id": "s2c.redact", "version": REDACT_VERSION}
    ctx.emit("measure", "done", 1.0)
    origin = "declared" if "device_pixel_ratio" in img.declared else "assumed"
    return Perception(img, src_id, root, regions, sink.items, producers, scale, origin, calls, list(img.warnings))
