"""Exports that need the drawing's coordinates: TikZ and GraphML.

Both read Graphviz's -Tjson of the positioned drawing (points, y up), so the
figure matches the SVG. (dot2tex cannot read the HTML-table class boxes, so
TikZ is written here.)
"""
from __future__ import annotations

from xml.sax.saxutils import escape as xml_escape

from ..model import UModel

TIKZ_STYLES = r"""% owl2uml TikZ styles: one per kind of line and box (edit to taste)
\usetikzlibrary{arrows.meta,shapes.multipart}
\definecolor{o2uline}{HTML}{33312E}
\definecolor{o2ublue}{HTML}{3A5A8C}
\definecolor{o2ured}{HTML}{C0392B}
\definecolor{o2uorange}{HTML}{D9822B}
\definecolor{o2uhead}{HTML}{EEF6EE}
\definecolor{o2ugrey}{HTML}{9A968C}
\tikzset{
  o2u class/.style={draw=o2ugrey, fill=white, rectangle split, rectangle split parts=2,
    rectangle split part fill={o2uhead,white}, align=left, inner sep=3pt, font=\sffamily\small},
  o2u plain/.style={draw=o2ugrey, fill=o2uhead, align=center, inner sep=3pt, font=\sffamily\small},
  o2u context/.style={o2u plain, fill=black!6, text=black!55},
  o2u anon/.style={circle, draw=o2uline, fill=white, inner sep=1pt, font=\small},
  o2u individual/.style={draw=o2uline, fill=white, inner sep=3pt, font=\sffamily\small},
  o2u generalization/.style={draw=o2uline, -{Triangle[open,length=7pt,width=7pt]}},
  o2u definition/.style={o2u generalization, dashed},
  o2u inferred/.style={o2u generalization, draw=o2uorange, line width=1pt},
  o2u trunk/.style={draw=o2uline},
  o2u association/.style={draw=o2ublue, -{Stealth[length=5pt]}},
  o2u restriction/.style={o2u association, dashed},
  o2u self/.style={o2u association},
  o2u equivalent/.style={draw=o2uline, dashed},
  o2u disjoint/.style={draw=o2ured, dotted, line width=0.8pt},
  o2u member/.style={draw=o2uline, dashed},
  o2u label/.style={font=\sffamily\scriptsize, text=o2ublue, align=center},
}
"""

_TEX_SPECIAL = {"\\": r"\textbackslash{}", "&": r"\&", "%": r"\%", "$": r"\$", "#": r"\#",
                "_": r"\_", "{": r"\{", "}": r"\}", "~": r"\textasciitilde{}",
                "^": r"\textasciicircum{}"}
_TEX_GLYPHS = {"⊥": r"$\bot$", "⊔": r"$\sqcup$", "¬": r"$\neg$", "∘": r"$\circ$",
               "↔": r"$\leftrightarrow$", "⁺": r"$^{+}$", "⁻¹": r"$^{-1}$", "¹": r"$^{1}$",
               "≡": r"$\equiv$", "⊒": r"$\sqsupseteq$", "→": r"$\rightarrow$", "…": r"\ldots{}",
               "«": r"\guillemotleft{}", "»": r"\guillemotright{}", "∃": r"$\exists$",
               "∀": r"$\forall$", "≥": r"$\geq$", "≤": r"$\leq$"}


def tex(text: str) -> str:
    out = "".join(_TEX_SPECIAL.get(ch, ch) for ch in text)
    for k, v in _TEX_GLYPHS.items():
        out = out.replace(k, v)
    return out.replace("\n", r"\\ ")


def _xy(p: str) -> tuple[float, float]:
    x, y = p.split(",")[:2]
    return float(x), float(y)


def _spline(pos: str):
    """(points, end tip or None) from a Graphviz edge pos."""
    tip = None
    pts = []
    for tok in pos.split():
        if tok.startswith(("e,", "s,")):
            if tok[0] == "e":
                tip = _xy(tok[2:])
            continue
        pts.append(_xy(tok))
    return pts, tip


def _objects(layout: dict):
    return {o["_gvid"]: o for o in layout.get("objects", [])}


