"""Compare two versions of an ontology: the three layers of spec WS4.1, the
summary counts, and the ``--fail-on`` checks of the CI action (WS4.4)."""
from __future__ import annotations

from rdflib import Graph, OWL, RDFS, URIRef

from . import axioms as ax_layer
from . import entities as ent_layer
from . import inferred as inf_layer

FAIL_ON = ("unsatisfiable", "inconsistent", "new-orphans", "removed-without-deprecation",
           "coverage-drop")


def compare(old: Graph, new: Graph, engine: str = "auto",
            coverage: tuple[dict, dict] | None = None) -> dict:
    """The change set, as written to diff.json."""
    ents = ent_layer.diff(old, new)
    axs = ax_layer.diff(old, new)
    inf = inf_layer.diff(old, new, engine)
    sups = inf.pop("superclasses")["new"]
    out = {
        "version": 1,
        "entities": ents,
        "axioms": axs,
        "inferred": inf,
        "orphans": _orphans(old, new, sups, ents),
    }
    if coverage:
        out["coverage"] = {"old": _share(coverage[0]), "new": _share(coverage[1])}
    out["summary"] = summary(out)
    return out


def _share(cov: dict) -> float:
    rows = cov.get("axioms") or []
    if not rows:
        return 1.0
    return round(1 - sum(1 for r in rows if r["status"] == "dropped") / len(rows), 4)


def _parents(g: Graph) -> set[str]:
    """Classes with a named superclass other than owl:Thing, asserted or by
    definition (a named member of an equivalentClass intersection)."""
    out = {str(s) for s, o in g.subject_objects(RDFS.subClassOf)
           if isinstance(s, URIRef) and isinstance(o, URIRef) and o != OWL.Thing}
    out |= {str(s) for s in g.subjects(OWL.equivalentClass, None) if isinstance(s, URIRef)}
    return out


def _orphans(old: Graph, new: Graph, sups_new: dict, ents: dict) -> list[str]:
    """Classes that, in the new version, have no parent but owl:Thing and did
    have one before (or are new)."""
    from .entities import entities
    en, eo = entities(new), entities(old)
    has_old = _parents(old)
    has_new = _parents(new) | {c for c, s in sups_new.items() if s}
    out = []
    for iri, e in en.items():
        if e["kind"] != "class" or e["deprecated"] or iri in has_new:
            continue
        if iri not in eo or iri in has_old:
            out.append(iri)
    return sorted(out)


def summary(d: dict) -> dict:
    e, a, i = d["entities"], d["axioms"], d["inferred"]
    logical = lambda rows: sum(1 for r in rows if not r["annotation"])  # noqa: E731
    return {
        "added": len(e["added"]), "removed": len(e["removed"]),
        "renamed": len(e["renamed"]) + len(e["replaced"]),
        "deprecated": len(e["deprecated"]), "suggested_renames": len(e["suggested_renames"]),
        "axioms_added": logical(a["added"]), "axioms_removed": logical(a["removed"]),
        "annotations_added": len(a["added"]) - logical(a["added"]),
        "annotations_removed": len(a["removed"]) - logical(a["removed"]),
        "inferred_added": len(i["added"]), "inferred_removed": len(i["removed"]),
        "unsatisfiable_new": len(i["unsatisfiable"]["added"]),
        "unsatisfiable": len(i["unsatisfiable"]["new"]),
        "inconsistent": i["inconsistent"]["new"], "moved": len(i["moved"]),
        "new_orphans": len(d["orphans"]),
    }


def changed(d: dict) -> bool:
    s = d["summary"]
    return any(v for k, v in s.items() if k not in ("unsatisfiable", "inconsistent")) \
        or s["inconsistent"]


def check(d: dict, conditions) -> list[dict]:
    """The ``--fail-on`` conditions that hold: [{condition, detail}]."""
    out = []
    i = d["inferred"]
    for c in conditions:
        if c not in FAIL_ON:
            raise ValueError(f"unknown fail-on condition {c!r} (one of {', '.join(FAIL_ON)})")
        if c == "unsatisfiable" and i["unsatisfiable"]["new"]:
            out.append({"condition": c, "detail": f"{len(i['unsatisfiable']['new'])} "
                        "unsatisfiable classes", "iris": i["unsatisfiable"]["new"]})
        elif c == "inconsistent" and i["inconsistent"]["new"]:
            out.append({"condition": c, "detail": "the ontology is inconsistent"})
        elif c == "new-orphans" and d["orphans"]:
            out.append({"condition": c, "detail": f"{len(d['orphans'])} classes without a "
                        "parent", "iris": d["orphans"]})
        elif c == "removed-without-deprecation":
            gone = [r["iri"] for r in d["entities"]["removed"] if not r["was_deprecated"]]
            if gone:
                out.append({"condition": c, "detail": f"{len(gone)} entities removed without "
                            "being deprecated first", "iris": gone})
        elif c == "coverage-drop" and d.get("coverage") and \
                d["coverage"]["new"] < d["coverage"]["old"]:
            cv = d["coverage"]
            out.append({"condition": c, "detail": f"axioms shown fell from "
                        f"{cv['old']:.1%} to {cv['new']:.1%}"})
    return out
