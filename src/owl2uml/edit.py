"""Apply diagram edits (made in the web UI's edit mode) to an rdflib Graph.

Edits are semantic operations naming classes and properties by IRI, so they
can be replayed onto a freshly parsed graph (the server keeps no state):

  {"op": "add_class",    "iri"?, "label", "parent"?}
  {"op": "rename",       "iri", "label"}
  {"op": "delete_class", "iri"}
  {"op": "add_property", "iri"?, "label"}
  {"op": "add_edge",     "kind", "src", "dst", "prop"?, "quant"?}
  {"op": "delete_edge",  "edge": {"kind", "src", "dst", "prop"?, "quant"?}}
  {"op": "retarget",     "edge": {...}, "end": "src"|"dst", "to"}

Edge kinds are the model's (see model.EDGE_KINDS) plus the shorthand
"subclass" (= generalization). "inferred" edges are not editable.
An op that cannot be applied is skipped and reported, never fatal.
"""
from __future__ import annotations

import re
from datetime import date

from rdflib import BNode, Graph, Literal, URIRef
from rdflib.collection import Collection
from rdflib.namespace import OWL, RDF, RDFS

MAX_OPS = 2000
OPS = ("add_class", "rename", "delete_class", "add_property",
       "add_edge", "delete_edge", "retarget")
QUANTS = {"some": OWL.someValuesFrom, "only": OWL.allValuesFrom}
_CARD = {"min": OWL.minQualifiedCardinality, "max": OWL.maxQualifiedCardinality,
         "exactly": OWL.qualifiedCardinality}
_IRI_RE = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*:[^\s<>\"{}|\\^`]+$")


class EditError(ValueError):
    """An op that cannot be applied to this graph."""


# ---- helpers -----------------------------------------------------------------
def _iri(v) -> URIRef:
    if not isinstance(v, str) or not _IRI_RE.match(v):
        raise EditError(f"not an IRI: {v!r}")
    return URIRef(v)


def _label(v) -> str:
    if not isinstance(v, str) or not v.strip() or len(v) > 500:
        raise EditError("label must be a non-empty string")
    return v.strip()


_OBO = "http://purl.obolibrary.org/obo/"


def _namespace(g: Graph) -> str:
    """Namespace for new IRIs: where most of the ontology's own classes live
    (imported OBO terms aside), else under the ontology IRI. The web UI's
    edit.js mints IRIs the same way."""
    onto = next((str(o) for o in g.subjects(RDF.type, OWL.Ontology) if isinstance(o, URIRef)), "")
    counts: dict[str, int] = {}
    for c in g.subjects(RDF.type, OWL.Class):
        if isinstance(c, URIRef):
            s = str(c)
            if s.startswith(_OBO) and not onto.startswith(_OBO):
                continue
            cut = max(s.rfind("#"), s.rfind("/"))
            if cut > 0:
                counts[s[:cut + 1]] = counts.get(s[:cut + 1], 0) + 1
    if counts:
        return max(counts, key=counts.get)
    if onto:
        return onto if onto.endswith(("#", "/")) else onto + "#"
    return "http://example.org/draft#"


def mint_iri(g: Graph, label: str, lower: bool = False) -> URIRef:
    """A fresh IRI in the ontology's namespace from a label (CamelCase)."""
    words = re.findall(r"[A-Za-z0-9]+", label) or ["New"]
    name = "".join(w[:1].upper() + w[1:] for w in words)
    if lower:
        name = name[:1].lower() + name[1:]
    if name[0].isdigit():
        name = "_" + name
    ns = _namespace(g)
    iri, n = URIRef(ns + name), 2
    while (iri, None, None) in g or (None, None, iri) in g:
        iri, n = URIRef(f"{ns}{name}{n}"), n + 1
    return iri


def _remove_bnode(g: Graph, node) -> None:
    """Remove a blank node and everything only reachable through it."""
    if not isinstance(node, BNode):
        return
    for p, o in list(g.predicate_objects(node)):
        g.remove((node, p, o))
        if isinstance(o, BNode) and (None, None, o) not in g:
            _remove_bnode(g, o)


