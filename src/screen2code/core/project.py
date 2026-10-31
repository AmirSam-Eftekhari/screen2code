"""Project storage: directory layout, atomic JSON IO, and a single-writer lock (ARCHITECTURE section 4)."""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

import psutil

from ..ir import canonical_dumps
from .artifacts import ArtifactStore
from .config import load_config
from .errors import S2CError
from .workspace import Workspace

SUBDIRS = ("ir", "assets", "artifacts", "cache", "plans", "renders", "evaluations", "runs", "exports")


class Project:
    def __init__(self, root: Path):
        self.root = root.resolve()
        self.ws = Workspace(self.root)
        self.artifacts = ArtifactStore(self.ws)
        self._locked = False

    # -- lifecycle
    @classmethod
    def create(cls, path: str | os.PathLike[str], name: str) -> "Project":
        root = Path(path)
        if (root / "project.toml").exists():
            raise S2CError("S2C-PROJECT-003", f"project already exists at {root}")
        root.mkdir(parents=True, exist_ok=True)
        for d in SUBDIRS:
            (root / d).mkdir(exist_ok=True)
        p = cls(root)
        safe = json.dumps(name)  # TOML basic strings accept JSON escapes
        p.ws.write_text("project.toml", f'[project]\nname = {safe}\n', overwrite=False)
        return p

    @classmethod
    def open(cls, path: str | os.PathLike[str]) -> "Project":
        root = Path(path)
        if not (root / "project.toml").exists():
            raise S2CError("S2C-PROJECT-002", f"{root} is not a Screen2Code project", "create one with `screen2code init`")
        for d in SUBDIRS:
            (root / d).mkdir(exist_ok=True)
        return cls(root)

    @classmethod
    def open_or_create(cls, path: str | os.PathLike[str], name: str | None = None) -> "Project":
        root = Path(path)
        return cls.open(root) if (root / "project.toml").exists() else cls.create(root, name or root.name or "project")

    @property
    def name(self) -> str:
        return str(self._raw_toml().get("project", {}).get("name", self.root.name))

    def _raw_toml(self) -> dict[str, Any]:
        import tomllib

        return tomllib.loads((self.root / "project.toml").read_text(encoding="utf-8"))

    def config(self, overrides: dict[str, Any] | None = None) -> dict[str, Any]:
        return load_config(self.root, None, overrides)

    # -- locking (single writer)
    def acquire(self) -> None:
        lock = self.root / ".lock"
        for _ in range(2):
            try:
                fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                with os.fdopen(fd, "w") as f:
                    f.write(json.dumps({"pid": os.getpid(), "t": time.time()}))
                self._locked = True
                return
            except FileExistsError:
                try:
                    holder = json.loads(lock.read_text())
                    pid = int(holder["pid"])
                except (OSError, ValueError, KeyError):
                    pid = -1
                if pid != os.getpid() and pid > 0 and psutil.pid_exists(pid):
                    raise S2CError("S2C-PROJECT-001", f"project is locked by process {pid}", "close the other Screen2Code instance")
                if pid == os.getpid() and self._locked:
                    return
                lock.unlink(missing_ok=True)  # stale lock
        raise S2CError("S2C-PROJECT-001", "could not acquire the project lock")

    def release(self) -> None:
        if self._locked:
            (self.root / ".lock").unlink(missing_ok=True)
            self._locked = False

    def __enter__(self) -> "Project":
        self.acquire()
        return self

    def __exit__(self, *exc: object) -> None:
        self.release()

    # -- JSON IO
    def write_json(self, rel: str, obj: Any, *, canonical: bool = False, overwrite: bool = True) -> Path:
        text = canonical_dumps(obj) if canonical else json.dumps(obj, indent=2, sort_keys=True, ensure_ascii=False)
        return self.ws.write_text(rel, text + "\n", overwrite=overwrite)

    def read_json(self, rel: str) -> Any:
        return json.loads(self.ws.read_bytes(rel).decode("utf-8"))

    def exists(self, rel: str) -> bool:
        return self.ws.resolve(rel).exists()
