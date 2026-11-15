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
#   "disjoint"        owl:disjointWith / AllDisjointClasses (between two
#                     classes, or from a ⊥ group node to each member)
#   "member"          from an anonymous ⊔ / ¬ node to the class it is built on
#   "self"            a hasSelf restriction (a loop on the class)
EDGE_KINDS = ("generalization", "definition", "association", "restriction",
              "equivalent", "inferred", "disjoint", "member", "self")

# Node kinds. "class" is a named OWL class; the others are drawn differently:
#   "union" ⊔ and "complement" ¬   anonymous class expressions (owner = the
#                                  class whose axiom they come from)
#   "disjoint"                     ⊥ node grouping 3+ mutually disjoint classes
#   "individual"                   a named individual (hasValue), UML object
#   "enumeration"                  an anonymous oneOf {a, b, c}
NODE_KINDS = ("class", "union", "complement", "disjoint", "individual", "enumeration")
ANON_KINDS = ("union", "complement", "disjoint", "enumeration")

# Kinds that place a class below another in the class hierarchy.
HIERARCHY_KINDS = ("generalization", "definition", "inferred")


@dataclass
class Edge:
    """A relationship between two classes."""
    src: str           # class id (URI string)
    dst: str           # class id (URI string)
    kind: str          # one of EDGE_KINDS
    label: str = ""    # property name (associations, restrictions)
    multiplicity: str = ""   # UML multiplicity at the target end: "1..*", "0..1", "3"
    genset: str = ""         # generalization set id (DisjointUnion): one shared arrowhead
    props: list[str] = field(default_factory=list)   # property IRIs behind the label


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
    kind: str = "class"    # one of NODE_KINDS
    owner: str = ""        # anonymous nodes: the class whose axiom made them
    deprecated: bool = False      # owl:deprecated true
    definition: str = ""          # IAO_0000115 / skos:definition / rdfs:comment

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
    iri: str = ""          # for a group made from an owl:imports ontology
    version_iri: str = ""


@dataclass
class UModel:
    classes: dict[str, UClass] = field(default_factory=dict)
    edges: list[Edge] = field(default_factory=list)
    groups: dict[str, Group] = field(default_factory=dict)
    ontology_iri: str = ""
    # from the loader (load.annotate_model): resolved owl:imports, and which
    # imported ontology each entity not declared in the main one came from
    imports: list[dict] = field(default_factory=list)
    import_of: dict[str, str] = field(default_factory=dict)
    # property IRI -> what the key says about it (constructs.property_key)
    properties: dict[str, dict] = field(default_factory=dict)
    # what the diagram cannot show (punning, anonymous individuals)
    notes: list[dict] = field(default_factory=list)

    def cls(self, cid: str, name: str | None = None) -> UClass:
        """Get or create a class node by id."""
        c = self.classes.get(cid)
        if c is None:
            c = UClass(id=cid, name=name or cid)
            self.classes[cid] = c
        elif name and (c.name == c.id or not c.name):
            c.name = name
        return c
