"""Bundle the desktop UI (ui/src -> ui/dist) with esbuild. Locates esbuild and React from the environment; no network access.

Usage: python scripts/build_ui.py   (needs node, esbuild, react, react-dom; set S2C_NODE_MODULES to a node_modules directory to override discovery)
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
UI = ROOT / "ui"


def node_modules() -> list[Path]:
    cands = []
    if os.environ.get("S2C_NODE_MODULES"):
        cands.append(Path(os.environ["S2C_NODE_MODULES"]))
    cands.append(UI / "node_modules")
    try:
        cands.append(Path(subprocess.run(["npm", "root", "-g"], capture_output=True, text=True, check=True, shell=(os.name == "nt")).stdout.strip()))
    except Exception:  # noqa: BLE001
        pass
    return [c for c in cands if c.is_dir()]


def find_esbuild(mods: list[Path]) -> Path | None:
    exe = "esbuild.exe" if os.name == "nt" else "esbuild"
    for m in mods:
        for p in (m / ".bin" / exe, m / "esbuild" / "bin" / exe, m / "tsx" / "node_modules" / "esbuild" / "bin" / exe):
            if p.exists():
                return p
        for p in m.glob("**/node_modules/esbuild/bin/" + exe):
            return p
    return None


def build() -> Path:
    mods = node_modules()
    es = find_esbuild(mods)
    if es is None or not mods:
        sys.exit("esbuild or node_modules not found: install node, then `npm install --prefix ui react react-dom esbuild`, or set S2C_NODE_MODULES")
    dist = UI / "dist"
    dist.mkdir(exist_ok=True)
    env = {**os.environ, "NODE_PATH": os.pathsep.join(str(m) for m in mods)}
    cmd = [str(es), str(UI / "src" / "main.tsx"), "--bundle", "--outfile=" + str(dist / "app.js"), "--format=iife", "--target=es2020", "--jsx=automatic",
           "--define:process.env.NODE_ENV=\"production\"", "--minify", "--log-level=warning"]
    subprocess.run(cmd, check=True, env=env)
    shutil.copy(UI / "index.html", dist / "index.html")
    shutil.copy(UI / "src" / "app.css", dist / "app.css")
    shutil.copy(UI / "src" / "host.js", dist / "host.js")
    return dist


if __name__ == "__main__":
    print(build())
