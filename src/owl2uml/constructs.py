"""OWL 2 constructs beyond subclass and restriction lines (spec WS1.2).

Helpers used while parsing (property badges, multiplicities, datatype
facets, individuals) and ``enrich``, a pass over a parsed model that adds
disjointness, disjoint unions, deprecation, definitions, a property key, and
notes on what the diagram cannot show (punning, anonymous individuals).
"""
from __future__ import annotations

from rdflib import BNode, Graph, Literal, OWL, RDF, RDFS, URIRef
from rdflib.collection import Collection
from rdflib.namespace import SKOS, XSD

from .axioms import binary_id, nary_id
from .model import Attr, Edge, UModel

OBO = "http://purl.obolibrary.org/obo/"
IAO_DEFINITION = URIRef(OBO + "IAO_0000115")
DEFINITION_PROPS = (IAO_DEFINITION, SKOS.definition, RDFS.comment)

# Badges on a property name: ⁻¹ has a named inverse, ↔ symmetric,
# ⁺ transitive, ¹ functional.
_BADGES = ((OWL.SymmetricProperty, "↔"), (OWL.TransitiveProperty, "⁺"),
           (OWL.FunctionalProperty, "¹"))
_CHAR_NAMES = {
    OWL.FunctionalProperty: "functional", OWL.InverseFunctionalProperty: "inverse functional",
    OWL.TransitiveProperty: "transitive", OWL.SymmetricProperty: "symmetric",
    OWL.AsymmetricProperty: "asymmetric", OWL.ReflexiveProperty: "reflexive",
    OWL.IrreflexiveProperty: "irreflexive",
}
_FACETS = {
    XSD.minInclusive: ">=", XSD.maxInclusive: "<=", XSD.minExclusive: ">",
    XSD.maxExclusive: "<", XSD.length: "length", XSD.minLength: "minLength",
    XSD.maxLength: "maxLength", XSD.pattern: "pattern",
    URIRef(str(RDF) + "langRange"): "langRange",
}
_PREFERRED_LANGS = ("", "en", "en-us", "en-gb")


def items(g: Graph, node, pred) -> list:
    lst = g.value(node, pred)
    if lst is None:
        return []
    try:
        return list(Collection(g, lst))
    except Exception:  # noqa: BLE001 - malformed list
        return []


def has_inverse(g: Graph, p) -> bool:
    return isinstance(p, URIRef) and (
        any(isinstance(o, URIRef) for o in g.objects(p, OWL.inverseOf))
        or any(isinstance(s, URIRef) for s in g.subjects(OWL.inverseOf, p)))


def badges(g: Graph, p) -> str:
    """' ⁻¹⁺' style suffix for a property name ('' when none apply)."""
    if not isinstance(p, URIRef):
        return ""
    b = "⁻¹" if has_inverse(g, p) else ""
    b += "".join(sym for t, sym in _BADGES if (p, RDF.type, t) in g)
    return f" {b}" if b else ""


def multiplicity(quantifier: str) -> str:
    """'min 1' -> '1..*', 'max 1' -> '0..1', 'exactly 3' -> '3' ('' otherwise)."""
    word, _, n = quantifier.partition(" ")
    if not n:
        return ""
    return {"min": f"{n}..*", "max": f"0..{n}", "exactly": n}.get(word, "")


def short(term) -> str:
    """Local name of a datatype ('integer'), as attribute types are shown."""
    s = str(term)
    for sep in ("#", "/"):
        if sep in s:
            return s.rsplit(sep, 1)[-1] or s
    return s


