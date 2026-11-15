"""Apply a notation profile to a UModel.

Two stages, around ``postprocess.merge_edges``:

* ``apply`` (before merging, one property per line): relation styles --
  ``compartment`` turns a line into a text row in the source box, ``hidden``
  removes it (its axioms stay in the source panel), ``stroke`` colours it;
* ``finish`` (after merging): ``symmetric_pair`` and ``inverse_merged`` join
  the two directions into one line, class styles (bands, lanes, colours),
  fixed motifs (the Hohfeld square) and BFO stub chains.

Every line that disappears hands its axiom ids to what replaces it, so the
source panel still shows each collapsed axiom.
"""
from __future__ import annotations

from rdflib import Graph, OWL, RDF, RDFS, URIRef

from ..model import ANON_KINDS, Attr, Edge, HIERARCHY_KINDS, UModel
from ..postprocess import PALETTE, merge_quantifiers
from .loader import Profile

_CHARS = {"symmetric": OWL.SymmetricProperty, "transitive": OWL.TransitiveProperty,
          "functional": OWL.FunctionalProperty}
_LINE_KINDS = ("restriction", "association", "self")


def color(spec: str) -> str:
    """'categorical-4' -> the 4th palette colour; '#hex' as is."""
    if isinstance(spec, str) and spec.startswith("categorical-"):
        try:
            return PALETTE[(int(spec.split("-", 1)[1]) - 1) % len(PALETTE)]
        except ValueError:
            return ""
    return spec or ""


class _Props:
    """What the graph says about properties: super-properties, inverses, types."""

    def __init__(self, g: Graph, prof: Profile):
        self.g, self.prof = g, prof
        self._sup: dict[str, set[str]] = {}

    def supers(self, p: str) -> set[str]:
        """``p`` and all its super-properties, canonicalized."""
        if p not in self._sup:
            out, stack = set(), [URIRef(p)]
            while stack:
                x = stack.pop()
                c = self.prof.canonical(str(x))
                if c in out:
                    continue
                out.add(c)
                out.add(str(x))
                stack += [s for s in self.g.objects(x, RDFS.subPropertyOf) if isinstance(s, URIRef)]
            self._sup[p] = out
        return self._sup[p]

    def inverses(self, p: str) -> set[str]:
        u = URIRef(p)
        return {str(x) for x in self.g.objects(u, OWL.inverseOf) if isinstance(x, URIRef)} | \
            {str(x) for x in self.g.subjects(OWL.inverseOf, u) if isinstance(x, URIRef)}

    def has(self, p: str, char: str) -> bool:
        t = _CHARS.get(char)
        return t is not None and (URIRef(p), RDF.type, t) in self.g


def _rule_matches(match: dict, p: str, info: _Props) -> bool:
    if not match:
        return False
    if "property" in match:
        target = info.prof.canonical(match["property"])
        names = info.supers(p) if match.get("subproperties") else \
            {p, info.prof.canonical(p)}
        if target not in names:
            return False
    if "characteristic" in match and not info.has(p, match["characteristic"]):
        return False
    if match.get("has_inverse") and not info.inverses(p):
        return False
    return True


def _edge_matches(match: dict, e, m: UModel) -> bool:
    """Conditions on the line itself, not its property."""
    if "kind" in match and e.kind != match["kind"]:
        return False
    if match.get("target") == "upper":
        d = m.classes.get(e.dst)
        g = m.groups.get(d.group) if d else None
        return bool(g and g.upper)
    return True


def relation_rule(prof: Profile, p: str, info: _Props, e=None, m=None) -> dict:
    """The last matching rule wins (profiles compose left to right)."""
    found: dict = {}
    for rule in prof.relation_styles:
        match = dict(rule.get("match") or {})
        line = {k: match.pop(k) for k in ("target", "kind") if k in match}
        if line and (e is None or not _edge_matches(line, e, m)):
            continue
        if (not match and line) or _rule_matches(match, p, info):
            found = rule
    return found