def _remove_triple(g: Graph, s, p, o) -> None:
    g.remove((s, p, o))
    # owl:Axiom annotations on the removed triple
    for ax in list(g.subjects(OWL.annotatedSource, s)):
        if (ax, OWL.annotatedProperty, p) in g and (ax, OWL.annotatedTarget, o) in g:
            for pp, oo in list(g.predicate_objects(ax)):
                g.remove((ax, pp, oo))
    if isinstance(o, BNode) and (None, None, o) not in g:
        _remove_bnode(g, o)


def _list_items(g: Graph, node, pred) -> list:
    lst = g.value(node, pred)
    if lst is None:
        return []
    try:
        return list(Collection(g, lst))
    except Exception:  # noqa: BLE001
        return []


def _set_list(g: Graph, node, pred, items: list) -> None:
    old = g.value(node, pred)
    if old is not None:
        g.remove((node, pred, old))
        cur, seen = old, set()
        while isinstance(cur, BNode) and cur not in seen:   # unlink the old cells
            seen.add(cur)
            nxt = g.value(cur, RDF.rest)
            g.remove((cur, RDF.first, None))
            g.remove((cur, RDF.rest, None))
            cur = nxt
    if not items:
        g.add((node, pred, RDF.nil))
        return
    head = BNode()
    Collection(g, head, items)
    g.add((node, pred, head))


def _restrictions(g: Graph, s, p, quant, d):
    """(axiom predicate, restriction node) pairs on s matching p / quant / filler d."""
    out = []
    for ap in (RDFS.subClassOf, OWL.equivalentClass):
        for r in g.objects(s, ap):
            cands = [r] if (r, OWL.onProperty, None) in g else [
                m for m in _list_items(g, r, OWL.intersectionOf)
                if (m, OWL.onProperty, None) in g]
            for rr in cands:
                if p is not None and g.value(rr, OWL.onProperty) != p:
                    continue
                if _filler_pred(g, rr, quant, d) is not None:
                    out.append((ap, r, rr))
    return out


def _filler_pred(g: Graph, r, quant, d):
    """The predicate linking restriction r to filler d (honouring quant), or None."""
    preds = list(QUANTS.values()) + [OWL.onClass]
    if quant:
        q = quant.split()[0]
        preds = [QUANTS[q]] if q in QUANTS else [OWL.onClass] if q in _CARD else preds
    for pred in preds:
        f = g.value(r, pred)
        if f == d:
            return pred
        if isinstance(f, BNode) and d in _list_items(g, f, OWL.unionOf) + _list_items(g, f, OWL.intersectionOf):
            return pred
    return None


def _norm_kind(k: str) -> str:
    k = {"subclass": "generalization", "domain_range": "association",
         "some": "restriction", "only": "restriction"}.get(k, k)
    if k not in ("generalization", "definition", "association", "restriction", "equivalent"):
        raise EditError(f"edge kind not editable: {k!r}")
    return k


def _edge(spec) -> dict:
    if not isinstance(spec, dict):
        raise EditError("edge must be an object")
    e = {"kind": spec.get("kind", ""), "src": _iri(spec.get("src")), "dst": _iri(spec.get("dst")),
         "prop": _iri(spec["prop"]) if spec.get("prop") else None,
         "quant": spec.get("quant") or ""}
    if spec.get("kind") in ("some", "only") and not e["quant"]:
        e["quant"] = spec["kind"]
    e["kind"] = _norm_kind(e["kind"])
    return e


# ---- ops ---------------------------------------------------------------------
def _add_class(g, op):
    label = _label(op.get("label"))
    iri = _iri(op["iri"]) if op.get("iri") else mint_iri(g, label)
    g.add((iri, RDF.type, OWL.Class))
    g.add((iri, RDFS.label, Literal(label)))
    if op.get("parent"):
        g.add((iri, RDFS.subClassOf, _iri(op["parent"])))
    return str(iri)


