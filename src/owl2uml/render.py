"""Render a laid-out UModel to an SVG string."""
from __future__ import annotations

from html import escape

from .model import UModel, UClass
from .layout import TITLE_H, ROW_H
from .postprocess import DEFAULT_COLOR, shade, tint

FONT = "Helvetica, Arial, sans-serif"


def _center(c: UClass) -> tuple[float, float]:
    return c.x + c.w / 2, c.y + c.h / 2


def _border_point(c: UClass, tx: float, ty: float) -> tuple[float, float]:
    """Intersection of the segment from c's center toward (tx,ty) with c's edge."""
    cx, cy = _center(c)
    dx, dy = tx - cx, ty - cy
    if dx == 0 and dy == 0:
        return cx, cy
    hw, hh = c.w / 2, c.h / 2
    # Scale so the segment just reaches the box border.
    sx = hw / abs(dx) if dx else float("inf")
    sy = hh / abs(dy) if dy else float("inf")
    s = min(sx, sy)
    return cx + dx * s, cy + dy * s


def _class_svg(c: UClass, color: str = DEFAULT_COLOR) -> str:
    stereo = c.stereotype or ("unsatisfiable" if c.unsatisfiable else
                              "defined" if c.defined else "")
    if c.unsatisfiable:
        color = "#c0392b"
    header_h = TITLE_H + (ROW_H if stereo else 0)
    header_bg = "#eef6ee" if color.lower() == DEFAULT_COLOR else tint(color)
    icon_border = "#5b9a5b" if color.lower() == DEFAULT_COLOR else shade(color)
    parts = [
        '<g>',
        # white body
        f'<rect x="{c.x:.1f}" y="{c.y:.1f}" width="{c.w:.1f}" height="{c.h:.1f}" '
        f'rx="3" fill="#ffffff" stroke="none"/>',
        # pale green header band
        f'<rect x="{c.x:.1f}" y="{c.y:.1f}" width="{c.w:.1f}" height="{header_h:.1f}" '
        f'fill="{header_bg}" stroke="none"/>',
        # rounded outline drawn on top so header corners stay clean
        f'<rect x="{c.x:.1f}" y="{c.y:.1f}" width="{c.w:.1f}" height="{c.h:.1f}" '
        f'rx="3" fill="none" stroke="#a0a0a0" stroke-width="1.2"/>',
    ]
    ty = c.y
    if stereo:
        parts.append(
            f'<text x="{c.x + c.w/2:.1f}" y="{ty + 14:.1f}" font-size="10" '
            f'font-style="italic" font-family="{FONT}" fill="#555" '
            f'text-anchor="middle">&#171;{escape(stereo)}&#187;</text>'
        )
        ty += ROW_H
    # green "C" class icon at the left of the name, mimicking PlantUML
    icon_cx = c.x + 15
    icon_cy = ty + 11
    parts.append(
        f'<circle cx="{icon_cx:.1f}" cy="{icon_cy:.1f}" r="7.5" '
        f'fill="{color}" stroke="{icon_border}" stroke-width="1"/>'
    )
    parts.append(
        f'<text x="{icon_cx:.1f}" y="{icon_cy + 3.5:.1f}" font-size="9.5" '
        f'font-weight="bold" font-family="{FONT}" fill="#ffffff" '
        f'text-anchor="middle">C</text>'
    )
    parts.append(
        f'<text x="{c.x + c.w/2 + 8:.1f}" y="{ty + 17:.1f}" font-size="13" '
        f'font-weight="bold" font-family="{FONT}" fill="#1a1a1a" '
        f'text-anchor="middle">{escape(c.name)}</text>'
    )
    title_bottom = ty + TITLE_H
    if c.attrs:
        parts.append(
            f'<line x1="{c.x:.1f}" y1="{title_bottom:.1f}" '
            f'x2="{c.x + c.w:.1f}" y2="{title_bottom:.1f}" stroke="#a0a0a0"/>'
        )
        ay = title_bottom + 14
        for a in c.attrs:
            parts.append(
                f'<text x="{c.x + 8:.1f}" y="{ay:.1f}" font-size="11.5" '
                f'font-family="{FONT}" fill="#222">{escape(a.label())}</text>'
            )
            ay += ROW_H
    parts.append("</g>")
    return "\n".join(parts)


def _edge_svg(m: UModel, e) -> str:
    src = m.classes.get(e.src)
    dst = m.classes.get(e.dst)
    if not src or not dst:
        return ""
    scx, scy = _center(src)
    dcx, dcy = _center(dst)
    x1, y1 = _border_point(src, dcx, dcy)
    x2, y2 = _border_point(dst, scx, scy)

    if e.kind == "inferred":
        return (
            f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" '
            f'stroke="#d9822b" stroke-width="2" marker-end="url(#tri)"/>'
        )
    if e.kind in ("generalization", "definition", "equivalent"):
        dash = ' stroke-dasharray="6 4"' if e.kind != "generalization" else ""
        marker = "" if e.kind == "equivalent" else ' marker-end="url(#tri)"'
        line = (
            f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" '
            f'stroke="#33312e" stroke-width="1.2"{dash}{marker}/>'
        )
        return line
    # association / restriction
    dash = ' stroke-dasharray="6 4"' if e.kind == "restriction" else ""
    line = (
        f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" '
        f'stroke="#3a5a8c" stroke-width="1.2"{dash} marker-end="url(#arrow)"/>'
    )
    if e.label:
        e_label = e.label.replace("\n", " / ")
        mx, my = (x1 + x2) / 2, (y1 + y2) / 2
        w = len(e_label) * 6.2 + 6
        bg = (
            f'<rect x="{mx - w/2:.1f}" y="{my - 9:.1f}" width="{w:.1f}" '
            f'height="14" fill="#ffffff" opacity="0.85"/>'
        )
        txt = (
            f'<text x="{mx:.1f}" y="{my + 2:.1f}" font-size="10.5" '
            f'font-family="{FONT}" fill="#3a5a8c" text-anchor="middle">'
            f'{escape(e_label)}</text>'
        )
        return line + "\n" + bg + "\n" + txt
    return line


_DEFS = """  <defs>
    <marker id="tri" markerWidth="16" markerHeight="14" refX="14" refY="7"
            orient="auto" markerUnits="userSpaceOnUse">
      <path d="M0,0 L14,7 L0,14 Z" fill="#fffdf5" stroke="#33312e" stroke-width="1.2"/>
    </marker>
    <marker id="arrow" markerWidth="12" markerHeight="12" refX="9" refY="5"
            orient="auto" markerUnits="userSpaceOnUse">
      <path d="M0,0 L10,5 L0,10" fill="none" stroke="#3a5a8c" stroke-width="1.4"/>
    </marker>
  </defs>"""


def render_svg(m: UModel, width: float, height: float) -> str:
    body = []
    # edges first (under boxes), then boxes on top
    for e in m.edges:
        s = _edge_svg(m, e)
        if s:
            body.append(s)
    for c in m.classes.values():
        g = m.groups.get(c.group)
        body.append(_class_svg(c, g.color if g and g.color else DEFAULT_COLOR))

    return (
        f'<?xml version="1.0" encoding="UTF-8"?>\n'
        f'<svg xmlns="http://www.w3.org/2000/svg" '
        f'width="{width:.0f}" height="{height:.0f}" '
        f'viewBox="0 0 {width:.0f} {height:.0f}" font-family="{FONT}">\n'
        f'  <rect width="100%" height="100%" fill="#f7f5ef"/>\n'
        f'{_DEFS}\n'
        + "\n".join(body)
        + "\n</svg>\n"
    )
