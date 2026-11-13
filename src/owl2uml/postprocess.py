"""Model clean-up between parsing and rendering.

* ``assign_groups``  -- group classes by IRI prefix or namespace and colour them,
  marking groups that come from outside the ontology (e.g. BFO) as upper-level.
* ``prune_unused``   -- drop imported classes the ontology never uses.
* ``merge_edges``    -- one line per (source, target, kind), with stacked labels,
  instead of several lines drawn on top of each other.
"""
from __future__ import annotations

import re

from .model import Group, HIERARCHY_KINDS, UModel

# Tableau-10-derived palette: distinct on the pale header tint and in grey-scale
# print. The yellow is darkened so a white class icon stays legible on it.
PALETTE = (
    "#4e79a7", "#f28e2b", "#59a14f", "#e15759", "#76b7b2",
    "#b6992d", "#b07aa1", "#ff9da7", "#9c755f", "#5f8fa3",
    "#8cd17d", "#d37295",
)
UPPER_COLOR = "#9a968c"     # imported upper-level vocabulary (e.g. BFO)
DEFAULT_COLOR = "#84be84"   # the classic single-ontology green

# OBO-style identifiers: ".../BFO_0000001", ".../ODP003_0001000".
_PREFIXED = re.compile(r"^(?P<ns>.*[/#])(?P<prefix>[A-Za-z][A-Za-z0-9]*)_[0-9]+$")


def group_of(iri: str) -> str:
    """Group name for a class IRI: its OBO-style prefix, else its namespace."""
    m = _PREFIXED.match(iri)
    if m:
        return m.group("prefix")
    for sep in ("#", "/"):
        if sep in iri:
            ns = iri.rsplit(sep, 1)[0]
            tail = ns.rstrip("/").rsplit("/", 1)[-1]
            return re.sub(r"\.(owl|ttl|rdf|xml|obo)$", "", tail) or ns
    return iri


def _home_base(ontology_iri: str) -> str:
    """Namespace the ontology's own terms are expected to live under."""
    if not ontology_iri:
        return ""
    if ontology_iri.endswith(("/", "#")):
        return ontology_iri
    return ontology_iri.rsplit("/", 1)[0] + "/"


def is_home(m: UModel, cid: str) -> bool:
    base = _home_base(m.ontology_iri)
    return bool(base) and (cid.startswith(base) or cid.startswith(m.ontology_iri))


def tint(hex_color: str, amount: float = 0.82) -> str:
    """Mix a colour with white (amount = share of white)."""
    h = hex_color.lstrip("#")
    r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
    mix = lambda c: round(c + (255 - c) * amount)  # noqa: E731
    return "#{:02x}{:02x}{:02x}".format(mix(r), mix(g), mix(b))


def shade(hex_color: str, amount: float = 0.25) -> str:
    """Darken a colour (amount = share of black)."""
    h = hex_color.lstrip("#")
    r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
    mix = lambda c: round(c * (1 - amount))  # noqa: E731
    return "#{:02x}{:02x}{:02x}".format(mix(r), mix(g), mix(b))


def assign_groups(m: UModel) -> None:
    """Set ``UClass.group`` and build ``m.groups`` with colours.

    A group is *upper* when none of its classes lives under the ontology's own
    namespace (for an ontology whose IRI is known and which has classes of its
    own). With a single group the classic green is kept and no legend is needed.
    """
    have_home = any(is_home(m, cid) for cid in m.classes)
    groups: dict[str, Group] = {}
    home_seen: dict[str, bool] = {}
    for cid, c in m.classes.items():
        c.group = group_of(cid)
        g = groups.setdefault(c.group, Group(name=c.group))
        g.count += 1
        home_seen[c.group] = home_seen.get(c.group, False) or is_home(m, cid)
    for name, g in groups.items():
        g.upper = have_home and not home_seen[name]

    home = sorted((g for g in groups.values() if not g.upper), key=lambda g: g.name)
    if len(groups) <= 1:
        for g in groups.values():
            g.color = DEFAULT_COLOR
    else:
        for i, g in enumerate(home):
            g.color = PALETTE[i % len(PALETTE)]
        for g in groups.values():
            if g.upper:
                g.color = UPPER_COLOR
    m.groups = groups


def prune_unused(m: UModel) -> int:
    """Remove upper-level classes the ontology's own classes never reach.

    Kept: the ontology's own classes; every class they reach through relations
    (associations, restrictions); and every ancestor of those, so the drawing
    stays connected to its upper-level backbone. Relations that run only
    between upper-level classes (BFO's own part-of, precedes, ...) are dropped
    too. Returns the number of classes removed. Does nothing unless groups
    have been assigned and at least one group is upper-level.
    """
    if not m.groups or not any(g.upper for g in m.groups.values()):
        return 0
    upper = {cid for cid, c in m.classes.items() if m.groups[c.group].upper}
    home = set(m.classes) - upper
    if not home:
        return 0

    parents: dict[str, set[str]] = {}
    for e in m.edges:
        if e.kind in HIERARCHY_KINDS:
            parents.setdefault(e.src, set()).add(e.dst)

    seeds = set(home)
    for e in m.edges:
        if e.kind not in HIERARCHY_KINDS and (e.src in home or e.dst in home):
            seeds.update((e.src, e.dst))

    keep: set[str] = set()
    stack = list(seeds)
    while stack:
        cid = stack.pop()
        if cid in keep:
            continue
        keep.add(cid)
        stack.extend(parents.get(cid, ()))

    removed = [cid for cid in m.classes if cid not in keep]
    for cid in removed:
        del m.classes[cid]
    m.edges = [
        e for e in m.edges
        if e.src in keep and e.dst in keep
        and not (e.kind not in HIERARCHY_KINDS and e.src in upper and e.dst in upper)
    ]
    counts: dict[str, int] = {}
    for c in m.classes.values():
        counts[c.group] = counts.get(c.group, 0) + 1
    for name in list(m.groups):
        if name in counts:
            m.groups[name].count = counts[name]
        else:
            del m.groups[name]
    return len(removed)


def merge_edges(m: UModel) -> None:
    """Collapse parallel edges.

    * Several relations between the same two classes become one line whose
      label lists them all (one per line).
    * A restriction ("p some B") makes a plain domain/range association
      ("p") between the same classes redundant; only the restriction is kept.
    * Duplicate subclass links are dropped; a definition supersedes an
      asserted subclass link between the same pair.
    """
    restricted = {(e.src, e.dst, e.label.rsplit(" ", 1)[0])
                  for e in m.edges if e.kind == "restriction"}
    restricted |= {(e.src, e.dst, e.label.rsplit(" ", 2)[0])
                   for e in m.edges if e.kind == "restriction"}
    defined = {(e.src, e.dst) for e in m.edges if e.kind == "definition"}

    merged: dict[tuple[str, str, str], object] = {}
    out = []
    for e in m.edges:
        if e.kind == "association" and (e.src, e.dst, e.label) in restricted:
            continue
        if e.kind == "generalization" and (e.src, e.dst) in defined:
            continue
        key = (e.src, e.dst, e.kind)
        prev = merged.get(key)
        if prev is None:
            merged[key] = e
            out.append(e)
        elif e.label and e.label not in prev.label.split("\n"):
            prev.label = "\n".join(sorted(prev.label.split("\n") + [e.label], key=str.lower)) \
                if prev.label else e.label
    m.edges = out


def postprocess(m: UModel, prune: bool = True) -> dict:
    """Run all steps; return a small report for the CLI/web UI."""
    assign_groups(m)
    removed = prune_unused(m) if prune else 0
    merge_edges(m)
    return {"pruned": removed}
