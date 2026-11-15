"""Parse an OWL/RDFS ontology (any rdflib-supported format) into a UModel."""
from __future__ import annotations

from rdflib import Graph, RDF, RDFS, OWL, URIRef, BNode, Literal
from rdflib.collection import Collection
from rdflib.namespace import XSD

from .bfo_labels import BFO_LABELS
from .model import Attr, Edge, UModel


def _local(term) -> str:
    """Human-friendly local name from a URI/BNode."""
    if isinstance(term, BNode):
        return ""
    s = str(term)
    for sep in ("#", "/"):
        if sep in s:
            tail = s.rsplit(sep, 1)[-1]
            if tail:
                return tail
    return s


# Language tags we treat as "preferred" when an entity carries rdfs:labels in
# several languages (untagged literals are assumed English / canonical).
_PREFERRED_LANGS = ("", "en", "en-us", "en-gb")


def _build_labels(g: Graph) -> dict[URIRef, str]:
    """Map each URI to its best rdfs:label.

    Ontologies like ECO/GO/OBO name classes with opaque numeric IDs
    (``ECO_0000001``) and put the readable name in ``rdfs:label``. Showing the
    label instead of the bare ID is what makes the diagram legible. When an
    entity has labels in multiple languages we prefer an English/untagged one.
    """
    chosen: dict[URIRef, tuple[bool, str]] = {}
    for s, o in g.subject_objects(RDFS.label):
        if not isinstance(s, URIRef):
            continue
        text = " ".join(str(o).split()).strip()
        if not text:
            continue
        lang = (getattr(o, "language", None) or "").lower()
        preferred = lang in _PREFERRED_LANGS
        prev = chosen.get(s)
        # Keep the first label seen, but let a preferred-language label win.
        if prev is None or (preferred and not prev[0]):
            chosen[s] = (preferred, text)
    return {uri: text for uri, (_pref, text) in chosen.items()}


def _display(term, labels: dict[URIRef, str]) -> str:
    """Readable name for a term: its rdfs:label if known, else the local name."""
    if isinstance(term, URIRef):
        lbl = labels.get(term)
        if lbl:
            return lbl
    name = _local(term)
    # Fall back to BFO's own published label for imported upper-level classes
    # that arrive without an rdfs:label (e.g. "BFO_0000001" -> "entity").
    return BFO_LABELS.get(name, name)


# ---------------------------------------------------------------------------
# Class expressions
#
# OWL ontologies say much of what they mean in anonymous class expressions:
# a *defined* class is owl:equivalentClass to an intersection ("a sanction is
# a legal position that sanctions some legal position"), and necessary
# conditions are restrictions under rdfs:subClassOf ("every legal order has
# some recognition criterion"). Reading only named superclasses leaves defined
# classes with no edges at all, so they float, disconnected, at the edge of
# the drawing. The helpers below turn those expressions into diagram edges.
# ---------------------------------------------------------------------------

def _members(g: Graph, node, pred) -> list:
    """Items of an RDF list hanging off ``node`` via ``pred`` (e.g. owl:intersectionOf)."""
    lst = g.value(node, pred)
    if lst is None:
        return []
    try:
        return list(Collection(g, lst))
    except Exception:  # noqa: BLE001 - malformed list
        return []


def _prop_name(g: Graph, p, labels) -> str:
    """Readable name for a restriction's property, including owl:inverseOf."""
    if isinstance(p, BNode):
        inv = g.value(p, OWL.inverseOf)
        return f"inverse {_display(inv, labels)}" if inv is not None else ""
    return _display(p, labels)