def _kind(cls: str) -> str:
    for k in ("trunk", "generalization", "definition", "inferred", "association", "restriction",
              "self", "equivalent", "disjoint", "member"):
        if f"rel-{k}" in cls:
            return k
    return "association"


def tikz(m: UModel, layout: dict) -> str:
    """A standalone LaTeX document with the figure as a tikzpicture."""
    by_name = {f"n{i}": cid for i, cid in enumerate(m.classes)}
    objs = _objects(layout)
    body = [r"\begin{tikzpicture}[x=1pt, y=1pt]"]
    for o in layout.get("objects", []):
        name, pos = o.get("name", ""), o.get("pos")
        if not pos:
            continue
        x, y = _xy(pos)
        if name.startswith("j"):
            body.append(f"  \\coordinate ({name}) at ({x:.1f},{y:.1f});")
            continue
        cid = by_name.get(name)
        if not cid:
            continue          # the key is not part of the TikZ figure
        c = m.classes[cid]
        w = float(o.get("width", 1)) * 72
        if c.kind in ("union", "complement", "disjoint"):
            node = f"[o2u anon] ({name}) at ({x:.1f},{y:.1f}) {{{tex(c.name)}}}"
        elif c.kind == "individual":
            node = f"[o2u individual] ({name}) at ({x:.1f},{y:.1f}) {{\\underline{{{tex(c.name)}}}}}"
        else:
            st = c.stereotype or ("defined" if c.defined else "deprecated" if c.deprecated else "")
            head = (f"{{\\scriptsize\\guillemotleft{{}}{tex(st)}\\guillemotright{{}}}}\\\\ "
                    if st else "") + (f"\\textbf{{{tex(c.name)}}}" if not c.context
                                      else tex(c.name))
            style = "o2u context" if c.context else "o2u class" if c.attrs else "o2u plain"
            width = f", minimum width={w:.0f}pt, text width={max(w - 8, 20):.0f}pt"
            if c.attrs:
                attrs = r"\\ ".join(tex(a.label()) for a in c.attrs)
                node = (f"[{style}{width}] ({name}) at ({x:.1f},{y:.1f}) "
                        f"{{{head}\\nodepart{{two}}{attrs}}}")
            else:
                node = f"[{style}{width}] ({name}) at ({x:.1f},{y:.1f}) {{{head}}}"
        body.append(f"  \\node{node};")
    for e in layout.get("edges", []):
        if "invis" in e.get("style", "") or not e.get("pos"):
            continue
        t, h = objs.get(e["tail"], {}), objs.get(e["head"], {})
        if t.get("name") == "legend" or h.get("name") == "legend":
            continue
        pts, tip = _spline(e["pos"])
        if len(pts) < 2:
            continue
        kind = _kind(e.get("class", ""))
        if e.get("arrowhead") == "none" and kind == "generalization":
            kind = "trunk"
        path = f"({pts[0][0]:.1f},{pts[0][1]:.1f})"
        for i in range(1, len(pts) - 2, 3):
            (a, b), (c2, d), (x3, y3) = pts[i], pts[i + 1], pts[i + 2]
            path += f" .. controls ({a:.1f},{b:.1f}) and ({c2:.1f},{d:.1f}) .. ({x3:.1f},{y3:.1f})"
        if tip:
            path += f" -- ({tip[0]:.1f},{tip[1]:.1f})"
        body.append(f"  \\draw[o2u {kind}] {path};")
        for key, lp in (("label", "lp"), ("xlabel", "xlp"), ("headlabel", "head_lp")):
            if e.get(key) and e.get(lp):
                lx, ly = _xy(e[lp])
                body.append(f"  \\node[o2u label] at ({lx:.1f},{ly:.1f}) {{{tex(_plain(e[key]))}}};")
    body.append(r"\end{tikzpicture}")
    return ("% Generated by owl2uml. Compile with pdflatex.\n"
            "\\documentclass[tikz,border=4pt]{standalone}\n\\usepackage[T1]{fontenc}\n"
            "\\usepackage{amssymb}\n% --- preamble: styles ---\n" + TIKZ_STYLES +
            "% --- end of preamble ---\n\\begin{document}\n" + "\n".join(body) +
            "\n\\end{document}\n")


