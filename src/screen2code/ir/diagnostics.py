"""Diagnostics produced by IR validation (IR_SPEC section 17.3)."""
from __future__ import annotations

from dataclasses import dataclass, field


def pointer(*parts: object) -> str:
    """Build a JSON Pointer from path parts."""
    return "".join("/" + str(p).replace("~", "~0").replace("/", "~1") for p in parts)


@dataclass(frozen=True)
class Diagnostic:
    code: str
    severity: str  # error | warning | info
    path: str
    message: str

    def to_dict(self) -> dict[str, str]:
        return {"code": self.code, "severity": self.severity, "path": self.path, "message": self.message}

    def __str__(self) -> str:
        return f"[{self.severity}] {self.code} {self.path or '/'}: {self.message}"


@dataclass
class Report:
    diagnostics: list[Diagnostic] = field(default_factory=list)

    def add(self, code: str, severity: str, path: str, message: str) -> None:
        self.diagnostics.append(Diagnostic(code, severity, path, message))

    def error(self, code: str, path: str, message: str) -> None:
        self.add(code, "error", path, message)

    def warn(self, code: str, path: str, message: str) -> None:
        self.add(code, "warning", path, message)

    def info(self, code: str, path: str, message: str) -> None:
        self.add(code, "info", path, message)

    @property
    def errors(self) -> list[Diagnostic]:
        return [d for d in self.diagnostics if d.severity == "error"]

    @property
    def warnings(self) -> list[Diagnostic]:
        return [d for d in self.diagnostics if d.severity == "warning"]

    @property
    def ok(self) -> bool:
        return not self.errors
