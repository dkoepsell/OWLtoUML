"""Print checks before a static export (spec WS2.5).

* smallest font at print size: the figure is scaled to ``page_width``
  inches; every label must stay at or above 8 pt;
* labels crossed by a line: each edge label's box (from Graphviz's layout)
  against the other edges' curves;
* classes per page.
``--strict`` turns warnings into a non-zero exit for CI.
"""
from __future__ import annotations

import re

MIN_PT = 8.0
MAX_NODES_PER_PAGE = 60
_FONT = re.compile(r'font-size="([\d.]+)"')


def _bezier(pts, steps=8):
    out = []
    for i in range(0, len(pts) - 3, 3):
        p0, p1, p2, p3 = pts[i:i + 4]
        for k in range(steps + 1):
            t = k / steps
            a, b, c, d = (1 - t) ** 3, 3 * t * (1 - t) ** 2, 3 * t * t * (1 - t), t ** 3
            out.append((a * p0[0] + b * p1[0] + c * p2[0] + d * p3[0],
                        a * p0[1] + b * p1[1] + c * p2[1] + d * p3[1]))
    return out


def _xy(p):
    x, y = p.split(",")[:2]
    return float(x), float(y)


def label_crossings(layout: dict, fontsize: float = 10.0) -> int:
    """How many edge labels some other edge's line passes through."""
    curves, boxes = [], []
    for k, e in enumerate(layout.get("edges", [])):
        if "invis" in e.get("style", "") or not e.get("pos"):
            continue
        pts = [_xy(t) for t in e["pos"].split() if not t.startswith(("e,", "s,"))]
        curves.append((k, _bezier(pts) if len(pts) >= 4 else pts))
        for key, lp in (("label", "lp"), ("xlabel", "xlp")):
            if e.get(key) and e.get(lp):
                lines = e[key].replace("\\l", "\\n").split("\\n")
                w = max(len(s) for s in lines) * fontsize * 0.55
                h = len(lines) * fontsize * 1.2
                x, y = _xy(e[lp])
                boxes.append((k, x - w / 2, y - h / 2, x + w / 2, y + h / 2))
    hits = 0
    for k, x0, y0, x1, y1 in boxes:
        pad = 1.0
        if any(j != k and any(x0 + pad < px < x1 - pad and y0 + pad < py < y1 - pad
                              for px, py in pts) for j, pts in curves):
            hits += 1
    return hits


def check(svg: str, layout: dict | None, classes: int, page_width: float = 6.5) -> dict:
    """Findings for a figure: {"warnings": [...], "scale", "min_font_pt", ...}."""
    m = re.search(r'<svg[^>]*\bwidth="([\d.]+)pt"', svg)
    width_pt = float(m.group(1)) if m else 0.0
    scale = min(1.0, page_width * 72 / width_pt) if width_pt else 1.0
    fonts = [float(f) for f in _FONT.findall(svg)]
    smallest = min(fonts) * scale if fonts else None
    crossings = label_crossings(layout) if layout else 0
    warnings = []
    if smallest is not None and smallest < MIN_PT:
        warnings.append(f"smallest text is {smallest:.1f} pt at {page_width:g} in wide "
                        f"(figure scaled to {scale:.0%}); aim for {MIN_PT:g} pt or more "
                        "(try a module view, --aspect, or a wider page)")
    if crossings:
        warnings.append(f"{crossings} label(s) crossed by a line")
    if classes > MAX_NODES_PER_PAGE:
        warnings.append(f"{classes} classes on one page; more than {MAX_NODES_PER_PAGE} "
                        "rarely reads well in print (try --all-modules)")
    return {"warnings": warnings, "scale": round(scale, 3),
            "min_font_pt": round(smallest, 1) if smallest is not None else None,
            "label_crossings": crossings, "classes": classes, "page_width_in": page_width}
