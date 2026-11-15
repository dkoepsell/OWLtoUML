"""Figure exports (spec WS2.4).

Every export draws the same figure as the SVG: PDF and PNG are rendered by
Graphviz from the positioned DOT the SVG came from (UModel.drawing), TikZ
and GraphML read that layout's coordinates, and the text formats (PlantUML,
ontopuml, Mermaid) are written from the model.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from ..model import UModel
from .. import twopass

# name -> (file extension, media type)
FORMATS = {
    "svg": ("svg", "image/svg+xml"),            # interactive (as rendered)
    "svg-static": ("svg", "image/svg+xml"),
    "pdf": ("pdf", "application/pdf"),
    "png": ("png", "image/png"),
    "tikz": ("tex", "application/x-tex"),
    "plantuml": ("puml", "text/plain"),
    "ontopuml": ("puml", "text/plain"),
    "mermaid": ("mmd", "text/plain"),
    "graphml": ("graphml", "application/xml"),
}
DEFAULT_DPI = 200


@dataclass
class Export:
    data: bytes
    ext: str
    mime: str
    warnings: list[str] = field(default_factory=list)


def static_svg(svg: str) -> str:
    """No script, no embedded source: for papers and slides."""
    svg = re.sub(r"<script\b.*?</script>", "", svg, flags=re.S)
    svg = re.sub(r'<(\w+)[^>]*\bid="o2u-source"[^>]*>.*?</\1>', "", svg, flags=re.S)
    return svg


def layout_json(m: UModel) -> dict:
    """Graphviz's -Tjson for the drawing (positions in points, y up)."""
    import json
    d = m.drawing
    if not d:
        raise RuntimeError("render the model first (dot.render_dot_svg)")
    return json.loads(twopass.run(d["program"], d["args"], d["text"], d["env"], "json"))


def export(m: UModel, fmt: str, svg: str | None = None, dpi: int = DEFAULT_DPI,
           graph=None) -> Export:
    """``m`` must have been rendered (render_dot_svg) for every format but the
    text ones; ``svg`` is that rendering. ``graph`` gives CURIEs for ontopuml."""
    if fmt not in FORMATS:
        raise ValueError(f"unknown export format '{fmt}' (formats: {', '.join(FORMATS)})")
    ext, mime = FORMATS[fmt]
    warnings: list[str] = []
    if fmt == "svg":
        data = (svg or "").encode("utf-8")
    elif fmt == "svg-static":
        data = static_svg(svg or "").encode("utf-8")
    elif fmt in ("pdf", "png"):
        d = m.drawing
        if not d:
            raise RuntimeError("render the model first (dot.render_dot_svg)")
        extra = [f"-Gdpi={int(dpi)}"] if fmt == "png" else []
        data = twopass.run(d["program"], d["args"], d["text"], d["env"],
                           "png:cairo" if fmt == "png" else "pdf:cairo", extra=extra)
    elif fmt == "tikz":
        from .positioned import tikz
        data = tikz(m, layout_json(m)).encode("utf-8")
    elif fmt == "graphml":
        from .positioned import graphml
        data = graphml(m, layout_json(m)).encode("utf-8")
    else:
        from . import text
        out = {"plantuml": text.plantuml, "ontopuml": text.ontopuml,
               "mermaid": text.mermaid}[fmt](m, warnings, graph)
        data = out.encode("utf-8")
    return Export(data=data, ext=ext, mime=mime, warnings=warnings)
