"""Classify an ontology with a reasoner and add what it infers to the diagram.

The asserted diagram shows what the ontology *says*. A reasoner shows what
follows: a defined class turns out to fall under another defined class, a
class turns out to be unsatisfiable, two classes turn out to be equivalent.
Those subsumptions are added as edges of kind "inferred", drawn in orange, so
the asserted view and the classified view can be compared on one layout.

Engines:
  hermit  HermiT via owlready2 (full OWL 2 DL classification). Needs Java.
  owlrl   owlrl's OWL 2 RL closure (pure Python). Finds subsumptions that
          follow by rule (intersections, property hierarchies on existentials)
          but cannot classify one defined class under another.
  auto    hermit when owlready2 and Java are available, else owlrl.
"""
from __future__ import annotations

import os
import shutil
import tempfile
import time
from dataclasses import dataclass, field

from rdflib import Graph, OWL, RDFS, URIRef

from .model import Edge, HIERARCHY_KINDS, UModel

ENGINES = ("none", "auto", "hermit", "owlrl")


@dataclass
class Inference:
    engine: str = "none"
    # (sub, sup) pairs between named classes, transitively closed by the engine
    subsumptions: set[tuple[str, str]] = field(default_factory=set)
    unsatisfiable: set[str] = field(default_factory=set)
    inconsistent: bool = False
    seconds: float = 0.0
    error: str = ""
    # filled in by apply(): what was added to the diagram
    added: int = 0
    equivalences: int = 0

    def report(self) -> dict:
        return {
            "engine": self.engine, "inferred": self.added,
            "equivalences": self.equivalences,
            "unsatisfiable": len(self.unsatisfiable), "inconsistent": self.inconsistent,
            "seconds": round(self.seconds, 2), "error": self.error,
        }


def hermit_available() -> bool:
    try:
        import owlready2  # noqa: F401
    except ImportError:
        return False
    return shutil.which("java") is not None


def classify(graph: Graph, engine: str = "auto") -> Inference:
    """Run the chosen reasoner over an already-parsed graph."""
    if engine == "none":
        return Inference()
    if engine == "auto":
        engine = "hermit" if hermit_available() else "owlrl"
    t = time.time()
    try:
        inf = _hermit(graph) if engine == "hermit" else _owlrl(graph)
    except Exception as exc:  # noqa: BLE001 - surface, never crash the render
        inf = Inference(engine=engine, error=f"{type(exc).__name__}: {exc}")
    inf.seconds = time.time() - t
    return inf


def _named(g: Graph) -> set[URIRef]:
    return {s for s in g.subjects(None, OWL.Class) if isinstance(s, URIRef)} | \
           {s for s in g.subjects(RDFS.subClassOf, None) if isinstance(s, URIRef)}


def _owlrl(graph: Graph) -> Inference:
    import owlrl
    g = Graph()
    for t in graph:
        g.add(t)
    named = _named(graph)
    owlrl.DeductiveClosure(owlrl.OWLRL_Semantics).expand(g)
    inf = Inference(engine="owlrl")
    for s, o in g.subject_objects(RDFS.subClassOf):
        if s in named and isinstance(o, URIRef) and s != o:
            if o == OWL.Nothing:
                inf.unsatisfiable.add(str(s))
            elif o in named:
                inf.subsumptions.add((str(s), str(o)))
    return inf


def _hermit(graph: Graph) -> Inference:
    from owlready2 import (World, ThingClass, sync_reasoner_hermit,
                           OwlReadyInconsistentOntologyError)
    if not shutil.which("java"):
        raise RuntimeError("HermiT needs Java (java not found on PATH)")
    # owlready2 reads RDF/XML and N-Triples, not Turtle: hand it N-Triples.
    fd, path = tempfile.mkstemp(suffix=".nt")
    os.close(fd)
    try:
        graph.serialize(path, format="nt", encoding="utf-8")
        w = World()
        onto = w.get_ontology("file://" + path).load()
        inf = Inference(engine="hermit")
        try:
            with onto:
                sync_reasoner_hermit(w, infer_property_values=False, debug=0)
        except OwlReadyInconsistentOntologyError:
            inf.inconsistent = True
            return inf
        nothing = {c.iri for c in w.inconsistent_classes() if c.iri != str(OWL.Nothing)}
        inf.unsatisfiable = nothing
        for c in w.classes():
            if c.iri in nothing:
                continue
            for a in c.ancestors(include_self=False):
                if isinstance(a, ThingClass) and a.iri != c.iri \
                        and not a.iri.startswith(str(OWL)):
                    inf.subsumptions.add((c.iri, a.iri))
            for e in c.equivalent_to:
                if isinstance(e, ThingClass) and e.iri != c.iri:
                    inf.subsumptions.update({(c.iri, e.iri), (e.iri, c.iri)})
        return inf
    finally:
        os.unlink(path)


def apply(m: UModel, inf: Inference) -> None:
    """Add the reasoner's *new, direct* subsumptions to the model.

    New: not already reachable through asserted subclass or definition edges.
    Direct: not implied by another inferred-or-asserted superclass of the same
    class (a transitive reduction), so classification adds as few lines as
    possible. Mutual subsumptions (inferred equivalences) are counted, not
    drawn. Unsatisfiable classes are flagged on the class itself.
    """
    for cid in inf.unsatisfiable:
        if cid in m.classes:
            m.classes[cid].unsatisfiable = True
    if not inf.subsumptions:
        return

    parents: dict[str, set[str]] = {}
    for e in m.edges:
        if e.kind in HIERARCHY_KINDS:
            parents.setdefault(e.src, set()).add(e.dst)

    def reach(a: str) -> set[str]:
        seen: set[str] = set()
        stack = [a]
        while stack:
            for p in parents.get(stack.pop(), ()):
                if p not in seen:
                    seen.add(p)
                    stack.append(p)
        return seen

    sups: dict[str, set[str]] = {}
    for a, b in inf.subsumptions:
        if a in m.classes and b in m.classes:
            sups.setdefault(a, set()).add(b)
    # The engine's answer may not be closed (owlrl is; HermiT ancestors are):
    # close it together with what is asserted, so "direct" is computed right.
    full = {a: set(bs) | reach(a) for a, bs in sups.items()}
    changed = True
    while changed:
        changed = False
        for a, bs in full.items():
            extra = set().union(*(full.get(b, set()) | reach(b) for b in bs)) - bs - {a}
            if extra:
                bs |= extra
                changed = True

    added: set[tuple[str, str]] = set()
    equivalences = 0
    for a, bs in sups.items():
        asserted = reach(a)
        allsup = full[a]
        for b in bs:
            if b in asserted:
                continue
            if a in full.get(b, set()):           # mutual: equivalent classes
                equivalences += 1
                continue
            # b is direct if no other superclass c of a lies strictly below b
            # (c is not also equivalent to a).
            if any(b in (full.get(c, set()) | reach(c)) and a not in full.get(c, set())
                   for c in allsup if c != b):
                continue
            added.add((a, b))
    for a, b in sorted(added):
        m.edges.append(Edge(src=a, dst=b, kind="inferred"))
        m.classes[a].inferred_placed = True
    inf.added = len(added)
    inf.equivalences = equivalences // 2
