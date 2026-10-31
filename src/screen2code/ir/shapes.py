"""A tiny declarative shape DSL: one definition yields both the L0 validator and the JSON Schema.

The committed JSON Schema (schema/ir-0.1.schema.json) is generated from these shapes and a test guards
against drift. Only the JSON Schema keywords listed below are used, so any draft 2020-12 validator accepts it.
"""
from __future__ import annotations

import re
from typing import Any

from .diagnostics import Report

JSON = Any


class Shape:
    def check(self, v: JSON, path: str, rep: Report) -> None:  # pragma: no cover - interface
        raise NotImplementedError

    def schema(self) -> dict[str, JSON]:  # pragma: no cover - interface
        raise NotImplementedError


def _tname(v: JSON) -> str:
    return "null" if v is None else type(v).__name__


class Str(Shape):
    def __init__(self, pattern: str | None = None, enum: tuple[str, ...] | list[str] | None = None, min_length: int = 0):
        self.pattern, self.enum, self.min_length = pattern, tuple(enum) if enum else None, min_length
        self._re = re.compile(pattern) if pattern else None

    def check(self, v: JSON, path: str, rep: Report) -> None:
        if not isinstance(v, str):
            rep.error("S2C-IR-L0-TYPE", path, f"expected string, got {_tname(v)}")
        elif self.enum and v not in self.enum:
            rep.error("S2C-IR-L0-ENUM", path, f"{v!r} not in {list(self.enum)}")
        elif self._re and not self._re.search(v):
            rep.error("S2C-IR-L0-PATTERN", path, f"{v!r} does not match {self.pattern}")
        elif len(v) < self.min_length:
            rep.error("S2C-IR-L0-LENGTH", path, "string too short")

    def schema(self) -> dict[str, JSON]:
        s: dict[str, JSON] = {"type": "string"}
        if self.enum:
            s["enum"] = list(self.enum)
        if self.pattern:
            s["pattern"] = self.pattern
        if self.min_length:
            s["minLength"] = self.min_length
        return s


class Num(Shape):
    def __init__(self, minimum: float | None = None, maximum: float | None = None, integer: bool = False):
        self.minimum, self.maximum, self.integer = minimum, maximum, integer

    def check(self, v: JSON, path: str, rep: Report) -> None:
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            rep.error("S2C-IR-L0-TYPE", path, f"expected number, got {_tname(v)}")
            return
        if self.integer and not (isinstance(v, int) or float(v).is_integer()):
            rep.error("S2C-IR-L0-TYPE", path, "expected integer")
        if self.minimum is not None and v < self.minimum:
            rep.error("S2C-IR-L0-RANGE", path, f"{v} < {self.minimum}")
        if self.maximum is not None and v > self.maximum:
            rep.error("S2C-IR-L0-RANGE", path, f"{v} > {self.maximum}")

    def schema(self) -> dict[str, JSON]:
        s: dict[str, JSON] = {"type": "integer" if self.integer else "number"}
        if self.minimum is not None:
            s["minimum"] = self.minimum
        if self.maximum is not None:
            s["maximum"] = self.maximum
        return s


class Bool(Shape):
    def check(self, v: JSON, path: str, rep: Report) -> None:
        if not isinstance(v, bool):
            rep.error("S2C-IR-L0-TYPE", path, f"expected boolean, got {_tname(v)}")

    def schema(self) -> dict[str, JSON]:
        return {"type": "boolean"}


class Null(Shape):
    def check(self, v: JSON, path: str, rep: Report) -> None:
        if v is not None:
            rep.error("S2C-IR-L0-TYPE", path, f"expected null, got {_tname(v)}")

    def schema(self) -> dict[str, JSON]:
        return {"type": "null"}


class Const(Shape):
    def __init__(self, value: JSON):
        self.value = value

    def check(self, v: JSON, path: str, rep: Report) -> None:
        if v != self.value:
            rep.error("S2C-IR-L0-CONST", path, f"expected {self.value!r}")

    def schema(self) -> dict[str, JSON]:
        return {"const": self.value}


