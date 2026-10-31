"""Content-addressed artifact store (ARCHITECTURE section 4). Immutable: same bytes, same key."""
from __future__ import annotations

import hashlib
from pathlib import Path

from .errors import S2CError
from .workspace import Workspace


class ArtifactStore:
    def __init__(self, ws: Workspace, subdir: str = "artifacts"):
        self.ws, self.subdir = ws, subdir
        (ws.root / subdir).mkdir(parents=True, exist_ok=True)

    @staticmethod
    def key_of(data: bytes) -> str:
        return hashlib.sha256(data).hexdigest()

    def _rel(self, key: str, suffix: str) -> str:
        if not key.isalnum() or len(key) != 64 or (suffix and not suffix.lstrip(".").isalnum()):
            raise S2CError("S2C-PATH-002", "invalid artifact key or suffix")
        return f"{self.subdir}/{key[:2]}/{key}{suffix}"

    def put(self, data: bytes, suffix: str = "") -> str:
        key = self.key_of(data)
        rel = self._rel(key, suffix)
        p = self.ws.resolve(rel)
        if not p.exists():
            self.ws.write_bytes(rel, data)
        return key

    def path(self, key: str, suffix: str = "") -> Path:
        return self.ws.resolve(self._rel(key, suffix))

    def get(self, key: str, suffix: str = "") -> bytes:
        data = self.path(key, suffix).read_bytes()
        if self.key_of(data) != key:
            raise S2CError("S2C-PATH-002", f"artifact {key[:12]} is corrupt (hash mismatch)")
        return data

    def exists(self, key: str, suffix: str = "") -> bool:
        return self.path(key, suffix).exists()