def apply(m: UModel, prof: Profile, g: Graph) -> None:
    """Stage 1, before merge_edges."""
    info = _Props(g, prof)
    m.render = {"profiles": list(prof.names), "hidden": 0, "compartments": 0, "keyed": {}}
    keyed = _keyed(m, prof, info)
    keep = []
    for e in m.edges:
        rule = relation_rule(prof, e.props[0], info, e, m) \
            if e.kind in _LINE_KINDS and e.props else {}
        style = rule.get("style", "directed")
        e.color = color(rule.get("stroke", "")) or e.color
        dst = m.classes.get(e.dst)
        if style == "hidden":
            m.render["hidden"] += 1
            # its axioms stay listed in the source box's panel
            m.classes[e.src].axioms = sorted(set(m.classes[e.src].axioms) | set(e.axioms))
            continue
        if style == "compartment" and dst is not None and dst.kind not in ANON_KINDS \
                and e.kind in ("restriction", "association"):
            name = rule.get("label") or _strip_some(e.label)
            if e.multiplicity:
                name += f" [{e.multiplicity}]"
            m.classes[e.src].attrs.append(Attr(name=name, type=dst.name, axioms=list(e.axioms),
                                               props=list(e.props)))
            m.render["compartments"] += 1
            continue
        if style in ("symmetric_pair", "inverse_merged", "containment"):
            e.style = style
        if e.kind in _LINE_KINDS and e.props and e.props[0] in keyed:
            # a keyed property: the line's colour names it; the key says which
            e.color, text = keyed[e.props[0]]
            m.render["keyed"][e.props[0]] = (e.color, text)
            e.note, e.label = e.label, ""
            if e.multiplicity:
                e.note += f" [{e.multiplicity}]"
        keep.append(e)
    m.edges = keep


_KEY_COLORS = ("#59a14f", "#e15759", "#b07aa1", "#f28e2b", "#76b7b2", "#9c755f",
               "#d37295", "#b6992d")


def _keyed(m: UModel, prof: Profile, info: _Props) -> dict[str, tuple[str, str]]:
    """Properties shown by colour plus one key entry instead of a label on
    every line: those a rule marks ``key: true``, and (``auto_key: N``) any
    drawn on N or more lines that all carry the same label. At most eight,
    so the colours stay distinct."""
    lines: dict[str, list] = {}
    for e in m.edges:
        if e.kind in _LINE_KINDS and len(e.props) == 1 and e.label:
            lines.setdefault(e.props[0], []).append(e)
    out: dict[str, tuple[str, str]] = {}
    ranked = sorted(lines.items(), key=lambda kv: (-len(kv[1]), kv[0]))
    for p, es in ranked:
        rule = relation_rule(prof, p, info)
        if rule.get("style") in ("hidden", "compartment"):
            continue
        auto = prof.badges.get("auto_key") or 0
        same = len({x.label for x in es}) == 1 and len({x.kind for x in es}) == 1
        if rule.get("key") or (auto and len(es) >= auto and same):
            used = {c for c, _t in out.values()} | {color(r.get("stroke", ""))
                                                    for r in prof.relation_styles}
            ink = color(rule.get("stroke", "")) or next(
                (c for c in _KEY_COLORS if c not in used), _KEY_COLORS[len(out) % len(_KEY_COLORS)])
            text = _key_text([x.label for x in es])
            if es[0].kind == "association":
                text += " (domain → range)"
            out[p] = (ink, text)
        if len(out) >= len(_KEY_COLORS):
            break
    return out


def _key_text(labels: list[str]) -> str:
    """'p some', 'p only' -> 'p ∃∀'; 'p some' -> 'p some'."""
    quants, bases = set(), set()
    for lb in labels:
        base, _, q = lb.rpartition(" ")
        if q in ("some", "only", "∃∀") and base:
            bases.add(base)
            quants.update(("some", "only") if q == "∃∀" else (q,))
        else:
            bases.add(lb)
    if len(bases) != 1:
        return " / ".join(sorted(set(labels)))
    q = "∃∀" if {"some", "only"} <= quants else next(iter(quants), "")
    return f"{bases.pop()} {q}".strip()


def _strip_some(label: str) -> str:
    return label[:-5] if label.endswith(" some") else label


