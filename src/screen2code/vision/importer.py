"""S0 import: validate, limit-check, normalize (sRGB, flatten alpha, strip metadata) an untrusted image (SECURITY section 4)."""
from __future__ import annotations

import hashlib
import io
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image, ImageCms

from ..core.errors import S2CError

ACCEPTED = {"PNG": "image/png", "JPEG": "image/jpeg", "WEBP": "image/webp"}
_SRGB = ImageCms.createProfile("sRGB")


@dataclass
class ImportedImage:
    name: str
    media_type: str
    sha256: str  # of the normalized PNG
    rgb: np.ndarray  # H x W x 3 uint8
    png: bytes
    pixel_size: dict[str, int]
    declared: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)


def import_image(path: Path, cfg: dict[str, Any], declared: dict[str, Any] | None = None) -> ImportedImage:
    lim = cfg["import"]
    try:
        size = path.stat().st_size
    except OSError as e:
        raise S2CError("S2C-IMPORT-003", f"cannot read {path.name}: {e.strerror}") from e
    if size > lim["max_file_mb"] * 1024 * 1024:
        raise S2CError("S2C-IMPORT-002", f"{path.name} is {size / 1e6:.1f} MB, above the {lim['max_file_mb']} MB limit")
    Image.MAX_IMAGE_PIXELS = int(lim["max_megapixels"] * 1e6)  # Pillow raises DecompressionBombError beyond 2x this
    warnings: list[str] = []
    try:
        with Image.open(path) as im:
            fmt = im.format or ""
            if fmt not in ACCEPTED:  # content-based, never trust the extension
                raise S2CError("S2C-IMPORT-001", f"{path.name}: format {fmt or 'unknown'} is not accepted", "use PNG, JPEG, or WebP")
            if getattr(im, "n_frames", 1) > 1 or getattr(im, "is_animated", False):
                raise S2CError("S2C-IMPORT-004", f"{path.name} is animated or multi-frame")
            w, h = im.size  # header only; checked before pixel decode
            if max(w, h) > lim["max_side_px"] or w * h > lim["max_megapixels"] * 1e6:
                raise S2CError("S2C-IMPORT-002", f"{path.name} is {w}x{h}, above the configured limits")
            im.load()
            icc = im.info.get("icc_profile")
            if im.mode in ("RGBA", "LA", "PA") or (im.mode == "P" and "transparency" in im.info):
                rgba = im.convert("RGBA")
                bg = Image.new("RGBA", rgba.size, (255, 255, 255, 255))
                bg.alpha_composite(rgba)
                rgb_im = bg.convert("RGB")
                warnings.append("alpha channel flattened onto white")
            else:
                rgb_im = im.convert("RGB")
            if icc:
                try:
                    rgb_im = ImageCms.profileToProfile(rgb_im, ImageCms.ImageCmsProfile(io.BytesIO(icc)), _SRGB, outputMode="RGB")
                except (ImageCms.PyCMSError, OSError):
                    warnings.append("embedded color profile could not be applied; assuming sRGB")
    except S2CError:
        raise
    except (Image.DecompressionBombError, Image.DecompressionBombWarning) as e:
        raise S2CError("S2C-IMPORT-002", f"{path.name} exceeds the pixel limit") from e
    except Exception as e:  # noqa: BLE001 - decoder errors of any kind become one clear input error
        raise S2CError("S2C-IMPORT-003", f"{path.name} could not be decoded: {type(e).__name__}") from e
    buf = io.BytesIO()
    rgb_im.save(buf, format="PNG")  # re-encode: metadata and trailing data are dropped
    png = buf.getvalue()
    return ImportedImage(path.name, ACCEPTED[fmt], hashlib.sha256(png).hexdigest(), np.asarray(rgb_im).copy(), png, {"w": rgb_im.width, "h": rgb_im.height},
                         dict(declared or {}), warnings)
