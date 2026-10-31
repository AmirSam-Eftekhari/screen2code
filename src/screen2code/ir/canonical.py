"""Canonical serialization, content hashing, and deterministic ID derivation (IR_SPEC sections 3.2-3.4, 5).

Canonical form: JSON, UTF-8, sorted keys, no insignificant whitespace, floats rounded to 3 decimals and
serialized as integers when integral. This follows RFC 8785 for the value domain the IR uses (ASCII keys,
no huge or tiny floats). Key ordering is by code point, which equals UTF-16 order for the BMP.
"""
from __future__ import annotations

import base64
import hashlib
import json
import math
from typing import Any

JSON = Any


def _norm(o: JSON) -> JSON:
    if isinstance(o, bool) or o is None or isinstance(o, str):
        return o
    if isinstance(o, int):
        return o
    if isinstance(o, float):
        if math.isnan(o) or math.isinf(o):
            raise ValueError("NaN/Infinity are not valid in the IR")
        r = round(o, 3)
        return int(r) if r == int(r) and abs(r) < 1e15 else r
    if isinstance(o, dict):
        return {str(k): _norm(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_norm(v) for v in o]
    raise TypeError(f"not JSON serializable in the IR: {type(o).__name__}")


def canonical_dumps(doc: JSON) -> str:
    """Deterministic JSON text for ``doc``."""
    return json.dumps(_norm(doc), sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def canonical_bytes(doc: JSON) -> bytes:
    return canonical_dumps(doc).encode("utf-8")


def content_hash(doc: dict[str, JSON]) -> str:
    """SHA-256 of the canonical form of the document without ``meta`` (D-1)."""
    core = {k: v for k, v in doc.items() if k != "meta"}
    return "sha256:" + hashlib.sha256(canonical_bytes(core)).hexdigest()


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def derive_id(prefix: str, *parts: object, length: int = 16) -> str:
    """Deterministic opaque ID: ``<prefix>_<base32>`` from the first 80 bits of SHA-256 over the parts (section 5)."""
    h = hashlib.sha256("\x1f".join(str(p) for p in parts).encode("utf-8")).digest()
    token = base64.b32encode(h).decode("ascii").lower().rstrip("=")[:length]
    return f"{prefix}_{token}"
