"""Coverage report (spec WS1.3): what happened to every axiom.

Each axiom of the ontology (axioms.inventory) ends up in exactly one of:

* ``drawn``  -- a line, attribute, badge, key entry or box shows it;
* ``panel``  -- not drawn, but listed in the source panel of a drawn class
  or property, so a reader can still find it;
* ``dropped`` -- in neither, with the reason.

So a diagram never omits an axiom silently. Axioms about entities that come
from owl:imports are counted separately from the ontology's own.
"""
from __future__ import annotations

import json
from collections import Counter

from rdflib import Graph, OWL, RDF, RDFS, URIRef

from .axioms import Axiom, canon, inventory
from .constructs import DEFINITION_PROPS
from .model import UModel

STATUSES = ("drawn", "panel", "dropped")
_BADGED = {"FunctionalProperty", "TransitiveObjectProperty", "SymmetricObjectProperty"}
_KEYED = {"SubPropertyOf": "super", "InverseObjectProperties": "inverse",
          "SubPropertyChainOf": "chains"}
_CLASS_AXIOMS = {"SubClassOf", "EquivalentClasses", "DisjointClasses", "DisjointUnion", "HasKey"}
_ABOX = {"ClassAssertion", "ObjectPropertyAssertion", "DataPropertyAssertion",
         "NegativePropertyAssertion", "SameIndividual", "DifferentIndividuals"}
_PROPERTY_AXIOMS = {"PropertyDomain", "PropertyRange", "SubPropertyOf", "EquivalentProperties",
                    "InverseObjectProperties", "DisjointProperties", "SubPropertyChainOf",
                    "InverseFunctionalObjectProperty", "AsymmetricObjectProperty",
                    "ReflexiveObjectProperty", "IrreflexiveObjectProperty"} | _BADGED
_DEFINITION_IRIS = {str(p) for p in DEFINITION_PROPS}


def build(g: Graph, m: UModel, definitions: bool = False) -> dict:
    """The coverage report for model ``m`` drawn from graph ``g``."""
    axioms = inventory(g)
    drawn_ids = {a for e in m.edges for a in e.axioms}
    for c in m.classes.values():
        drawn_ids.update(c.axioms)
        for at in c.attrs:
            drawn_ids.update(at.axioms)
    boxes = {cid for cid, c in m.classes.items() if c.kind in ("class", "individual")} | \
        {x for x in m.mentioned if x not in _properties(g)}
    on_lines = {p for e in m.edges for p in e.props} | \
        {p for c in m.classes.values() for at in c.attrs for p in at.props}
    # Properties a reader can find in the source panel: those on lines, and
    # those named in an axiom of a drawn class.
    panel_props = set(on_lines) | set(m.properties) | m.mentioned
    class_text = " ".join(canon(g, t) for a in axioms
                          if a.type in _CLASS_AXIOMS and a.subject in boxes for t in a.terms)
    for p in _properties(g):
        if f"<{p}>" in class_text:
            panel_props.add(p)
    pruned = set(m.pruned)

    rows = []
    for a in axioms:
        status, reason = _classify(a, drawn_ids, boxes, on_lines, panel_props, pruned, m,
                                   definitions)
        rows.append({"id": a.id, "type": a.type, "subject": a.subject, "status": status,
                     "reason": reason, "imported": a.subject in m.import_of})
    own = [r for r in rows if not r["imported"]]
    imp = [r for r in rows if r["imported"]]
    return {
        "version": 1,
        "ontology": m.ontology_iri,
        "totals": _totals(own),
        "by_type": _by_type(own),
        "dropped_reasons": dict(Counter(r["reason"] for r in own if r["status"] == "dropped")
                                .most_common()),
        "imported": {"totals": _totals(imp), "by_type": _by_type(imp)},
        "notes": m.notes,
        "axioms": rows,
    }


def _properties(g: Graph) -> set[str]:
    return {str(s) for t in (OWL.ObjectProperty, OWL.DatatypeProperty)
            for s in g.subjects(RDF.type, t) if isinstance(s, URIRef)}


def _classify(a: Axiom, drawn, boxes, on_lines, panel_props, pruned, m, definitions):
    subj = a.subject
    if a.id in drawn:
        return "drawn", ""
    gone = ("imported class not used by the ontology (left out; --keep-unused keeps it)"
            if subj in pruned else "its subject is not on the diagram")
    if a.type == "Declaration":
        what = a.terms[1]
        if what in (OWL.Class, RDFS.Class, OWL.NamedIndividual):
            return ("drawn", "") if subj in boxes else ("dropped", gone if what != OWL.NamedIndividual
                                                         else "individuals are not drawn")
        if what in (OWL.ObjectProperty, OWL.DatatypeProperty):
            if subj in on_lines:
                return "drawn", ""
            if subj in panel_props:
                return "panel", ""
            return "dropped", "property not used by any drawn class"
        return "dropped", "annotation properties and datatypes are not drawn"
    if a.type == "AnnotationAssertion":
        if subj in boxes:
            if a.predicate == str(RDFS.label) or a.predicate == str(OWL.deprecated):
                return "drawn", ""
            if a.predicate in _DEFINITION_IRIS and definitions:
                return "drawn", ""
            return "panel", ""
        if subj in panel_props:
            return "panel", ""
        return "dropped", gone if subj in pruned else "annotation on an entity not on the diagram"
    if a.type in _CLASS_AXIOMS:
        if subj in boxes:
            return "panel", ""
        return "dropped", gone
    if a.type in _PROPERTY_AXIOMS:
        if a.type in _BADGED and subj in on_lines:
            return "drawn", ""
        key = _KEYED.get(a.type)
        if key and m.properties.get(subj, {}).get(key):
            return "drawn", ""
        if subj in panel_props:
            return "panel", ""
        return "dropped", "property not used by any drawn class"
    if a.type in _ABOX:
        if subj in boxes:
            return "drawn", ""
        return "dropped", "individuals (ABox) are not drawn"
    return "dropped", "not an OWL axiom the diagram reads"


def _totals(rows: list) -> dict:
    c = Counter(r["status"] for r in rows)
    return {"axioms": len(rows), **{s: c.get(s, 0) for s in STATUSES}}


def _by_type(rows: list) -> dict:
    out: dict[str, dict] = {}
    for r in rows:
        t = out.setdefault(r["type"], {"total": 0, **{s: 0 for s in STATUSES}})
        t["total"] += 1
        t[r["status"]] += 1
    return dict(sorted(out.items()))


def summary(report: dict, max_rows: int = 200) -> dict:
    """The report without the per-axiom rows (for the SVG and the web app),
    keeping up to ``max_rows`` dropped axioms."""
    out = {k: v for k, v in report.items() if k != "axioms"}
    out["dropped"] = [r for r in report["axioms"]
                      if r["status"] == "dropped" and not r["imported"]][:max_rows]
    return out


def to_json(report: dict) -> str:
    return json.dumps(report, indent=1, ensure_ascii=False)


def headline(report: dict) -> str:
    t = report["totals"]
    if not t["axioms"]:
        return "no axioms"
    return (f"{t['axioms']} axioms: {t['drawn']} drawn, {t['panel']} in the source panel, "
            f"{t['dropped']} left out")