def datatype_text(g: Graph, node) -> str | None:
    """Text for a data range: 'xsd:integer [>= 18]', '{"a", "b"}', or None
    when ``node`` is not a datatype expression."""
    if isinstance(node, URIRef):
        if str(node).startswith(str(XSD)) or node == RDFS.Literal or \
                (node, RDF.type, RDFS.Datatype) in g:
            return short(node)
        return None
    if not isinstance(node, BNode):
        return None
    base = g.value(node, OWL.onDatatype)
    if base is not None:
        facets = []
        for f in items(g, node, OWL.withRestrictions):
            for p, v in g.predicate_objects(f):
                if p in _FACETS:
                    facets.append(f"{_FACETS[p]} {v}")
        return f"{short(base)} [{', '.join(facets)}]" if facets else short(base)
    lits = items(g, node, OWL.oneOf)
    if lits and all(isinstance(x, Literal) for x in lits):
        return "{" + ", ".join(f'"{x}"' for x in lits) + "}"
    for pred, op in ((OWL.unionOf, " or "), (OWL.intersectionOf, " and ")):
        parts = items(g, node, pred)
        if parts:
            texts = [datatype_text(g, x) for x in parts]
            if all(texts):
                return op.join(texts)
    c = g.value(node, OWL.datatypeComplementOf)
    if c is not None:
        inner = datatype_text(g, c)
        return f"not {inner}" if inner else None
    return None


def is_individual(g: Graph, node) -> bool:
    """A named individual (declared, or typed by a class and not a class itself)."""
    if not isinstance(node, URIRef):
        return False
    if (node, RDF.type, OWL.NamedIndividual) in g:
        return True
    if (node, RDF.type, OWL.Class) in g or (node, RDF.type, RDFS.Class) in g:
        return False
    return any(isinstance(t, URIRef) and ((t, RDF.type, OWL.Class) in g)
               for t in g.objects(node, RDF.type))


def individual_type(g: Graph, node) -> URIRef | None:
    return next((t for t in sorted(g.objects(node, RDF.type), key=str)
                 if isinstance(t, URIRef) and t != OWL.NamedIndividual
                 and not str(t).startswith(str(OWL))), None)


def best_literal(g: Graph, s, preds) -> str:
    """First value of ``preds`` on ``s``, preferring English/untagged."""
    for p in preds:
        vals = [o for o in g.objects(s, p) if isinstance(o, Literal)]
        vals.sort(key=lambda o: (getattr(o, "language", None) or "").lower() not in _PREFERRED_LANGS)
        if vals:
            return " ".join(str(vals[0]).split())
    return ""


# --------------------------------------------------------------------------

def enrich(g: Graph, m: UModel, register, display) -> None:
    """Add what the subclass/restriction pass does not draw.

    ``register(uri) -> cid`` adds a named class to the model; ``display(term)``
    names a term. Called by parse_ontology after its own passes.
    """
    _disjointness(g, m, register)
    _sibling_cliques(g, m)
    _disjoint_unions(g, m, register)
    for cid, c in m.classes.items():
        if c.kind not in ("class", "individual"):
            continue
        u = URIRef(cid)
        c.deprecated = any(str(v).lower() in ("true", "1") for v in g.objects(u, OWL.deprecated))
        c.definition = best_literal(g, u, DEFINITION_PROPS)
    m.properties = property_key(g, m, display)
    m.notes = _unhandled(g, display)


def _disjointness(g: Graph, m: UModel, register) -> None:
    seen: set[frozenset] = set()
    for a, b in g.subject_objects(OWL.disjointWith):
        if isinstance(a, URIRef) and isinstance(b, URIRef) and a != b:
            key = frozenset((a, b))
            if key not in seen:
                seen.add(key)
                m.edges.append(Edge(src=register(a), dst=register(b), kind="disjoint", label="⊥",
                                    axioms=[binary_id(g, OWL.disjointWith, a, b)]))
    hub = 0
    for ax in g.subjects(RDF.type, OWL.AllDisjointClasses):
        all_members = items(g, ax, OWL.members)
        ids = [nary_id(g, "DisjointClasses", all_members)]
        members = [x for x in all_members if isinstance(x, URIRef)]
        if len(members) == 2:
            key = frozenset(members)
            if key not in seen:
                seen.add(key)
                m.edges.append(Edge(src=register(members[0]), dst=register(members[1]),
                                    kind="disjoint", label="⊥", axioms=ids))
        elif len(members) > 2:
            hub += 1
            hid = f"_:disjoint{hub}"
            node = m.cls(hid, "⊥")
            node.kind = "disjoint"
            node.owner = str(members[0])
            for x in members:
                m.edges.append(Edge(src=hid, dst=register(x), kind="disjoint", axioms=ids))


