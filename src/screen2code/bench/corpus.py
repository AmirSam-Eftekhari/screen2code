"""Procedural synthetic corpus with known ground truth (BENCHMARKS section 2).

Scenes are generated from a seed by grammars per category. The HTML emitter here is deliberately independent of the
product's generation adapters (inline styles, different structure) so the system cannot learn its own generator's idioms.
Known limitation (stated in every report): synthetic scenes are cleaner and more regular than real sites, and they are rendered
with the same font family the product's font policy uses, so typography results are optimistic.
"""
from __future__ import annotations

import html
import random
from dataclasses import dataclass, field
from typing import Any

DATASET_VERSION = "0.1.0"
CATEGORIES = ("landing", "cards", "form", "navbar", "dashboard", "multicolumn", "typography", "ecommerce")
FONT = '"Liberation Sans", Arial, sans-serif'
WORDS = "design system build ship faster team plan pricing product studio launch grow secure simple modern flexible reliable insights report update account profile settings billing order cart checkout".split()
PRIMARY = ["#2563eb", "#16a34a", "#dc2626", "#7c3aed", "#ea580c", "#0891b2"]
PALETTES = {
    "light": {"bg": "#ffffff", "alt": "#f3f4f8", "surface": "#ffffff", "text": "#1f2937", "muted": "#6b7280", "border": "#d9dde7", "dark": "#18182b", "on_dark": "#e5e7ef"},
    "dark": {"bg": "#0f172a", "alt": "#162036", "surface": "#1e293b", "text": "#e2e8f0", "muted": "#94a3b8", "border": "#334155", "dark": "#0a0f1d", "on_dark": "#cbd5e1"},
}


@dataclass
class El:
    id: str
    kind: str  # box | text | image
    css: dict[str, str]
    children: list["El"] = field(default_factory=list)
    text: str = ""
    gt: dict[str, Any] = field(default_factory=dict)


@dataclass
class Scene:
    id: str
    category: str
    seed: int
    theme: str
    width: int
    root: El
    params: dict[str, Any] = field(default_factory=dict)


class Builder:
    def __init__(self, rng: random.Random, theme: str):
        self.rng, self.pal, self.n = rng, PALETTES[theme], 0
        self.primary = rng.choice(PRIMARY)
        self.radius = rng.choice([0, 4, 6, 8, 10, 12])

    def nid(self) -> str:
        self.n += 1
        return f"gt_{self.n}"

    def words(self, lo: int, hi: int) -> str:
        return " ".join(self.rng.choice(WORDS) for _ in range(self.rng.randint(lo, hi))).capitalize()

    def box(self, children: list[El] | None = None, *, layout: str = "none", axis: str = "column", role: str = "", **css: str) -> El:
        base: dict[str, str] = {"box-sizing": "border-box"}
        if layout == "flex":
            base.update({"display": "flex", "flex-direction": axis})
        elif layout == "grid":
            base["display"] = "grid"
        base.update(css)
        gt = {"kind": "container", "layout": layout if layout != "none" else "none", "axis": axis if layout == "flex" else None, "role": role,
              "fill": css.get("background-color"), "radius": float(css["border-radius"][:-2]) if css.get("border-radius", "").endswith("px") and " " not in css["border-radius"] else 0.0}
        if layout == "grid":
            gt["columns"] = len(css["grid-template-columns"].split("repeat(")[1].split(",")[0].split(")")[0:1]) if False else int(css["grid-template-columns"].split("repeat(")[1].split(",")[0])
        return El(self.nid(), "box", base, children or [], gt=gt)

    def text(self, s: str, size: int, weight: int = 400, color: str | None = None, **css: str) -> El:
        base = {"font-size": f"{size}px", "font-weight": str(weight), "color": color or self.pal["text"], "white-space": "nowrap", "line-height": "1.25"}
        base.update(css)
        return El(self.nid(), "text", base, text=s, gt={"kind": "text", "text": s, "font_size": size, "weight": weight, "color": base["color"]})

    def image(self, w: int, h: int) -> El:
        a, b = self.rng.sample(["#f97316", "#06b6d4", "#8b5cf6", "#22c55e", "#ec4899", "#eab308"], 2)
        return El(self.nid(), "image", {"width": f"{w}px", "height": f"{h}px", "background-image": f"linear-gradient(135deg, {a}, {b})", "flex-shrink": "0"}, gt={"kind": "image", "w": w, "h": h})

    def button(self, label: str, size: int = 16) -> El:
        t = self.text(label, size, 400, "#ffffff")
        return self.box([t], layout="flex", axis="row", role="button", **{"background-color": self.primary, "padding": "12px 24px", "border-radius": f"{self.radius}px", "align-self": "flex-start", "align-items": "center"})

    def card(self, title: str, desc: str, button: bool = False) -> El:
        kids = [self.text(title, 20, 700), self.text(desc, 14, 400, self.pal["muted"], **{"margin-top": "8px"})]
        if button:
            kids.append(self.button("Buy now", 14))
            kids[-1].css["margin-top"] = "14px"
        return self.box(kids, layout="flex", axis="column", role="card", **{"border": f"1px solid {self.pal['border']}", "border-radius": f"{self.radius}px", "padding": "20px", "background-color": self.pal["surface"]})

    def header(self, W: int) -> El:
        logo = self.text(self.words(1, 2).title(), 22, 700, self.pal["on_dark"])
        links = [self.text(w.capitalize(), 15, 400, self.pal["on_dark"]) for w in self.rng.sample(WORDS, self.rng.randint(3, 4))]
        nav = self.box(links, layout="flex", axis="row", **{"gap": "28px"})
        return self.box([logo, nav], layout="flex", axis="row", role="header", **{"justify-content": "space-between", "align-items": "center", "padding": "20px 40px", "background-color": self.pal["dark"]})