def finish(m: UModel, prof: Profile, g: Graph, show_bfo: str = "stub") -> None:
    """Stage 2, after merge_edges."""
    info = _Props(g, prof)
    _fold_inverse_associations(m, info)
    _pairs(m, info)
    _classes(m, prof, g)
    _motifs(m, prof)
    if prof.badges.get("hide_class_badge"):
        m.render["hide_class_badge"] = True
    if prof.bfo_stub and show_bfo != "full":
        m.render["stubbed"] = _stub_bfo(m, prof)


def _fold_inverse_associations(m: UModel, info: _Props) -> None:
    """A domain/range line A -P-> B says no more than a restriction
    B -Q-> A on P's inverse Q: the restriction's line stands for both."""
    rest: dict[tuple, list] = {}
    for e in m.edges:
        if e.kind == "restriction":
            rest.setdefault((e.src, e.dst), []).append(e)
    out = []
    for e in m.edges:
        if e.kind == "association" and e.props:
            keeper = next((r for r in rest.get((e.dst, e.src), [])
                           if any(q in info.inverses(p) for p in e.props for q in r.props)), None)
            if keeper is not None:
                keeper.axioms = sorted(set(keeper.axioms) | set(e.axioms))
                m.render["folded"] = m.render.get("folded", 0) + 1
                continue
        out.append(e)
    m.edges = out


def _pairs(m: UModel, info: _Props) -> None:
    """symmetric_pair: A–B and B–A become one undirected line.
    inverse_merged: A -P-> B and B -Q-> A (Q inverse of P) become one line
    with P at B's end and Q at A's end."""
    by_ends: dict[tuple, list[Edge]] = {}
    for e in m.edges:
        if e.style in ("symmetric_pair", "inverse_merged"):
            by_ends.setdefault((e.src, e.dst, e.kind), []).append(e)
    gone: set[int] = set()
    for e in m.edges:
        if id(e) in gone or e.style not in ("symmetric_pair", "inverse_merged"):
            continue
        for r in by_ends.get((e.dst, e.src, e.kind), []):
            if id(r) in gone or r is e:
                continue
            if e.style == "symmetric_pair" and r.style == "symmetric_pair" and \
                    set(r.props) == set(e.props):
                e.label = merge_quantifiers("\n".join(dict.fromkeys(
                    e.label.split("\n") + r.label.split("\n"))))
            elif e.style == "inverse_merged" and r.style == "inverse_merged" and \
                    any(q in info.inverses(p) for p in e.props for q in r.props):
                e.tail_label = r.label
            else:
                continue
            e.axioms = sorted(set(e.axioms) | set(r.axioms))
            e.props = sorted(set(e.props) | set(r.props))
            gone.add(id(r))
            break
        if e.style == "inverse_merged" and not e.tail_label:
            e.style = ""          # no partner: an ordinary arrow
    m.edges = [e for e in m.edges if id(e) not in gone]


def _ancestors(m: UModel, g: Graph) -> dict[str, set[str]]:
    """Every class's superclasses (reflexive, transitive), from the graph's
    named subClassOf links and the model's hierarchy lines."""
    up: dict[str, set[str]] = {}
    for s, o in g.subject_objects(RDFS.subClassOf):
        if isinstance(s, URIRef) and isinstance(o, URIRef):
            up.setdefault(str(s), set()).add(str(o))
    for e in m.edges:
        if e.kind in HIERARCHY_KINDS:
            up.setdefault(e.src, set()).add(e.dst)
    out: dict[str, set[str]] = {}
    for cid in m.classes:
        seen, stack = set(), [cid]
        while stack:
            x = stack.pop()
            if x not in seen:
                seen.add(x)
                stack += list(up.get(x, ()))
        out[cid] = seen
    return out


def _class_matches(match: dict, c, anc: set[str], prof: Profile) -> bool:
    if not match:
        return False
    if "subclass_of" in match and prof.canonical(match["subclass_of"]) not in \
            {prof.canonical(a) for a in anc}:
        return False
    if "iri" in match and c.id != match["iri"]:
        return False
    if "label" in match and c.name.lower() != str(match["label"]).lower():
        return False
    if "defined" in match and bool(match["defined"]) != c.defined:
        return False
    return True


