"""Render a UModel to SVG via Graphviz `dot` (scalable layered layout).

Locates a `dot` binary either on PATH or in the project-local prefix
(`.local/`) created by scripts/setup.sh, and renders UML class boxes using
Graphviz HTML-like table labels.
"""
from __future__ import annotations

import subprocess
from html import escape as _h
from pathlib import Path

from .source import embed as embed_source
from .model import UModel, UClass
from .postprocess import DEFAULT_COLOR, UPPER_COLOR, shade, tint
from .tools import graphviz

_ROOT = Path(__file__).resolve().parents[2]
_PREFIX = _ROOT / ".local"


def _gv() -> tuple[str | None, dict | None]:
    """Return (dot_path, env) — local prefix first, then system PATH."""
    return graphviz("dot")


def dot_available() -> bool:
    return _gv()[0] is not None


def _attr(s: str) -> str:
    """Escape a value used inside a double-quoted DOT string."""
    return s.replace("\\", "\\\\").replace('"', '\\"')


# Wrap class titles longer than this (in characters) onto multiple lines.
# rdfs:labels can be whole phrases ("inference from background scientific
# knowledge"); without wrapping a single box would stretch across the diagram.
_WRAP_AT = 24


def _wrap(text: str, width: int = _WRAP_AT) -> list[str]:
    """Greedy word-wrap; falls back to hard-splitting tokens longer than width."""
    lines: list[str] = []
    cur = ""
    for word in text.split():
        while len(word) > width:
            head, word = word[:width], word[width:]
            if cur:
                lines.append(cur)
                cur = ""
            lines.append(head)
        if not cur:
            cur = word
        elif len(cur) + 1 + len(word) <= width:
            cur += " " + word
        else:
            lines.append(cur)
            cur = word
    if cur:
        lines.append(cur)
    return lines or [text]


# PlantUML-style palette for class boxes: light border, faint green-tinted
# header, white body, and a green disc "C" class icon.
_BORDER = "#A0A0A0"
_HEADER_BG = "#EEF6EE"
_BODY_BG = "#FFFFFF"
_ICON_BG = "#84BE84"
_ICON_BORDER = "#5B9A5B"


def _icon(color: str = _ICON_BG) -> str:
    """A small rounded 'C' badge, mimicking PlantUML's class icon.

    Coloured by the class's group (namespace / IRI prefix) when there is more
    than one group, so the patterns or modules of an ontology read at a glance.
    """
    border = _ICON_BORDER if color.lower() == _ICON_BG.lower() else shade(color)
    return (
        f'<table border="1" color="{border}" cellborder="0" '
        f'cellspacing="0" cellpadding="0" bgcolor="{color}" style="rounded">'
        '<tr><td width="15" height="15" align="center">'
        '<font color="white" point-size="10"><b>C</b></font>'
        '</td></tr></table>'
    )


_DEPRECATED = "#9a968c"
_DEF_WRAP = 34


def _label(c: UClass, color: str = "", definitions: bool = False) -> str:
    """HTML-like table label for one UML class box (PlantUML-style)."""
    color = color or _ICON_BG
    header_bg = _HEADER_BG if color.lower() == _ICON_BG.lower() else tint(color)
    if c.deprecated:
        color, header_bg = _DEPRECATED, "#e8e6e0"
    title = ""
    stereo = c.stereotype or ("unsatisfiable" if c.unsatisfiable else
                              "defined" if c.defined else "")
    if c.unsatisfiable:
        color, header_bg = "#c0392b", "#f6d5d1"
    if stereo:
        title += f'<font point-size="9">&#171;{_h(stereo)}&#187;</font><br/>'
    if c.deprecated:
        title += '<font point-size="9">&#171;deprecated&#187;</font><br/>'
        title += "<br/>".join(f'<s><font color="#6b675e">{_h(line)}</font></s>'
                              for line in _wrap(c.name))
    else:
        title += "<br/>".join(f"<b>{_h(line)}</b>" for line in _wrap(c.name))
    # Header: green class icon to the left of the (optionally stereotyped) name.
    header = (
        '<table border="0" cellborder="0" cellspacing="0" cellpadding="0"><tr>'
        f'<td valign="middle">{_icon(color)}</td>'
        '<td width="6"></td>'
        f'<td valign="middle">{title}</td>'
        '</tr></table>'
    )
    rows = [
        f'<table border="1" color="{_BORDER}" cellborder="0" cellspacing="0" '
        f'cellpadding="6" bgcolor="{_BODY_BG}">',
        f'<tr><td bgcolor="{header_bg}" align="center">{header}</td></tr>',
    ]
    if definitions and c.definition:
        lines = _wrap(c.definition, _DEF_WRAP)
        if len(lines) > 3:
            lines = lines[:3]
            lines[-1] = lines[-1].rstrip(".,;") + " …"
        text = "<br/>".join(_h(ln) for ln in lines)
        rows.append(f'<tr><td align="left" balign="left"><font point-size="9" '
                    f'color="#55524b"><i>{text}</i></font></td></tr>')
    if c.attrs:
        rows.append("<hr/>")
        body = "<br/>".join(_h(a.label()) for a in c.attrs)
        rows.append(f'<tr><td align="left" balign="left">{body}</td></tr>')
    rows.append("</table>")
    return "".join(rows)


