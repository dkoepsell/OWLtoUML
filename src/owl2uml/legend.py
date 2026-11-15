"""The key drawn on a diagram: groups, properties, coverage, line styles."""
from __future__ import annotations

from html import escape as _h

from .model import UModel

INFERRED_COLOR = "#d9822b"


def _coverage_rows(cov: dict | None) -> list[str]:
    """Key rows saying what happened to the ontology's axioms (WS1.3)."""
    if not cov:
        return []
    t = cov["totals"]
    rows = ['<tr><td colspan="2" align="left"><b>Coverage</b> <font point-size="10">'
            f'{t["axioms"]} axioms: {t["drawn"]} drawn · {t["panel"]} in the source panel · '
            f'{t["dropped"]} left out</font></td></tr>']
    for reason, n in list(cov.get("dropped_reasons", {}).items())[:3]:
        rows.append(f'<tr><td></td><td align="left"><font point-size="10">{n} left out: '
                    f'{_h(reason)}</font></td></tr>')
    notes = cov.get("notes") or []
    if notes:
        rows.append(f'<tr><td></td><td align="left"><font point-size="10">{len(notes)} note(s): '
                    + _h("; ".join(f"{n['name']} {n['reason']}" for n in notes[:2]))
                    + ("…" if len(notes) > 2 else "") + '</font></td></tr>')
    return rows


def legend(m: UModel, coverage: dict | None = None, compact: bool = False) -> str:
    """A key: one swatch per group, plus the line styles used. ``compact``
    (print): no property or coverage rows -- they stay in the interactive
    figure."""
    rows = ['<tr><td colspan="2" align="left"><b>Key</b></td></tr>']
    # one group says nothing: its swatch is left out
    shown = m.groups.values() if len(m.groups) > 1 else []
    for g in sorted(shown, key=lambda g: (g.upper, g.name)):
        note = " (imported)" if g.upper else ""
        ident = ""
        if g.iri:
            # an owl:imports ontology: show which version was drawn
            ident = (f'<br/><font point-size="10" color="#6b675e">'
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
    rows += _profile_rows(m)
    if not compact:
        rows += _property_rows(m)
        rows += _coverage_rows(coverage)
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


def _profile_rows(m: UModel) -> list[str]:
    """What the notation profile (profiles/) changed: coloured lines named
    here instead of on the line, and the other styles in use."""
    r = m.render or {}
    if not r.get("profiles"):
        return []
    rows = [f'<tr><td colspan="2" align="left"><b>Notation</b> <font point-size="10">'
            f'{_h(", ".join(r["profiles"]))} profile</font></td></tr>']
    for _p, (ink, text) in sorted((r.get("keyed") or {}).items(), key=lambda kv: kv[1][1].lower()):
        rows.append(f'<tr><td bgcolor="{ink}" width="14" height="3"> </td>'
                    f'<td align="left"><font point-size="10">{_h(text)}</font></td></tr>')
    notes = []
    if r.get("compartments"):
        notes.append("row “p: B” in a box: the class is related to B by p")
    if any(e.style == "symmetric_pair" for e in m.edges):
        notes.append("line without arrowheads: a symmetric relation")
    if any(e.tail_label for e in m.edges):
        notes.append("arrows at both ends: a property and its inverse")
    if r.get("stubbed"):
        notes.append(f"{len(r['stubbed'])} BFO classes between a class and its "
                     "superclass are skipped (hover a line)")
    if r.get("motifs"):
        notes.append("Hohfeld square: correlatives side by side, opposites diagonal"
                     if any(x["name"] == "hohfeld" for x in r["motifs"]) else "fixed motifs")
    if notes:
        rows.append('<tr><td></td><td align="left" balign="left"><font point-size="10">'
                    + "<br/>".join(_h(n) for n in notes) + "</font></td></tr>")
    return rows


def _property_rows(m: UModel) -> list[str]:
    """Key rows for the properties on the lines: badges explained, sub-property,
    inverse and chain axioms (which are not drawn as lines themselves)."""
    if not m.properties:
        return []
    rows = ['<tr><td colspan="2" align="left"><b>Properties</b> '
            '<font point-size="10">⁻¹ has inverse · ↔ symmetric · ⁺ transitive · ¹ functional'
            '</font></td></tr>']
    items = sorted(m.properties.values(), key=lambda p: p["name"].lower())
    for info in items[:_MAX_PROPERTY_ROWS]:
        bits = list(info["characteristics"])
        bits += [f"sub-property of {x}" for x in info["super"]]
        bits += [f"inverse of {x}" for x in info["inverse"]]
        bits += [f"chain: {x}" for x in info["chains"]]
        text = _h(info["name"]) + ': <font point-size="10">' + _h("; ".join(bits)) + "</font>"
        rows.append(f'<tr><td></td><td align="left" balign="left">{text}</td></tr>')
    if len(items) > _MAX_PROPERTY_ROWS:
        rows.append(f'<tr><td></td><td align="left"><font point-size="10">… and '
                    f'{len(items) - _MAX_PROPERTY_ROWS} more (see the source panel)</font></td></tr>')
    return rows
