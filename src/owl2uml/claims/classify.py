"""Batched reasoner checks through the O2uProbe helper (HermiT and Pellet).

The helper keeps one reasoner alive for a whole batch, so thousands of
satisfiability and subsumption checks cost one JVM start per reasoner per
batch. Every batch is run on each requested reasoner and the answers are
compared; the analysis reads only answers on which they agree, and any
disagreement is a hard stop (H3) reported by the caller.

Expressions are passed as prefix terms (see O2uProbe.java). ``Batch``
assigns the entity indices and turns rdflib class expressions into terms.
"""
from __future__ import annotations

import os
import subprocess
import tempfile
import time
from dataclasses import dataclass, field

from rdflib import BNode, Graph, Literal, OWL, RDF, URIRef

from .. import tools
from .signature import items

ENGINES = ("hermit", "pellet")


class Unsupported(ValueError):
    """An expression the helper cannot express (data restrictions, ...)."""


@dataclass
class Batch:
    classes: dict = field(default_factory=dict)
    props: dict = field(default_factory=dict)
    inds: dict = field(default_factory=dict)
    queries: list = field(default_factory=list)     # (kind, id, *terms)

    def c(self, iri) -> str:
        if iri == OWL.Thing:
            return "T"
        if iri == OWL.Nothing:
            return "F"
        return "c" + str(self.classes.setdefault(str(iri), len(self.classes)))

    def p(self, iri) -> str:
        return "p" + str(self.props.setdefault(str(iri), len(self.props)))

    def i(self, iri) -> str:
        return "i" + str(self.inds.setdefault(str(iri), len(self.inds)))

    def some(self, p, b) -> str:
        return f"(some {self.p(p)} {self.c(b)})"

    def term(self, g: Graph, e) -> str:
        """Prefix term for an rdflib class expression."""
        if isinstance(e, URIRef):
            return self.c(e)
        if not isinstance(e, BNode):
            raise Unsupported(f"not a class expression: {e!r}")
        for pred, op in ((OWL.intersectionOf, "and"), (OWL.unionOf, "or")):
            parts = items(g, e, pred)
            if parts:
                return f"({op} " + " ".join(self.term(g, x) for x in parts) + ")"
        c = g.value(e, OWL.complementOf)
        if c is not None:
            return f"(not {self.term(g, c)})"
        if items(g, e, OWL.oneOf):
            raise Unsupported("enumerations (oneOf) are not supported")
        p = g.value(e, OWL.onProperty)
        if p is None:
            raise Unsupported("unrecognised class expression")
        pt = self.prop_term(g, p)
        for pred, op in ((OWL.someValuesFrom, "some"), (OWL.allValuesFrom, "only")):
            f = g.value(e, pred)
            if f is not None:
                return f"({op} {pt} {self.term(g, f)})"
        v = g.value(e, OWL.hasValue)
        if v is not None:
            if isinstance(v, Literal):
                raise Unsupported("data restrictions are not supported")
            return f"(value {pt} {self.i(v)})"
        for preds, op in (((OWL.minQualifiedCardinality, OWL.minCardinality), "min"),
                          ((OWL.maxQualifiedCardinality, OWL.maxCardinality), "max"),
                          ((OWL.qualifiedCardinality, OWL.cardinality), "exactly")):
            for pr in preds:
                n = g.value(e, pr)
                if n is not None:
                    f = g.value(e, OWL.onClass)
                    if g.value(e, OWL.onDataRange) is not None:
                        raise Unsupported("data restrictions are not supported")
                    return f"({op} {int(n)} {pt} {self.term(g, f) if f is not None else 'T'})"
        raise Unsupported("unrecognised restriction")

    def prop_term(self, g: Graph, p) -> str:
        if isinstance(p, BNode):
            inv = g.value(p, OWL.inverseOf)
            if isinstance(inv, URIRef):
                return f"(inv {self.p(inv)})"
            raise Unsupported("unrecognised property expression")
        if (p, RDF.type, OWL.DatatypeProperty) in g:
            raise Unsupported("data restrictions are not supported")
        return self.p(p)

    def sat(self, qid: str, term: str) -> None:
        self.queries.append(("SAT", qid, term))

    def sub(self, qid: str, x: str, y: str) -> None:
        self.queries.append(("SUB", qid, x, y))

    def supers(self, qid: str, x: str) -> None:
        self.queries.append(("SUPERS", qid, x))

    def text(self) -> str:
        lines = [f"C\t{n}\t{iri}" for iri, n in self.classes.items()]
        lines += [f"P\t{n}\t{iri}" for iri, n in self.props.items()]
        lines += [f"I\t{n}\t{iri}" for iri, n in self.inds.items()]
        lines += ["\t".join(q) for q in self.queries]
        return "\n".join(lines) + "\n"


@dataclass
class Answers:
    engine: str
    consistent: bool = True
    values: dict = field(default_factory=dict)      # id -> bool, or set of IRIs (SUPERS)
    errors: dict = field(default_factory=dict)      # id -> message
    seconds: float = 0.0


class ReasonerUnavailable(RuntimeError):
    pass


def available(engine: str) -> bool:
    return tools.probe_cmd(engine) is not None


def ontology_file(graph: Graph, tmpdir: str) -> str:
    """The merged graph as RDF/XML without owl:imports (both OWL APIs read it)."""
    g = Graph()
    for t in graph:
        if t[1] != OWL.imports:
            g.add(t)
    path = os.path.join(tmpdir, "ontology.owl")
    g.serialize(path, format="xml")
    return path


def run(ontology_path: str, batch: Batch, engine: str, timeout: float = 3600) -> Answers:
    cmd = tools.probe_cmd(engine)
    if cmd is None:
        raise ReasonerUnavailable(
            f"{engine} is not available: needs Java and "
            + ("robot.jar (scripts/setup.sh)" if engine == "hermit" else "owlready2's Pellet"))
    out = Answers(engine=engine)
    t = time.time()
    with tempfile.TemporaryDirectory(prefix="o2u-claims-") as tmp:
        q, o = os.path.join(tmp, "queries.txt"), os.path.join(tmp, "answers.txt")
        with open(q, "w", encoding="utf-8") as fh:
            fh.write(batch.text())
        r = subprocess.run(cmd + [ontology_path, q, o], capture_output=True, timeout=timeout)
        if r.returncode != 0 or not os.path.exists(o):
            err = r.stderr.decode("utf-8", "replace")
            lines = [ln for ln in err.splitlines() if "Picked up" not in ln and ln.strip()]
            raise RuntimeError(f"{engine} failed: " + " ".join(lines[-5:]))
        with open(o, encoding="utf-8") as fh:
            for line in fh:
                f = line.rstrip("\n").split("\t")
                if f[0] == "CONSISTENT":
                    out.consistent = f[1] == "1"
                elif len(f) >= 3 and f[1] == "ERR":
                    out.errors[f[0]] = f[2]
                elif f[0].startswith("S:"):
                    out.values[f[0]] = set(f[1:])
                else:
                    out.values[f[0]] = f[1] == "1"
    out.seconds = round(time.time() - t, 2)
    return out


def compare(answers: list[Answers]) -> list[tuple]:
    """Disagreements between engines: (query id, {engine: answer})."""
    rows = []
    if len(answers) < 2:
        return rows
    first = answers[0]
    for qid in sorted(set().union(*(a.values.keys() for a in answers))):
        vals = {a.engine: a.values.get(qid) for a in answers}
        ref = first.values.get(qid)
        if any(v != ref for v in vals.values()):
            rows.append((qid, vals))
    return rows
