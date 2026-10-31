"""Confined filesystem access (SECURITY section 3). All core file operations go through a Workspace."""
from __future__ import annotations

import os
import re
import tempfile
from pathlib import Path, PurePosixPath, PureWindowsPath

from .errors import S2CError

_RESERVED = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}
_BAD_CHARS = re.compile(r'[<>:"|?*\x00-\x1f]')
MAX_PATH = 240


def check_component(name: str) -> None:
    """Reject a single path component that is unsafe on any supported platform."""
    if name in ("", ".", ".."):
        raise S2CError("S2C-PATH-002", f"forbidden path component {name!r}")
    if "/" in name or "\\" in name:
        raise S2CError("S2C-PATH-002", f"path component {name!r} contains a path separator")
    if _BAD_CHARS.search(name):
        raise S2CError("S2C-PATH-002", f"path component {name!r} contains forbidden characters (including ':' alternate data streams)")
    if name.endswith((".", " ")):
        raise S2CError("S2C-PATH-002", f"path component {name!r} ends with a dot or space")
    if name.split(".")[0].upper() in _RESERVED:
        raise S2CError("S2C-PATH-002", f"path component {name!r} is a reserved device name")


def sanitize_name(raw: str, fallback: str = "item", max_len: int = 64) -> str:
    """Derive a safe ASCII file/identifier name from arbitrary text (never used to *authorize* a path)."""
    s = re.sub(r"[^A-Za-z0-9._-]+", "-", raw.encode("ascii", "ignore").decode("ascii")).strip("-._ ")[:max_len]
    if not s or s.split(".")[0].upper() in _RESERVED:
        s = fallback
    return s


def check_relative(rel: str) -> PurePosixPath:
    """Validate a relative, forward-slash path from untrusted input and return it."""
    if not isinstance(rel, str) or not rel:
        raise S2CError("S2C-PATH-002", "empty path")
    if rel.startswith(("/", "\\")) or PureWindowsPath(rel).drive or PureWindowsPath(rel).anchor:
        raise S2CError("S2C-PATH-001", f"absolute or drive-relative path rejected: {rel!r}")
    if len(rel) > MAX_PATH:
        raise S2CError("S2C-PATH-002", "path too long")
    parts = rel.replace("\\", "/").split("/")
    for p in parts:
        check_component(p)
    return PurePosixPath(*parts)


class Workspace:
    """A project root plus optional extra allowed roots. ``resolve`` is the only way to turn names into paths."""

    def __init__(self, root: str | os.PathLike[str], extra_roots: tuple[str | os.PathLike[str], ...] = ()):
        self.root = Path(root).resolve()
        self.roots = (self.root, *(Path(r).resolve() for r in extra_roots))

    def _inside(self, p: Path) -> bool:
        return any(p == r or r in p.parents for r in self.roots)

    def resolve(self, rel: str, base: str | os.PathLike[str] | None = None) -> Path:
        """Resolve an untrusted relative path under ``base`` (default: the project root); reject any escape."""
        rp = check_relative(rel)
        b = Path(base).resolve() if base else self.root
        if not self._inside(b):
            raise S2CError("S2C-PATH-001", f"base directory is outside the workspace: {b}")
        target = (b / rp).resolve()  # resolves symlinks/junctions that already exist
        if not (target == b or b in target.parents) or not self._inside(target):
            raise S2CError("S2C-PATH-001", f"path escapes the allowed directory: {rel!r}")
        return target

    def write_bytes(self, rel: str, data: bytes, *, base: str | os.PathLike[str] | None = None, overwrite: bool = False) -> Path:
        """Atomically write ``data`` (temp file + os.replace); refuses to overwrite unless asked."""
        target = self.resolve(rel, base)
        if target.exists() and not overwrite:
            raise S2CError("S2C-PATH-003", f"refusing to overwrite {rel!r}", "pass overwrite=True after confirming with the user")
        if target.is_dir():
            raise S2CError("S2C-PATH-003", f"{rel!r} is a directory")
        target.parent.mkdir(parents=True, exist_ok=True)
        if not self._inside(target.parent.resolve()):
            raise S2CError("S2C-PATH-001", "parent directory escapes the workspace")
        fd, tmp = tempfile.mkstemp(dir=target.parent, prefix=".s2c-tmp-")
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(data)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, target)
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise
        return target

    def write_text(self, rel: str, text: str, **kw: object) -> Path:
        return self.write_bytes(rel, text.encode("utf-8"), **kw)  # type: ignore[arg-type]

    def read_bytes(self, rel: str, base: str | os.PathLike[str] | None = None) -> bytes:
        return self.resolve(rel, base).read_bytes()


def check_no_case_collisions(names: list[str]) -> None:
    """Reject name sets that collide on case-insensitive filesystems (Windows, macOS)."""
    seen: dict[str, str] = {}
    for n in names:
        k = n.casefold()
        if k in seen and seen[k] != n:
            raise S2CError("S2C-PATH-002", f"names {seen[k]!r} and {n!r} collide on case-insensitive filesystems")
        seen[k] = n
