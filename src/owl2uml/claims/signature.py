"""The vocabulary the candidate grammar ranges over (spec section 5.2).

* N, native classes: named classes in a native namespace.
* F, filler classes: N plus every named class in a class position of an
  axiom on a native entity (so BFO's ``disposition`` or ODP003's ``legal
  position`` come in when NAO uses them, and the rest of BFO stays out).
* P, properties: native object properties, the object properties native
  axioms use, and their told super-properties.

Also collected here, because analysis needs them: what each native class
states directly (told superclasses, existentials, negated existentials,
disjoint classes), the definitions of defined classes, and the nested
filler expressions that G5 tests for satisfiability.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from rdflib import BNode, Graph, OWL, RDF, RDFS, URIRef
from rdflib.collection import Collection

from . import PROBE_NS


def native_namespace(ontology_iri: str) -> str:
    """Namespace of the ontology IRI: everything up to the last '/' or '#'."""
    s = ontology_iri.rstrip("/#")
    cut = max(s.rfind("/"), s.rfind("#"))
    return s[:cut + 1] if cut > len("https://") else s + "/"


def items(g: Graph, node, pred) -> list:
    lst = g.value(node, pred)
    if lst is None:
        return []
    try:
        return list(Collection(g, lst))
    except Exception:  # noqa: BLE001 - malformed list
        return []


def classes_in(g: Graph, e, out: set | None = None) -> set:
    """Named classes in class positions of expression ``e``."""
    out = set() if out is None else out
    if isinstance(e, URIRef):
        if e not in (OWL.Thing, OWL.Nothing):
            out.add(e)
        return out
    if not isinstance(e, BNode):
        return out
    for pred in (OWL.intersectionOf, OWL.unionOf):
        for m in items(g, e, pred):
            classes_in(g, m, out)
    for pred in (OWL.complementOf, OWL.someValuesFrom, OWL.allValuesFrom, OWL.onClass):
        x = g.value(e, pred)
        if x is not None and not _is_datarange(g, x):
            classes_in(g, x, out)
    return out


def props_in(g: Graph, e, out: set | None = None) -> set:
    """Named object properties used in expression ``e``."""
    out = set() if out is None else out
    if not isinstance(e, BNode):
        return out
    p = g.value(e, OWL.onProperty)
    if isinstance(p, URIRef) and (p, RDF.type, OWL.DatatypeProperty) not in g:
        out.add(p)
    elif isinstance(p, BNode):
        inv = g.value(p, OWL.inverseOf)
        if isinstance(inv, URIRef):
            out.add(inv)
    for pred in (OWL.intersectionOf, OWL.unionOf):
        for m in items(g, e, pred):
            props_in(g, m, out)
    for pred in (OWL.complementOf, OWL.someValuesFrom, OWL.allValuesFrom, OWL.onClass):
        x = g.value(e, pred)
        if x is not None:
            props_in(g, x, out)
    return out


def _is_datarange(g: Graph, x) -> bool:
    return isinstance(x, URIRef) and str(x).startswith("http://www.w3.org/2001/XMLSchema#") \
        or (x, RDF.type, RDFS.Datatype) in g


def some_parts(g: Graph, e):
    """(p, B) when ``e`` is ObjectSomeValuesFrom(p, B) with named p and B."""
    if not isinstance(e, BNode):
        return None
    p, b = g.value(e, OWL.onProperty), g.value(e, OWL.someValuesFrom)
    if isinstance(p, URIRef) and isinstance(b, URIRef):
        return p, b
    return None


def conjuncts(g: Graph, e) -> list:
    """The conjuncts of an intersection, or [e]."""
    parts = items(g, e, OWL.intersectionOf) if isinstance(e, BNode) else []
    return parts or [e]


@dataclass
class Signature:
    namespaces: list[str]
    native: list[URIRef]                     # N
    fillers: list[URIRef]                    # F
    props: list[URIRef]                      # P
    native_props: list[URIRef]
    told_sub: dict = field(default_factory=dict)       # A -> {B}
    told_some: dict = field(default_factory=dict)      # A -> {(p, B)}
    told_nosome: dict = field(default_factory=dict)    # A -> {(p, B)}
    told_disj: dict = field(default_factory=dict)      # A -> {B}
    told_parents: dict = field(default_factory=dict)   # every class -> told named parents
    definitions: dict = field(default_factory=dict)    # A -> [expression nodes]
    nested: list = field(default_factory=list)         # G5 expression nodes

    def is_native(self, term) -> bool:
        return isinstance(term, URIRef) and any(str(term).startswith(n) for n in self.namespaces)


def _named_classes(g: Graph) -> set[URIRef]:
    out = {s for s in g.subjects(RDF.type, OWL.Class) if isinstance(s, URIRef)}
    out |= {s for s in g.subjects(RDFS.subClassOf, None) if isinstance(s, URIRef)}
    out |= {s for s in g.subjects(OWL.equivalentClass, None) if isinstance(s, URIRef)}
    return {c for c in out if c not in (OWL.Thing, OWL.Nothing)
            and not str(c).startswith(PROBE_NS)}


def build(g: Graph, namespaces: list[str]) -> Signature:
    classes = _named_classes(g)
    s = Signature(namespaces=list(namespaces), native=[], fillers=[], props=[], native_props=[])
    native = sorted(c for c in classes if s.is_native(c))
    objprops = {p for p in g.subjects(RDF.type, OWL.ObjectProperty) if isinstance(p, URIRef)}
    native_props = sorted(p for p in objprops if s.is_native(p))
    fill: set = set(native)
    used: set = set(native_props)

    for c in classes:
        s.told_parents[c] = {o for o in g.objects(c, RDFS.subClassOf) if isinstance(o, URIRef)
                             and o != OWL.Thing}

    for a in native:
        sub, some, nosome, disj = set(), set(), set(), set()
        exprs = list(g.objects(a, RDFS.subClassOf))
        defs = [e for e in g.objects(a, OWL.equivalentClass)]
        defs += [e for e in g.subjects(OWL.equivalentClass, a) if isinstance(e, URIRef)]
        for e in exprs + defs:
            for c in conjuncts(g, e):
                if isinstance(c, URIRef):
                    if c != OWL.Thing:
                        sub.add(c)
                    continue
                sp = some_parts(g, c)
                if sp:
                    some.add(sp)
                neg = g.value(c, OWL.complementOf)
                if isinstance(neg, URIRef):
                    disj.add(neg)
                elif neg is not None and some_parts(g, neg):
                    nosome.add(some_parts(g, neg))
            fill |= classes_in(g, e)
            used |= props_in(g, e)
            _collect_nested(g, e, s.nested)
        for o in set(g.objects(a, OWL.disjointWith)) | set(g.subjects(OWL.disjointWith, a)):
            if isinstance(o, URIRef) and o != a:
                disj.add(o)
                fill.add(o)
        for ad in g.subjects(RDF.type, OWL.AllDisjointClasses):
            members = items(g, ad, OWL.members)
            if a in members:
                disj |= {m for m in members if isinstance(m, URIRef) and m != a}
        s.told_sub[a], s.told_some[a], s.told_nosome[a], s.told_disj[a] = sub, some, nosome, disj
        bdefs = [e for e in g.objects(a, OWL.equivalentClass) if isinstance(e, BNode)]
        if bdefs:
            s.definitions[a] = bdefs
    for p in native_props:
        for pred in (RDFS.domain, RDFS.range):
            for e in g.objects(p, pred):
                fill |= classes_in(g, e)

    # told super-properties, transitively
    stack = list(used)
    while stack:
        p = stack.pop()
        for sup in g.objects(p, RDFS.subPropertyOf):
            if isinstance(sup, URIRef) and sup not in used and sup != OWL.topObjectProperty:
                used.add(sup)
                stack.append(sup)
    s.native = native
    s.fillers = sorted(c for c in fill if c in classes or (c, RDF.type, OWL.Class) in g
                       or c in native)
    s.props = sorted(p for p in used if (p, RDF.type, OWL.DatatypeProperty) not in g)
    s.native_props = native_props
    return s


def _collect_nested(g: Graph, e, out: list, depth: int = 0) -> None:
    """Non-atomic filler expressions inside ``e`` (spec G5)."""
    if not isinstance(e, BNode):
        return
    for pred in (OWL.someValuesFrom, OWL.allValuesFrom, OWL.onClass):
        f = g.value(e, pred)
        if isinstance(f, BNode) and (g.value(f, OWL.intersectionOf) is not None
                                     or g.value(f, OWL.unionOf) is not None
                                     or g.value(f, OWL.onProperty) is not None
                                     or g.value(f, OWL.complementOf) is not None):
            out.append(f)
        if f is not None:
            _collect_nested(g, f, out, depth + 1)
    for pred in (OWL.intersectionOf, OWL.unionOf):
        for m in items(g, e, pred):
            _collect_nested(g, m, out, depth + 1)
    c = g.value(e, OWL.complementOf)
    if c is not None:
        _collect_nested(g, c, out, depth + 1)
