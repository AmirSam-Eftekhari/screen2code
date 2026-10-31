"""Typographic cell model: map a text leaf's ink box to its nominal line box (heuristic, sans-serif metrics).

The measured ink extents are kept in ``text_metrics`` evidence; the *cell* is a deterministic function of them and the recognised
text, with the metric constants recorded in ``inference_config`` (Liberation Sans-like faces: ascent .905, descent .212, cap/ascender
.73, x-height .52, normal line spacing 1.2). Other typefaces will deviate; calibrate on the corpus.
"""
from __future__ import annotations

from typing import Any

import numpy as np

ASC = set("bdfhijklABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789!?/&%$#")
DESC = set("gjpqy,;()[]{}|@")
ASC_H, X_H, DESC_H = 0.73, 0.52, 0.21
ASCENT_EM, CONTENT_EM, LINE_RATIO = 0.905, 1.117, 1.2
INK_T = 24


def estimate_size(ink_h: float, text: str, lines: int = 1) -> float:
    top = ASC_H if any(c in ASC for c in text) else X_H
    bot = DESC_H if any(c in DESC for c in text) else 0.0
    return max(8.0, round((ink_h / max(1, lines)) / (top + bot)))


def ink_rows(rgb: np.ndarray, rect: tuple[int, int, int, int], fill: tuple[int, int, int]) -> tuple[int, int, int] | None:
    """Return (ink_top, ink_bottom, baseline) as absolute y of the strongest rows, or None if there is no ink."""
    x, y, w, h = rect
    reg = rgb[y : y + h, x : x + w].astype(np.int16)
    mask = np.abs(reg - np.array(fill, dtype=np.int16)).max(axis=2) > INK_T
    if not mask.any():
        return None
    rows = mask.sum(axis=1)
    nz = np.nonzero(rows)[0]
    dense = np.nonzero(rows >= 0.5 * rows.max())[0]
    return y + int(nz[0]), y + int(nz[-1]), y + int(dense[-1])


def cell_for(rgb: np.ndarray, rect: tuple[int, int, int, int], fill: tuple[int, int, int], text: str, scale: float) -> tuple[int, int, int, int] | None:
    """Nominal line-box rectangle (source px) for a text leaf, or None when no ink is found."""
    r = ink_rows(rgb, rect, fill)
    if r is None:
        return None
    top, bot, base = r
    lines = max(1, text.count("\n") + 1)
    if lines > 1:  # multi-line leaves keep their measured extent (line spacing is not modelled)
        return None
    size = estimate_size((bot - top + 1) / scale, text) * scale
    L = round(LINE_RATIO * size)
    cell_top = int(round(base - (L / 2 + (ASCENT_EM - CONTENT_EM / 2) * size)))
    x, _, w, _ = rect
    return x, cell_top, w, int(L)
