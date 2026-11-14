"""The OWL source behind the diagram: what each box and line was drawn from.

A diagram is a summary. This module keeps the axioms it summarises, so a
reader can click a class and see its IRI, definition and axioms (in
Manchester syntax and as the original Turtle), or click a line and see the
axiom that produced it. For a line the reasoner inferred there is no such
axiom; the axioms it most likely rests on are listed instead.

The result is a JSON block embedded in the SVG
(``<script type="application/json" id="o2u-source">``), so a downloaded
diagram still shows its source offline. interact.js reads it.
"""
from __future__ import annotations

import json
import re

from rdflib import BNode, Graph, Literal, OWL, RDF, RDFS, URIRef
from rdflib.collection import Collection
from rdflib.namespace import SKOS, XSD

from .edit import edge_parts
from .model import UModel
from .parse import _build_labels, _display, _local

SCRIPT_ID = "o2u-source"

OBO = "http://purl.obolibrary.org/obo/"
IAO_DEFINITION = URIRef(OBO + "IAO_0000115")
IAO_ELUCIDATION = URIRef(OBO + "IAO_0000600")

# Annotation properties shown first, with readable names when the file
# does not label them itself.
_ANNOTATION_NAMES = {
    IAO_DEFINITION: "definition",
    SKOS.definition: "definition",
    IAO_ELUCIDATION: "elucidation",
    URIRef(OBO + "IAO_0000112"): "example of usage",
    SKOS.example: "example",
    SKOS.scopeNote: "scope note",
    URIRef(OBO + "IAO_0000116"): "editor note",
    SKOS.editorialNote: "editor note",
    RDFS.comment: "comment",
    SKOS.altLabel: "alternative label",
    SKOS.prefLabel: "preferred label",
    URIRef("http://purl.org/dc/elements/1.1/identifier"): "identifier",
    URIRef("http://purl.org/dc/terms/identifier"): "identifier",
}
_DEFINITION_PROPS = (IAO_DEFINITION, SKOS.definition, IAO_ELUCIDATION)

# Structural predicates: shown as axioms, never as annotations.
_LOGICAL = {
    RDF.type, RDFS.subClassOf, OWL.equivalentClass, OWL.disjointWith,
    RDFS.label, RDFS.subPropertyOf, RDFS.domain, RDFS.range, OWL.inverseOf,
    OWL.propertyChainAxiom, OWL.disjointUnionOf, OWL.equivalentProperty,
    OWL.propertyDisjointWith,
}

_CHARACTERISTICS = {
    OWL.FunctionalProperty: "Functional", OWL.InverseFunctionalProperty: "InverseFunctional",
    OWL.TransitiveProperty: "Transitive", OWL.SymmetricProperty: "Symmetric",
    OWL.AsymmetricProperty: "Asymmetric", OWL.ReflexiveProperty: "Reflexive",
    OWL.IrreflexiveProperty: "Irreflexive",
}


