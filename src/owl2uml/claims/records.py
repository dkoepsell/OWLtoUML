"""Claims and asserted axioms as output records (spec section 7.3 and 7.4).

Each record carries the English sentence, its Manchester form, the IRIs it
uses and, for claims that can be explained, the Functional-syntax axiom the
explainer is asked about.
"""
from __future__ import annotations

from rdflib import BNode, Graph, Literal, OWL, RDF, URIRef
from rdflib.collection import Collection

from ..axioms import Axiom, inventory
from ..source import _named_in
from .analyze import Claim
from .signature import Signature, items
from .verbalize import Verbalizer, cap

NOTHING = "<http://www.w3.org/2002/07/owl#Nothing>"
STATUS_ORDER = {"ENTAILED": 0, "REFUTED": 1, "POSSIBLE": 2, "UNDETERMINED": 3, "ASSERTED": 4}

_LOGICAL = {"SubClassOf", "EquivalentClasses", "DisjointClasses", "DisjointUnion",
            "PropertyDomain", "PropertyRange", "SubPropertyOf", "InverseObjectProperties",
            "EquivalentProperties", "DisjointProperties", "SubPropertyChainOf",
            "FunctionalProperty", "InverseFunctionalObjectProperty", "TransitiveObjectProperty",
            "SymmetricObjectProperty", "AsymmetricObjectProperty", "ReflexiveObjectProperty",
            "IrreflexiveObjectProperty", "ClassAssertion", "ObjectPropertyAssertion", "HasKey"}
_CHAR_NAMES = {"FunctionalProperty": "Functional",
               "InverseFunctionalObjectProperty": "InverseFunctional",
               "TransitiveObjectProperty": "Transitive", "SymmetricObjectProperty": "Symmetric",
               "AsymmetricObjectProperty": "Asymmetric", "ReflexiveObjectProperty": "Reflexive",
               "IrreflexiveObjectProperty": "Irreflexive"}


# ---- Functional syntax (for the explainer) ----------------------------------

def fs(g: Graph, e) -> str:
    if isinstance(e, URIRef):
        return f"<{e}>"
    if not isinstance(e, BNode):
        raise ValueError(f"not a class expression: {e!r}")
    for pred, op in ((OWL.intersectionOf, "ObjectIntersectionOf"), (OWL.unionOf, "ObjectUnionOf")):
        parts = items(g, e, pred)
        if parts:
            return f"{op}(" + " ".join(fs(g, x) for x in parts) + ")"
    c = g.value(e, OWL.complementOf)
    if c is not None:
        return f"ObjectComplementOf({fs(g, c)})"
    p = g.value(e, OWL.onProperty)
    if p is None:
        raise ValueError("unsupported class expression")
    pt = _fs_prop(g, p)
    for pred, op in ((OWL.someValuesFrom, "ObjectSomeValuesFrom"),
                     (OWL.allValuesFrom, "ObjectAllValuesFrom")):
        f = g.value(e, pred)
        if f is not None:
            return f"{op}({pt} {fs(g, f)})"
    v = g.value(e, OWL.hasValue)
    if isinstance(v, URIRef):
        return f"ObjectHasValue({pt} <{v}>)"
    for preds, op in (((OWL.minQualifiedCardinality, OWL.minCardinality), "ObjectMinCardinality"),
                      ((OWL.maxQualifiedCardinality, OWL.maxCardinality), "ObjectMaxCardinality"),
                      ((OWL.qualifiedCardinality, OWL.cardinality), "ObjectExactCardinality")):
        for pr in preds:
            n = g.value(e, pr)
            if n is not None:
                f = g.value(e, OWL.onClass)
                return f"{op}({int(n)} {pt}" + (f" {fs(g, f)})" if f is not None else ")")
    raise ValueError("unsupported class expression")


def _fs_prop(g: Graph, p) -> str:
    if isinstance(p, BNode):
        return f"ObjectInverseOf(<{g.value(p, OWL.inverseOf)}>)"
    return f"<{p}>"


# ---- claims ----------------------------------------------------------------------

