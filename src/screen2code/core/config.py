"""Layered configuration (ARCHITECTURE section 12): defaults < user file < project.toml < explicit overrides."""
from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Any

from .errors import S2CError

DEFAULTS: dict[str, Any] = {
    "import": {"max_file_mb": 50, "max_side_px": 16384, "max_megapixels": 100},
    "ocr": {"provider": "tesseract", "lang": "eng", "min_conf": 30.0, "timeout_s": 30},
    "thresholds": {
        "align.tolerance_px": 2.0, "gap.uniform_tolerance_px": 1.5, "token.color.merge_delta_e2000": 3.0, "token.length.merge_px": 1.0,
        "token.mode_merge.min_nodes": 2, "component.min_support": 2, "similarity.record_above": 0.75, "screen.correspondence.min": 0.7,
        "text.status.uncertain_below": 0.8, "text.status.unreadable_below": 0.3, "layout.absolute.max_residual_px": 2.0,
        "layout.absolute.max_ratio": 0.05, "asset.extract.min_size_px": 24, "refine.max_iterations": 5,
    },
    "render": {"allow_no_sandbox": False, "timeout_s": 30, "browsers_path": ""},
    "policy": {"asset_rights": "default", "navigation": "asserted_only", "placeholder_text": "[unreadable text]"},
    "privacy": {"remote_providers": False, "redact_text": False},
}


def _merge(a: dict[str, Any], b: dict[str, Any]) -> dict[str, Any]:
    out = dict(a)
    for k, v in b.items():
        out[k] = _merge(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else v
    return out


def load_toml(path: Path) -> dict[str, Any]:
    try:
        return tomllib.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except tomllib.TOMLDecodeError as e:
        raise S2CError("S2C-CONFIG-001", f"invalid TOML in {path}: {e}") from e


def validate_config(cfg: dict[str, Any]) -> None:
    pol = cfg["policy"]
    if pol["asset_rights"] not in ("strict", "default", "permissive"):
        raise S2CError("S2C-CONFIG-001", "policy.asset_rights must be strict, default, or permissive")
    if pol["navigation"] not in ("asserted_only", "evidenced_and_asserted"):
        raise S2CError("S2C-CONFIG-001", "policy.navigation must be asserted_only or evidenced_and_asserted")
    for k, v in cfg["import"].items():
        if not isinstance(v, (int, float)) or v <= 0:
            raise S2CError("S2C-CONFIG-001", f"import.{k} must be a positive number")


def load_config(project_dir: Path | None = None, user_file: Path | None = None, overrides: dict[str, Any] | None = None) -> dict[str, Any]:
    cfg = DEFAULTS
    if user_file:
        cfg = _merge(cfg, load_toml(user_file))
    if project_dir:
        cfg = _merge(cfg, load_toml(project_dir / "project.toml"))
    if overrides:
        cfg = _merge(cfg, overrides)
    validate_config(cfg)
    return cfg
