"""Modules: draw one part of an ontology, or an overview of all parts (WS2.2).

Each class gets a module from the first source that applies to it:

1. an annotation property on the class (``--module-property``, default
   ``https://w3id.org/lof/module``);
2. an OBO-style IRI prefix (``.../ODP003_0001000`` -> ODP003);
3. the owl:imports ontology it came from;
4. community detection (Louvain) on the class graph, when the ontology's
   own classes would otherwise all be one module.

A module view keeps the module's classes and adds a context ring, greyed:
the direct superclasses of its classes and the far ends of its restrictions.
"""
from __future__ import annotations

import copy
import re
from collections import Counter

from rdflib import Graph, Literal, URIRef

from .model import ANON_KINDS, HIERARCHY_KINDS, Edge, Group, UModel
from .postprocess import _import_name, is_home

DEFAULT_PROPERTY = "https://w3id.org/lof/module"
_PREFIXED = re.compile(r"^.*[/#](?P<prefix>[A-Za-z][A-Za-z0-9]*)_[0-9]+$")
_COMMUNITY_MIN = 30      # classes before community detection is worth it


def assign(m: UModel, g: Graph, prop: str | None = None) -> dict[str, dict]:
    """Set ``UClass.module`` and return {module id: {id, source, members, upper}}."""
    p = URIRef(prop or DEFAULT_PROPERTY)
    found: dict[str, tuple[str, str]] = {}
    for cid, c in m.classes.items():
        if c.kind in ANON_KINDS:
            continue
        val = g.value(URIRef(cid), p) if not cid.startswith("_:") else None
        if val is not None:
            mid = str(val) if isinstance(val, Literal) else str(val).rstrip("/#").rsplit("/", 1)[-1]
            found[cid] = (mid, "annotation")
        elif (mt := _PREFIXED.match(cid)):
            found[cid] = (mt.group("prefix"), "prefix")
        elif cid in m.import_of:
            found[cid] = (_import_name(m.import_of[cid]), "import")
    home = [cid for cid, c in m.classes.items() if c.kind == "class" and is_home(m, cid)] \
        or [cid for cid, c in m.classes.items() if c.kind == "class" and cid not in m.import_of]
    home_modules = {found[c][0] for c in home if c in found}
    if len(home_modules) <= 1 and len(home) >= _COMMUNITY_MIN:
        for cid, mid in _communities(m, home).items():
            found[cid] = (mid, "community")
    for cid, c in m.classes.items():
        c.module = found.get(cid, ("", ""))[0]
    # anonymous nodes belong to their owner's module
    for c in m.classes.values():
        if c.kind in ANON_KINDS and c.owner in m.classes:
            c.module = m.classes[c.owner].module
    out: dict[str, dict] = {}
    upper_groups = {n for n, gr in m.groups.items() if gr.upper}
    for cid, c in m.classes.items():
        if not c.module or c.kind in ANON_KINDS:
            continue
        mod = out.setdefault(c.module, {"id": c.module, "source": found[cid][1],
                                        "members": [], "upper": True})
        mod["members"].append(cid)
        mod["upper"] = mod["upper"] and c.group in upper_groups
    m.modules = dict(sorted(out.items()))
    return m.modules


def _communities(m: UModel, home: list[str]) -> dict[str, str]:
    import networkx as nx
    g = nx.Graph()
    g.add_nodes_from(home)
    keep = set(home)
    for e in m.edges:
        if e.src in keep and e.dst in keep and e.src != e.dst:
            w = 2.0 if e.kind in HIERARCHY_KINDS else 1.0
            g.add_edge(e.src, e.dst, weight=g.get_edge_data(e.src, e.dst, {}).get("weight", 0) + w)
    parts = nx.algorithms.community.louvain_communities(g, weight="weight", seed=1)
    parts = sorted(parts, key=lambda p: (-len(p), min(p)))
    return {cid: f"M{i + 1}" for i, part in enumerate(parts) for cid in part}


def view(m: UModel, module: str) -> UModel:
    """The module's classes plus a greyed context ring."""
    if module not in m.modules:
        raise ValueError(f"no module '{module}' (modules: {', '.join(m.modules) or 'none'})")
    members = set(m.modules[module]["members"])
    members |= {cid for cid, c in m.classes.items()
                if c.kind in ANON_KINDS and c.owner in members}
    context: set[str] = set()
    edges: list[Edge] = []
    for e in m.edges:
        if e.src in members and e.dst in members:
            edges.append(e)
        elif e.src in members and e.dst in m.classes and e.kind not in ("disjoint", "inferred"):
            # direct superclass, or the far end of a restriction / association
            context.add(e.dst)
            edges.append(e)
        elif e.kind == "disjoint" and e.src in members and e.dst in members:
            edges.append(e)
    # a ⊥ group node stays when two or more of its members are in view
    for cid, c in m.classes.items():
        if c.kind == "disjoint":
            ends = [e for e in m.edges if e.src == cid and e.dst in members]
            if len(ends) >= 2:
                members.add(cid)
                edges.extend(ends)
    sub = UModel(ontology_iri=m.ontology_iri, imports=m.imports, import_of=m.import_of,
                 notes=m.notes, groups=m.groups, modules=m.modules)
    for cid, c in m.classes.items():
        if cid in members or cid in context:
            cc = copy.copy(c)
            if cid not in members:
                cc.context = True
                cc.attrs = []
            sub.classes[cid] = cc
    seen = set()
    for e in edges:
        if id(e) not in seen and e.src in sub.classes and e.dst in sub.classes:
            seen.add(id(e))
            sub.edges.append(e)
    used = {p for e in sub.edges for p in e.props}
    sub.properties = {p: v for p, v in m.properties.items() if p in used}
    counts = Counter(c.group for c in sub.classes.values() if c.group)
    sub.groups = {n: _with_count(gr, counts[n]) for n, gr in m.groups.items() if counts.get(n)}
    return sub


def _with_count(gr: Group, n: int) -> Group:
    g2 = copy.copy(gr)
    g2.count = n
    return g2


def overview(m: UModel, include_upper: bool = False) -> UModel:
    """One node per module; lines count the relations between modules."""
    mods = {k: v for k, v in m.modules.items() if include_upper or not v["upper"]}
    of = {cid: c.module for cid, c in m.classes.items()}
    o = UModel(ontology_iri=m.ontology_iri)
    for mid, info in mods.items():
        node = o.cls(f"module:{mid}", mid)
        node.stereotype = "module"
        node.attrs = []
        first = m.classes[info["members"][0]]
        node.group = first.group
        node.attrs.append(_attr_count(len(info["members"])))
    tally: Counter = Counter()
    for e in m.edges:
        a, b = of.get(e.src), of.get(e.dst)
        if a and b and a != b and a in mods and b in mods:
            kind = "generalization" if e.kind in HIERARCHY_KINDS else "association"
            tally[(a, b, kind)] += 1
    for (a, b, kind), n in sorted(tally.items()):
        label = f"{n} subclass link{'s' * (n != 1)}" if kind == "generalization" \
            else f"{n} relation{'s' * (n != 1)}"
        o.edges.append(Edge(src=f"module:{a}", dst=f"module:{b}", kind=kind, label=label))
    o.groups = {n: gr for n, gr in m.groups.items()
                if any(c.group == n for c in o.classes.values())}
    return o


def _attr_count(n: int):
    from .model import Attr
    return Attr(name=f"{n} classes")
