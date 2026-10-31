"""Model manager (MODEL_STRATEGY section 4): manifests, checksum verification, license gate, local storage.

Weights are never bundled and never downloaded at startup. Installation is an explicit user action from a
local file (offline) or, in a future provider, a URL; both paths verify the manifest SHA-256.
"""
from __future__ import annotations

import hashlib
import json
import shutil
from dataclasses import asdict, dataclass
from pathlib import Path

from .errors import S2CError

REQUIRED = ("id", "version", "source_url", "license_spdx", "license_class", "sha256", "size_bytes", "format")
LICENSE_CLASSES = ("permissive", "copyleft", "restricted", "unknown")


@dataclass(frozen=True)
class ModelManifest:
    id: str
    version: str
    source_url: str
    license_spdx: str
    license_class: str
    sha256: str
    size_bytes: int
    format: str
    runtime: str = "onnx"
    notes: str = ""

    @classmethod
    def from_dict(cls, d: dict) -> "ModelManifest":
        missing = [k for k in REQUIRED if d.get(k) in (None, "")]
        if missing:
            raise S2CError("S2C-MODEL-001", f"model manifest is missing {missing}", "version, source, license, and checksum are mandatory")
        if d["license_class"] not in LICENSE_CLASSES:
            raise S2CError("S2C-MODEL-001", f"unknown license_class {d['license_class']!r}")
        return cls(**{k: d[k] for k in cls.__dataclass_fields__ if k in d})


class ModelStore:
    def __init__(self, root: Path):
        self.root = root

    def _dir(self, mid: str, ver: str) -> Path:
        from .workspace import check_component

        check_component(mid), check_component(ver)
        return self.root / mid / ver

    @staticmethod
    def _sha256(p: Path) -> str:
        h = hashlib.sha256()
        with p.open("rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h.update(chunk)
        return h.hexdigest()

    def install_from_file(self, manifest: ModelManifest, file: Path, *, accept_license: bool = False) -> Path:
        """Verify checksum, apply the license gate, then register. Nothing is stored if any check fails."""
        if manifest.license_class != "permissive" and not accept_license:
            raise S2CError("S2C-MODEL-003", f"model {manifest.id} is licensed {manifest.license_spdx} ({manifest.license_class})",
                           "review the license and pass explicit acceptance; such models are bring-your-own and never redistributed")
        if self._sha256(file) != manifest.sha256.lower() or file.stat().st_size != manifest.size_bytes:
            raise S2CError("S2C-MODEL-002", f"checksum or size mismatch for {manifest.id} {manifest.version}")
        d = self._dir(manifest.id, manifest.version)
        d.mkdir(parents=True, exist_ok=True)
        dest = d / file.name
        shutil.copyfile(file, dest)
        (d / "manifest.json").write_text(json.dumps({**asdict(manifest), "file": file.name}, indent=2, sort_keys=True), encoding="utf-8")
        return dest

    def list(self) -> list[dict]:
        out = []
        for m in sorted(self.root.glob("*/*/manifest.json")):
            out.append(json.loads(m.read_text(encoding="utf-8")))
        return out

    def verify(self, mid: str, ver: str) -> bool:
        d = self._dir(mid, ver)
        meta = json.loads((d / "manifest.json").read_text(encoding="utf-8"))
        ok = self._sha256(d / meta["file"]) == meta["sha256"].lower()
        if not ok:
            raise S2CError("S2C-MODEL-002", f"installed model {mid} {ver} no longer matches its checksum")
        return True

    def remove(self, mid: str, ver: str) -> None:
        d = self._dir(mid, ver)
        if d.exists():
            shutil.rmtree(d)