class _Writer:
    """Manchester-syntax rendering of class expressions, using labels."""

    def __init__(self, g: Graph, labels: dict):
        self.g = g
        self.labels = labels

    def name(self, term) -> str:
        if isinstance(term, URIRef):
            if term == OWL.Thing:
                return "owl:Thing"
            if term == OWL.Nothing:
                return "owl:Nothing"
            if str(term).startswith(str(XSD)):
                return "xsd:" + _local(term)
            n = _display(term, self.labels)
            return f"'{n}'" if re.search(r"[^\w:.-]", n) else n
        if isinstance(term, Literal):
            dt = f"^^xsd:{_local(term.datatype)}" if term.datatype else ""
            return json.dumps(str(term), ensure_ascii=False) + dt
        return "?"

    def _items(self, node, pred) -> list:
        lst = self.g.value(node, pred)
        if lst is None:
            return []
        try:
            return list(Collection(self.g, lst))
        except Exception:  # noqa: BLE001
            return []

    def prop(self, p) -> str:
        if isinstance(p, BNode):
            inv = self.g.value(p, OWL.inverseOf)
            return f"inverse ({self.name(inv)})" if inv is not None else "?"
        return self.name(p)

    def expr(self, e, nested: bool = False) -> str:
        if not isinstance(e, BNode):
            return self.name(e)
        g = self.g
        wrap = (lambda s: f"({s})") if nested else (lambda s: s)
        for pred, op in ((OWL.intersectionOf, " and "), (OWL.unionOf, " or ")):
            parts = self._items(e, pred)
            if parts:
                return wrap(op.join(self.expr(p, nested=True) for p in parts))
        c = g.value(e, OWL.complementOf)
        if c is not None:
            return f"not {self.expr(c, nested=True)}"
        one = self._items(e, OWL.oneOf)
        if one:
            return "{" + ", ".join(self.name(i) for i in one) + "}"
        p = g.value(e, OWL.onProperty)
        if p is not None:
            pn = self.prop(p)
            for pred, q in ((OWL.someValuesFrom, "some"), (OWL.allValuesFrom, "only")):
                f = g.value(e, pred)
                if f is not None:
                    return wrap(f"{pn} {q} {self.expr(f, nested=True)}")
            v = g.value(e, OWL.hasValue)
            if v is not None:
                return wrap(f"{pn} value {self.name(v)}")
            if g.value(e, OWL.hasSelf) is not None:
                return wrap(f"{pn} Self")
            for preds, q in (((OWL.minQualifiedCardinality, OWL.minCardinality), "min"),
                             ((OWL.maxQualifiedCardinality, OWL.maxCardinality), "max"),
                             ((OWL.qualifiedCardinality, OWL.cardinality), "exactly")):
                for pr in preds:
                    n = g.value(e, pr)
                    if n is not None:
                        f = g.value(e, OWL.onClass) or g.value(e, OWL.onDataRange)
                        tail = f" {self.expr(f, nested=True)}" if f is not None else ""
                        return wrap(f"{pn} {q} {n}{tail}")
        return "?"


def _named_in(g: Graph, e, seen=None) -> set:
    """Every named class and property mentioned inside an expression."""
    seen = seen if seen is not None else set()
    out: set = set()
    if isinstance(e, URIRef):
        return {e}
    if not isinstance(e, BNode) or e in seen:
        return out
    seen.add(e)
    for p, o in g.predicate_objects(e):
        if p == RDF.type:
            continue
        if p in (RDF.first, RDF.rest) or isinstance(o, BNode):
            out |= _named_in(g, o, seen)
        elif isinstance(o, URIRef):
            out.add(o)
    return out


def _cbd(g: Graph, node, out: Graph, seen=None) -> None:
    """Concise bounded description: node's triples, following blank nodes."""
    seen = seen if seen is not None else set()
    if node in seen:
        return
    seen.add(node)
    for p, o in g.predicate_objects(node):
        out.add((node, p, o))
        if isinstance(o, BNode):
            _cbd(g, o, out, seen)


def _turtle(g: Graph, subjects: list) -> str:
    sub = Graph()
    for prefix, ns in g.namespaces():
        sub.bind(prefix, ns, override=True)
    seen: set = set()
    for s in subjects:
        _cbd(g, s, sub, seen)
    text = sub.serialize(format="turtle")
    # Prefix lines are noise in a per-class excerpt.
    body = [ln for ln in text.splitlines() if not ln.startswith("@prefix")]
    return "\n".join(body).strip()


def _curie(g: Graph, term: URIRef) -> str:
    s = str(term)
    if s.startswith(OBO):
        local = s[len(OBO):]
        if "_" in local:
            return local.replace("_", ":", 1)
    try:
        prefix, _ns, local = g.namespace_manager.compute_qname(s, generate=False)
        return f"{prefix}:{local}" if prefix else f":{local}"
    except Exception:  # noqa: BLE001
        pass
    # No prefix bound: an OBO-style local id ("ODP005_0001001") is the
    # short name people use; otherwise keep the full IRI.
    local = _local(term)
    return local if re.fullmatch(r"[A-Za-z]+\d*_\d+", local) else s


