"""``--expect FILE``: candidate axioms the user wants checked (grammar row G6).

One axiom per line, in Manchester syntax, with entities named by their
rdfs:label (quoted when it has spaces), a CURIE the ontology binds, or a
full <IRI>:

    'irreversibly accountable agent' SubClassOf 'accountable agent'
    sanction SubClassOf realizes some answerability
    nao:0001020 DisjointWith 'irreversibly accountable agent'

Supported: SubClassOf, EquivalentTo, DisjointWith; and, or, not, some,
only, value, min/max/exactly n, inverse (p), owl:Thing, owl:Nothing,
parentheses. Blank lines and lines starting with # are ignored.
"""
from __future__ import annotations

import re

from rdflib import BNode, Graph, Literal, OWL, RDF, RDFS, URIRef
from rdflib.collection import Collection

KEYWORDS = ("SubClassOf", "EquivalentTo", "DisjointWith")
_TOKEN = re.compile(r"\s*(?:(<[^>]*>)|('(?:[^'\\]|\\.)*')|(\()|(\))|([^\s()]+))")


class ExpectError(ValueError):
    pass


def _tokens(text: str) -> list[str]:
    out, pos = [], 0
    while pos < len(text):
        m = _TOKEN.match(text, pos)
        if not m or m.end() == pos:
            if text[pos:].strip():
                raise ExpectError(f"cannot read '{text[pos:]}'")
            break
        tok = next(x for x in m.groups() if x is not None)
        out.append(tok)
        pos = m.end()
    return out


class _Resolver:
    def __init__(self, g: Graph):
        self.g = g
        self.by_label: dict[str, set] = {}
        for s, o in g.subject_objects(RDFS.label):
            if isinstance(s, URIRef):
                self.by_label.setdefault(" ".join(str(o).split()).lower(), set()).add(s)
        self.props = {p for p in g.subjects(RDF.type, OWL.ObjectProperty)}
        self.inds = {i for i in g.subjects(RDF.type, OWL.NamedIndividual)}

    def resolve(self, tok: str, want: str) -> URIRef:
        if tok.startswith("<") and tok.endswith(">"):
            return URIRef(tok[1:-1])
        if tok in ("owl:Thing", "Thing"):
            return OWL.Thing
        if tok in ("owl:Nothing", "Nothing"):
            return OWL.Nothing
        name = tok[1:-1].replace("\\'", "'") if tok.startswith("'") else tok
        found = self.by_label.get(" ".join(name.split()).lower(), set())
        if not found and ":" in name and not name.startswith("'"):
            prefix, local = name.split(":", 1)
            for pfx, ns in self.g.namespaces():
                if pfx == prefix:
                    found = {URIRef(str(ns) + local)}
        if want == "property":
            pick = [x for x in found if x in self.props] or list(found)
        elif want == "individual":
            pick = [x for x in found if x in self.inds] or list(found)
        else:
            pick = [x for x in found if x not in self.props and x not in self.inds] or list(found)
        if len(pick) != 1:
            raise ExpectError(f"'{name}' names {'no' if not pick else 'more than one'} {want}")
        return pick[0]


class _Parser:
    def __init__(self, toks: list[str], r: _Resolver, out: Graph):
        self.t, self.i, self.r, self.g = toks, 0, r, out

    def peek(self):
        return self.t[self.i] if self.i < len(self.t) else None

    def take(self, want=None):
        tok = self.peek()
        if tok is None or (want is not None and tok != want):
            raise ExpectError(f"expected {want or 'more'}, got {tok or 'end of line'}")
        self.i += 1
        return tok

    def expr(self):
        parts = [self.conj()]
        while self.peek() == "or":
            self.take()
            parts.append(self.conj())
        return parts[0] if len(parts) == 1 else self._list(OWL.unionOf, parts)

    def conj(self):
        parts = [self.unary()]
        while self.peek() == "and":
            self.take()
            parts.append(self.unary())
        return parts[0] if len(parts) == 1 else self._list(OWL.intersectionOf, parts)

    def unary(self):
        if self.peek() == "not":
            self.take()
            n = BNode()
            self.g.add((n, RDF.type, OWL.Class))
            self.g.add((n, OWL.complementOf, self.unary()))
            return n
        if self.peek() == "(":
            self.take("(")
            e = self.expr()
            self.take(")")
            return e
        if self.peek() == "inverse" or (self.i + 1 < len(self.t)
                                        and self.t[self.i + 1] in ("some", "only", "value",
                                                                   "min", "max", "exactly")):
            return self.restriction()
        return self.r.resolve(self.take(), "class")

    def prop(self):
        if self.peek() == "inverse":
            self.take()
            self.take("(")
            p = self.r.resolve(self.take(), "property")
            self.take(")")
            n = BNode()
            self.g.add((n, OWL.inverseOf, p))
            return n
        return self.r.resolve(self.take(), "property")

    def restriction(self):
        p = self.prop()
        q = self.take()
        n = BNode()
        self.g.add((n, RDF.type, OWL.Restriction))
        self.g.add((n, OWL.onProperty, p))
        if q in ("some", "only"):
            self.g.add((n, OWL.someValuesFrom if q == "some" else OWL.allValuesFrom, self.unary()))
        elif q == "value":
            self.g.add((n, OWL.hasValue, self.r.resolve(self.take(), "individual")))
        elif q in ("min", "max", "exactly"):
            k = int(self.take())
            pred = {"min": OWL.minQualifiedCardinality, "max": OWL.maxQualifiedCardinality,
                    "exactly": OWL.qualifiedCardinality}[q]
            self.g.add((n, pred, Literal(k)))
            self.g.add((n, OWL.onClass, self.unary()))
        else:
            raise ExpectError(f"unknown restriction keyword '{q}'")
        return n

    def _list(self, pred, parts):
        n, head = BNode(), BNode()
        self.g.add((n, RDF.type, OWL.Class))
        self.g.add((n, pred, head))
        Collection(self.g, head, parts)
        return n


def load(path: str, g: Graph) -> list[dict]:
    """Candidates from ``path``: {"kind", "lhs", "rhs", "graph", "line", "text"}."""
    r = _Resolver(g)
    out = []
    with open(path, encoding="utf-8") as fh:
        for n, raw in enumerate(fh, 1):
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            toks = _tokens(line)
            idx = [i for i, t in enumerate(toks) if t in KEYWORDS]
            if len(idx) != 1:
                raise ExpectError(f"line {n}: expected exactly one of {', '.join(KEYWORDS)}")
            k = idx[0]
            eg = Graph()
            try:
                lp = _Parser(toks[:k], r, eg)
                lhs = lp.expr()
                if lp.peek() is not None:
                    raise ExpectError(f"unexpected '{lp.peek()}'")
                rp = _Parser(toks[k + 1:], r, eg)
                rhs = rp.expr()
                if rp.peek() is not None:
                    raise ExpectError(f"unexpected '{rp.peek()}'")
            except ExpectError as exc:
                raise ExpectError(f"line {n}: {exc}") from None
            for t in g.triples((None, RDFS.label, None)):
                eg.add(t)
            out.append({"kind": toks[k], "lhs": lhs, "rhs": rhs, "graph": eg, "line": n,
                        "text": line})
    return out