def _sibling_cliques(g: Graph, m: UModel) -> None:
    """Three or more siblings that are pairwise disjoint get one ⊥ group node
    instead of a line for every pair (BFO states its disjointness pairwise)."""
    pair = {frozenset((e.src, e.dst)): e for e in m.edges if e.kind == "disjoint" and e.src != e.dst
            and not e.src.startswith("_:")}
    if len(pair) < 3:
        return
    children: dict[str, set] = {}
    for sub, sup in g.subject_objects(RDFS.subClassOf):
        if isinstance(sub, URIRef) and isinstance(sup, URIRef):
            children.setdefault(str(sup), set()).add(str(sub))
    used: set[frozenset] = set()
    hub = sum(1 for c in m.classes.values() if c.kind == "disjoint")
    for parent in sorted(children):
        pool = sorted(children[parent])
        clique: list[str] = []
        for c in pool:                       # greedy: grow while pairwise disjoint
            if all(frozenset((c, x)) in pair and frozenset((c, x)) not in used for x in clique):
                clique.append(c)
        if len(clique) < 3:
            continue
        hub += 1
        hid = f"_:disjoint{hub}"
        node = m.cls(hid, "⊥")
        node.kind, node.owner = "disjoint", clique[0]
        ids = sorted({x for i, a in enumerate(clique) for b in clique[i + 1:]
                      for x in pair[frozenset((a, b))].axioms})
        for i, a in enumerate(clique):
            for b in clique[i + 1:]:
                used.add(frozenset((a, b)))
            m.edges.append(Edge(src=hid, dst=a, kind="disjoint", axioms=ids))
    if used:
        m.edges = [e for e in m.edges
                   if not (e.kind == "disjoint" and frozenset((e.src, e.dst)) in used)]


def _disjoint_unions(g: Graph, m: UModel, register) -> None:
    for n, (whole, lst) in enumerate(sorted(g.subject_objects(OWL.disjointUnionOf), key=str)):
        if not isinstance(whole, URIRef):
            continue
        wid = register(whole)
        ids = [binary_id(g, OWL.disjointUnionOf, whole, lst)]
        parts = [x for x in items(g, whole, OWL.disjointUnionOf) if isinstance(x, URIRef)]
        for i, part in enumerate(parts):
            m.edges.append(Edge(src=register(part), dst=wid, kind="generalization",
                                genset=f"gs{n}", axioms=ids,
                                label="{disjoint, complete}" if i == 0 else ""))


def property_key(g: Graph, m: UModel, display) -> dict:
    """What the key says about each property drawn on a line: badges,
    characteristics, super-properties, inverse, chains."""
    used = {p for e in m.edges for p in e.props}
    out = {}
    for p in sorted(used):
        u = URIRef(p)
        info = {
            "name": display(u) + badges(g, u),
            "characteristics": [n for t, n in _CHAR_NAMES.items() if (u, RDF.type, t) in g],
            "super": [display(s) for s in g.objects(u, RDFS.subPropertyOf) if isinstance(s, URIRef)],
            "inverse": [display(i) for i in set(g.objects(u, OWL.inverseOf))
                        | set(g.subjects(OWL.inverseOf, u)) if isinstance(i, URIRef) and i != u],
            "chains": [" ∘ ".join(display(x) for x in Collection(g, c) if isinstance(x, URIRef))
                       for c in g.objects(u, OWL.propertyChainAxiom)],
        }
        if info["characteristics"] or info["super"] or info["inverse"] or info["chains"]:
            out[p] = info
            m.mentioned.update(str(x) for x in g.objects(u, RDFS.subPropertyOf))
            m.mentioned.update(str(x) for x in set(g.objects(u, OWL.inverseOf))
                               | set(g.subjects(OWL.inverseOf, u)))
    return out