def _annotations(g: Graph, term, labels) -> list[list[str]]:
    rows = []
    for p, o in g.predicate_objects(term):
        if p in _LOGICAL or not isinstance(o, Literal):
            continue
        name = _ANNOTATION_NAMES.get(p) or labels.get(p) or _local(p)
        rows.append((0 if p in _DEFINITION_PROPS else 1, name, " ".join(str(o).split())))
    rows.sort(key=lambda r: (r[0], r[1]))
    return [[n, v] for _k, n, v in rows]


def _axiom_sources(g: Graph, term) -> list:
    """Subjects whose descriptions together state term's axioms: the term
    itself plus owl:Axiom annotations on its triples."""
    subs = [term]
    subs += [a for a in g.subjects(OWL.annotatedSource, term) if isinstance(a, BNode)]
    subs += [a for a in g.subjects(RDF.type, OWL.AllDisjointClasses)
             if term in _items_of(g, a, OWL.members)]
    return subs


def _items_of(g: Graph, node, pred) -> list:
    lst = g.value(node, pred)
    if lst is None:
        return []
    try:
        return list(Collection(g, lst))
    except Exception:  # noqa: BLE001
        return []


def _class_axioms(g: Graph, c: URIRef, w: _Writer) -> list[dict]:
    """Logical axioms about a class: kind, Manchester text, terms mentioned."""
    out = []

    def add(kind, expr, owner_first=True):
        out.append({"k": kind, "m": w.expr(expr),
                    "refs": sorted(str(t) for t in _named_in(g, expr))})

    for e in g.objects(c, OWL.equivalentClass):
        add("EquivalentTo", e)
    for e in g.subjects(OWL.equivalentClass, c):
        if isinstance(e, URIRef) and e != c:
            add("EquivalentTo", e)
    for e in g.objects(c, RDFS.subClassOf):
        add("SubClassOf", e)
    for e in set(g.objects(c, OWL.disjointWith)) | {
            s for s in g.subjects(OWL.disjointWith, c) if isinstance(s, URIRef)}:
        add("DisjointWith", e)
    for a in g.subjects(RDF.type, OWL.AllDisjointClasses):
        members = _items_of(g, a, OWL.members)
        if c in members:
            others = [x for x in members if x != c]
            out.append({"k": "DisjointWith",
                        "m": ", ".join(w.expr(x) for x in others),
                        "refs": sorted(str(x) for x in others if isinstance(x, URIRef))})
    du = _items_of(g, c, OWL.disjointUnionOf)
    if du:
        out.append({"k": "DisjointUnionOf", "m": ", ".join(w.expr(x) for x in du),
                    "refs": sorted(str(x) for x in du if isinstance(x, URIRef))})
    order = {"EquivalentTo": 0, "SubClassOf": 1, "DisjointUnionOf": 2, "DisjointWith": 3}
    out.sort(key=lambda a: (order.get(a["k"], 9), a["m"]))
    return out


def _property_axioms(g: Graph, p: URIRef, w: _Writer) -> list[dict]:
    out = []

    def add(kind, text, refs):
        out.append({"k": kind, "m": text, "refs": sorted(str(r) for r in refs)})

    chars = [n for t, n in _CHARACTERISTICS.items() if (p, RDF.type, t) in g]
    if chars:
        add("Characteristics", ", ".join(chars), [])
    for d in g.objects(p, RDFS.domain):
        add("Domain", w.expr(d), _named_in(g, d))
    for r in g.objects(p, RDFS.range):
        add("Range", w.expr(r), _named_in(g, r))
    for s in g.objects(p, RDFS.subPropertyOf):
        add("SubPropertyOf", w.prop(s), [s] if isinstance(s, URIRef) else [])
    for i in set(g.objects(p, OWL.inverseOf)) | set(g.subjects(OWL.inverseOf, p)):
        if isinstance(i, URIRef) and i != p:
            add("InverseOf", w.prop(i), [i])
    for e in g.objects(p, OWL.equivalentProperty):
        add("EquivalentTo", w.prop(e), [e] if isinstance(e, URIRef) else [])
    for chain in g.objects(p, OWL.propertyChainAxiom):
        try:
            links = list(Collection(g, chain))
        except Exception:  # noqa: BLE001
            continue
        add("SubPropertyChain", " o ".join(w.prop(x) for x in links),
            [x for x in links if isinstance(x, URIRef)])
    return out


