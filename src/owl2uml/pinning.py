"""Saved layouts (spec WS2.3): positions that survive regeneration.

A sidecar ``<ontology>.layout.json`` lives next to the ontology in version
control::

    {"https://w3id.org/lof/ODP003_0001000": {"x": 120.5, "y": 340.0, "pinned": true}}

Coordinates are Graphviz points (y up), the units of the drawing. Pinned
classes keep their place when the diagram is drawn again; the rest are laid
out by `dot` as usual (twopass.render applies the pins).

The same data can live in a *layout ontology* that imports the main one
(``--layout-in-ontology``), as annotation assertions -- never on the main
ontology itself.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

from rdflib import Graph, Literal, Namespace, OWL, RDF, URIRef
from rdflib.namespace import XSD

O2U = Namespace("https://w3id.org/owl2uml/layout#")
MAX_ENTRIES = 50_000


def sidecar_path(ontology_path: str) -> Path:
    p = Path(ontology_path)
    return p.with_name(p.stem + ".layout.json")


def parse(data: dict) -> dict[str, dict]:
    """Validate a layout mapping (from JSON): {iri: {x, y, pinned}}."""
    if not isinstance(data, dict):
        raise ValueError("a layout must be a JSON object keyed by class IRI")
    if len(data) > MAX_ENTRIES:
        raise ValueError(f"layout has more than {MAX_ENTRIES} entries")
    out = {}
    for iri, v in data.items():
        if not isinstance(iri, str) or not isinstance(v, dict):
            raise ValueError(f"layout entry for {iri!r} must be an object with x and y")
        try:
            x, y = float(v["x"]), float(v["y"])
        except (KeyError, TypeError, ValueError):
            raise ValueError(f"layout entry for {iri} needs numeric x and y") from None
        if not (math.isfinite(x) and math.isfinite(y)):
            raise ValueError(f"layout entry for {iri} has a non-finite position")
        out[iri] = {"x": x, "y": y, "pinned": bool(v.get("pinned", True))}
    return out


def load(path: str) -> dict[str, dict]:
    """A sidecar (.json) or a layout ontology (any RDF syntax rdflib reads)."""
    p = Path(path)
    if p.suffix.lower() == ".json":
        return parse(json.loads(p.read_text(encoding="utf-8")))
    g = Graph()
    g.parse(str(p))
    out = {}
    for s in set(g.subjects(O2U.x, None)):
        x, y = g.value(s, O2U.x), g.value(s, O2U.y)
        if x is None or y is None:
            continue
        pinned = g.value(s, O2U.pinned)
        out[str(s)] = {"x": float(x), "y": float(y),
                       "pinned": pinned is None or str(pinned).lower() in ("true", "1")}
    return parse(out)


def pins(layout: dict[str, dict]) -> dict[str, tuple[float, float]]:
    """Only the pinned positions."""
    return {iri: (v["x"], v["y"]) for iri, v in layout.items() if v.get("pinned")}


def save(path: str, layout: dict[str, dict]) -> None:
    Path(path).write_text(json.dumps(dict(sorted(layout.items())), indent=1) + "\n",
                          encoding="utf-8")


def layout_ontology(layout: dict[str, dict], ontology_iri: str) -> Graph:
    """A separate ontology that imports the main one and carries the layout
    as annotation assertions (o2u:x, o2u:y, o2u:pinned)."""
    g = Graph()
    g.bind("o2u", O2U)
    base = (ontology_iri or "urn:owl2uml:ontology").rstrip("/#")
    me = URIRef(base + "-layout")
    g.add((me, RDF.type, OWL.Ontology))
    if ontology_iri:
        g.add((me, OWL.imports, URIRef(ontology_iri)))
    for p in (O2U.x, O2U.y, O2U.pinned):
        g.add((p, RDF.type, OWL.AnnotationProperty))
    for iri, v in sorted(layout.items()):
        s = URIRef(iri)
        g.add((s, O2U.x, Literal(round(v["x"], 2), datatype=XSD.decimal)))
        g.add((s, O2U.y, Literal(round(v["y"], 2), datatype=XSD.decimal)))
        g.add((s, O2U.pinned, Literal(bool(v.get("pinned", True)))))
    return g


def from_svg(svg: str, nodes: dict[str, str], pinned: bool = False) -> dict[str, dict]:
    """Positions of every class in a rendered SVG (to start a sidecar).

    ``nodes`` maps Graphviz node ids (n0, n1, ...) to class IRIs.
    """
    import re
    out = {}
    for m in re.finditer(r'<g id="(n\d+)" class="node[^"]*">.*?</g>', svg, re.S):
        nid = m.group(1)
        if nid not in nodes:
            continue
        xs, ys = [], []
        for pm in re.finditer(r'points="([^"]+)"', m.group(0)):
            for pair in pm.group(1).split():
                px, _, py = pair.partition(",")
                xs.append(float(px))
                ys.append(float(py))
        for em in re.finditer(r'<ellipse[^>]*cx="([-\d.]+)" cy="([-\d.]+)"', m.group(0)):
            xs.append(float(em.group(1)))
            ys.append(float(em.group(2)))
        if xs:
            out[nodes[nid]] = {"x": round((min(xs) + max(xs)) / 2, 2),
                               "y": round(-(min(ys) + max(ys)) / 2, 2), "pinned": pinned}
    return out
