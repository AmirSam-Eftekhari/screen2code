"""Structured JSON-lines logging without image/OCR content or secrets by default (SECURITY section 7)."""
from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any

_SECRET = re.compile(r"(?i)(api[_-]?key|token|secret|password|authorization)(\"?\s*[:=]\s*\"?)([^\s\",}]+)")
_DROP_KEYS = {"text", "ocr_text", "image", "pixels", "content"}
_SECRET_KEY = re.compile(r"(?i)(api[_-]?key|token|secret|password|authorization|credential)")


def scrub(value: Any) -> Any:
    if isinstance(value, str):
        return _SECRET.sub(r"\1\2[redacted]", value)
    if isinstance(value, dict):
        return {k: ("[omitted]" if k in _DROP_KEYS else "[redacted]" if _SECRET_KEY.search(str(k)) else scrub(v)) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [scrub(v) for v in value]
    return value


class JsonLog:
    def __init__(self, path: Path | None = None):
        self.path = path
        if path:
            path.parent.mkdir(parents=True, exist_ok=True)

    def event(self, name: str, **fields: Any) -> None:
        if not self.path:
            return
        rec = {"t": round(time.time(), 3), "event": name, **scrub(fields)}
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, sort_keys=True) + "\n")
