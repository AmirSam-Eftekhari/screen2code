"""Tier 0 renderer (SECURITY section 5.1; EVALUATION section 3): static HTML only, JavaScript disabled, offline,
file access confined to the project directory, per-node boxes read through the DevTools protocol (no page script).
"""
from __future__ import annotations

import hashlib
import os
import subprocess
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

from ..core.errors import S2CError


@dataclass
class RenderRecord:
    screenshot: str
    viewport_width: int
    scale: float
    css_size: dict[str, float]
    pixel_size: dict[str, int]
    browser: str
    chromium_sandbox: bool
    javascript_enabled: bool
    offline: bool
    load_ms: float
    boxes: dict[str, dict[str, float]] = field(default_factory=dict)
    blocked_requests: list[str] = field(default_factory=list)
    fonts: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def resolve_fonts() -> dict[str, Any]:
    """Record which concrete font files the generic families resolve to (the 'fonts' pin, ADR amendment A1)."""
    out: dict[str, Any] = {}
    for fam in ("sans-serif", "serif", "monospace"):
        try:
            r = subprocess.run(["fc-match", "-f", "%{family}|%{file}", fam], capture_output=True, text=True, timeout=10)
            family, _, file = r.stdout.partition("|")
            h = hashlib.sha256(Path(file).read_bytes()).hexdigest() if file and Path(file).is_file() else None
            out[fam] = {"family": family, "sha256": h}
        except (OSError, subprocess.SubprocessError):
            out[fam] = {"family": None, "sha256": None}
    return out


def _inside(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def render_static(html: Path, root: Path, out_png: Path, *, viewport_width: int, scale: float = 1.0, allow_no_sandbox: bool = False,
                  browsers_path: str = "", timeout_s: float = 30.0, collect_boxes: bool = True) -> RenderRecord:
    """Render ``html`` (which must be inside ``root``) to ``out_png`` under the Tier 0 restrictions."""
    try:
        from playwright.sync_api import Error as PWError
        from playwright.sync_api import sync_playwright
    except ImportError as e:  # pragma: no cover
        raise S2CError("S2C-RENDER-001", "Playwright is not installed", "pip install playwright") from e
    html, root = html.resolve(), root.resolve()
    if not _inside(html, root):
        raise S2CError("S2C-PATH-001", "HTML file is outside the project directory")
    if browsers_path:
        os.environ["PLAYWRIGHT_BROWSERS_PATH"] = browsers_path
    blocked: list[str] = []
    warnings: list[str] = []

    def handler(route: Any) -> None:
        url = route.request.url
        u = urlparse(url)
        if u.scheme == "file" and _inside(Path(unquote(u.path)), root):
            route.continue_()
        else:
            blocked.append(url[:200])
            route.abort()

    t0 = time.perf_counter()
    with sync_playwright() as p:
        try:
            browser = p.chromium.launch(chromium_sandbox=not allow_no_sandbox, args=["--disable-extensions"], timeout=timeout_s * 1000)
        except PWError as e:
            msg = str(e).splitlines()[0][:200] if str(e) else "launch failed"
            if "sandbox" in str(e).lower() and not allow_no_sandbox:
                raise S2CError("S2C-RENDER-002", "the Chromium sandbox is unavailable in this environment", "set render.allow_no_sandbox = true only if you accept rendering without the browser sandbox (JavaScript stays disabled and the network blocked)") from e
            raise S2CError("S2C-RENDER-001", f"could not start Chromium: {msg}", "run `screen2code doctor`") from e
        if allow_no_sandbox:
            warnings.append("Chromium sandbox disabled by explicit opt-in (render.allow_no_sandbox)")
        try:
            ctx = browser.new_context(viewport={"width": viewport_width, "height": 800}, device_scale_factor=scale, java_script_enabled=False,
                                      offline=True, accept_downloads=False, service_workers="block", locale="en-US", timezone_id="UTC")
            ctx.route("**/*", handler)
            page = ctx.new_page()
            page.set_default_timeout(timeout_s * 1000)
            page.goto(html.as_uri(), wait_until="load")
            cdp = ctx.new_cdp_session(page)
            size = cdp.send("Page.getLayoutMetrics")["cssContentSize"]
            h = max(1, int(-(-size["height"] // 1)))
            page.set_viewport_size({"width": viewport_width, "height": h})
            out_png.parent.mkdir(parents=True, exist_ok=True)
            page.screenshot(path=str(out_png), full_page=False, animations="disabled")
            boxes: dict[str, dict[str, float]] = {}
            if collect_boxes:
                doc = cdp.send("DOM.getDocument", {"depth": 0})
                ids = cdp.send("DOM.querySelectorAll", {"nodeId": doc["root"]["nodeId"], "selector": "[data-s2c-id]"})["nodeIds"]
                for nid in ids:
                    attrs = cdp.send("DOM.getAttributes", {"nodeId": nid})["attributes"]
                    a = dict(zip(attrs[::2], attrs[1::2]))
                    try:
                        q = cdp.send("DOM.getBoxModel", {"nodeId": nid})["model"]["border"]
                    except PWError:
                        continue  # display:none or otherwise without a box
                    xs, ys = q[0::2], q[1::2]
                    boxes[a["data-s2c-id"]] = {"x": round(min(xs), 2), "y": round(min(ys), 2), "w": round(max(xs) - min(xs), 2), "h": round(max(ys) - min(ys), 2)}
            version = browser.version
        finally:
            browser.close()
    from PIL import Image

    with Image.open(out_png) as im:
        px = {"w": im.width, "h": im.height}
    return RenderRecord(screenshot=str(out_png), viewport_width=viewport_width, scale=scale, css_size={"w": float(viewport_width), "h": float(h)}, pixel_size=px,
                        browser=f"chromium {version}", chromium_sandbox=not allow_no_sandbox, javascript_enabled=False, offline=True,
                        load_ms=round((time.perf_counter() - t0) * 1000, 1), boxes=boxes, blocked_requests=blocked, fonts=resolve_fonts(), warnings=warnings)