def _restriction(g: Graph, r, labels):
    """(property name, quantifier, filler) for an owl:Restriction, or None."""
    prop = g.value(r, OWL.onProperty)
    if prop is None:
        return None
    pname = _prop_name(g, prop, labels)
    for pred, q in ((OWL.someValuesFrom, "some"), (OWL.allValuesFrom, "only")):
        filler = g.value(r, pred)
        if filler is not None:
            return pname, q, filler
    for pred, q in ((OWL.minQualifiedCardinality, "min"), (OWL.maxQualifiedCardinality, "max"),
                    (OWL.qualifiedCardinality, "exactly")):
        n = g.value(r, pred)
        if n is not None:
            return pname, f"{q} {n}", g.value(r, OWL.onClass) or g.value(r, OWL.onDataRange)
    for pred, q in ((OWL.minCardinality, "min"), (OWL.maxCardinality, "max"),
                    (OWL.cardinality, "exactly")):
        n = g.value(r, pred)
        if n is not None:
            return pname, f"{q} {n}", None
    v = g.value(r, OWL.hasValue)
    if v is not None:
        return pname, "value", v
    return None


def _named_fillers(g: Graph, filler) -> list:
    """Named classes a restriction filler points at (expanding unions/intersections)."""
    if isinstance(filler, URIRef):
        return [filler]
    if isinstance(filler, BNode):
        out = []
        for pred in (OWL.unionOf, OWL.intersectionOf):
            for item in _members(g, filler, pred):
                if isinstance(item, URIRef):
                    out.append(item)
        return out
    return []


def _union_or_self(g: Graph, node) -> list:
    """A named class, or the named members of an owl:unionOf (for domains/ranges)."""
    if isinstance(node, URIRef):
        return [node]
    if isinstance(node, BNode):
        return [m for m in _members(g, node, OWL.unionOf) if isinstance(m, URIRef)]
    return []


def _is_datatype(g: Graph, node) -> bool:
    return isinstance(node, URIRef) and (
        str(node).startswith(str(XSD)) or str(node) == str(RDFS.Literal)
        or (node, RDF.type, RDFS.Datatype) in g)


def load_graph(path: str, fmt: str | None = None) -> Graph:
    """Parse one file into an rdflib Graph, without its imports. Any OWL 2
    syntax is accepted (see load.py); use ``load.load`` for imports."""
    from .load import load
    return load(path, fmt=fmt, imports="none").graph