def _entity(g: Graph, term: URIRef, labels, w: _Writer, axioms: list[dict], frame: str) -> dict:
    # The Manchester frame is assembled in the browser from "ann" and "ax"
    # (see manchester() in interact.js and here), so it is not stored twice.
    return {
        "iri": str(term), "curie": _curie(g, term), "label": _display(term, labels),
        "name": w.name(term), "frame": frame,
        "ann": _annotations(g, term, labels), "ax": axioms,
        "ttl": _turtle(g, _axiom_sources(g, term)),
    }


def manchester(entity: dict) -> str:
    """Manchester-syntax frame for one entity of build_source()'s output."""
    lines = [f"{entity['frame']}: {entity['name']}"]
    parts = [f"rdfs:label {json.dumps(entity['label'], ensure_ascii=False)}"] + \
            [f"{n} {json.dumps(v, ensure_ascii=False)}" for n, v in entity["ann"]]
    lines.append("    Annotations:")
    lines += [f"        {a}" + ("," if i < len(parts) - 1 else "") for i, a in enumerate(parts)]
    kinds: list[str] = []
    for a in entity["ax"]:
        if a["k"] not in kinds:
            kinds.append(a["k"])
    for k in kinds:
        same = [x for x in entity["ax"] if x["k"] == k]
        lines.append(f"    {k}:")
        lines += [f"        {x['m']}" + ("," if i < len(same) - 1 else "")
                  for i, x in enumerate(same)]
    return "\n".join(lines)


def _domains(g: Graph, p) -> set:
    return {x for d in g.objects(p, RDFS.domain) for x in _named_in(g, d)}


def _ranges(g: Graph, p) -> set:
    return {x for r in g.objects(p, RDFS.range) for x in _named_in(g, r)}


def build_source(g: Graph, m: UModel) -> dict:
    """Source excerpts for every class in the model and the axioms behind
    each drawn line. Node and edge keys match the ids Graphviz gives them
    (``n<i>``, ``e<i>``, see dot.to_dot)."""
    labels = _build_labels(g)
    w = _Writer(g, labels)

    classes: dict[str, dict] = {}
    nodes: dict[str, str] = {}
    for i, cid in enumerate(m.classes):
        nodes[f"n{i}"] = cid
        term = URIRef(cid)
        classes[cid] = _entity(g, term, labels, w, _class_axioms(g, term, w), "Class")

    props: dict[str, dict] = {}

    def prop(p: URIRef) -> str:
        key = str(p)
        if key not in props:
            props[key] = _entity(g, p, labels, w, _property_axioms(g, p, w), "ObjectProperty"
                                 if (p, RDF.type, OWL.ObjectProperty) in g else "Property")
        return key

    # Properties referenced by the classes' axioms are available to the panel.
    for c in classes.values():
        for a in c["ax"]:
            for r in a["refs"]:
                t = URIRef(r)
                if (t, RDF.type, OWL.ObjectProperty) in g or (t, RDF.type, OWL.DatatypeProperty) in g:
                    prop(t)

    obj_props = [p for p in g.subjects(RDF.type, OWL.ObjectProperty) if isinstance(p, URIRef)]
    edges: dict[str, dict] = {}
    for i, e in enumerate(m.edges):
        if e.src not in classes or e.dst not in classes:
            continue
        src, dst = URIRef(e.src), URIRef(e.dst)
        info: dict = {"src": e.src, "dst": e.dst, "kind": e.kind, "label": e.label}
        if e.kind == "association":
            info["props"] = [prop(p) for p in obj_props
                             if src in _domains(g, p) and dst in _ranges(g, p)]
        elif e.kind == "inferred":
            info["premises"] = _premises(g, src, dst, classes, prop)
        else:
            refs = [[e.src, j] for j, a in enumerate(classes[e.src]["ax"]) if e.dst in a["refs"]]
            if e.kind == "equivalent":
                refs += [[e.dst, j] for j, a in enumerate(classes[e.dst]["ax"])
                         if e.src in a["refs"]]
            info["axioms"] = refs
            if e.kind == "restriction":   # edit mode: one handle per axiom
                info["parts"] = edge_parts(g, e.kind, e.src, e.dst)
        edges[f"e{i}"] = info

    # Every object property, for edit mode's property picker.
    plabels = _build_labels(g)
    objprops = {str(p): _display(p, plabels) for p in set(g.subjects(RDF.type, OWL.ObjectProperty))
                if isinstance(p, URIRef)}
    return {"version": 1, "ontology": m.ontology_iri, "nodes": nodes,
            "classes": classes, "props": props, "edges": edges, "objprops": objprops}


