"""Entity layer of a version diff (spec WS4.1): what was added, removed,
renamed or deprecated.

Renames are found by IRI first (same IRI, new label), then by
``owl:deprecated`` plus ``IAO_0100001`` (term replaced by), and last by label
similarity above 0.9 between a removed and an added entity, reported as a
suggestion only.
"""
from __future__ import annotations

from difflib import SequenceMatcher

from rdflib import Graph, Literal, OWL, RDF, RDFS, URIRef
from rdflib.namespace import SKOS

REPLACED_BY = URIRef("http://purl.obolibrary.org/obo/IAO_0100001")
KINDS = {
    OWL.Class: "class", RDFS.Class: "class",
    OWL.ObjectProperty: "object property", OWL.DatatypeProperty: "data property",
    OWL.AnnotationProperty: "annotation property", OWL.NamedIndividual: "individual",
}
SIMILAR = 0.9


def label(g: Graph, iri) -> str:
    """The entity's rdfs:label (English or untagged first), else its local name."""
    best = ""
    for pred in (RDFS.label, SKOS.prefLabel):
        for v in g.objects(iri, pred):
            if isinstance(v, Literal) and (v.language in (None, "", "en") or not best):
                best = str(v)
                if v.language in (None, "", "en"):
                    return best
        if best:
            return best
    s = str(iri)
    return s.rsplit("#", 1)[-1].rsplit("/", 1)[-1] or s


def _true(g: Graph, s, p) -> bool:
    return any(str(v).lower() in ("true", "1") for v in g.objects(s, p))


def entities(g: Graph) -> dict[str, dict]:
    """IRI -> {kind, label, deprecated, replaced_by} for every declared entity."""
    out: dict[str, dict] = {}
    for t, kind in KINDS.items():
        for s in g.subjects(RDF.type, t):
            if not isinstance(s, URIRef) or str(s).startswith(str(OWL)):
                continue
            e = out.setdefault(str(s), {"kind": kind, "label": label(g, s),
                                        "deprecated": _true(g, s, OWL.deprecated),
                                        "replaced_by": ""})
            rb = g.value(s, REPLACED_BY)
            if isinstance(rb, URIRef):
                e["replaced_by"] = str(rb)
    return out


def similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, a.lower(), b.lower()).ratio()


def diff(old: Graph, new: Graph) -> dict:
    eo, en = entities(old), entities(new)
    added = sorted(set(en) - set(eo))
    removed = sorted(set(eo) - set(en))

    def row(iri, e):
        return {"iri": iri, "kind": e["kind"], "label": e["label"]}

    renamed = [{"iri": i, "kind": en[i]["kind"], "old": eo[i]["label"], "new": en[i]["label"]}
               for i in sorted(set(eo) & set(en)) if eo[i]["label"] != en[i]["label"]]
    deprecated = [dict(row(i, en[i]), replaced_by=en[i]["replaced_by"])
                  for i in sorted(set(eo) & set(en))
                  if en[i]["deprecated"] and not eo[i]["deprecated"]]
    # deprecated + term replaced by: the old IRI was renamed to the new one
    replaced = [{"old": d["iri"], "new": d["replaced_by"], "kind": d["kind"],
                 "old_label": d["label"],
                 "new_label": (en.get(d["replaced_by"]) or {}).get("label", "")}
                for d in deprecated if d["replaced_by"]]
    # also a term removed outright whose replacement is named in the old version
    replaced += [{"old": i, "new": eo[i]["replaced_by"], "kind": eo[i]["kind"],
                  "old_label": eo[i]["label"],
                  "new_label": (en.get(eo[i]["replaced_by"]) or {}).get("label", "")}
                 for i in removed if eo[i]["replaced_by"]]
    paired = {r["old"] for r in replaced} | {r["new"] for r in replaced}
    suggested = []
    for r in removed:
        if r in paired:
            continue
        best = max(((similarity(eo[r]["label"], en[a]["label"]), a) for a in added
                    if a not in paired and en[a]["kind"] == eo[r]["kind"]), default=None)
        if best and best[0] >= SIMILAR:
            suggested.append({"old": r, "new": best[1], "kind": eo[r]["kind"],
                              "old_label": eo[r]["label"], "new_label": en[best[1]]["label"],
                              "score": round(best[0], 3)})
    return {
        "added": [row(i, en[i]) for i in added],
        "removed": [dict(row(i, eo[i]), was_deprecated=eo[i]["deprecated"]) for i in removed],
        "renamed": renamed,
        "deprecated": deprecated,
        "replaced": replaced,
        "suggested_renames": suggested,
    }