def parse_ontology(path: str, fmt: str | None = None, graph: Graph | None = None) -> UModel:
    """Build the UML model. Pass ``graph`` to reuse an already-parsed graph."""
    g = graph if graph is not None else load_graph(path, fmt)

    m = UModel()
    labels = _build_labels(g)
    onts = [o for o in g.subjects(RDF.type, OWL.Ontology) if isinstance(o, URIRef)]
    if onts:
        m.ontology_iri = str(sorted(onts, key=str)[0])

    # --- 1. Named classes -------------------------------------------------
    class_uris: set[URIRef] = set()
    for ctype in (OWL.Class, RDFS.Class):
        for s in g.subjects(RDF.type, ctype):
            if isinstance(s, URIRef):
                class_uris.add(s)

    def register_class(uri: URIRef) -> str:
        cid = str(uri)
        m.cls(cid, _display(uri, labels))
        return cid

    for uri in class_uris:
        register_class(uri)

    # --- 2. Subclass (generalization) edges -------------------------------
    for sub, sup in g.subject_objects(RDFS.subClassOf):
        # "subclass of owl:Thing" says nothing worth a box and a line
        if isinstance(sub, URIRef) and isinstance(sup, URIRef) and sup != OWL.Thing:
            register_class(sub)
            register_class(sup)
            m.edges.append(Edge(src=str(sub), dst=str(sup), kind="generalization"))

    # --- 2b. Class expressions: definitions and restrictions --------------
    owl_thing = OWL.Thing

    def add_expr(cls_uri: URIRef, expr, defining: bool) -> None:
        """Turn one superclass / equivalent-class expression into edges."""
        cid = str(cls_uri)
        if isinstance(expr, URIRef):
            if expr == owl_thing:
                return
            register_class(expr)
            if defining:
                m.edges.append(Edge(src=cid, dst=str(expr), kind="equivalent", label="≡"))
            return
        if not isinstance(expr, BNode):
            return
        parts = _members(g, expr, OWL.intersectionOf)
        if parts:
            for part in parts:
                if isinstance(part, URIRef):
                    if part == owl_thing:
                        continue
                    register_class(part)
                    m.edges.append(Edge(
                        src=cid, dst=str(part),
                        kind="definition" if defining else "generalization"))
                else:
                    add_expr(cls_uri, part, defining=defining)
            return
        if (expr, RDF.type, OWL.Restriction) in g or g.value(expr, OWL.onProperty) is not None:
            res = _restriction(g, expr, labels)
            if res is None:
                return
            pname, q, filler = res
            label = f"{pname} {q}"
            targets = _named_fillers(g, filler) if filler is not None else []
            if filler is not None and _is_datatype(g, filler):
                m.classes[cid].attrs.append(Attr(name=label, type=_local(filler)))
                return
            for t in targets:
                if t == owl_thing:
                    continue
                register_class(t)
                m.edges.append(Edge(src=cid, dst=str(t), kind="restriction", label=label))
            if not targets and isinstance(filler, (Literal, URIRef)) and q == "value":
                m.classes[cid].attrs.append(Attr(name=label, type=_display(filler, labels)))
            elif not targets and filler is None:
                m.classes[cid].attrs.append(Attr(name=label))
        # unionOf / complementOf as a superclass or definition: no faithful
        # single edge exists, so it is left out of the diagram.

    for sub, sup in g.subject_objects(RDFS.subClassOf):
        if isinstance(sub, URIRef) and isinstance(sup, BNode):
            register_class(sub)
            add_expr(sub, sup, defining=False)

    for a, b in g.subject_objects(OWL.equivalentClass):
        for cls_uri, expr in ((a, b), (b, a)):
            if isinstance(cls_uri, URIRef) and not (isinstance(expr, URIRef) and str(expr) < str(cls_uri)):
                if isinstance(expr, BNode) and not _members(g, expr, OWL.intersectionOf) \
                        and g.value(expr, OWL.onProperty) is None:
                    continue
                register_class(cls_uri)
                if isinstance(expr, BNode):
                    m.classes[str(cls_uri)].defined = True
                add_expr(cls_uri, expr, defining=True)

    # --- 3. Properties ----------------------------------------------------
    prop_uris: set[URIRef] = set()
    for ptype in (OWL.ObjectProperty, OWL.DatatypeProperty,
                  RDF.Property, OWL.FunctionalProperty):
        for s in g.subjects(RDF.type, ptype):
            if isinstance(s, URIRef):
                prop_uris.add(s)

    for p in prop_uris:
        name = _display(p, labels)
        # Domains/ranges may be unions of classes ("legal order or legal
        # content"); expand them to their named members.
        domains = [d for x in g.objects(p, RDFS.domain) for d in _union_or_self(g, x)]
        ranges = [r for x in g.objects(p, RDFS.range) for r in _union_or_self(g, x)]
        is_object = (p, RDF.type, OWL.ObjectProperty) in g
        is_data = (p, RDF.type, OWL.DatatypeProperty) in g

        # Classify: datatype -> attribute; object/class-range -> association.
        def is_class_range(r: URIRef) -> bool:
            return r in class_uris or (str(r).startswith(str(OWL)) is False
                                       and not str(r).startswith(str(XSD))
                                       and not is_data)

        if not domains:
            # Orphan property: skip (cannot attach to a class box).
            continue

        for d in domains:
            dcid = str(d)
            m.cls(dcid, _display(d, labels))
            if not ranges:
                # Unknown range -> show as attribute with no type.
                if not is_object:
                    m.classes[dcid].attrs.append(Attr(name=name))
                continue
            for r in ranges:
                if is_data or str(r).startswith(str(XSD)):
                    m.classes[dcid].attrs.append(Attr(name=name, type=_local(r)))
                elif is_object or r in class_uris:
                    rcid = str(r)
                    m.cls(rcid, _display(r, labels))
                    m.edges.append(
                        Edge(src=dcid, dst=rcid, kind="association", label=name)
                    )
                else:
                    m.classes[dcid].attrs.append(Attr(name=name, type=_local(r)))

    # Deduplicate attributes per class (stable order).
    for c in m.classes.values():
        seen: set[tuple[str, str]] = set()
        unique: list[Attr] = []
        for a in c.attrs:
            key = (a.name, a.type)
            if key not in seen:
                seen.add(key)
                unique.append(a)
        c.attrs = unique

    return m