def _rename(g, op):
    iri, label = _iri(op.get("iri")), _label(op.get("label"))
    old = list(g.objects(iri, RDFS.label))
    lang = next((o.language for o in old if isinstance(o, Literal) and o.language), None)
    if lang:   # only replace labels in that language
        for o in old:
            if isinstance(o, Literal) and o.language == lang:
                g.remove((iri, RDFS.label, o))
    else:
        g.remove((iri, RDFS.label, None))
    g.add((iri, RDFS.label, Literal(label, lang=lang)))


def _delete_class(g, op):
    iri = _iri(op.get("iri"))
    if (iri, None, None) not in g and (None, None, iri) not in g:
        raise EditError(f"no such class: {iri}")
    for p, o in list(g.predicate_objects(iri)):
        _remove_triple(g, iri, p, o)
    # References elsewhere: drop it from lists, and drop restrictions/axioms that use it.
    _detach(g, iri)


def _detach(g: Graph, node, depth: int = 0) -> None:
    """Remove every reference to node: from a list, it is taken out of the list;
    a named subject loses the triple; a blank-node expression that used it
    (e.g. a restriction whose filler was deleted) is itself detached."""
    if depth > 50:
        return
    for s, p in list(g.subject_predicates(node)):
        if (s, p, node) not in g:
            continue
        if p == RDF.first:
            head, owner = _list_owner(g, s)
            if owner is not None:
                os_, op_ = owner
                _set_list(g, os_, op_, [i for i in _list_items(g, os_, op_) if i != node])
            else:
                g.remove((s, p, node))
        elif isinstance(s, URIRef):
            _remove_triple(g, s, p, node)
        else:
            g.remove((s, p, node))
            _detach(g, s, depth + 1)
            _remove_bnode(g, s)


def _list_owner(g: Graph, cell):
    """(head cell, (subject, predicate) holding the list) for a list cell."""
    head, seen = cell, set()
    while head not in seen:
        seen.add(head)
        prev = g.value(predicate=RDF.rest, object=head)
        if prev is None:
            break
        head = prev
    owner = next(iter(g.subject_predicates(head)), None)
    return head, owner


def _add_property(g, op):
    label = _label(op.get("label"))
    iri = _iri(op["iri"]) if op.get("iri") else mint_iri(g, label, lower=True)
    g.add((iri, RDF.type, OWL.ObjectProperty))
    g.add((iri, RDFS.label, Literal(label)))
    return str(iri)


def _add_edge(g, e):
    k, s, d, p = e["kind"], e["src"], e["dst"], e["prop"]
    if k == "generalization":
        g.add((s, RDFS.subClassOf, d))
    elif k == "equivalent":
        g.add((s, OWL.equivalentClass, d))
    elif k == "association":
        if p is None:
            raise EditError("an association needs a property")
        g.add((p, RDF.type, OWL.ObjectProperty))
        g.add((p, RDFS.domain, s))
        g.add((p, RDFS.range, d))
    elif k == "restriction":
        if p is None:
            raise EditError("a restriction needs a property")
        q = (e["quant"] or "some").split()
        r = BNode()
        g.add((r, RDF.type, OWL.Restriction))
        g.add((r, OWL.onProperty, p))
        if q[0] in QUANTS:
            g.add((r, QUANTS[q[0]], d))
        elif q[0] in _CARD and len(q) > 1 and q[1].isdigit():
            g.add((r, _CARD[q[0]], Literal(int(q[1]), datatype=URIRef(
                "http://www.w3.org/2001/XMLSchema#nonNegativeInteger"))))
            g.add((r, OWL.onClass, d))
        else:
            raise EditError(f"unknown quantifier: {e['quant']!r}")
        g.add((s, RDFS.subClassOf, r))
    elif k == "definition":
        defs = [x for x in g.objects(s, OWL.equivalentClass)
                if isinstance(x, BNode) and g.value(x, OWL.intersectionOf) is not None]
        if defs:
            _set_list(g, defs[0], OWL.intersectionOf,
                      _list_items(g, defs[0], OWL.intersectionOf) + [d])
        else:
            x = BNode()
            g.add((x, RDF.type, OWL.Class))
            _set_list(g, x, OWL.intersectionOf, [d])
            g.add((s, OWL.equivalentClass, x))