_ANON_STYLE = {
    # kind: (glyph colour, tooltip)
    "union": ("#33312e", "union (or) of the classes it links to"),
    "complement": ("#33312e", "complement (not) of the class it links to"),
    "disjoint": ("#c0392b", "these classes are pairwise disjoint"),
}


def _node(nid: str, cid: str, c: UClass, color: str, gcls: str, defcls: str,
          definitions: bool) -> str:
    """One DOT node statement for a class, an anonymous expression or an individual."""
    if c.kind in _ANON_STYLE:
        ink, tip = _ANON_STYLE[c.kind]
        return (f'  {nid} [shape=circle, fixedsize=true, width=0.32, label="{_attr(c.name)}", '
                f'fontsize=15, fontcolor="{ink}", color="{ink}", style=filled, '
                f'fillcolor="#ffffff", tooltip="{tip}", id="{nid}", '
                f'class="uml-class anon anon-{c.kind}"];')
    if c.kind == "individual":
        # UML object: "name : Type", underlined, in a plain box
        label = ('<table border="1" color="#55524b" cellborder="0" cellpadding="5" '
                 f'bgcolor="#ffffff"><tr><td><u>{_h(c.name)}</u></td></tr></table>')
        return (f'  {nid} [label=<{label}>, tooltip="{_attr(cid)}", id="{nid}", '
                f'class="uml-class individual"];')
    extra = " anon" if c.kind == "enumeration" else ""
    extra += " deprecated" if c.deprecated else ""
    return (f'  {nid} [label=<{_label(c, color, definitions)}>, tooltip="{_attr(cid)}", '
            f'id="{nid}", class="uml-class{gcls}{defcls}{extra}"];')


# Above this many classes, use straight-line edges: spline/polyline routing
# becomes slow and unreliable on large, dense graphs.
_SPLINE_LIMIT = 300

# Above this many classes the hierarchical `dot` engine becomes prohibitively
# slow (super-linear), so we switch to `sfdp` (scalable force-directed).
_SFDP_LIMIT = 500

# Hard cap on how long `dot` may run before we fall back to `sfdp`.
_DOT_TIMEOUT_S = 45


def _engine_for(m: UModel) -> str:
    return "sfdp" if len(m.classes) > _SFDP_LIMIT else "dot"


INFERRED_COLOR = "#d9822b"

# Embedded in every Graphviz SVG so the effect also works in downloaded files:
# classes the reasoner moved get an orange outline while inferred edges show;
# `svg.hide-inferred` (toggled by the web UI, or "i" in a standalone file)
# hides inferred edges and those outlines together.
SVG_STYLE = f"""<style class="o2u-style">
g.node.inferred-placed polygon[stroke="#a0a0a0"] {{ stroke: {INFERRED_COLOR}; stroke-width: 2.5px; }}
svg.hide-inferred g.edge.rel-inferred {{ display: none; }}
svg.hide-inferred g.node.inferred-placed polygon[stroke="#a0a0a0"] {{ stroke: #a0a0a0; stroke-width: 1px; }}
</style>"""


def _slug(name: str) -> str:
    return "".join(ch if ch.isalnum() else "-" for ch in name)