def claim_record(v: Verbalizer, c: Claim, sig: Signature | None = None) -> dict:
    rec = {"grammar": c.grammar, "status": c.status, "tier": c.tier,
           "defn_linked": c.defn_linked, "reasoners": dict(c.reasoners)}
    iris = [x for x in (c.a, c.p, c.b) if x is not None]
    query = None
    if c.kind in ("sub", "near"):
        la = v.label(c.a)
        if c.kind == "sub":
            text = f"Every {la} is {v.a(c.b)}."
        else:
            text = f"The ontology neither entails nor rules out that every {la} is {v.a(c.b)}."
        man = f"{v.m(c.a)} SubClassOf {v.m(c.b)}"
        query = f"SubClassOf(<{c.a}> <{c.b}>)"
    elif c.kind == "disj":
        # A native class is the subject; between two native classes, label order.
        x, y = sorted((c.a, c.b), key=lambda t: (not (sig and sig.is_native(t)), v.label(t)))
        text = f"No {v.label(x)} is {v.a(y)}."
        man = f"{v.m(x)} DisjointWith {v.m(y)}"
        query = f"DisjointClasses(<{x}> <{y}>)"
        iris = [x, y]
    elif c.kind == "some":
        text = f"Every {v.label(c.a)} {v.verb_phrase(c.p)} some {v.label(c.b)}."
        man = f"{v.m(c.a)} SubClassOf {v.m(c.p)} some {v.m(c.b)}"
        query = f"SubClassOf(<{c.a}> ObjectSomeValuesFrom(<{c.p}> <{c.b}>))"
    elif c.kind == "nosome":
        text = f"No {v.label(c.a)} {v.verb_phrase(c.p)} {v.a(c.b)}."
        man = f"{v.m(c.a)} SubClassOf not ({v.m(c.p)} some {v.m(c.b)})"
        query = f"SubClassOf(<{c.a}> ObjectComplementOf(ObjectSomeValuesFrom(<{c.p}> <{c.b}>)))"
    elif c.kind == "unsat":
        text = f"There cannot be {v.a(c.a)}."
        man = f"{v.m(c.a)} SubClassOf owl:Nothing"
        query = f"SubClassOf(<{c.a}> {NOTHING})"
    elif c.kind in ("possible", "impossible"):
        np = v.np(c.node, c.graph)
        iris = sorted(_named_in(c.graph, c.node), key=str)
        if c.kind == "possible":
            text = f"There can be {np}."
            man = f"not ({v.m(c.node, c.graph)} SubClassOf owl:Nothing)"
        else:
            text = f"There cannot be {np}."
            man = f"{v.m(c.node, c.graph)} SubClassOf owl:Nothing"
            query = f"SubClassOf({fs(c.graph, c.node)} {NOTHING})"
    elif c.kind == "expect":
        text, man, query, iris = _expect_record(v, c)
    else:
        raise ValueError(f"unknown claim kind {c.kind}")
    rec.update(text=text, manchester=man, iris=sorted({str(i) for i in iris}))
    if c.tier == "inferred" and query:
        rec["_query"] = query
    if c.grammar == "G6":
        rec["expect_line"] = c.node["line"]
    return rec


def _expect_record(v: Verbalizer, c: Claim):
    cand, g = c.node, c.graph
    lhs, rhs, kind = cand["lhs"], cand["rhs"], cand["kind"]
    nl, pr, npr = v.nom(lhs, g), v.pred(rhs, g), v.np(rhs, g)
    if kind == "SubClassOf":
        claim = f"every {nl} {pr}"
    elif kind == "EquivalentTo":
        claim = f"every {nl} {pr}, and every {v.nom(rhs, g)} {v.pred(lhs, g)}"
    else:
        claim = f"no {nl} is {npr}"
    if c.status == "UNDETERMINED":
        text = f"The ontology neither entails nor rules out that {claim}."
    elif c.status == "REFUTED":
        text = f"No {nl} is {npr}."
    else:
        text = cap(claim) + "."
    man = f"{v.m(lhs, g)} {kind} {v.m(rhs, g)}"
    l_fs, r_fs = fs(g, lhs), fs(g, rhs)
    if c.status == "REFUTED" or (c.status == "ENTAILED" and kind == "DisjointWith"):
        query = f"DisjointClasses({l_fs} {r_fs})"
    elif kind == "EquivalentTo":
        query = f"EquivalentClasses({l_fs} {r_fs})"
    else:
        query = f"SubClassOf({l_fs} {r_fs})"
    iris = _named_in(g, lhs) | _named_in(g, rhs)
    return text, man, query, iris


# ---- asserted axioms -----------------------------------------------------------

def asserted_records(g: Graph, sig: Signature, v: Verbalizer) -> list[dict]:
    out = []
    for ax in inventory(g):
        if ax.type not in _LOGICAL:
            continue
        subj = URIRef(ax.subject) if ax.subject else None
        if subj is None or not sig.is_native(subj):
            continue
        text = sentence(g, ax, v)
        man = manchester(g, ax, v)
        names = set()
        for t in ax.terms:
            if isinstance(t, URIRef):
                names.add(t)
            elif isinstance(t, BNode):
                names |= _named_in(g, t)
        out.append({"grammar": "A", "status": "ASSERTED", "tier": "asserted",
                    "text": text, "manchester": man, "axiom_id": ax.id,
                    "iris": sorted(str(n) for n in names if not str(n).startswith(str(OWL))),
                    "defn_linked": False, "reasoners": {}})
    return out