def _unhandled(g: Graph, display) -> list[dict]:
    """Things a class diagram cannot show; listed in the coverage report."""
    notes = []
    classes = {s for t in (OWL.Class, RDFS.Class) for s in g.subjects(RDF.type, t)
               if isinstance(s, URIRef)}
    props = {s for t in (OWL.ObjectProperty, OWL.DatatypeProperty, OWL.AnnotationProperty)
             for s in g.subjects(RDF.type, t) if isinstance(s, URIRef)}
    individuals = {s for s in g.subjects(RDF.type, OWL.NamedIndividual) if isinstance(s, URIRef)}
    for x in sorted((classes & (props | individuals)) | (props & individuals), key=str):
        roles = [r for r, s in (("class", classes), ("property", props),
                                ("individual", individuals)) if x in s]
        notes.append({"kind": "punning", "iri": str(x), "name": display(x),
                      "reason": f"used as {' and '.join(roles)}; drawn as {roles[0]} only"})
    anon = {s for s, t in g.subject_objects(RDF.type)
            if isinstance(s, BNode) and isinstance(t, URIRef) and t in classes}
    if anon:
        notes.append({"kind": "anonymous individuals", "iri": "", "name": f"{len(anon)}",
                      "reason": "blank-node individuals are not drawn"})
    return notes


def property_model(g: Graph, display) -> UModel:
    """``--property-view``: the property hierarchy as its own diagram."""
    m = UModel()
    kinds = ((OWL.ObjectProperty, "object property"), (OWL.DatatypeProperty, "data property"))
    for t, stereo in kinds:
        for p in sorted(g.subjects(RDF.type, t), key=str):
            if not isinstance(p, URIRef):
                continue
            c = m.cls(str(p), display(p) + badges(g, p))
            c.stereotype = stereo
            for d in g.objects(p, RDFS.domain):
                c.attrs.append(_attr("domain", display(d) if isinstance(d, URIRef) else "(expression)"))
            for r in g.objects(p, RDFS.range):
                txt = datatype_text(g, r) or (display(r) if isinstance(r, URIRef) else "(expression)")
                c.attrs.append(_attr("range", txt))
            chars = [n for ct, n in _CHAR_NAMES.items() if (p, RDF.type, ct) in g]
            if chars:
                c.attrs.append(_attr("characteristics", ", ".join(chars)))
            for chain in g.objects(p, OWL.propertyChainAxiom):
                c.attrs.append(_attr("chain", " ∘ ".join(
                    display(x) for x in Collection(g, chain) if isinstance(x, URIRef))))
            c.deprecated = any(str(v).lower() in ("true", "1") for v in g.objects(p, OWL.deprecated))
    for p, s in g.subject_objects(RDFS.subPropertyOf):
        if str(p) in m.classes and str(s) in m.classes:
            m.edges.append(Edge(src=str(p), dst=str(s), kind="generalization"))
    seen = set()
    for p, q in g.subject_objects(OWL.inverseOf):
        key = frozenset((str(p), str(q)))
        if str(p) in m.classes and str(q) in m.classes and key not in seen and p != q:
            seen.add(key)
            m.edges.append(Edge(src=str(p), dst=str(q), kind="equivalent", label="inverse of"))
    for p, q in g.subject_objects(OWL.equivalentProperty):
        if str(p) in m.classes and str(q) in m.classes and p != q:
            m.edges.append(Edge(src=str(p), dst=str(q), kind="equivalent", label="≡"))
    return m


def _attr(name: str, typ: str) -> Attr:
    return Attr(name=name, type=typ)