def _legend(m: UModel) -> str:
    """A key: one swatch per group, plus the line styles used."""
    rows = ['<tr><td colspan="2" align="left"><b>Key</b></td></tr>']
    # one group says nothing: its swatch is left out
    shown = m.groups.values() if len(m.groups) > 1 else []
    for g in sorted(shown, key=lambda g: (g.upper, g.name)):
        note = " (imported)" if g.upper else ""
        ident = ""
        if g.iri:
            # an owl:imports ontology: show which version was drawn
            ident = (f'<br/><font point-size="9" color="#6b675e">'
                     f'{_h(g.version_iri or g.iri)}</font>')
        rows.append(
            f'<tr><td bgcolor="{g.color}" width="14"> </td>'
            f'<td align="left">{_h(g.name)}{note} · {g.count}{ident}</td></tr>')
    inferred = any(e.kind == "inferred" for e in m.edges)
    unsat = any(c.unsatisfiable for c in m.classes.values())
    extra = ""
    if inferred:
        extra += (f'<br/><font color="{INFERRED_COLOR}">orange arrow: subclass of, '
                  'inferred by the reasoner</font>')
    if unsat:
        extra += '<br/><font color="#c0392b">red class: unsatisfiable</font>'
    kinds = {e.kind for e in m.edges}
    if "disjoint" in kinds:
        extra += '<br/><font color="#c0392b">red dotted line / ⊥: disjoint classes</font>'
    if any(c.kind in ("union", "complement") for c in m.classes.values()):
        extra += '<br/>⊔ / ¬ node: union (or) / complement (not) of the classes it links to'
    if any(e.genset for e in m.edges):
        extra += '<br/>shared hollow arrow {disjoint, complete}: disjoint union'
    if any(e.multiplicity for e in m.edges):
        extra += '<br/>number at an arrowhead: how many (1..* at least one, 0..1 at most one)'
    if any(c.deprecated for c in m.classes.values()):
        extra += '<br/><font color="#6b675e">grey, struck-through: deprecated</font>'
    if any(c.kind == "individual" for c in m.classes.values()):
        extra += '<br/>underlined box: an individual (value)'
    rows += _property_rows(m)
    rows.append('<tr><td align="left" colspan="2">'
                '<font point-size="10">solid hollow arrow: subclass of<br/>'
                'dashed hollow arrow: defined as a kind of (≡)<br/>'
                'blue arrow: property domain → range<br/>'
                'dashed blue arrow: restriction (some / only / min …)'
                + extra + '</font></td></tr>')
    table = ('<table border="1" color="#a0a0a0" cellborder="0" cellspacing="2" '
             'cellpadding="3" bgcolor="#ffffff">' + "".join(rows) + "</table>")
    return (f'  legend [label=<{table}>, id="legend", class="uml-legend", '
            f'tooltip="key"];')


_MAX_PROPERTY_ROWS = 12


def _property_rows(m: UModel) -> list[str]:
    """Key rows for the properties on the lines: badges explained, sub-property,
    inverse and chain axioms (which are not drawn as lines themselves)."""
    if not m.properties:
        return []
    rows = ['<tr><td colspan="2" align="left"><b>Properties</b> '
            '<font point-size="9">⁻¹ has inverse · ↔ symmetric · ⁺ transitive · ¹ functional'
            '</font></td></tr>']
    items = sorted(m.properties.values(), key=lambda p: p["name"].lower())
    for info in items[:_MAX_PROPERTY_ROWS]:
        bits = list(info["characteristics"])
        bits += [f"sub-property of {x}" for x in info["super"]]
        bits += [f"inverse of {x}" for x in info["inverse"]]
        bits += [f"chain: {x}" for x in info["chains"]]
        text = _h(info["name"]) + ': <font point-size="9">' + _h("; ".join(bits)) + "</font>"
        rows.append(f'<tr><td></td><td align="left" balign="left">{text}</td></tr>')
    if len(items) > _MAX_PROPERTY_ROWS:
        rows.append(f'<tr><td></td><td align="left"><font point-size="9">… and '
                    f'{len(items) - _MAX_PROPERTY_ROWS} more (see the source panel)</font></td></tr>')
    return rows


