"""Stable error model (ARCHITECTURE section 8). Codes are ``S2C-<AREA>-<NNN>`` and registered here."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

#: CLI exit codes (ARCHITECTURE section 7)
EXIT = {"ok": 0, "general": 1, "usage": 2, "validation": 3, "provider": 4, "input": 5, "execution_refused": 6, "cancelled": 130}
CATEGORY_EXIT = {"validation": 3, "provider": 4, "input": 5, "security": 5, "execution_refused": 6, "io": 1, "internal": 1, "cancelled": 130}

#: code -> (category, summary). New codes must be added here.
REGISTRY: dict[str, tuple[str, str]] = {
    "S2C-IMPORT-001": ("input", "file type not accepted"),
    "S2C-IMPORT-002": ("input", "image exceeds configured limits"),
    "S2C-IMPORT-003": ("input", "image could not be decoded"),
    "S2C-IMPORT-004": ("input", "animated or multi-frame image rejected"),
    "S2C-PATH-001": ("security", "path escapes the allowed directories"),
    "S2C-PATH-002": ("security", "path contains a forbidden component"),
    "S2C-PATH-003": ("security", "refusing to overwrite an existing file"),
    "S2C-PROJECT-001": ("io", "project is locked by another process"),
    "S2C-PROJECT-002": ("io", "not a Screen2Code project"),
    "S2C-PROJECT-003": ("io", "project already exists"),
    "S2C-PROVIDER-001": ("provider", "required provider is not available"),
    "S2C-PROVIDER-002": ("provider", "provider returned an invalid response"),
    "S2C-PROVIDER-003": ("provider", "provider timed out"),
    "S2C-IR-INVALID": ("validation", "the IR failed validation"),
    "S2C-STAGE-001": ("internal", "stage failed"),
    "S2C-STAGE-002": ("cancelled", "operation cancelled"),
    "S2C-MODEL-001": ("io", "model manifest is incomplete"),
    "S2C-MODEL-002": ("io", "model checksum mismatch"),
    "S2C-MODEL-003": ("security", "model license requires explicit acceptance"),
    "S2C-RENDER-001": ("provider", "browser is not available"),
    "S2C-RENDER-002": ("provider", "browser sandbox is unavailable; explicit opt-in required"),
    "S2C-RENDER-003": ("security", "render attempted a forbidden operation"),
    "S2C-EXEC-001": ("execution_refused", "execution of generated code is not available or not authorized"),
    "S2C-GEN-001": ("input", "IR cannot be generated: not committed or invalid"),
    "S2C-CONFIG-001": ("input", "invalid configuration"),
}


@dataclass
class S2CError(Exception):
    code: str
    message: str
    remedy: str = ""
    details: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        Exception.__init__(self, f"{self.code}: {self.message}")

    @property
    def category(self) -> str:
        return REGISTRY.get(self.code, ("internal", ""))[0]

    @property
    def exit_code(self) -> int:
        return CATEGORY_EXIT.get(self.category, 1)

    def to_dict(self) -> dict[str, Any]:
        return {"code": self.code, "category": self.category, "message": self.message, "remedy": self.remedy, "details": self.details}

    def __str__(self) -> str:
        return f"{self.code}: {self.message}" + (f" ({self.remedy})" if self.remedy else "")


class Cancelled(S2CError):
    def __init__(self) -> None:
        super().__init__("S2C-STAGE-002", "operation cancelled")