def _delete_edge(g, e):
    """Remove the axiom(s) behind an edge; return a dict to re-create it elsewhere."""
    k, s, d, p = e["kind"], e["src"], e["dst"], e["prop"]
    if k == "generalization":
        if (s, RDFS.subClassOf, d) not in g:
            raise EditError("subclass axiom not found")
        _remove_triple(g, s, RDFS.subClassOf, d)
        return {}
    if k == "equivalent":
        if (s, OWL.equivalentClass, d) in g:
            _remove_triple(g, s, OWL.equivalentClass, d)
        elif (d, OWL.equivalentClass, s) in g:
            _remove_triple(g, d, OWL.equivalentClass, s)
        else:
            raise EditError("equivalence axiom not found")
        return {}
    if k == "association":
        props = [p] if p is not None else [
            x for x in g.subjects(RDFS.domain, None)
            if _in_union(g, g.value(x, RDFS.domain), s) and _in_union(g, g.value(x, RDFS.range), d)]
        # The diagram draws domain x range as a cross product, so one line is
        # removed by taking src out of the domain; the range goes too only
        # when src was the property's sole domain class.
        hit = False
        for pp in props:
            dom = _members(g, pp, RDFS.domain)
            rng = _members(g, pp, RDFS.range)
            if s not in dom or d not in rng:
                continue
            hit = True
            _drop_member(g, pp, RDFS.domain, s)
            if len(dom) == 1:
                _drop_member(g, pp, RDFS.range, d)
        if not hit:
            raise EditError("domain/range not found")
        return {}
    if k == "restriction":
        found = _restrictions(g, s, p, e["quant"], d)
        if not found:
            raise EditError("restriction not found")
        ap, top, r = found[0]
        f = g.value(r, _filler_pred(g, r, e["quant"], d))
        if isinstance(f, BNode) and d in _list_items(g, f, OWL.unionOf) \
                and len(_list_items(g, f, OWL.unionOf)) > 1:
            # "p some (A or B)": only this line's class leaves the union
            _set_list(g, f, OWL.unionOf, [i for i in _list_items(g, f, OWL.unionOf) if i != d])
        elif top == r:
            _remove_triple(g, s, ap, r)
        else:   # a conjunct of a definition: drop it from the intersection
            _set_list(g, top, OWL.intersectionOf,
                      [m for m in _list_items(g, top, OWL.intersectionOf) if m != r])
            _remove_bnode(g, r)
        return {}
    if k == "definition":
        for x in list(g.objects(s, OWL.equivalentClass)):
            items = _list_items(g, x, OWL.intersectionOf) if isinstance(x, BNode) else []
            if d in items:
                _set_list(g, x, OWL.intersectionOf, [i for i in items if i != d])
                return {}
        raise EditError("definition member not found")
    raise EditError(f"cannot delete {k}")


def _members(g, p, pred) -> list:
    out = []
    for o in g.objects(p, pred):
        out += _list_items(g, o, OWL.unionOf) if isinstance(o, BNode) else [o]
    return out


def _drop_member(g, p, pred, cls) -> None:
    for o in list(g.objects(p, pred)):
        if o == cls:
            g.remove((p, pred, o))
        elif isinstance(o, BNode) and cls in _list_items(g, o, OWL.unionOf):
            _set_list(g, o, OWL.unionOf, [i for i in _list_items(g, o, OWL.unionOf) if i != cls])


def _in_union(g, node, cls) -> bool:
    return node == cls or (isinstance(node, BNode) and cls in _list_items(g, node, OWL.unionOf))


