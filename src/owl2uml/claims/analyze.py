"""Candidate grammar, reasoner passes, statuses and tiers (spec sections 4 to 6).

Passes (each one batch, answered by every requested reasoner):

1. Consistency; named superclasses of every named class; satisfiability of
   each class, of each ``p some B`` (p in P, B in F) and of each
   ``A and p some Thing`` (A in N), which says whether A can stand in p at
   all; G5 nested expressions; G6 candidates.
2. G2 ``A and B`` satisfiable?  G3 ``A SubClassOf p some B``?
3. G4 ``A and p some B`` satisfiable?, only where G3 failed.
4. Lazy checks for section 6.2: the same claim for strict named superclasses
   of A, asked only for claims that hold for A.

Checks that are implied by earlier answers are not sent: a subject that
cannot stand in p at all gets G3 = no and G4 = empty for every filler.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from rdflib import BNode, Graph, OWL, URIRef

from . import classify
from .classify import Batch, Unsupported
from .signature import Signature, classes_in, conjuncts, some_parts

_OWL = str(OWL)


class HardStop(RuntimeError):
    def __init__(self, code: str, message: str, detail=None):
        super().__init__(message)
        self.code, self.detail = code, detail


@dataclass
class Claim:
    grammar: str                 # G1..G6
    kind: str                    # sub, disj, some, nosome, possible, impossible, unsat, near, expect
    status: str
    a: URIRef | None = None
    p: URIRef | None = None
    b: URIRef | None = None
    node: object = None          # class expression (G5) or expect candidate (G6)
    graph: Graph | None = None   # graph the node lives in
    tier: str = ""
    defn_linked: bool = False
    reduced: bool = False
    note: str = ""
    reasoners: dict = field(default_factory=dict)


@dataclass
class Analysis:
    claims: list
    checks: dict                 # grammar row -> checks sent
    planned: dict
    seconds: dict                # engine -> seconds
    consistent: bool = True
    warnings: list = field(default_factory=list)


class Checker:
    """Runs a batch on every engine; stops on disagreement (H3)."""

    def __init__(self, ontology_path: str, engines: list[str]):
        self.path, self.engines = ontology_path, engines
        self.seconds = {e: 0.0 for e in engines}
        self.sent = 0

    def __call__(self, batch: Batch) -> dict:
        if not batch.queries:
            return {}
        answers = [classify.run(self.path, batch, e) for e in self.engines]
        self.sent += len(batch.queries)
        for a in answers:
            self.seconds[a.engine] += a.seconds
            if not a.consistent:
                raise HardStop("H2", "the ontology is inconsistent")
            if a.errors:
                qid, msg = next(iter(a.errors.items()))
                raise RuntimeError(f"{a.engine} could not answer {qid}: {msg}")
        rows = classify.compare(answers)
        if rows:
            raise HardStop("H3", "the reasoners disagree", (batch, rows))
        return answers[0].values


def _builtin(iri: str) -> bool:
    return iri.startswith(_OWL)


def plan(sig: Signature, n_expect: int) -> dict:
    """Upper bound on the checks per grammar row (for H4), before any is sent."""
    n, f, p = len(sig.native), len(sig.fillers), len(sig.props)
    return {"G1": n, "G2": n * f, "G3": n * p * f, "G4": n * p * f,
            "G5": len(sig.nested), "G6": 4 * n_expect}


def run(g: Graph, sig: Signature, check: Checker, expect: list | None = None) -> Analysis:
    expect = expect or []
    an = Analysis(claims=[], checks={k: 0 for k in ("G1", "G2", "G3", "G4", "G5", "G6", "6.2")},
                  planned=plan(sig, len(expect)), seconds=check.seconds)
    N, F, P = sig.native, sig.fillers, sig.props
    named = sorted({c for c in sig.told_parents} | set(F) | set(N))

    # ---- pass 1 ---------------------------------------------------------
    b = Batch()
    for c in named:
        b.supers(f"S:{c}", b.c(c))
        b.sat(f"sat:{c}", b.c(c))
    for p in P:
        for x in F:
            b.sat(f"xs:{p}|{x}", b.some(p, x))
    for a in N:
        for p in P:
            b.sat(f"dom:{a}|{p}", f"(and {b.c(a)} {b.some(p, OWL.Thing)})")
    nested_ok = []
    for i, node in enumerate(sig.nested):
        try:
            b.sat(f"g5:{i}", b.term(g, node))
            nested_ok.append((i, node))
        except Unsupported as exc:
            an.warnings.append(f"G5: skipped an expression: {exc}")
    for i, cand in enumerate(expect):
        try:
            lt, rt = b.term(cand["graph"], cand["lhs"]), b.term(cand["graph"], cand["rhs"])
        except Unsupported as exc:
            an.warnings.append(f"--expect line {cand['line']}: {exc}")
            continue
        b.sat(f"e:{i}:l", lt)
        b.sub(f"e:{i}:lr", lt, rt)
        b.sub(f"e:{i}:rl", rt, lt)
        b.sat(f"e:{i}:both", f"(and {lt} {rt})")
        cand["ok"] = True
    an.checks["G1"] += len(named)
    an.checks["G5"] += len(nested_ok)
    an.checks["G6"] += 4 * sum(1 for c in expect if c.get("ok"))
    v = check(b)

    sup = {str(c): {s for s in v.get(f"S:{c}", set()) if not _builtin(s) and s != str(c)}
           for c in named}
    unsat = {str(c) for c in named if v.get(f"sat:{c}") is False}

    def equiv(x: str) -> set:
        return {y for y in sup.get(x, ()) if x in sup.get(y, ())}

    def strict_supers(x: str) -> list:
        return sorted(sup.get(x, set()) - equiv(x))

    xsat = {(p, x): v.get(f"xs:{p}|{x}", False) for p in P for x in F}
    dom = {(a, p): v.get(f"dom:{a}|{p}", False) for a in N for p in P}
    live = [a for a in N if str(a) not in unsat]
    for a in N:
        if str(a) in unsat:
            an.claims.append(Claim("G5", "unsat", "REFUTED", a=a, tier="inferred"))
            an.warnings.append(f"unsatisfiable class: {a}")

    # ---- pass 2: G2, G3 -------------------------------------------------
    b = Batch()
    for a in live:
        for x in F:
            if x == a or str(x) in unsat or str(x) in sup[str(a)] or str(a) in sup.get(str(x), ()):
                continue
            b.sat(f"g2:{a}|{x}", f"(and {b.c(a)} {b.c(x)})")
            an.checks["G2"] += 1
        for p in P:
            if not dom[(a, p)]:
                continue
            for x in F:
                if xsat[(p, x)]:
                    b.sub(f"g3:{a}|{p}|{x}", b.c(a), b.some(p, x))
                    an.checks["G3"] += 1
    v2 = check(b)
    disj = {(a, x): v2.get(f"g2:{a}|{x}") is False for a in live for x in F}
    some = {(a, p, x): bool(v2.get(f"g3:{a}|{p}|{x}")) for a in live for p in P for x in F}

    # ---- pass 3: G4 -----------------------------------------------------
    b = Batch()
    nosome = {}
    for a in live:
        for p in P:
            for x in F:
                if not xsat[(p, x)] or some[(a, p, x)]:
                    nosome[(a, p, x)] = False
                elif not dom[(a, p)]:
                    nosome[(a, p, x)] = True
                else:
                    b.sat(f"g4:{a}|{p}|{x}", f"(and {b.c(a)} {b.some(p, x)})")
                    an.checks["G4"] += 1
    v3 = check(b)
    for k, val in v3.items():
        if k.startswith("g4:"):
            a, p, x = (URIRef(s) for s in k[3:].split("|"))
            nosome[(a, p, x)] = val is False

    # ---- candidate claims ------------------------------------------------
    cands: list[Claim] = []
    for a in live:
        sa = str(a)
        for x in F:
            if x == a or str(x) in equiv(sa):
                continue
            if str(x) in sup[sa]:
                cands.append(Claim("G1", "sub", "ENTAILED", a=a, b=x))
            if disj.get((a, x)):
                cands.append(Claim("G2", "disj", "REFUTED", a=a, b=x))
        for p in P:
            for x in F:
                if some[(a, p, x)]:
                    cands.append(Claim("G3", "some", "ENTAILED", a=a, p=p, b=x))
                elif nosome.get((a, p, x)) and str(x) not in unsat:
                    cands.append(Claim("G4", "nosome", "REFUTED", a=a, p=p, b=x))

    # 6.1 asserted duplicates
    kept = []
    for c in cands:
        if _told(sig, c):
            continue
        kept.append(c)
    cands = kept

    # G2 symmetric pairs among native classes: keep one
    seen_pairs = set()
    kept = []
    for c in cands:
        if c.kind == "disj":
            key = frozenset((c.a, c.b))
            if key in seen_pairs:
                continue
            seen_pairs.add(key)
        kept.append(c)
    cands = kept

    # ---- pass 4: 6.2 inheritance (lazy) ----------------------------------
    b = Batch()
    for c in cands:
        sa = str(c.a)
        if c.kind == "sub":
            continue
        for a2 in strict_supers(sa):
            if a2 == str(c.b):
                continue
            ref = URIRef(a2)
            if c.kind == "disj":
                b.sat(f"i:{len(b.queries)}:{a2}|{c.b}", f"(and {b.c(ref)} {b.c(c.b)})")
            elif c.kind == "some":
                b.sub(f"i:{len(b.queries)}:{a2}|{c.p}|{c.b}", b.c(ref), b.some(c.p, c.b))
            elif c.kind == "nosome":
                b.sat(f"i:{len(b.queries)}:{a2}|{c.p}|{c.b}",
                      f"(and {b.c(ref)} {b.some(c.p, c.b)})")
        if c.kind == "disj":
            for b2 in strict_supers(str(c.b)):
                b.sat(f"i:{len(b.queries)}:{c.a}|{b2}", f"(and {b.c(c.a)} {b.c(URIRef(b2))})")
    an.checks["6.2"] += len(b.queries)
    v4 = check(b)
    kinds = {q[1]: q[0] for q in b.queries}
    inherited_keys = set()
    for k, val in v4.items():
        if not k.startswith("i:"):
            continue
        # SAT asks "is the conjunction satisfiable?": the claim holds when it is not.
        holds = (val is False) if kinds.get(k) == "SAT" else bool(val)
        if holds:
            inherited_keys.add(k.split(":", 2)[2])

    for c in cands:
        sa = str(c.a)
        if c.kind == "sub":
            inh = any(str(c.b) in sup.get(a2, ()) for a2 in strict_supers(sa) if a2 != str(c.b))
        elif c.kind == "disj":
            inh = any(f"{a2}|{c.b}" in inherited_keys for a2 in strict_supers(sa)) or \
                any(f"{c.a}|{b2}" in inherited_keys for b2 in strict_supers(str(c.b)))
        else:
            inh = any(f"{a2}|{c.p}|{c.b}" in inherited_keys for a2 in strict_supers(sa))
        c.tier = "inherited" if inh else "inferred"

    # 6.4 filler reduction, with the definitional-link exception
    for c in cands:
        c.defn_linked = _linked(g, sig, c.a, c.b)
        if c.tier != "inferred":
            continue
        if c.kind == "some":
            stronger = [x for x in F if x != c.b and str(c.b) in sup.get(str(x), ())
                        and str(x) not in equiv(str(c.b)) and some.get((c.a, c.p, x))]
        elif c.kind == "nosome":
            stronger = [x for x in F if str(x) in strict_supers(str(c.b))
                        and nosome.get((c.a, c.p, x))]
        else:
            stronger = []
        if stronger:
            c.reduced = True
    an.claims += [c for c in cands if not (c.reduced and not c.defn_linked)]

    # ---- G5 ----------------------------------------------------------------
    for i, node in nested_ok:
        ok = v.get(f"g5:{i}")
        an.claims.append(Claim("G5", "possible" if ok else "impossible",
                               "POSSIBLE" if ok else "REFUTED", node=node, graph=g,
                               tier="possible" if ok else "inferred"))
        if not ok:
            an.warnings.append("a nested class expression is unsatisfiable (vacuous definition)")

    # ---- 6.3 near misses ---------------------------------------------------
    for a in live:
        for x in live:
            if a == x or a not in sig.definitions or x not in sig.definitions:
                continue
            if str(x) in sup[str(a)] or disj.get((a, x)) or disj.get((x, a)):
                continue
            if _near_miss(g, sig, a, x, sup):
                an.claims.append(Claim("G1", "near", "UNDETERMINED", a=a, b=x,
                                       tier="undetermined", note="6.3"))

    # ---- G6 ------------------------------------------------------------------
    for i, cand in enumerate(expect):
        if not cand.get("ok"):
            continue
        ls, lr, rl, both = (v.get(f"e:{i}:{k}") for k in ("l", "lr", "rl", "both"))
        kind = cand["kind"]
        if kind == "SubClassOf":
            status = "ENTAILED" if lr else ("REFUTED" if ls and both is False else "UNDETERMINED")
        elif kind == "EquivalentTo":
            status = "ENTAILED" if (lr and rl) else (
                "REFUTED" if ls and both is False else "UNDETERMINED")
        else:  # DisjointWith
            status = "ENTAILED" if both is False else "UNDETERMINED"
        if ls is False:
            an.warnings.append(f"--expect line {cand['line']}: the left side is unsatisfiable")
        tier = "undetermined" if status == "UNDETERMINED" else "inferred"
        an.claims.append(Claim("G6", "expect", status, node=cand, graph=cand["graph"], tier=tier,
                               a=cand.get("lhs") if isinstance(cand.get("lhs"), URIRef) else None,
                               b=cand.get("rhs") if isinstance(cand.get("rhs"), URIRef) else None))

    # G6 supersedes the same 6.3 near miss
    exp_pairs = {(c.a, c.b) for c in an.claims if c.kind == "expect"
                 and c.node["kind"] == "SubClassOf" and c.a is not None and c.b is not None}
    an.claims = [c for c in an.claims if not (c.kind == "near" and (c.a, c.b) in exp_pairs)]
    for c in an.claims:
        c.reasoners = {e: c.status for e in check.engines}
    an.seconds = check.seconds
    return an


def _told(sig: Signature, c: Claim) -> bool:
    a = c.a
    if c.kind == "sub":
        return c.b in sig.told_sub.get(a, ())
    if c.kind == "disj":
        return c.b in sig.told_disj.get(a, ()) or a in sig.told_disj.get(c.b, ())
    if c.kind == "some":
        return (c.p, c.b) in sig.told_some.get(a, ())
    if c.kind == "nosome":
        return (c.p, c.b) in sig.told_nosome.get(a, ())
    return False


def _linked(g: Graph, sig: Signature, a, b) -> bool:
    """B's definition mentions A, or A's definition mentions B."""
    if a is None or b is None:
        return False
    for x, y in ((a, b), (b, a)):
        for d in sig.definitions.get(y, ()):
            if x in classes_in(g, d):
                return True
    return False


def _definition_parts(g: Graph, sig: Signature, a):
    """(genus: frozenset of named conjuncts, [(p, F) restrictions]) of a's first
    intersection definition, or None."""
    for d in sig.definitions.get(a, ()):
        parts = conjuncts(g, d)
        if len(parts) < 2:
            continue
        genus = frozenset(x for x in parts if isinstance(x, URIRef))
        rest = [some_parts(g, x) for x in parts if isinstance(x, BNode)]
        if genus and all(rest):
            return genus, rest
    return None


def _near_miss(g: Graph, sig: Signature, a, b, sup: dict) -> bool:
    """Section 6.3: a and b share a genus, and every restriction p some F of
    b's definition is matched in a's by p some F' with F' a sibling of F
    (a shared direct told parent) and F' not under F."""
    da, db = _definition_parts(g, sig, a), _definition_parts(g, sig, b)
    if not da or not db or da[0] != db[0]:
        return False
    for p, f in db[1]:
        pf = sig.told_parents.get(f, set())
        if not any(p2 == p and f2 != f and (sig.told_parents.get(f2, set()) & pf)
                   and str(f) not in sup.get(str(f2), ()) for p2, f2 in da[1]):
            return False
    return True
