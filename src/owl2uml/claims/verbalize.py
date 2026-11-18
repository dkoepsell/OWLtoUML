"""Deterministic English for claims and asserted axioms (spec section 7).

Templates only: no model is involved, so the same ontology always gives the
same sentences, and every sentence can be traced to its Manchester form.

Labels come from rdfs:label (else the IRI fragment), lowercased unless the
label has a capital after its first character. Property labels become verb
phrases by three rules (``verb_phrase``), which ``--verb-map`` overrides.
"""
from __future__ import annotations

import csv
import re

from rdflib import BNode, Graph, Literal, OWL, URIRef

from ..parse import _build_labels, _display
from ..source import _Writer
from .signature import items


def _read_map(path: str | None) -> dict:
    """Two-column TSV: key (IRI or label) -> value. Lines starting with # are skipped."""
    out: dict = {}
    if not path:
        return out
    with open(path, encoding="utf-8") as fh:
        for row in csv.reader(fh, delimiter="\t"):
            if len(row) >= 2 and row[0].strip() and not row[0].startswith("#"):
                out[row[0].strip()] = row[1].strip()
    return out


class Verbalizer:
    def __init__(self, g: Graph, verb_map: str | None = None, article_map: str | None = None):
        self.g = g
        self.labels = _build_labels(g)
        self.writer = _Writer(g, self.labels)
        self.verbs = _read_map(verb_map)
        self.articles = _read_map(article_map)

    # ---- words ---------------------------------------------------------------
    def label(self, term) -> str:
        if term == OWL.Thing:
            return "thing"
        if term == OWL.Nothing:
            return "nothing"
        lab = _display(term, self.labels)
        return lab if any(ch.isupper() for ch in lab[1:]) else lab.lower()

    def article(self, word: str) -> str:
        if word in self.articles:
            return self.articles[word]
        return "an" if word[:1].lower() in "aeiou" else "a"

    def a(self, term) -> str:
        """Label with its indefinite article: 'a norm', 'an answerability'."""
        w = self.label(term)
        return f"{self.article(w)} {w}"

    def verb_phrase(self, p) -> str:
        """Section 7.1: 'is attributed to', 'is a bearer of', 'answers for'."""
        if isinstance(p, BNode):
            inv = self.g.value(p, OWL.inverseOf)
            named = next((q for q in self.g.objects(inv, OWL.inverseOf) if isinstance(q, URIRef)),
                         None) or next((q for q in self.g.subjects(OWL.inverseOf, inv)
                                        if isinstance(q, URIRef)), None)
            if named is not None:
                return self.verb_phrase(named)
            return f"is the subject of something that {self.verb_phrase(inv)}"
        if str(p) in self.verbs:
            return self.verbs[str(p)]
        lab = self.label(p)
        if lab in self.verbs:
            return self.verbs[lab]
        words = lab.split()
        if not words:
            return lab
        # 1. a participle: 'attributed to', and with an adverb 'specifically depended on by'
        if words[0].endswith("ed") or (len(words) > 1 and words[0].endswith("ly")
                                       and words[1].endswith("ed")):
            return f"is {lab}"
        # 2. a relational noun: 'bearer of', 'repeat of'
        if words[-1] == "of" and len(words) > 1:
            return f"is {self.article(lab)} {lab}"
        # 2b. 'has' + noun: 'has participant' -> 'has as participant'
        if words[0] == "has" and len(words) > 1 and words[1] not in ("as", "a", "an", "the"):
            return "has as " + " ".join(words[1:])
        # 3. a verb: 'answers for', 'realizes'
        return lab

    def negated_vp(self, p) -> str:
        """'is not a bearer of', 'does not answer for' (for complements)."""
        vp = self.verb_phrase(p)
        if vp.startswith("is "):
            return "is not " + vp[3:]
        if vp.startswith("has "):
            return "does not have " + vp[4:]
        first, _, rest = vp.partition(" ")
        base = re.sub(r"ies$", "y", first) if first.endswith("ies") else \
            re.sub(r"(ss|sh|ch|x|z|o)es$", r"\1", first) if re.search(r"(ss|sh|ch|x|z|o)es$", first) \
            else re.sub(r"s$", "", first)
        return f"does not {base}" + (f" {rest}" if rest else "")

    # ---- expressions -----------------------------------------------------------
    def _parts(self, e, pred) -> list:
        return items(self.g, e, pred) if isinstance(e, BNode) else []

    def pred(self, e, g: Graph | None = None) -> str:
        """Predicate for 'Every A ...': 'is a norm', 'answers for some breach'."""
        g = g or self.g
        if not isinstance(e, BNode):
            return f"is {self.a(e)}"
        inter = items(g, e, OWL.intersectionOf)
        if inter:
            return " and ".join(self.pred(x, g) for x in inter)
        union = items(g, e, OWL.unionOf)
        if union:
            if all(isinstance(x, URIRef) for x in union):
                return "is " + " or ".join(self.a(x) for x in union)
            return " or ".join(self.pred(x, g) for x in union)
        c = g.value(e, OWL.complementOf)
        if c is not None:
            if isinstance(c, URIRef):
                return f"is not {self.a(c)}"
            p, f = g.value(c, OWL.onProperty), g.value(c, OWL.someValuesFrom)
            if p is not None and f is not None:
                return f"{self.negated_vp(p)} any {self.nom(f, g)}"
            return f"is not {self.np(c, g)}"
        p = g.value(e, OWL.onProperty)
        if p is not None:
            vp = self.verb_phrase(p)
            for pr, q in ((OWL.someValuesFrom, "some"), (OWL.allValuesFrom, "only")):
                f = g.value(e, pr)
                if f is not None:
                    return f"{vp} {q} {self.nom(f, g)}"
            v = g.value(e, OWL.hasValue)
            if v is not None:
                return f"{vp} {self._value(v)}"
            for preds, q in (((OWL.minQualifiedCardinality, OWL.minCardinality), "at least"),
                             ((OWL.maxQualifiedCardinality, OWL.maxCardinality), "at most"),
                             ((OWL.qualifiedCardinality, OWL.cardinality), "exactly")):
                for pr in preds:
                    n = g.value(e, pr)
                    if n is not None:
                        f = g.value(e, OWL.onClass) or g.value(e, OWL.onDataRange)
                        return f"{vp} {q} {n} {self.nom(f, g) if f is not None else 'things'}"
        return f"is {self.writer.expr(e)}"

    def nom(self, e, g: Graph | None = None) -> str:
        """Noun phrase without article: 'normative breach', 'norm that ...'."""
        g = g or self.g
        if not isinstance(e, BNode):
            return self.label(e)
        inter = items(g, e, OWL.intersectionOf)
        genus = [x for x in inter if isinstance(x, URIRef)]
        if inter and len(genus) == 1:
            rest = [x for x in inter if x is not genus[0]]
            return f"{self.label(genus[0])} that " + " and ".join(self.pred(x, g) for x in rest)
        return f"thing that {self.pred(e, g)}"

    def np(self, e, g: Graph | None = None) -> str:
        """Noun phrase with article: 'a norm', 'a breach that is attributed to ...'."""
        g = g or self.g
        if not isinstance(e, BNode):
            return self.a(e)
        union = items(g, e, OWL.unionOf)
        if union:
            return " or ".join(self.np(x, g) for x in union)
        inter = items(g, e, OWL.intersectionOf)
        genus = [x for x in inter if isinstance(x, URIRef)]
        if inter and len(genus) == 1:
            w = self.label(genus[0])
            rest = [x for x in inter if x is not genus[0]]
            return f"{self.article(w)} {w} that " + " and ".join(self.pred(x, g) for x in rest)
        return f"something that {self.pred(e, g)}"

    def _value(self, v) -> str:
        if isinstance(v, Literal):
            return str(v)
        return _display(v, self.labels)

    def m(self, term, g: Graph | None = None) -> str:
        """Manchester rendering."""
        if g is not None and g is not self.g:
            return _Writer(g, self.labels).expr(term)
        return self.writer.expr(term) if isinstance(term, BNode) else self.writer.name(term)


def cap(s: str) -> str:
    return s[:1].upper() + s[1:]