def to_dot(m: UModel, legend: bool = True, xlabels: bool = False,
           definitions: bool = False, chains: bool = False) -> str:
    """``definitions``: definition text under each class name
    (--show-definitions). ``chains``: property chains added to line labels
    (--draw-chains)."""
    # Curved splines look best for small diagrams; straight lines scale.
    splines = "true" if len(m.classes) <= _SPLINE_LIMIT else "line"
    # sfdp ignores rankdir/ranksep; overlap removal keeps boxes from stacking.
    big = len(m.classes) > _SFDP_LIMIT
    overlap = '  graph [overlap="prune", sep="+8"];\n' if big else ""
    lines = [
        "digraph G {",
        overlap +
        f'  graph [rankdir=BT, bgcolor="#f7f5ef", splines={splines}, '
        "nodesep=0.4, ranksep=0.7, pad=0.3];",
        '  node [shape=plaintext, fontname="Helvetica,Arial,sans-serif", fontsize=12];',
        '  edge [fontname="Helvetica,Arial,sans-serif", fontsize=10];',
    ]
    ids: dict[str, str] = {}
    groups = m.groups
    for i, (cid, c) in enumerate(m.classes.items()):
        nid = f"n{i}"
        ids[cid] = nid
        g = groups.get(c.group)
        color = g.color if g else ""
        gcls = f" grp-{_slug(c.group)}" if c.group else ""
        defcls = (" defined" if c.defined else "") + \
                 (" inferred-placed" if c.inferred_placed else "") + \
                 (" unsatisfiable" if c.unsatisfiable else "")
        # id/class are copied onto the SVG <g>, giving the browser-side
        # interaction script (webapp/static/interact.js) stable hooks.
        lines.append(_node(nid, cid, c, color, gcls, defcls, definitions))

    for i, e in enumerate(m.edges):
        if e.src not in ids or e.dst not in ids:
            continue
        s, d = ids[e.src], ids[e.dst]
        mult = (f', headlabel="{_attr(e.multiplicity)}", labelfontsize=9, '
                f'labelfontcolor="#3a5a8c", labeldistance=1.4') if e.multiplicity else ""
        if e.kind == "generalization":
            # A generalization set (DisjointUnion) shares one arrowhead.
            gs = (f', samehead="{e.genset}", label="{_attr(e.label)}", fontsize=9'
                  if e.genset else "")
            lines.append(
                f'  {s} -> {d} [arrowhead=empty, color="#33312e", penwidth=1.2{gs}, '
                f'id="e{i}", class="rel-generalization", tooltip="subclass of"];'
            )
        elif e.kind == "disjoint":
            lbl = f', label="{_attr(e.label)}", fontcolor="#c0392b"' if e.label else ""
            lines.append(
                f'  {s} -> {d} [dir=none, style=dotted, color="#c0392b", penwidth=1.4, '
                f'constraint=false{lbl}, id="e{i}", class="rel-disjoint", '
                f'tooltip="disjoint with"];')
        elif e.kind == "member":
            lines.append(
                f'  {s} -> {d} [dir=none, style=dashed, color="#55524b", '
                f'id="e{i}", class="rel-member", tooltip="member of the expression"];')
        elif e.kind == "self":
            lines.append(
                f'  {s} -> {d} [arrowhead=vee, color="#3a5a8c", fontcolor="#3a5a8c", '
                f'label="{_attr(e.label)}", id="e{i}", class="rel-self", '
                f'tooltip="{_attr(e.label)}"];')
        elif e.kind == "definition":
            # Dashed hollow triangle: the class is *defined* as a kind of the
            # target (a named member of its owl:equivalentClass intersection).
            lines.append(
                f'  {s} -> {d} [arrowhead=empty, style=dashed, color="#33312e", '
                f'penwidth=1.2, id="e{i}", class="rel-definition", '
                f'tooltip="defined as a kind of (equivalent class)"];'
            )
        elif e.kind == "inferred":
            # Found by the reasoner, not asserted: orange, so the classified
            # view can be compared with the asserted one on the same layout.
            lines.append(
                f'  {s} -> {d} [arrowhead=empty, color="{INFERRED_COLOR}", '
                f'penwidth=2, id="e{i}", class="rel-inferred", '
                f'tooltip="subclass of (inferred by the reasoner)"];'
            )
        elif e.kind == "equivalent":
            lines.append(
                f'  {s} -> {d} [dir=both, arrowhead=none, arrowtail=none, '
                f'style=dashed, color="#33312e", label="{_attr(e.label or "≡")}", '
                f'constraint=false, id="e{i}", class="rel-equivalent", '
                f'tooltip="{_attr("equivalent" if e.label in ("", "≡") else e.label)}"];'
            )
        else:
            restriction = e.kind == "restriction"
            text = e.label
            if chains:
                extra = [f"⊒ {c}" for p in e.props for c in m.properties.get(p, {}).get("chains", [])]
                text = "\n".join([text] + extra) if extra else text
            # Merged relations: one per line (DOT "\n" escape, not a raw newline).
            key = "xlabel" if xlabels else "label"
            lbl = f', {key}="{_attr(text).replace(chr(10), chr(92) + "n")}"' if text else ""
            tip = _attr((e.label or e.kind).replace(chr(10), "; "))
            style = ", style=dashed" if restriction else ""
            lines.append(
                f'  {s} -> {d} [arrowhead=vee, color="#3a5a8c", '
                f"fontcolor=\"#3a5a8c\", constraint=false{style}{lbl}{mult}, "
                f'id="e{i}", class="rel-{_attr(e.kind)}", tooltip="{tip}"];'
            )
    special = any(e.kind in ("inferred", "disjoint", "member") or e.genset for e in m.edges) or \
        any(c.unsatisfiable or c.deprecated for c in m.classes.values()) or bool(m.properties)
    if legend and (len(groups) > 1 or special):
        lines.append(_legend(m))
    lines.append("}")
    return "\n".join(lines)


