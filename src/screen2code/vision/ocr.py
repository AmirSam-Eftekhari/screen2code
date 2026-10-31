"""S2 OCR via a provider interface; the default provider drives the local Tesseract binary (Apache-2.0)."""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any, Protocol

import cv2
import numpy as np
import pytesseract
from pytesseract import Output

from ..core.errors import S2CError
from ..core.runner import ProviderCache
from .segment import Node


class OCRProvider(Protocol):
    id: str
    version: str

    def available(self) -> tuple[bool, str]: ...
    def read(self, rgb: np.ndarray, bg: tuple[int, int, int], multiline: bool) -> dict[str, Any]: ...


@dataclass
class TesseractOCR:
    lang: str = "eng"
    timeout_s: float = 30.0
    id: str = "ocr.tesseract"
    version: str = "unknown"

    def available(self) -> tuple[bool, str]:
        try:
            self.version = f"tesseract {pytesseract.get_tesseract_version()}"
            if self.lang not in pytesseract.get_languages(config=""):
                return False, f"language data {self.lang!r} is not installed"
            return True, ""
        except Exception as e:  # noqa: BLE001
            return False, f"tesseract is not installed or not on PATH ({type(e).__name__})"

    def read(self, rgb: np.ndarray, bg: tuple[int, int, int], multiline: bool) -> dict[str, Any]:
        pad = 8
        g = cv2.cvtColor(cv2.copyMakeBorder(rgb, pad, pad, pad, pad, cv2.BORDER_CONSTANT, value=bg), cv2.COLOR_RGB2GRAY)
        if int(g[: pad // 2].mean()) < 128:  # light-on-dark: invert so text is dark on light
            g = 255 - g
        h = g.shape[0]
        scale = 3 if h < 40 else 2 if h < 90 else 1
        if scale > 1:
            g = cv2.resize(g, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
        cfg = f"--psm {6 if multiline else 7}"
        try:
            d = pytesseract.image_to_data(g, lang=self.lang, config=cfg, output_type=Output.DICT, timeout=self.timeout_s)
        except RuntimeError as e:
            raise S2CError("S2C-PROVIDER-003", f"tesseract timed out or failed: {e}") from e
        lines: dict[tuple[int, int, int], list[str]] = {}
        confs: list[float] = []
        for i, t in enumerate(d["text"]):
            t = t.strip()
            c = float(d["conf"][i])
            if t and c >= 0:
                lines.setdefault((d["block_num"][i], d["par_num"][i], d["line_num"][i]), []).append(t)
                confs.append(c)
        value = "\n".join(" ".join(ws) for _, ws in sorted(lines.items()))
        return {"value": value, "conf": round(float(np.mean(confs)) / 100.0, 3) if confs else 0.0, "words": len(confs)}


def validate_response(res: Any) -> dict[str, Any]:
    """Provider output is untrusted: enforce shape, types, and bounds before it can influence the IR (SECURITY section 6)."""
    if not isinstance(res, dict) or not isinstance(res.get("value"), str) or isinstance(res.get("conf"), bool) or not isinstance(res.get("conf"), (int, float)):
        raise S2CError("S2C-PROVIDER-002", "OCR provider returned a malformed response")
    if not 0.0 <= float(res["conf"]) <= 1.0 or len(res["value"]) > 4000 or any(ord(c) < 32 and c not in "\n\t" for c in res["value"]):
        raise S2CError("S2C-PROVIDER-002", "OCR provider returned an out-of-range or unsafe response")
    return {"value": res["value"], "conf": float(res["conf"]), "words": int(res.get("words", 0)) if isinstance(res.get("words", 0), int) else 0}


def run_ocr(rgb: np.ndarray, root: Node, provider: OCRProvider, cache: ProviderCache, min_conf: float, cancel=None) -> int:
    """Attach ``node.reading`` to text-like leaves. Returns the number of OCR calls that missed the cache."""
    calls = 0
    for n in root.walk():
        if n.kind != "leaf" or n.h <= 3 or n.w <= 3 or n.h > 220:
            continue
        if cancel:
            cancel.check()
        crop = np.ascontiguousarray(rgb[n.y : n.y + n.h, n.x : n.x + n.w])
        multiline = n.h > 56
        key = ProviderCache.key("ocr", provider.id, provider.version, getattr(provider, "lang", ""), multiline, hashlib.sha256(crop.tobytes()).hexdigest(), crop.shape, n.fill)
        res = cache.get(key)
        if res is None:
            res = validate_response(provider.read(crop, n.fill, multiline))
            cache.put(key, res)
            calls += 1
        else:
            res = validate_response(res)
        if res["value"] and any(ch.isalnum() for ch in res["value"]) and res["conf"] * 100 >= min_conf:
            n.reading = {"value": res["value"], "conf": res["conf"]}
    return calls
