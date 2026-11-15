"""WS2.2: modules, module views with a context ring, the overview."""
import sys
from pathlib import Path

import pytest
from rdflib import Graph

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from owl2uml import modules  # noqa: E402
from owl2uml.cli import main as cli_main  # noqa: E402
from owl2uml.dot import dot_available  # noqa: E402
from owl2uml.parse import parse_ontology  # noqa: E402
from owl2uml.postprocess import postprocess  # noqa: E402

TTL = """@prefix : <https://w3id.org/x/> .
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix obo: <http://purl.obolibrary.org/obo/> .
<https://w3id.org/x> a owl:Ontology .
obo:BFO_0000001 a owl:Class .
:P1_001 a owl:Class ; rdfs:subClassOf obo:BFO_0000001 .
:P1_002 a owl:Class ; rdfs:subClassOf :P1_001 ;
    rdfs:subClassOf [ a owl:Restriction ; owl:onProperty :p ; owl:someValuesFrom :P2_001 ] .
:P2_001 a owl:Class ; rdfs:subClassOf obo:BFO_0000001 .
:P2_002 a owl:Class ; rdfs:subClassOf :P2_001 .
:Tagged a owl:Class ; <https://w3id.org/lof/module> "Extra" ; rdfs:subClassOf :P1_001 .
:p a owl:ObjectProperty .
"""
X = "https://w3id.org/x/"


@pytest.fixture()
def model():
    g = Graph().parse(data=TTL, format="turtle")
    m = parse_ontology("x", graph=g)
    postprocess(m, prune=False)
    modules.assign(m, g)
    return m, g


def test_sources_in_priority_order(model):
    m, _ = model
    assert m.modules["P1"]["source"] == "prefix"
    assert m.modules["Extra"]["source"] == "annotation"     # annotation beats prefix rules
    assert m.classes[X + "Tagged"].module == "Extra"
    assert set(m.modules["P2"]["members"]) == {X + "P2_001", X + "P2_002"}


def test_view_has_a_greyed_context_ring(model):
    m, _ = model
    v = modules.view(m, "P1")
    ctx = {cid for cid, c in v.classes.items() if c.context}
    # direct superclass (BFO entity) and the restriction's far end (P2_001)
    assert ctx == {"http://purl.obolibrary.org/obo/BFO_0000001", X + "P2_001"}
    assert X + "P2_002" not in v.classes
    assert any(e.kind == "restriction" and e.dst == X + "P2_001" for e in v.edges)
    assert not m.classes[X + "P2_001"].context             # the full model is untouched
    with pytest.raises(ValueError):
        modules.view(m, "nope")


def test_overview_counts_cross_module_relations(model):
    m, _ = model
    o = modules.overview(m)
    assert {c.name for c in o.classes.values()} >= {"P1", "P2", "Extra"}
    rel = [e for e in o.edges if e.src == "module:P1" and e.dst == "module:P2"]
    assert rel and rel[0].label == "1 relation"


def test_community_detection_when_one_prefix(tmp_path):
    lines = ["@prefix : <http://example.org/o#> .",
             "@prefix owl: <http://www.w3.org/2002/07/owl#> .",
             "@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .",
             "<http://example.org/o> a owl:Ontology ."]
    for cluster in "AB":
        lines.append(f":{cluster}root a owl:Class .")
        for i in range(18):
            lines.append(f":{cluster}{i} a owl:Class ; rdfs:subClassOf :{cluster}root .")
    g = Graph().parse(data="\n".join(lines), format="turtle")
    m = parse_ontology("x", graph=g)
    postprocess(m)
    found = modules.assign(m, g)
    assert {v["source"] for v in found.values()} == {"community"} and len(found) >= 2


@pytest.mark.skipif(not dot_available(), reason="needs graphviz")
def test_cli_all_modules(tmp_path):
    src = tmp_path / "x.ttl"
    src.write_text(TTL)
    out = tmp_path / "x.svg"
    assert cli_main([str(src), "-o", str(out), "--all-modules"]) == 0
    names = sorted(p.name for p in tmp_path.glob("x-*.svg"))
    assert "x-modules.svg" in names and "x-P1.svg" in names and "x-P2.svg" in names
    assert cli_main([str(src), "-o", str(out), "--view", "module=P2"]) == 0
    assert "context" in out.read_text()
