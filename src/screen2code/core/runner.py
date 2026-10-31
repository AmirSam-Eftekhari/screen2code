"""Stage runner: events, cancellation, timing, error wrapping, and a provider-output cache (PIPELINE section 3)."""
from __future__ import annotations

import hashlib
import json
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Protocol

from .errors import Cancelled, S2CError
from .log import JsonLog
from .project import Project


@dataclass(frozen=True)
class Event:
    stage: str
    status: str  # pending | running | done | degraded | failed
    progress: float = 0.0
    message: str = ""


class CancelToken:
    def __init__(self) -> None:
        self._ev = threading.Event()

    def cancel(self) -> None:
        self._ev.set()

    @property
    def cancelled(self) -> bool:
        return self._ev.is_set()

    def check(self) -> None:
        if self._ev.is_set():
            raise Cancelled()


class ProviderCache:
    """Replay cache keyed by (input hash, provider id+version, config hash, seed) so IR construction is deterministic (P-4)."""

    def __init__(self, project: Project | None):
        self.project = project
        self.hits = self.misses = 0

    @staticmethod
    def key(*parts: Any) -> str:
        return hashlib.sha256(json.dumps(parts, sort_keys=True, default=str).encode()).hexdigest()

    def get(self, key: str) -> Any | None:
        if not self.project:
            return None
        rel = f"cache/{key}.json"
        if self.project.exists(rel):
            self.hits += 1
            return self.project.read_json(rel)
        self.misses += 1
        return None

    def put(self, key: str, value: Any) -> None:
        if self.project:
            self.project.write_json(f"cache/{key}.json", value)


@dataclass
class Context:
    project: Project | None
    cfg: dict[str, Any]
    log: JsonLog = field(default_factory=JsonLog)
    cancel: CancelToken = field(default_factory=CancelToken)
    listener: Callable[[Event], None] | None = None
    cache: ProviderCache = field(default_factory=lambda: ProviderCache(None))
    timings: dict[str, float] = field(default_factory=dict)

    def emit(self, stage: str, status: str, progress: float = 0.0, message: str = "") -> None:
        ev = Event(stage, status, progress, message)
        self.log.event("stage", stage=stage, status=status, progress=progress, message=message)
        if self.listener:
            self.listener(ev)


class Stage(Protocol):
    name: str
    version: str

    def run(self, ctx: Context, state: dict[str, Any]) -> str | None:
        """Mutate ``state``; return 'degraded' only when the user explicitly selected reduced capability."""


def run_stages(stages: list[Stage], ctx: Context, state: dict[str, Any]) -> dict[str, Any]:
    for st in stages:
        ctx.cancel.check()
        ctx.emit(st.name, "running")
        t0 = time.perf_counter()
        try:
            status = st.run(ctx, state) or "done"
        except Cancelled:
            ctx.emit(st.name, "failed", message="cancelled")
            raise
        except S2CError as e:
            ctx.emit(st.name, "failed", message=str(e))
            raise
        except Exception as e:  # noqa: BLE001 - wrapped with context and re-raised, never swallowed
            ctx.emit(st.name, "failed", message=f"{type(e).__name__}: {e}")
            raise S2CError("S2C-STAGE-001", f"stage {st.name!r} failed: {type(e).__name__}: {e}", details={"stage": st.name}) from e
        ctx.timings[st.name] = round(time.perf_counter() - t0, 4)
        ctx.emit(st.name, status, 1.0)
    return state
