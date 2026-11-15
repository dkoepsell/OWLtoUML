"""Every OWL axiom in a graph, with a stable id (spec: ontology model, WS1.3).

An axiom id is a short hash of a canonical rendering in which IRIs are
written out, blank-node expressions are rendered structurally, and set-like
lists (intersection, union, oneOf, members) are sorted. The same axiom
therefore gets the same id in any syntax, and the parser tags each drawn
line and attribute with the ids it came from (``Edge.axioms``,
``Attr.axioms``). The coverage report (coverage.py) and the version diff
build on these ids.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass

from rdflib import BNode, Graph, Literal, OWL, RDF, RDFS, URIRef
from rdflib.collection import Collection

_SET_LISTS = {OWL.intersectionOf, OWL.unionOf, OWL.oneOf, OWL.members,
              OWL.distinctMembers, OWL.disjointUnionOf}
_SKIP_IN_EXPR = {(RDF.type, OWL.Class), (RDF.type, OWL.Restriction), (RDF.type, RDFS.Datatype)}

_DECLARATIONS = {
    OWL.Class: "Class", RDFS.Class: "Class", OWL.ObjectProperty: "ObjectProperty",
    OWL.DatatypeProperty: "DataProperty", OWL.AnnotationProperty: "AnnotationProperty",
    OWL.NamedIndividual: "NamedIndividual", RDFS.Datatype: "Datatype",
}
_CHARACTERISTICS = {
    OWL.FunctionalProperty: "FunctionalProperty",
    OWL.InverseFunctionalProperty: "InverseFunctionalObjectProperty",
    OWL.TransitiveProperty: "TransitiveObjectProperty",
    OWL.SymmetricProperty: "SymmetricObjectProperty",
    OWL.AsymmetricProperty: "AsymmetricObjectProperty",
    OWL.ReflexiveProperty: "ReflexiveObjectProperty",
    OWL.IrreflexiveProperty: "IrreflexiveObjectProperty",
}
# predicate -> (axiom type, symmetric?)
_BINARY = {
    RDFS.subClassOf: ("SubClassOf", False),
    OWL.equivalentClass: ("EquivalentClasses", True),
    OWL.disjointWith: ("DisjointClasses", True),
    OWL.disjointUnionOf: ("DisjointUnion", False),
    RDFS.subPropertyOf: ("SubPropertyOf", False),
    OWL.equivalentProperty: ("EquivalentProperties", True),
    OWL.inverseOf: ("InverseObjectProperties", True),
    OWL.propertyDisjointWith: ("DisjointProperties", True),
    RDFS.domain: ("PropertyDomain", False),
    RDFS.range: ("PropertyRange", False),
    OWL.propertyChainAxiom: ("SubPropertyChainOf", False),
    OWL.hasKey: ("HasKey", False),
    OWL.sameAs: ("SameIndividual", True),
    OWL.differentFrom: ("DifferentIndividuals", True),
}
_NARY = {OWL.AllDisjointClasses: ("DisjointClasses", OWL.members),
         OWL.AllDisjointProperties: ("DisjointProperties", OWL.members),
         OWL.AllDifferent: ("DifferentIndividuals", OWL.distinctMembers)}
# Not axioms: ontology header and plumbing.
_IGNORED = {OWL.imports, OWL.versionIRI, OWL.priorVersion, OWL.backwardCompatibleWith,
            OWL.incompatibleWith, OWL.versionInfo}
_BUILTIN = (str(OWL), str(RDF), str(RDFS), "http://www.w3.org/2001/XMLSchema#")


@dataclass
class Axiom:
    id: str
    type: str              # OWL 2 axiom type, e.g. "SubClassOf"
    subject: str           # the entity the axiom is about (its frame in the source panel)
    terms: tuple           # the rdflib terms it states, for rendering
    predicate: str = ""    # annotation property, for AnnotationAssertion


# --------------------------------------------------------------------------

def canon(g: Graph, node, _seen: frozenset = frozenset()) -> str:
    """Canonical text for a term; blank nodes rendered by structure."""
    if isinstance(node, URIRef):
        return f"<{node}>"
    if isinstance(node, Literal):
        dt = f"^^<{node.datatype}>" if node.datatype else ""
        lang = f"@{node.language}" if node.language else ""
        return f'"{node}"{lang}{dt}'
    if not isinstance(node, BNode) or node in _seen:
        return "_"
    seen = _seen | {node}
    if (node, RDF.first, None) in g:
        try:
            return "(" + " ".join(canon(g, x, seen) for x in Collection(g, node)) + ")"
        except Exception:  # noqa: BLE001 - malformed list
            return "(?)"
    parts = []
    for p, o in g.predicate_objects(node):
        if (p, o) in _SKIP_IN_EXPR:
            continue
        if p in _SET_LISTS and isinstance(o, BNode):
            try:
                items = sorted(canon(g, x, seen) for x in Collection(g, o))
                parts.append(f"<{p}>{{{' '.join(items)}}}")
                continue
            except Exception:  # noqa: BLE001
                pass
        parts.append(f"<{p}>{canon(g, o, seen)}")
    return "[" + " ".join(sorted(parts)) + "]"


def axiom_id(g: Graph, kind: str, *terms, symmetric: bool = False) -> str:
    texts = [canon(g, t) for t in terms]
    if symmetric:
        texts.sort()
    raw = f"{kind}({' '.join(texts)})"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]


def binary_id(g: Graph, pred, s, o) -> str:
    """Id of the axiom stated by the triple (s pred o), e.g. rdfs:subClassOf."""
    kind, sym = _BINARY[pred]
    return axiom_id(g, kind, s, o, symmetric=sym)


def nary_id(g: Graph, kind: str, members: list) -> str:
    """Id of an n-ary axiom (DisjointClasses of 2+ classes, ...)."""
    if len(members) == 2:
        return axiom_id(g, kind, *members, symmetric=True)
    return axiom_id(g, kind, *sorted(members, key=lambda t: canon(g, t)))


# --------------------------------------------------------------------------

def _is_annotation(g: Graph, p) -> bool:
    if (p, RDF.type, OWL.AnnotationProperty) in g:
        return True
    if (p, RDF.type, OWL.ObjectProperty) in g or (p, RDF.type, OWL.DatatypeProperty) in g:
        return False
    return p in (RDFS.label, RDFS.comment, RDFS.seeAlso, RDFS.isDefinedBy, OWL.deprecated) \
        or not str(p).startswith(_BUILTIN)


def inventory(g: Graph) -> list[Axiom]:
    """All axioms in ``g``, one entry each (symmetric pairs counted once)."""
    out: dict[str, Axiom] = {}

    def add(ax: Axiom) -> None:
        out.setdefault(ax.id, ax)

    ontologies = {s for s in g.subjects(RDF.type, OWL.Ontology)}
    for s, p, o in g:
        if s in ontologies or p in _IGNORED:
            continue
        if isinstance(s, BNode):
            if p == RDF.type and o in _NARY:
                kind, pred = _NARY[o]
                members = [x for x in _list(g, s, pred)]
                add(Axiom(nary_id(g, kind, members), kind, str(members[0]) if members else "",
                          tuple(members)))
            elif p == RDF.type and o == OWL.NegativePropertyAssertion:
                src = g.value(s, OWL.sourceIndividual)
                add(Axiom(axiom_id(g, "NegativePropertyAssertion", s),
                          "NegativePropertyAssertion", str(src or ""), (s,)))
            continue
        if not isinstance(s, URIRef):
            continue
        if p == RDF.type:
            if o in _DECLARATIONS:
                kind = "Declaration"
                add(Axiom(axiom_id(g, f"Declaration({_DECLARATIONS[o]})", s), kind, str(s), (s, o)))
            elif o in _CHARACTERISTICS:
                add(Axiom(axiom_id(g, _CHARACTERISTICS[o], s), _CHARACTERISTICS[o], str(s), (s,)))
            elif o == OWL.Ontology or o == OWL.Axiom or (
                    isinstance(o, URIRef) and str(o).startswith(_BUILTIN)):
                continue
            else:
                add(Axiom(axiom_id(g, "ClassAssertion", o, s), "ClassAssertion", str(s), (o, s)))
        elif p in _BINARY:
            kind = _BINARY[p][0]
            add(Axiom(binary_id(g, p, s, o), kind, str(s), (s, o)))
        elif p == OWL.deprecated or _is_annotation(g, p):
            add(Axiom(axiom_id(g, "AnnotationAssertion", p, s, o), "AnnotationAssertion",
                      str(s), (s, o), predicate=str(p)))
        elif isinstance(p, URIRef) and not str(p).startswith(_BUILTIN):
            kind = "DataPropertyAssertion" if isinstance(o, Literal) else "ObjectPropertyAssertion"
            add(Axiom(axiom_id(g, kind, p, s, o), kind, str(s), (s, p, o)))
        else:
            add(Axiom(axiom_id(g, "Other", p, s, o), "Other", str(s), (s, p, o),
                      predicate=str(p)))
    return sorted(out.values(), key=lambda a: (a.type, a.subject, a.id))


def _list(g: Graph, node, pred) -> list:
    lst = g.value(node, pred)
    if lst is None:
        return []
    try:
        return list(Collection(g, lst))
    except Exception:  # noqa: BLE001
        return []
