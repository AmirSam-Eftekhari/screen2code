"""Provider registry (MODEL_STRATEGY section 2): explicit selection, no silent substitution."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from .errors import S2CError


@dataclass(frozen=True)
class ProviderInfo:
    id: str
    version: str
    capability: str
    locality: str = "local"
    network_required: bool = False
    determinism: str = "deterministic"
    license_summary: str = ""


class Registry:
    def __init__(self) -> None:
        self._f: dict[tuple[str, str], Callable[..., Any]] = {}

    def register(self, capability: str, name: str, factory: Callable[..., Any]) -> None:
        self._f[(capability, name)] = factory

    def names(self, capability: str) -> list[str]:
        return sorted(n for (c, n) in self._f if c == capability)

    def get(self, capability: str, name: str, **kw: Any) -> Any:
        if (capability, name) not in self._f:
            raise S2CError("S2C-PROVIDER-001", f"no {capability} provider named {name!r}", f"available: {self.names(capability) or 'none'}")
        prov = self._f[(capability, name)](**kw)
        ok, why = prov.available()
        if not ok:
            raise S2CError("S2C-PROVIDER-001", f"{capability} provider {name!r} is unavailable: {why}", "run `screen2code doctor`")
        return prov


REGISTRY = Registry()