def make_scene(category: str, seed: int, theme: str | None = None, width: int = 1000) -> Scene:
    rng = random.Random(f"{category}:{seed}")
    theme = theme or rng.choice(["light", "light", "dark"])
    b = Builder(rng, theme)
    p = b.pal
    page: list[El] = []
    if category == "landing":
        page.append(b.header(width))
        h1 = b.text(b.words(2, 3), rng.choice([36, 40, 44, 48]), 700)
        hero = b.box([h1, b.text(b.words(4, 6), rng.choice([16, 18]), 400, p["muted"], **{"margin-top": "14px"}), b.button("Get started", 16)], layout="flex", axis="column",
                     **{"padding": "56px 40px", "background-color": p["alt"], "gap": "18px"})
        cards = [b.card(b.words(1, 2), b.words(3, 4)) for _ in range(3)]
        grid = b.box(cards, layout="grid", **{"grid-template-columns": "repeat(3, 1fr)", "gap": "24px", "padding": "40px"})
        footer = b.box([b.text("Copyright 2026 " + b.words(1, 2), 13, 400, p["on_dark"])], layout="flex", axis="row", **{"padding": "24px 40px", "background-color": p["dark"]})
        page += [hero, grid, footer]
    elif category == "cards":
        n = rng.choice([2, 3, 4])
        title = b.text(b.words(2, 3), 32, 700)
        grid = b.box([b.card(b.words(1, 2), b.words(3, 4), button=True) for _ in range(n)], layout="grid", **{"grid-template-columns": f"repeat({n}, 1fr)", "gap": "24px", "margin-top": "28px"})
        page.append(b.box([title, grid], layout="flex", axis="column", **{"padding": "48px 40px"}))
    elif category == "form":
        fields = []
        for _ in range(rng.choice([2, 3, 4])):
            label = b.text(b.words(1, 2), 14, 700)
            inp = b.box([b.text(b.words(1, 2), 15, 400, p["muted"])], layout="flex", axis="row", **{"border": f"1px solid {p['border']}", "border-radius": f"{b.radius}px", "padding": "10px 12px", "background-color": p["surface"], "margin-top": "6px"})
            fields.append(b.box([label, inp], layout="flex", axis="column"))
        form = b.box([b.text(b.words(2, 3), 28, 700)] + fields + [b.button("Submit", 16)], layout="flex", axis="column", **{"gap": "18px", "width": "480px", "padding": "40px"})
        page.append(form)
    elif category == "navbar":
        links = [b.text(w.capitalize(), 15, 400) for w in rng.sample(WORDS, 4)]
        nav = b.box([b.text(b.words(1, 2).title(), 22, 700), b.box(links, layout="flex", axis="row", **{"gap": "26px"}), b.button("Sign up", 14)], layout="flex", axis="row",
                    **{"justify-content": "space-between", "align-items": "center", "padding": "16px 40px", "background-color": p["surface"], "border-bottom": f"1px solid {p['border']}"})
        page += [nav, b.box([b.text(b.words(2, 4), 40, 700), b.text(b.words(5, 7), 18, 400, p["muted"], **{"margin-top": "14px"})], layout="flex", axis="column", **{"padding": "80px 40px"})]
    elif category == "dashboard":
        menu = b.box([b.text(w.capitalize(), 15, 400, p["on_dark"]) for w in rng.sample(WORDS, 5)], layout="flex", axis="column", **{"gap": "18px"})
        side = b.box([b.text("Console", 20, 700, p["on_dark"], **{"margin-bottom": "28px"}), menu], layout="flex", axis="column", **{"width": "220px", "padding": "28px 24px", "background-color": p["dark"], "flex-shrink": "0", "min-height": "560px"})
        stats = [b.box([b.text(str(rng.randint(100, 9999)), 28, 700), b.text(b.words(1, 2), 13, 400, p["muted"], **{"margin-top": "6px"})], layout="flex", axis="column", role="card",
                       **{"border": f"1px solid {p['border']}", "border-radius": f"{b.radius}px", "padding": "18px", "background-color": p["surface"]}) for _ in range(3)]
        main = b.box([b.text(b.words(1, 2), 26, 700), b.box(stats, layout="grid", **{"grid-template-columns": "repeat(3, 1fr)", "gap": "20px", "margin-top": "22px"})], layout="flex", axis="column", **{"padding": "32px", "flex-grow": "1"})
        page.append(b.box([side, main], layout="flex", axis="row", **{"width": f"{width}px"}))
    elif category == "multicolumn":
        left = b.box([b.text(b.words(4, 6), 16, 400, p["muted"]) for _ in range(3)], layout="flex", axis="column", **{"gap": "12px", "width": "560px"})
        right = b.card(b.words(1, 2), b.words(3, 4))
        right.css["width"] = "280px"
        page.append(b.box([b.text(b.words(2, 4), 32, 700), b.box([left, right], layout="flex", axis="row", **{"gap": "40px", "margin-top": "24px"})], layout="flex", axis="column", **{"padding": "48px 40px"}))
    elif category == "typography":
        items = [b.text(b.words(2, 3), 40, 700), b.text(b.words(2, 4), 32, 700), b.text(b.words(3, 4), 24, 700), b.text(b.words(3, 5), 20, 700)]
        items += [b.text(b.words(5, 7), s, 400, c, **{"margin-top": "6px"}) for s, c in ((16, p["text"]), (14, p["muted"]), (13, p["muted"]))]
        page.append(b.box(items, layout="flex", axis="column", **{"padding": "48px 40px", "gap": "14px"}))
    elif category == "ecommerce":
        page.append(b.header(width))
        n = rng.choice([3, 4])
        prods = []
        for _ in range(n):
            price = b.text(f"${rng.randint(9, 199)}.00", 18, 700, b.primary, **{"margin-top": "4px"})
            prods.append(b.box([b.image(rng.choice([180, 200]), 150), b.text(b.words(1, 2), 16, 700, **{"margin-top": "10px"}), price, b.button("Add to cart", 14)], layout="flex", axis="column", role="card",
                               **{"border": f"1px solid {p['border']}", "border-radius": f"{b.radius}px", "padding": "14px", "background-color": p["surface"], "gap": "6px"}))
        page.append(b.box(prods, layout="grid", **{"grid-template-columns": f"repeat({n}, 1fr)", "gap": "22px", "padding": "36px 40px"}))
    else:
        raise ValueError(f"unknown category {category!r}")
    root = El("gt_root", "box", {"width": f"{width}px", "background-color": p["bg"], "font-family": FONT, "color": p["text"]}, page, gt={"kind": "container", "layout": "flex", "axis": "column", "role": "page"})
    return Scene(f"{category}-{seed}", category, seed, theme, width, root, {"primary": b.primary, "radius": b.radius})