def sentence(g: Graph, ax: Axiom, v: Verbalizer) -> str:
    t = ax.type
    try:
        if t == "SubClassOf":
            s, o = ax.terms
            neg = g.value(o, OWL.complementOf) if isinstance(o, BNode) else None
            if isinstance(neg, URIRef):
                return f"No {v.nom(s)} is {v.a(neg)}."
            if neg is not None and g.value(neg, OWL.onProperty) is not None \
                    and g.value(neg, OWL.someValuesFrom) is not None:
                f = g.value(neg, OWL.someValuesFrom)
                return f"No {v.nom(s)} {v.verb_phrase(g.value(neg, OWL.onProperty))} {v.np(f)}."
            return f"Every {v.nom(s)} {v.pred(o)}."
        if t == "EquivalentClasses":
            s, o = ax.terms
            if isinstance(o, URIRef):
                return f"Every {v.label(s)} is {v.a(o)}, and every {v.label(o)} is {v.a(s)}."
            return f"{cap(v.a(s))} is defined as {v.np(o)}."
        if t == "DisjointClasses":
            ms = list(ax.terms)
            if len(ms) == 2:
                x, y = sorted(ms, key=lambda m: v.nom(m))
                return f"No {v.nom(x)} is {v.np(y)}."
            return "Nothing is more than one of: " + ", ".join(v.np(m) for m in ms) + "."
        if t == "PropertyDomain":
            p, d = ax.terms
            return f"Only {v.np(d)} {v.verb_phrase(p)} anything."
        if t == "PropertyRange":
            p, r = ax.terms
            return f"Whatever something {v.verb_phrase(p)} is {v.np(r)}."
        if t == "SubPropertyOf":
            p, q = ax.terms
            return f"For any x and y: if x {v.verb_phrase(p)} y, then x {v.verb_phrase(q)} y."
        if t == "InverseObjectProperties":
            p, q = ax.terms
            return f"For any x and y: x {v.verb_phrase(p)} y exactly when y {v.verb_phrase(q)} x."
        if t == "SubPropertyChainOf":
            p, head = ax.terms
            links = list(Collection(g, head))
            if len(links) == 2:
                return (f"For any x, y and z: if x {v.verb_phrase(links[0])} y and "
                        f"y {v.verb_phrase(links[1])} z, then x {v.verb_phrase(p)} z.")
        if t == "TransitiveObjectProperty":
            vp = v.verb_phrase(ax.terms[0])
            return f"For any x, y and z: if x {vp} y and y {vp} z, then x {vp} z."
        if t == "SymmetricObjectProperty":
            vp = v.verb_phrase(ax.terms[0])
            return f"For any x and y: if x {vp} y, then y {vp} x."
        if t == "FunctionalProperty" and (ax.terms[0], RDF.type, OWL.ObjectProperty) in g:
            return f"Each thing {v.verb_phrase(ax.terms[0])} at most one thing."
        if t == "InverseFunctionalObjectProperty":
            return f"For any y: at most one thing {v.verb_phrase(ax.terms[0])} y."
        if t == "ClassAssertion":
            c, i = ax.terms
            return f"{cap(v.label(i))} {v.pred(c)}."
        if t == "ObjectPropertyAssertion":
            s, p, o = ax.terms
            return f"{cap(v.label(s))} {v.verb_phrase(p)} {v.label(o)}."
    except Exception:  # noqa: BLE001 - fall back to Manchester
        pass
    return "Asserted: " + manchester(g, ax, v)


def manchester(g: Graph, ax: Axiom, v: Verbalizer) -> str:
    t, terms = ax.type, ax.terms

    def m(x):
        return v.m(x, g)

    if t == "SubClassOf":
        return f"{m(terms[0])} SubClassOf {m(terms[1])}"
    if t == "EquivalentClasses":
        return f"{m(terms[0])} EquivalentTo {m(terms[1])}"
    if t == "DisjointClasses":
        return "DisjointClasses: " + ", ".join(m(x) for x in terms) if len(terms) > 2 \
            else f"{m(terms[0])} DisjointWith {m(terms[1])}"
    if t == "PropertyDomain":
        return f"{m(terms[0])} Domain {m(terms[1])}"
    if t == "PropertyRange":
        return f"{m(terms[0])} Range {m(terms[1])}"
    if t == "SubPropertyOf":
        return f"{m(terms[0])} SubPropertyOf {m(terms[1])}"
    if t == "InverseObjectProperties":
        return f"{m(terms[0])} InverseOf {m(terms[1])}"
    if t == "EquivalentProperties":
        return f"{m(terms[0])} EquivalentTo {m(terms[1])}"
    if t == "DisjointProperties":
        return f"{m(terms[0])} DisjointWith {m(terms[1])}"
    if t == "SubPropertyChainOf":
        try:
            links = list(Collection(g, terms[1]))
            return " o ".join(m(x) for x in links) + f" SubPropertyOf {m(terms[0])}"
        except Exception:  # noqa: BLE001
            return f"{m(terms[0])} SubPropertyChain ?"
    if t in _CHAR_NAMES:
        return f"{m(terms[0])} Characteristics: {_CHAR_NAMES[t]}"
    if t == "ClassAssertion":
        return f"{m(terms[1])} Types: {m(terms[0])}"
    if t == "ObjectPropertyAssertion":
        return f"{m(terms[0])} Facts: {m(terms[1])} {m(terms[2])}"
    if t == "DisjointUnion":
        try:
            return f"{m(terms[0])} DisjointUnionOf: " + ", ".join(
                m(x) for x in Collection(g, terms[1]))
        except Exception:  # noqa: BLE001
            pass
    return f"{t}(" + " ".join(m(x) if not isinstance(x, Literal) else str(x) for x in terms) + ")"