def _plain(label: str) -> str:
    """Graphviz label text without escapes ("\\n" between merged labels)."""
    return label.replace("\\n", "\n").replace("\\l", "\n").strip()


def graphml(m: UModel, layout: dict) -> str:
    """GraphML for yEd, with positions, sizes and labels."""
    by_name = {f"n{i}": cid for i, cid in enumerate(m.classes)}
    objs = _objects(layout)
    out = ['<?xml version="1.0" encoding="UTF-8"?>',
           '<graphml xmlns="http://graphml.graphdrawing.org/xmlns" '
           'xmlns:y="http://www.yworks.com/xml/graphml" '
           'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">',
           '  <key id="d0" for="node" yfiles.type="nodegraphics"/>',
           '  <key id="d1" for="edge" yfiles.type="edgegraphics"/>',
           '  <key id="d2" for="node" attr.name="iri" attr.type="string"/>',
           '  <key id="d3" for="edge" attr.name="kind" attr.type="string"/>',
           '  <graph id="G" edgedefault="directed">']
    top = max((_xy(o["pos"])[1] for o in objs.values() if o.get("pos")), default=0)
    for o in layout.get("objects", []):
        name = o.get("name", "")
        cid = by_name.get(name)
        if not cid or not o.get("pos"):
            continue
        c = m.classes[cid]
        x, y = _xy(o["pos"])
        w, h = float(o.get("width", 1)) * 72, float(o.get("height", 0.5)) * 72
        text = c.name + "".join("\n" + a.label() for a in c.attrs)
        fill = "#E8E6E0" if c.context or c.deprecated else "#EEF6EE"
        shape = "ellipse" if c.kind in ("union", "complement", "disjoint") else "rectangle"
        # yEd: top-left corner, y down
        out += [f'    <node id="{name}">',
                f'      <data key="d2">{xml_escape(cid)}</data>',
                '      <data key="d0"><y:ShapeNode>',
                f'        <y:Geometry x="{x - w / 2:.1f}" y="{top - y - h / 2:.1f}" '
                f'width="{w:.1f}" height="{h:.1f}"/>',
                f'        <y:Fill color="{fill}"/><y:BorderStyle color="#8A8780" width="1.0"/>',
                f'        <y:NodeLabel>{xml_escape(text)}</y:NodeLabel>',
                f'        <y:Shape type="{shape}"/>',
                '      </y:ShapeNode></data>', '    </node>']
    for k, e in enumerate(layout.get("edges", [])):
        t, h = objs.get(e["tail"], {}).get("name"), objs.get(e["head"], {}).get("name")
        if t not in by_name or h not in by_name or "invis" in e.get("style", ""):
            continue
        kind = _kind(e.get("class", ""))
        line = "dashed" if kind in ("definition", "restriction", "equivalent", "member") else \
            "dotted" if kind == "disjoint" else "line"
        arrow = "white_delta" if kind in ("generalization", "definition", "inferred") else \
            "none" if kind in ("disjoint", "member", "equivalent") else "standard"
        label = _plain(e.get("label") or e.get("xlabel") or "")
        out += [f'    <edge id="e{k}" source="{t}" target="{h}">',
                f'      <data key="d3">{kind}</data>',
                '      <data key="d1"><y:PolyLineEdge>',
                f'        <y:LineStyle type="{line}" color="{_edge_color(kind)}" width="1.0"/>',
                f'        <y:Arrows source="none" target="{arrow}"/>']
        if label:
            out.append(f"        <y:EdgeLabel>{xml_escape(label)}</y:EdgeLabel>")
        out += ['      </y:PolyLineEdge></data>', '    </edge>']
    out += ["  </graph>", "</graphml>"]
    return "\n".join(out) + "\n"


def _edge_color(kind: str) -> str:
    return {"disjoint": "#C0392B", "inferred": "#D9822B", "association": "#3A5A8C",
            "restriction": "#3A5A8C", "self": "#3A5A8C"}.get(kind, "#33312E")


