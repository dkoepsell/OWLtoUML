"""Asserted-axiom layer of a version diff (spec WS4.1).

Axioms are compared by the stable ids of axioms.py: a canonical rendering in
which blank-node expressions are written out structurally, so the same
restriction in two files (or two syntaxes) is the same axiom. Declarations
are left to the entity layer.
"""
from __future__ import annotations

from rdflib import RDF, BNode, Graph, URIRef
from rdflib.collection import Collection

from ..axioms import Axiom, inventory
from ..parse import _build_labels
from ..source import _Writer

LOGICAL_SKIP = {"Declaration"}
_INFIX = {"SubClassOf", "EquivalentClasses", "DisjointClasses", "SubPropertyOf",
          "EquivalentProperties", "InverseObjectProperties", "DisjointProperties",
          "SameIndividual", "DifferentIndividuals", "DisjointUnion", "SubPropertyChainOf",
          "HasKey"}
_WORD = {"SubClassOf": "SubClassOf", "EquivalentClasses": "EquivalentTo",
         "DisjointClasses": "DisjointWith", "SubPropertyOf": "SubPropertyOf",
         "EquivalentProperties": "EquivalentTo", "InverseObjectProperties": "InverseOf",
         "DisjointProperties": "DisjointWith", "SameIndividual": "SameAs",
         "DifferentIndividuals": "DifferentFrom", "DisjointUnion": "DisjointUnionOf",
         "SubPropertyChainOf": "SubPropertyChain", "HasKey": "HasKey"}


class Texts:
    """Manchester-style text for the axioms of one graph."""

    def __init__(self, g: Graph):
        self.g = g
        self.w = _Writer(g, _build_labels(g))

    def term(self, t) -> str:
        if isinstance(t, BNode) and (t, RDF.first, None) in self.g:
            try:
                return ", ".join(self.w.expr(x, nested=True) for x in Collection(self.g, t))
            except Exception:  # noqa: BLE001 - malformed list
                return "?"
        return self.w.expr(t) if isinstance(t, BNode) else self.w.name(t)

    def __call__(self, ax: Axiom) -> str:
        t, k = ax.terms, ax.type
        if k in _INFIX and len(t) == 2:
            if k == "SubPropertyChainOf":
                return f"{self.term(t[0])} SubPropertyChain {' o '.join(self._list(t[1]))}"
            return f"{self.term(t[0])} {_WORD[k]} {self.term(t[1])}"
        if k in ("PropertyDomain", "PropertyRange") and len(t) == 2:
            return f"{self.term(t[0])} {k[8:]} {self.term(t[1])}"
        if k == "ClassAssertion" and len(t) == 2:
            return f"{self.term(t[1])} Type {self.term(t[0])}"
        if k == "AnnotationAssertion" and len(t) == 2:
            return f"{self.term(t[0])} {self.w.name(URIRef(ax.predicate))} {self.term(t[1])}"
        if k.endswith("PropertyAssertion") and len(t) == 3:
            return f"{self.term(t[0])} {self.term(t[1])} {self.term(t[2])}"
        if k == "Declaration" and len(t) == 2:
            return f"Declaration({self.w.name(t[1])} {self.term(t[0])})"
        return f"{k}({', '.join(self.term(x) for x in t)})"

    def _list(self, node) -> list[str]:
        try:
            return [self.w.name(x) if isinstance(x, URIRef) else self.w.prop(x)
                    for x in Collection(self.g, node)]
        except Exception:  # noqa: BLE001
            return ["?"]


def index(g: Graph) -> dict[str, Axiom]:
    return {a.id: a for a in inventory(g)}


def row(ax: Axiom, text: Texts) -> dict:
    return {"id": ax.id, "type": ax.type, "subject": ax.subject, "text": text(ax),
            "annotation": ax.type == "AnnotationAssertion"}


def diff(old: Graph, new: Graph, io: dict | None = None, inew: dict | None = None) -> dict:
    io = io if io is not None else index(old)
    inew = inew if inew is not None else index(new)
    to, tn = Texts(old), Texts(new)
    added = [row(inew[i], tn) for i in sorted(set(inew) - set(io))
             if inew[i].type not in LOGICAL_SKIP]
    removed = [row(io[i], to) for i in sorted(set(io) - set(inew))
               if io[i].type not in LOGICAL_SKIP]
    key = (lambda r: (r["annotation"], r["type"], r["text"]))
    return {"added": sorted(added, key=key), "removed": sorted(removed, key=key)}