def _run_engine(dot: str, engine: str, src: bytes, env: dict | None,
                timeout: float | None) -> subprocess.CompletedProcess:
    # `dot` is the binary; -K selects the actual layout engine (dot/sfdp/...).
    return subprocess.run(
        [dot, f"-K{engine}", "-Tsvg"],
        input=src, capture_output=True, env=env, timeout=timeout,
    )


# Above this many classes, relation labels become Graphviz "xlabels": placed
# after layout instead of reserving space in it. Edge labels otherwise widen
# a large diagram by about a third (98-class LOF ontology: 7,667pt -> 5,410pt).
_XLABEL_MIN = 40


def render_dot_svg(m: UModel, legend: bool = True, compact_labels: str = "auto",
                   source: dict | None = None, definitions: bool = False,
                   chains: bool = False) -> str:
    """Render with Graphviz.

    ``compact_labels``: "auto" (diagrams of 40+ classes), "on", "off". When on,
    relation labels do not take up layout space (see _XLABEL_MIN).
    ``source``: output of source.build_source(), embedded so a click on a
    class or line can show the OWL it was drawn from.
    """
    dot, env = _gv()
    if not dot:
        raise RuntimeError("graphviz 'dot' not found (run scripts/setup.sh)")
    compact = compact_labels == "on" or (
        compact_labels == "auto" and len(m.classes) >= _XLABEL_MIN)
    src = to_dot(m, legend=legend, xlabels=compact, definitions=definitions,
                 chains=chains).encode("utf-8")
    engine = _engine_for(m)

    try:
        timeout = _DOT_TIMEOUT_S if engine == "dot" else None
        proc = _run_engine(dot, engine, src, env, timeout)
    except subprocess.TimeoutExpired:
        # `dot` is too slow for this graph; fall back to the scalable engine.
        proc = _run_engine(dot, "sfdp", src, env, None)

    out = proc.stdout.decode("utf-8")
    # On large/dense graphs the engine may emit recoverable warnings (e.g.
    # "trouble in init_rank") and exit non-zero while still producing a valid
    # SVG. Accept the output whenever it actually contains an <svg> element.
    if "<svg" in out:
        # Insert the inferred-view stylesheet just inside the root element.
        i = out.find(">", out.find("<svg")) + 1
        out = out[:i] + "\n" + SVG_STYLE + out[i:]
        return embed_source(out, source) if source else out
    raise RuntimeError(proc.stderr.decode("utf-8", "replace") or "dot produced no SVG")
