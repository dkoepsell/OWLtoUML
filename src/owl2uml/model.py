"""UML class-diagram model produced from an OWL/RDFS ontology."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Attr:
    """A datatype property rendered as a class attribute."""
    name: str
    type: str = ""

    def label(self) -> str:
        return f"{self.name}: {self.type}" if self.type else self.name


# Edge kinds:
#   "generalization"  rdfs:subClassOf between named classes (asserted)
#   "definition"      a named member of an owl:equivalentClass intersection:
#                     the class is *defined* as (among other things) a kind of
#                     this one (necessary and sufficient)
#   "association"     an object property's rdfs:domain -> rdfs:range
#   "restriction"     an existential/universal/cardinality restriction on the
#                     class (in rdfs:subClassOf or owl:equivalentClass)
#   "equivalent"      owl:equivalentClass between two named classes
#   "inferred"        a subclass relation found by a reasoner and not already
#                     implied by the asserted hierarchy (see reason.py)
EDGE_KINDS = ("generalization", "definition", "association", "restriction",
              "equivalent", "inferred")

# Kinds that place a class below another in the class hierarchy.
HIERARCHY_KINDS = ("generalization", "definition", "inferred")


@dataclass
class Edge:
    """A relationship between two classes."""
    src: str           # class id (URI string)
    dst: str           # class id (URI string)
    kind: str          # one of EDGE_KINDS
    label: str = ""    # property name (associations, restrictions)


@dataclass
class UClass:
    """A UML class box."""
    id: str
    name: str
    attrs: list[Attr] = field(default_factory=list)
    stereotype: str = ""
    group: str = ""        # namespace / IRI-prefix group, for colouring
    defined: bool = False  # has an owl:equivalentClass definition
    unsatisfiable: bool = False   # reasoner: equivalent to owl:Nothing
    inferred_placed: bool = False # reasoner: gained a superclass nobody asserted

    # filled in by the layout pass
    x: float = 0.0
    y: float = 0.0
    w: float = 0.0
    h: float = 0.0
    layer: int = 0


@dataclass
class Group:
    """A set of classes sharing a namespace or IRI prefix (e.g. BFO, ODP003)."""
    name: str
    color: str = ""
    count: int = 0
    upper: bool = False    # imported upper-level / external vocabulary


@dataclass
class UModel:
    classes: dict[str, UClass] = field(default_factory=dict)
    edges: list[Edge] = field(default_factory=list)
    groups: dict[str, Group] = field(default_factory=dict)
    ontology_iri: str = ""

    def cls(self, cid: str, name: str | None = None) -> UClass:
        """Get or create a class node by id."""
        c = self.classes.get(cid)
        if c is None:
            c = UClass(id=cid, name=name or cid)
            self.classes[cid] = c
        elif name and (c.name == c.id or not c.name):
            c.name = name
        return c
