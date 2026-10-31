"""S1 region segmentation (classical CV): recursive container decomposition on flat-colour interfaces.

Method: at each level, estimate the local background, threshold differing pixels, close horizontally to group
glyphs into words/lines, take connected components, then classify each as a fill container, a framed container,
an image-like region, or a leaf. Containers are decomposed recursively with their own background. Everything
produced here is *measured* geometry; roles and layout are inferred later (S5).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import cv2
import numpy as np

T_DIFF = 24  # strong difference: ink, borders
T_LOW = 6    # weak difference: large flat regions that only slightly differ from their surroundings
MAX_DEPTH = 7


@dataclass
class Node:
    x: int
    y: int
    w: int
    h: int
    kind: str  # container | group | leaf | image
    fill: tuple[int, int, int]  # background colour *inside* this node (container) or dominant colour (leaf)
    border_w: int = 0
    border_rgb: tuple[int, int, int] | None = None
    radius: float = 0.0
    children: list["Node"] = field(default_factory=list)
    rid: str = ""
    reading: dict[str, Any] | None = None  # reported OCR reading {value, conf}
    notes: dict[str, Any] = field(default_factory=dict)

    @property
    def rect(self) -> tuple[int, int, int, int]:
        return self.x, self.y, self.w, self.h

    def walk(self):
        yield self
        for c in self.children:
            yield from c.walk()


def _rgb(v: Any) -> tuple[int, int, int]:
    return int(v[0]), int(v[1]), int(v[2])


def dist(a: tuple[int, int, int], b: tuple[int, int, int]) -> int:
    return max(abs(a[0] - b[0]), abs(a[1] - b[1]), abs(a[2] - b[2]))


def dominant(region: np.ndarray) -> tuple[tuple[int, int, int], float]:
    """Most frequent exact colour of ``region`` and its pixel fraction."""
    flat = region.reshape(-1, 3).astype(np.uint32)
    key = (flat[:, 0] << 16) | (flat[:, 1] << 8) | flat[:, 2]
    vals, counts = np.unique(key, return_counts=True)
    i = int(counts.argmax())
    v = int(vals[i])
    return ((v >> 16) & 255, (v >> 8) & 255, v & 255), float(counts[i]) / flat.shape[0]


def colorfulness(region: np.ndarray) -> int:
    q = (region.reshape(-1, 3) >> 4).astype(np.uint32)
    return int(np.unique((q[:, 0] << 8) | (q[:, 1] << 4) | q[:, 2]).size)


def unique_colors(region: np.ndarray) -> int:
    """Exact distinct colours: smooth gradients and photos have hundreds, text on a flat fill only a few dozen."""
    flat = region.reshape(-1, 3).astype(np.uint32)
    return int(np.unique((flat[:, 0] << 16) | (flat[:, 1] << 8) | flat[:, 2]).size)


def _detect_border(region: np.ndarray, fill: tuple[int, int, int]) -> tuple[int, tuple[int, int, int] | None]:
    h, w = region.shape[:2]
    if h < 8 or w < 8:
        return 0, None
    mid_x = slice(w // 4, 3 * w // 4)
    c, frac = dominant(region[0, mid_x].reshape(1, -1, 3))
    if frac < 0.9 or dist(c, fill) <= T_LOW:
        return 0, None
    bottom, _ = dominant(region[h - 1, mid_x].reshape(1, -1, 3))
    left, _ = dominant(region[h // 4 : 3 * h // 4, 0].reshape(1, -1, 3))
    if dist(bottom, c) > 6 or dist(left, c) > 6:
        return 0, None
    b = 1
    while b < min(6, h // 4) and dist(_rgb(np.median(region[b, mid_x], axis=0)), c) <= 6:
        b += 1
    return b, c


def _radius(region: np.ndarray, target: tuple[int, int, int], outside: tuple[int, int, int]) -> float:
    """Corner radius from where the diagonal first leaves the outside colour (circle arc: d = r(1 - 1/sqrt2))."""
    h, w = region.shape[:2]
    limit = min(h, w) // 2
    half = max(T_LOW, dist(target, outside) // 2)
    rs = []
    for (sy, sx, dy, dx) in ((0, 0, 1, 1), (0, w - 1, 1, -1), (h - 1, 0, -1, 1), (h - 1, w - 1, -1, -1)):
        d = 0
        while d < limit and dist(_rgb(region[sy + dy * d, sx + dx * d]), outside) < half:
            d += 1
        rs.append(d / 0.2929 if d else 0.0)
    r = float(np.median(rs))
    return round(min(r, limit), 1) if r >= 1.5 else 0.0


def _classify(rgb: np.ndarray, box: tuple[int, int, int, int], bg: tuple[int, int, int], depth: int) -> Node:
    """Classify a non-flat component as a framed container (same colour as its surroundings), an image, or a leaf."""
    x, y, w, h = box
    reg = rgb[y : y + h, x : x + w]
    fill, frac = dominant(reg)
    if w >= 14 and h >= 14 and w * h >= 144 and depth < MAX_DEPTH and dist(fill, bg) <= T_LOW:
        bw, bc = _detect_border(reg, fill)
        if bw:
            return Node(x, y, w, h, "container", fill, bw, bc, _radius(reg, bc, bg))
    if w >= 32 and h >= 32 and frac < 0.45 and (colorfulness(reg) > 64 or unique_colors(reg) > 150):
        return Node(x, y, w, h, "image", fill)
    return Node(x, y, w, h, "leaf", fill)


def _flat_containers(rgb: np.ndarray, rect: tuple[int, int, int, int], sub: np.ndarray, bg: tuple[int, int, int]) -> list[Node]:
    """Large flat-colour regions that differ from the background are containers (sections, cards, buttons)."""
    x0, y0, _, _ = rect
    key = (sub[..., 0].astype(np.uint32) << 16) | (sub[..., 1].astype(np.uint32) << 8) | sub[..., 2].astype(np.uint32)
    vals, counts = np.unique(key, return_counts=True)
    out: list[Node] = []
    for i in np.argsort(-counts)[:24]:
        if counts[i] < 800:
            break
        v = int(vals[i])
        c = ((v >> 16) & 255, (v >> 8) & 255, v & 255)
        if dist(c, bg) <= T_LOW:
            continue
        n, _, st, _ = cv2.connectedComponentsWithStats((key == v).astype(np.uint8), connectivity=8)
        for j in range(1, n):
            cx, cy, cw, ch, area = (int(q) for q in st[j])
            if area >= 800 and cw >= 14 and ch >= 14 and area / (cw * ch) >= 0.4:
                out.append(_with_border(rgb, Node(x0 + cx, y0 + cy, cw, ch, "container", c), bg))
    return out


def _with_border(rgb: np.ndarray, n: Node, bg: tuple[int, int, int]) -> Node:
    """If a uniform ring of a different colour surrounds the flat region, it is the container's border: grow the box and record it."""
    H, W = rgb.shape[:2]
    if n.x < 1 or n.y < 1 or n.x + n.w >= W or n.y + n.h >= H or n.w < 8 or n.h < 8:
        n.radius = _radius(rgb[n.y : n.y + n.h, n.x : n.x + n.w], n.fill, bg)
        return n
    mx = slice(n.x + n.w // 4, n.x + 3 * n.w // 4)
    c, frac = dominant(rgb[n.y - 1, mx].reshape(1, -1, 3))
    bottom, _ = dominant(rgb[n.y + n.h, mx].reshape(1, -1, 3))
    if frac >= 0.9 and dist(c, n.fill) > T_LOW and dist(c, bg) > T_LOW and dist(bottom, c) <= 6:
        b = 1
        while b < 6 and n.y - 1 - b >= 0 and dist(_rgb(np.median(rgb[n.y - 1 - b, mx], axis=0)), c) <= 6:
            b += 1
        n = Node(n.x - b, n.y - b, n.w + 2 * b, n.h + 2 * b, "container", n.fill, b, c, 0.0)
        n.radius = _radius(rgb[n.y : n.y + n.h, n.x : n.x + n.w], c, bg)
        return n
    n.radius = _radius(rgb[n.y : n.y + n.h, n.x : n.x + n.w], n.fill, bg)
    return n


def _merge_glyphs(boxes: list[tuple[int, int, int, int]]) -> list[tuple[int, int, int, int]]:
    """Group glyph-sized components into words/lines: same-line neighbours within ~0.9 glyph heights, and dots/accents above stems."""
    n = len(boxes)
    parent = list(range(n))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    order = sorted(range(n), key=lambda i: boxes[i][0])
    for ai, i in enumerate(order):
        ax, ay, aw, ah = boxes[i]
        for j in order[ai + 1 :]:
            bx, by, bw, bh = boxes[j]
            hmax = max(ah, bh)
            if bx - (ax + aw) > 0.9 * hmax + 3 and bx > ax + aw:
                break  # sorted by x: later boxes are farther away
            gx = max(0, max(ax, bx) - min(ax + aw, bx + bw))
            gy = max(0, max(ay, by) - min(ay + ah, by + bh))
            yo = max(0, min(ay + ah, by + bh) - max(ay, by)) / max(1, min(ah, bh))
            xo = max(0, min(ax + aw, bx + bw) - max(ax, bx)) / max(1, min(aw, bw))
            if (yo >= 0.5 and gx <= 0.9 * hmax + 2) or (xo >= 0.2 and gy <= 0.5 * hmax + 1):
                parent[find(i)] = find(j)
    groups: dict[int, list[int]] = {}
    for i in range(n):
        groups.setdefault(find(i), []).append(i)
    out = []
    for g in groups.values():
        x0 = min(boxes[i][0] for i in g); y0 = min(boxes[i][1] for i in g)
        x1 = max(boxes[i][0] + boxes[i][2] for i in g); y1 = max(boxes[i][1] + boxes[i][3] for i in g)
        out.append((x0, y0, x1 - x0, y1 - y0))
    return out


def _segment_rect(rgb: np.ndarray, rect: tuple[int, int, int, int], bg: tuple[int, int, int], depth: int, corner_r: float = 0.0) -> list[Node]:
    x0, y0, w0, h0 = rect
    if w0 < 3 or h0 < 3:
        return []
    sub = rgb[y0 : y0 + h0, x0 : x0 + w0].copy()
    if corner_r > 0:  # rounded parent: its outside-corner pixels must not become fake children
        k = min(int(corner_r) + 3, h0 // 2, w0 // 2)
        sub[:k, :k] = bg; sub[:k, -k:] = bg; sub[-k:, :k] = bg; sub[-k:, -k:] = bg
    comps: list[Node] = _flat_containers(rgb, rect, sub, bg) if depth < MAX_DEPTH else []
    diff = np.abs(sub.astype(np.int16) - np.array(bg, dtype=np.int16)).max(axis=2)
    # framed containers: strong-difference components whose surroundings share the background colour
    strong = (diff > T_LOW).astype(np.uint8)  # weak threshold: anti-aliased rounded frames must stay connected
    for c in comps:
        strong[c.y - y0 : c.y - y0 + c.h, c.x - x0 : c.x - x0 + c.w] = 0
    n, _, st, _ = cv2.connectedComponentsWithStats(strong, connectivity=8)
    frames: list[Node] = []
    for i in range(1, n):
        cx, cy, cw, ch, area = (int(v) for v in st[i])
        if cw >= 14 and ch >= 14 and area >= 40:
            nd = _classify(rgb, (x0 + cx, y0 + cy, cw, ch), bg, depth)
            if nd.kind == "container":
                frames.append(nd)
    comps += frames
    # glyph-like leaves and images from what is left
    weak = (diff > T_LOW).astype(np.uint8)
    for c in comps:
        weak[c.y - y0 : c.y - y0 + c.h, c.x - x0 : c.x - x0 + c.w] = 0
    n, _, st, _ = cv2.connectedComponentsWithStats(weak, connectivity=8)
    glyphs: list[tuple[int, int, int, int]] = []
    for i in range(1, n):
        cx, cy, cw, ch, area = (int(v) for v in st[i])
        if area < 3:
            continue
        nd = _classify(rgb, (x0 + cx, y0 + cy, cw, ch), bg, depth)
        if nd.kind == "image":
            comps.append(nd)
        else:
            glyphs.append((x0 + cx, y0 + cy, cw, ch))
    for bx, by, bw, bh in _merge_glyphs(glyphs):
        comps.append(Node(bx, by, bw, bh, "leaf", bg))
    containers = [c for c in comps if c.kind == "container"]
    keep: list[Node] = []
    for c in sorted(comps, key=lambda c: -c.w * c.h):
        inside = any(o is not c and o.x <= c.x and o.y <= c.y and o.x + o.w >= c.x + c.w and o.y + o.h >= c.y + c.h and o.w * o.h > c.w * c.h for o in containers)
        if not inside:
            keep.append(c)
    for c in keep:
        if c.kind == "container":
            ins = c.border_w
            c.children = _segment_rect(rgb, (c.x + ins, c.y + ins, c.w - 2 * ins, c.h - 2 * ins), c.fill, depth + 1, c.radius)
            if not c.children and c.border_w == 0 and c.w * c.h < 24 * 24:
                c.kind = "leaf"
    keep.sort(key=lambda c: (c.y, c.x))
    return keep


def _yrange_overlap(a: Node, b_y0: int, b_y1: int) -> float:
    return max(0, min(a.y + a.h, b_y1) - max(a.y, b_y0)) / max(1, min(a.h, b_y1 - b_y0))


def _group_children(n: Node) -> None:
    """Gestalt grouping of invisible wrappers: rows of siblings and proximity clusters become ``group`` nodes (measured union boxes)."""
    for c in n.children:
        if c.kind in ("container", "group"):
            _group_children(c)
    kids = sorted(n.children, key=lambda c: (c.y, c.x))
    if len(kids) < 2:
        return
    bands: list[list[Node]] = []
    for k in kids:
        for b in bands:
            if _yrange_overlap(k, min(m.y for m in b), max(m.y + m.h for m in b)) >= 0.4:
                b.append(k)
                break
        else:
            bands.append([k])
    out: list[Node] = []
    for b in bands:
        if len(b) == 1:
            out.append(b[0])
            continue
        b.sort(key=lambda c: c.x)
        gaps = [b[i + 1].x - (b[i].x + b[i].w) for i in range(len(b) - 1)]
        clusters: list[list[Node]] = [[b[0]]]
        if len(b) >= 3:
            med = max(float(np.median(gaps)), 1.0)
            for g, k in zip(gaps, b[1:]):
                (clusters.append([k]) if g > max(2.5 * med, 12) else clusters[-1].append(k))
        else:
            clusters = [[k] for k in b] if False else [b]
        members: list[Node] = []
        for cl in clusters:
            if len(cl) == 1:
                members.append(cl[0])
            else:
                x0 = min(m.x for m in cl); y0 = min(m.y for m in cl)
                x1 = max(m.x + m.w for m in cl); y1 = max(m.y + m.h for m in cl)
                members.append(Node(x0, y0, x1 - x0, y1 - y0, "group", n.fill, children=cl))
        # a band that is the only content of the container needs no wrapper; otherwise a single multi-child cluster becomes one group
        if len(clusters) == 1 and len(bands) == 1 and len(b) == len(kids):
            out.extend(cl for cl in b)
        else:
            out.extend(members)
    n.children = sorted(out, key=lambda c: (c.y, c.x))


def segment_image(rgb: np.ndarray) -> Node:
    """Return the region tree; the root is the whole image with its dominant border colour as background."""
    h, w = rgb.shape[:2]
    ring = np.concatenate([rgb[0], rgb[-1], rgb[:, 0], rgb[:, -1]]).reshape(1, -1, 3)
    bg, _ = dominant(ring)
    root = Node(0, 0, w, h, "container", bg)
    root.children = _segment_rect(rgb, (0, 0, w, h), bg, 0)
    _group_children(root)
    return root