def _classes(m: UModel, prof: Profile, g: Graph) -> None:
    anc = _ancestors(m, g)
    bands: dict[str, list[str]] = {}
    lanes: dict[str, list[str]] = {}
    for cid, c in m.classes.items():
        if c.kind != "class":
            continue
        band = lane = col = None
        for rule in prof.class_styles:
            if _class_matches(rule.get("match") or {}, c, anc[cid], prof):
                band = rule.get("band", band)
                lane = rule.get("lane", lane)
                col = rule.get("color", col)
        if band:
            bands.setdefault(band, []).append(cid)
        if lane:
            lanes.setdefault(lane, []).append(cid)
        if col:
            c.color = color(col)
    if len(bands) > 1:
        m.render["bands"] = bands
    if lanes:
        m.render["lanes"] = lanes


def _find(m: UModel, spec, prof: Profile) -> str | None:
    """A motif cell: an IRI or a label, or a list of alternatives."""
    for alt in (spec if isinstance(spec, list) else [spec]):
        alt = prof.canonical(str(alt))
        if alt in m.classes:
            return alt
        for cid, c in m.classes.items():
            if c.kind == "class" and c.name.lower() == alt.lower():
                return cid
    return None


def _motifs(m: UModel, prof: Profile) -> None:
    """Fixed arrangements, e.g. the Hohfeld square: rows of classes kept in
    place. A motif is drawn only when all its classes are in the diagram."""
    out, fixed = [], set()
    for motif in prof.motifs:
        rows = [[_find(m, cell, prof) for cell in row] for row in motif.get("rows", [])]
        if not rows or any(x is None for row in rows for x in row):
            continue
        out.append({"name": motif.get("name", "motif"), "rows": rows})
        fixed.update(x for row in rows for x in row)
    if out:
        m.render["motifs"] = out
        m.render["fixed"] = sorted(fixed)


def _stub_bfo(m: UModel, prof: Profile) -> list[str]:
    """Collapse chains of upper-level BFO classes that only pass the
    hierarchy through (one parent, one child, no other lines): the child's
    line goes straight to the grandparent, its tooltip naming the classes
    skipped. Classes a profile rule names (band anchors) stay."""
    named = {prof.canonical(str(v)) for r in prof.class_styles
             for v in (r.get("match") or {}).values() if isinstance(v, str)}
    stubbed = []
    changed = True
    while changed:
        changed = False
        for cid, c in list(m.classes.items()):
            if "/obo/BFO_" not in cid or cid in named or c.kind != "class":
                continue
            touching = [e for e in m.edges if cid in (e.src, e.dst)]
            ups = [e for e in touching if e.src == cid and e.kind == "generalization"]
            downs = [e for e in touching if e.dst == cid and e.kind == "generalization"]
            if len(ups) != 1 or len(downs) != 1 or len(touching) != 2 or ups[0].genset \
                    or downs[0].genset:
                continue
            up, down = ups[0], downs[0]
            via = [x for x in (down.note.removeprefix("via ").split(", ") if down.note else []) if x]
            via += [c.name] + [x for x in (up.note.removeprefix("via ").split(", ")
                                           if up.note else []) if x]
            m.edges = [e for e in m.edges if e is not up and e is not down]
            m.edges.append(Edge(src=down.src, dst=up.dst, kind="generalization",
                                axioms=sorted(set(up.axioms) | set(down.axioms) | set(c.axioms)),
                                style="collapsed", note="via " + ", ".join(via)))
            del m.classes[cid]
            m.mentioned.add(cid)
            stubbed.append(cid)
            changed = True
    for name, gr in list(m.groups.items()):
        gr.count = sum(1 for c in m.classes.values() if c.group == name)
        if not gr.count:
            del m.groups[name]
    return stubbed


def label_count(m: UModel) -> int:
    """Text labels on lines: one per property name shown (spec WS3 target)."""
    n = 0
    for e in m.edges:
        if e.kind in _LINE_KINDS or (e.kind == "equivalent" and e.label not in ("", "≡")):
            n += len([x for x in e.label.split("\n") if x]) if e.label else 0
            n += len([x for x in e.tail_label.split("\n") if x]) if e.tail_label else 0
    return n