def emit_html(scene: Scene) -> str:
    """Independent emitter: inline styles only, ids as data attributes (used for ground-truth boxes)."""
    def one(e: El, ind: int) -> str:
        style = "; ".join(f"{k}: {v}" for k, v in e.css.items())
        pad = "  " * ind
        if e.kind == "text":
            return f'{pad}<div data-s2c-id="{e.id}" style="{style}">{html.escape(e.text)}</div>\n'
        kids = "".join(one(c, ind + 1) for c in e.children)
        return f'{pad}<div data-s2c-id="{e.id}" style="{style}">\n{kids}{pad}</div>\n'

    body = one(scene.root, 1)
    return (f'<!doctype html><html lang="en"><head><meta charset="utf-8"><title>{scene.id}</title>'
            f'<style>*{{margin:0}} body{{background:{PALETTES[scene.theme]["bg"]};font-family:{FONT}}}</style></head><body>\n{body}</body></html>\n')


def ground_truth(scene: Scene) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []

    def walk(e: El, depth: int) -> None:
        out.append({"id": e.id, "depth": depth, **e.gt})
        for c in e.children:
            walk(c, depth + 1)

    walk(scene.root, 0)
    page_bg = (scene.root.css.get("background-color") or "").lower()
    by_id = {e["id"]: e for e in out}

    def has_border(e: El) -> bool:
        return any(k.startswith("border") and k != "border-radius" for k in e.css)

    def mark(e: El) -> None:  # a container is "visible" if a viewer can see its edge: a border or a fill different from the page background
        by_id[e.id]["visible"] = e.kind == "box" and e.id != "gt_root" and (has_border(e) or (e.css.get("background-color", page_bg).lower() != page_bg))
        for c in e.children:
            mark(c)

    mark(scene.root)
    return out


def smoke_scenes(seed: int, per_category: int = 1) -> list[Scene]:
    return [make_scene(c, seed * 1000 + i) for c in CATEGORIES for i in range(per_category)]