class Any_(Shape):
    """Opaque JSON value (documented fields only; used for patch values and extension payloads)."""

    def check(self, v: JSON, path: str, rep: Report) -> None:
        return

    def schema(self) -> dict[str, JSON]:
        return {}


class Arr(Shape):
    def __init__(self, item: Shape, min_items: int = 0, max_items: int | None = None):
        self.item, self.min_items, self.max_items = item, min_items, max_items

    def check(self, v: JSON, path: str, rep: Report) -> None:
        if not isinstance(v, list):
            rep.error("S2C-IR-L0-TYPE", path, f"expected array, got {_tname(v)}")
            return
        if len(v) < self.min_items:
            rep.error("S2C-IR-L0-LENGTH", path, f"expected at least {self.min_items} items")
        if self.max_items is not None and len(v) > self.max_items:
            rep.error("S2C-IR-L0-LENGTH", path, f"expected at most {self.max_items} items")
        for i, x in enumerate(v):
            self.item.check(x, f"{path}/{i}", rep)

    def schema(self) -> dict[str, JSON]:
        s: dict[str, JSON] = {"type": "array", "items": self.item.schema()}
        if self.min_items:
            s["minItems"] = self.min_items
        if self.max_items is not None:
            s["maxItems"] = self.max_items
        return s


class MapOf(Shape):
    def __init__(self, value: Shape, key_pattern: str | None = None):
        self.value, self.key_pattern = value, key_pattern
        self._re = re.compile(key_pattern) if key_pattern else None

    def check(self, v: JSON, path: str, rep: Report) -> None:
        if not isinstance(v, dict):
            rep.error("S2C-IR-L0-TYPE", path, f"expected object, got {_tname(v)}")
            return
        for k, x in v.items():
            if self._re and not self._re.search(k):
                rep.error("S2C-IR-L0-KEY", f"{path}/{k}", f"key {k!r} does not match {self.key_pattern}")
            self.value.check(x, f"{path}/{k}", rep)

    def schema(self) -> dict[str, JSON]:
        s: dict[str, JSON] = {"type": "object", "additionalProperties": self.value.schema()}
        if self.key_pattern:
            s["propertyNames"] = {"pattern": self.key_pattern}
        return s


class Obj(Shape):
    def __init__(self, props: dict[str, Shape], required: tuple[str, ...] | list[str] = (), extra: bool | Shape = False):
        self.props, self.required, self.extra = props, tuple(required), extra

    def check(self, v: JSON, path: str, rep: Report) -> None:
        if not isinstance(v, dict):
            rep.error("S2C-IR-L0-TYPE", path, f"expected object, got {_tname(v)}")
            return
        for r in self.required:
            if r not in v:
                rep.error("S2C-IR-L0-REQUIRED", path, f"missing required field {r!r}")
        for k, x in v.items():
            if k in self.props:
                self.props[k].check(x, f"{path}/{k}", rep)
            elif self.extra is True:
                continue
            elif isinstance(self.extra, Shape):
                self.extra.check(x, f"{path}/{k}", rep)
            else:
                rep.error("S2C-IR-L0-UNKNOWN", f"{path}/{k}", f"unknown field {k!r}")

    def schema(self) -> dict[str, JSON]:
        s: dict[str, JSON] = {"type": "object", "properties": {k: p.schema() for k, p in self.props.items()}}
        if self.required:
            s["required"] = list(self.required)
        s["additionalProperties"] = self.extra.schema() if isinstance(self.extra, Shape) else bool(self.extra)
        return s


class OneOf(Shape):
    """First alternative that validates cleanly wins."""

    def __init__(self, *alts: Shape):
        self.alts = alts

    def check(self, v: JSON, path: str, rep: Report) -> None:
        best: Report | None = None
        for a in self.alts:
            r = Report()
            a.check(v, path, r)
            if r.ok:
                return
            if best is None or len(r.diagnostics) < len(best.diagnostics):
                best = r
        rep.error("S2C-IR-L0-ONEOF", path, "no alternative matches" + (f" (closest: {best.diagnostics[0].message})" if best and best.diagnostics else ""))

    def schema(self) -> dict[str, JSON]:
        return {"oneOf": [a.schema() for a in self.alts]}
