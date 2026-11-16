"""Inferred layer of a version diff (spec WS4.1): classify both versions and
compare their direct superclasses and unsatisfiable classes.

This catches the case the asserted diff misses: one edited axiom (a
definition, a domain, a disjointness) that moves classes elsewhere in the
classified hierarchy.
"""
from __future__ import annotations

from rdflib import Graph, OWL, RDFS, URIRef

from .. import reason


def asserted(g: Graph) -> set[tuple[str, str]]:
    """Named rdfs:subClassOf pairs as stated."""
    return {(str(s), str(o)) for s, o in g.subject_objects(RDFS.subClassOf)
            if isinstance(s, URIRef) and isinstance(o, URIRef) and o != OWL.Thing and s != o}


def closure(pairs) -> dict[str, set[str]]:
    sups: dict[str, set[str]] = {}
    for a, b in pairs:
        sups.setdefault(a, set()).add(b)
    changed = True
    while changed:
        changed = False
        for a, bs in sups.items():
            extra = set().union(*(sups.get(b, set()) for b in bs)) - bs - {a}
            if extra:
                bs |= extra
                changed = True
    return sups


def direct(sups: dict[str, set[str]]) -> set[tuple[str, str]]:
    """Transitive reduction; mutual (equivalent) pairs are left out."""
    out = set()
    for a, bs in sups.items():
        strict = {b for b in bs if a not in sups.get(b, set())}
        for b in strict:
            if not any(b in sups.get(c, set()) and c not in sups.get(b, set())
                       for c in strict if c != b):
                out.add((a, b))
    return out


def _side(g: Graph, engine: str) -> tuple[reason.Inference, dict, set]:
    inf = reason.classify(g, engine)
    pairs = asserted(g) | ({p for p in inf.subsumptions if p[1] != str(OWL.Thing)}
                           if not inf.error else set())
    sups = closure(pairs)
    return inf, sups, direct(sups)


def diff(old: Graph, new: Graph, engine: str = "auto") -> dict:
    io, so, do = _side(old, engine)
    inew, sn, dn = _side(new, engine)
    ao, an = asserted(old), asserted(new)
    common = _classes(old) & _classes(new)
    moved = []
    for c in sorted(common):
        a = so.get(c, set()) & common
        b = sn.get(c, set()) & common
        if a != b and c not in inew.unsatisfiable:
            moved.append({"iri": c, "gained": sorted(b - a), "lost": sorted(a - b)})
    ran = io.engine != "none" and not io.error and not inew.error
    return {
        "engine": inew.engine,
        "error": io.error or inew.error,
        "seconds": round(io.seconds + inew.seconds, 2),
        # direct superclass links the reasoner adds that nobody asserted
        "added": sorted([a, b] for a, b in dn - do - an) if ran else [],
        "removed": sorted([a, b] for a, b in do - dn - ao) if ran else [],
        "unsatisfiable": {"old": sorted(io.unsatisfiable), "new": sorted(inew.unsatisfiable),
                          "added": sorted(inew.unsatisfiable - io.unsatisfiable),
                          "removed": sorted(io.unsatisfiable - inew.unsatisfiable)},
        "inconsistent": {"old": io.inconsistent, "new": inew.inconsistent},
        "moved": moved,
        "superclasses": {"new": {k: sorted(v) for k, v in sn.items()}},
    }


def _classes(g: Graph) -> set[str]:
    return {str(s) for s in reason._named(g) if not str(s).startswith(str(OWL))}
