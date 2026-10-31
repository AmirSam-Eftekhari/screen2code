"""Forward-only IR migrations (IR_SPEC section 4.3). Pure functions registered per source version."""
from __future__ import annotations

import copy
from typing import Any, Callable

from .vocab import SCHEMA_VERSION

JSON = Any
Migration = Callable[[dict[str, JSON]], dict[str, JSON]]

#: source version -> (target version, function). Empty for 0.1, the first schema version.
MIGRATIONS: dict[str, tuple[str, Migration]] = {}


class MigrationError(Exception):
    """Raised when a document cannot be migrated to the requested version."""


def migrate(doc: dict[str, JSON], target: str = SCHEMA_VERSION, registry: dict[str, tuple[str, Migration]] | None = None) -> tuple[dict[str, JSON], list[str]]:
    """Return ``(migrated copy, version chain)``. Never mutates ``doc``. Downgrades are not supported."""
    reg = MIGRATIONS if registry is None else registry
    out = copy.deepcopy(doc)
    chain = [str(out.get("schema_version"))]
    seen = {chain[0]}
    while out.get("schema_version") != target:
        cur = out.get("schema_version")
        if cur not in reg:
            raise MigrationError(f"no migration path from schema_version {cur!r} to {target!r}")
        nxt, fn = reg[cur]
        out = fn(out)
        if out.get("schema_version") != nxt:
            raise MigrationError(f"migration from {cur!r} did not produce version {nxt!r}")
        if nxt in seen:
            raise MigrationError("migration cycle")
        seen.add(nxt)
        chain.append(nxt)
    if len(chain) > 1:
        out.setdefault("lineage", {}).setdefault("migrated_from", [])
        out["lineage"]["migrated_from"] = list(out["lineage"]["migrated_from"]) + chain[:-1]
    return out, chain