def _retarget(g, op):
    e = _edge(op.get("edge"))
    end = op.get("end")
    if end not in ("src", "dst"):
        raise EditError("end must be 'src' or 'dst'")
    to = _iri(op.get("to"))
    if e["kind"] == "restriction" and end == "dst":
        # Keep the restriction node (cardinality, annotations): swap its filler.
        found = _restrictions(g, e["src"], e["prop"], e["quant"], e["dst"])
        if not found:
            raise EditError("restriction not found")
        r = found[0][2]
        pred = _filler_pred(g, r, e["quant"], e["dst"])
        f = g.value(r, pred)
        if f == e["dst"]:
            g.set((r, pred, to))
        else:  # union/intersection filler
            lp = OWL.unionOf if e["dst"] in _list_items(g, f, OWL.unionOf) else OWL.intersectionOf
            _set_list(g, f, lp, [to if i == e["dst"] else i for i in _list_items(g, f, lp)])
        return
    _delete_edge(g, e)
    new = dict(e)
    new[end] = to
    _add_edge(g, new)


_QUANT_NAME = {OWL.someValuesFrom: "some", OWL.allValuesFrom: "only"}
_CARD_NAME = {OWL.minQualifiedCardinality: "min", OWL.maxQualifiedCardinality: "max",
              OWL.qualifiedCardinality: "exactly", OWL.minCardinality: "min",
              OWL.maxCardinality: "max", OWL.cardinality: "exactly"}


def edge_parts(g: Graph, kind: str, src: str, dst: str) -> list[dict]:
    """The separately editable axioms behind one drawn restriction line
    (a merged line like "hasPart some / partOf only" has several):
    [{"prop": iri, "quant": "some"|"only"|"min 2"|...}]."""
    if kind != "restriction":
        return []
    out, seen = [], set()
    for _ap, _top, r in _restrictions(g, URIRef(src), None, "", URIRef(dst)):
        p = g.value(r, OWL.onProperty)
        q = next((n for pred, n in _QUANT_NAME.items() if (r, pred, None) in g), None)
        if q is None:
            for pred, n in _CARD_NAME.items():
                v = g.value(r, pred)
                if v is not None:
                    q = f"{n} {v}"
                    break
        key = (str(p), q or "some")
        if p is not None and key not in seen:
            seen.add(key)
            out.append({"prop": key[0], "quant": key[1]})
    return out


def apply_edits(g: Graph, ops) -> dict:
    """Apply ops in order. Returns {"applied": n, "skipped": [{"i", "op", "reason"}], "minted": {i: iri}}."""
    if not isinstance(ops, list):
        raise EditError("edits must be a list")
    if len(ops) > MAX_OPS:
        raise EditError(f"too many edits (max {MAX_OPS})")
    applied, skipped, minted = 0, [], {}
    for i, op in enumerate(ops):
        try:
            if not isinstance(op, dict) or op.get("op") not in OPS:
                raise EditError(f"unknown op: {op!r:.80}")
            kind = op["op"]
            if kind == "add_class":
                minted[i] = _add_class(g, op)
            elif kind == "rename":
                _rename(g, op)
            elif kind == "delete_class":
                _delete_class(g, op)
            elif kind == "add_property":
                minted[i] = _add_property(g, op)
            elif kind == "add_edge":
                _add_edge(g, _edge(op))
            elif kind == "delete_edge":
                _delete_edge(g, _edge(op.get("edge")))
            elif kind == "retarget":
                _retarget(g, op)
            applied += 1
        except (EditError, KeyError, TypeError) as exc:
            skipped.append({"i": i, "op": op.get("op") if isinstance(op, dict) else None,
                            "reason": str(exc)})
    return {"applied": applied, "skipped": skipped, "minted": minted}


def serialize(g: Graph, fmt: str = "turtle") -> bytes:
    """Serialize an edited graph, noting the edit on the ontology header."""
    for o in g.subjects(RDF.type, OWL.Ontology):
        g.add((o, RDFS.comment, Literal(f"Draft edited with owl2uml on {date.today().isoformat()}.")))
        break
    fmt = {"ttl": "turtle", "owl": "xml", "rdf": "xml"}.get(fmt, fmt)
    if fmt not in ("turtle", "xml", "nt", "json-ld"):
        fmt = "turtle"
    return g.serialize(format=fmt, encoding="utf-8")
