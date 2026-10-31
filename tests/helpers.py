from __future__ import annotations

import hashlib
import os
import tempfile
import unittest
from pathlib import Path

from screen2code.core import Context
from screen2code.core.config import load_config
from screen2code.vision import TesseractOCR

ROOT = Path(__file__).resolve().parent.parent
FIX = ROOT / "tests" / "fixtures"
LANDING = FIX / "landing.png"
OCR_OK, OCR_WHY = TesseractOCR().available()
needs_ocr = unittest.skipUnless(OCR_OK, f"tesseract unavailable: {OCR_WHY}")
NO_SANDBOX = {"render": {"allow_no_sandbox": True, "browsers_path": os.environ.get("PLAYWRIGHT_BROWSERS_PATH", "")}}


def browser_ok() -> tuple[bool, str]:
    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            return Path(p.chromium.executable_path).exists(), "chromium missing"
    except Exception as e:  # noqa: BLE001
        return False, type(e).__name__


needs_browser = unittest.skipUnless(browser_ok()[0], "Chromium unavailable: " + browser_ok()[1])


class Perceived:
    """Cache one perception of the landing fixture across tests (it is deterministic)."""

    _p = None
    store: dict[str, bytes] = {}

    @classmethod
    def get(cls):
        from screen2code.vision import perceive

        if cls._p is None:
            cls._p = perceive(LANDING, Context(None, load_config()), TesseractOCR())
        return cls._p

    @classmethod
    def write_asset(cls, b: bytes) -> str:
        h = hashlib.sha256(b).hexdigest()
        cls.store[h] = b
        return h