def _premises(g: Graph, src: URIRef, dst: URIRef, classes: dict, prop) -> dict:
    """Axioms an inferred subsumption most likely rests on: the subclass's own
    axioms, the superclass's definition, and the property hierarchy that
    connects the properties the two mention. (A full justification needs a
    reasoner's explanation service; this is the usual case.)"""
    sa = classes[str(src)]["ax"]
    da = classes[str(dst)]["ax"]
    out = {"classes": [[str(src), j] for j in range(len(sa))
                       if sa[j]["k"] in ("SubClassOf", "EquivalentTo")],
           "props": []}
    out["classes"] += [[str(dst), j] for j in range(len(da)) if da[j]["k"] == "EquivalentTo"]

    def mentioned(axs):
        return {URIRef(r) for a in axs for r in a["refs"]
                if (URIRef(r), RDF.type, OWL.ObjectProperty) in g}

    sp = mentioned(sa[j] for _c, j in out["classes"] if _c == str(src))
    dp = mentioned(da)
    keep: set = set()
    # Walk up rdfs:subPropertyOf from each property the subclass uses; keep
    # every property on a path that reaches one the superclass's definition uses.
    for p in sp:
        stack = [(p, [p])]
        seen = set()
        while stack:
            q, path = stack.pop()
            if q in dp and len(path) > 1:
                keep.update(path)
            for up in g.objects(q, RDFS.subPropertyOf):
                if isinstance(up, URIRef) and up not in seen:
                    seen.add(up)
                    stack.append((up, path + [up]))
    # Property chains on the superclass's properties that use the subclass's.
    for q in dp:
        for chain in g.objects(q, OWL.propertyChainAxiom):
            try:
                links = set(Collection(g, chain))
            except Exception:  # noqa: BLE001
                continue
            if links & sp:
                keep.add(q)
                keep.update(x for x in links if isinstance(x, URIRef))
    out["props"] = [prop(p) for p in sorted(keep, key=str)]
    return out


def to_json(data: dict) -> str:
    """JSON safe to put inside an SVG/HTML <script> element as text."""
    s = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    return s.replace("&", "\\u0026").replace("<", "\\u003c").replace(">", "\\u003e")


def embed(svg: str, data: dict) -> str:
    """Insert the source block just inside the root <svg> element."""
    block = (f'<script type="application/json" id="{SCRIPT_ID}">'
             f"{to_json(data)}</script>")
    i = svg.find(">", svg.find("<svg")) + 1
    return svg[:i] + "\n" + block + svg[i:]


def inline_viewer(svg: str) -> str:
    """Append the browser viewer (webapp/static/interact.js) to an SVG, as the
    web app's Download button does, so the file is interactive on its own."""
    import os
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    with open(os.path.join(here, "webapp", "static", "interact.js"), encoding="utf-8") as fh:
        js = fh.read()
    js = js.replace("]]>", "]]]]><![CDATA[>")
    script = ("<script><![CDATA[\n" + js +
              "\nOwlUmlInteract.attach(document.documentElement, { standalone: true });\n]]></script>\n")
    i = svg.rfind("</svg>")
    return svg[:i] + script + svg[i:]
