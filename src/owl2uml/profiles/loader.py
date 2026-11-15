"""Read, compose and match notation profiles.

A profile file (YAML or JSON):

    profile: legal
    extends: bfo
    relation_styles:
      - match: {property: "https://w3id.org/lof/ODP003_0001102"}
        style: symmetric_pair
        stroke: categorical-4
    class_styles:
      - match: {subclass_of: "http://purl.obolibrary.org/obo/BFO_0000003"}
        band: occurrent
    badges: {hide_class_badge: true}

Profiles compose left to right (``--profile bfo,legal``): later rules win.
Properties may also carry ``o2u:style "symmetric_pair"`` in the ontology
itself; those come last, so an ontology's own styling wins.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

import yaml
from rdflib import Graph, Literal, URIRef

HERE = Path(__file__).resolve().parent
O2U = "https://w3id.org/owl2uml/ns#"
STYLES = ("directed", "symmetric_pair", "inverse_merged", "compartment",
          "containment", "hidden")
BANDS_ORDER = ("continuant", "occurrent")   # top to bottom


class ProfileError(ValueError):
    pass


@dataclass
class Profile:
    names: list[str] = field(default_factory=list)
    relation_styles: list[dict] = field(default_factory=list)
    class_styles: list[dict] = field(default_factory=list)
    badges: dict = field(default_factory=dict)
    motifs: list[dict] = field(default_factory=list)
    aliases: dict[str, str] = field(default_factory=dict)   # IRI -> canonical IRI
    bfo_stub: bool = False

    def canonical(self, iri: str) -> str:
        return self.aliases.get(iri, iri)


def available() -> list[str]:
    return sorted(p.stem for p in HERE.glob("*.yaml"))


def _read(name: str) -> dict:
    path = Path(name)
    if not path.suffix:
        path = HERE / f"{name}.yaml"
    if not path.is_file():
        raise ProfileError(f"no profile {name!r} (bundled: {', '.join(available())})")
    text = path.read_text(encoding="utf-8")
    try:
        data = json.loads(text) if path.suffix == ".json" else yaml.safe_load(text)
    except (ValueError, yaml.YAMLError) as exc:
        raise ProfileError(f"{path.name}: {exc}") from exc
    if not isinstance(data, dict):
        raise ProfileError(f"{path.name}: a profile is a mapping")
    for rule in data.get("relation_styles") or []:
        st = rule.get("style", "directed")
        if st not in STYLES:
            raise ProfileError(f"{path.name}: unknown style {st!r} (one of {', '.join(STYLES)})")
    return data


def _merge(into: Profile, data: dict, seen: set) -> None:
    name = data.get("profile") or "?"
    if name in seen:
        return
    seen.add(name)
    for parent in _as_list(data.get("extends")):
        _merge(into, _read(parent), seen)
    into.names.append(name)
    into.relation_styles += data.get("relation_styles") or []
    into.class_styles += data.get("class_styles") or []
    into.badges.update(data.get("badges") or {})
    into.motifs += data.get("motifs") or []
    into.aliases.update(data.get("aliases") or {})
    into.bfo_stub = bool(data.get("bfo_stub", into.bfo_stub))


def _as_list(v) -> list[str]:
    if not v:
        return []
    return [x.strip() for x in v.split(",")] if isinstance(v, str) else list(v)


def load(names, graph: Graph | None = None) -> Profile:
    """Compose the named profiles (left to right), then the ontology's own
    ``o2u:style`` annotations."""
    prof = Profile()
    seen: set = set()
    for n in _as_list(names):
        if n and n != "none":
            _merge(prof, _read(n), seen)
    if graph is not None:
        for p, v in sorted(graph.subject_objects(URIRef(O2U + "style"))):
            if isinstance(p, URIRef) and isinstance(v, Literal) and str(v) in STYLES:
                prof.relation_styles.append({"match": {"property": str(p)}, "style": str(v),
                                             "source": "ontology"})
        if prof.relation_styles and "ontology" not in prof.names and \
                any(r.get("source") == "ontology" for r in prof.relation_styles):
            prof.names.append("ontology")
    return prof


def detect(graph: Graph) -> list[str]:
    """Profiles that fit an ontology: bfo when it uses BFO terms, legal when
    it is a LOF ontology (or declares Hohfeldian correlatives)."""
    text = {str(t) for t in graph.all_nodes() if isinstance(t, URIRef)}
    out = []
    if any("purl.obolibrary.org/obo/BFO_" in t for t in text):
        out.append("bfo")
    if any(t.startswith("https://w3id.org/lof/") for t in text):
        out.append("legal")
    return out or ["core"]
