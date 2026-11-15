"""WS1.3: every axiom is accounted for (drawn, source panel, or left out with a reason)."""
import json
import random
import sys
from pathlib import Path

import pytest
from rdflib import BNode, Graph, Literal, OWL, RDF, RDFS, URIRef
from rdflib.collection import Collection

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from owl2uml import coverage  # noqa: E402
from owl2uml.axioms import axiom_id, inventory  # noqa: E402
from owl2uml.cli import main as cli_main  # noqa: E402
from owl2uml.dot import to_dot  # noqa: E402
from owl2uml.load import load  # noqa: E402
from owl2uml.parse import parse_ontology  # noqa: E402
from owl2uml.postprocess import postprocess  # noqa: E402

FIX = ROOT / "tests" / "fixtures"
EX = "http://example.org/r#"


def report(g, **kw):
    m = parse_ontology("x", graph=g)
    postprocess(m)
    return m, coverage.build(g, m, **kw)


def test_fixture_fully_accounted():
    g = load(str(FIX / "constructs.ttl")).merge()
    _m, r = report(g)
    t = r["totals"]
    assert t["axioms"] == t["drawn"] + t["panel"] + t["dropped"] == len(r["axioms"])
    assert t["dropped"] == 0 and t["drawn"] > 40


def test_definitions_count_as_drawn_only_when_shown():
    g = load(str(FIX / "constructs.ttl")).merge()
    _, hidden = report(g)
    _, shown = report(g, definitions=True)
    assert shown["totals"]["drawn"] == hidden["totals"]["drawn"] + 2


def test_axiom_ids_do_not_depend_on_syntax_or_blank_nodes():
    a = Graph().parse(data="""@prefix : <http://x/> . @prefix owl: <http://www.w3.org/2002/07/owl#> .
        @prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
        :A rdfs:subClassOf [ a owl:Restriction ; owl:onProperty :p ;
            owl:someValuesFrom [ owl:unionOf ( :B :C ) ] ] .""", format="turtle")
    b = Graph().parse(data="""<?xml version="1.0"?>
        <rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"
                 xmlns:rdfs="http://www.w3.org/2000/01/rdf-schema#"
                 xmlns:owl="http://www.w3.org/2002/07/owl#">
          <rdf:Description rdf:about="http://x/A"><rdfs:subClassOf><owl:Restriction>
            <owl:someValuesFrom><owl:Class><owl:unionOf rdf:parseType="Collection">
              <rdf:Description rdf:about="http://x/C"/><rdf:Description rdf:about="http://x/B"/>
            </owl:unionOf></owl:Class></owl:someValuesFrom>
            <owl:onProperty rdf:resource="http://x/p"/>
          </owl:Restriction></rdfs:subClassOf></rdf:Description></rdf:RDF>""", format="xml")
    ia = {x.id for x in inventory(a) if x.type == "SubClassOf"}
    ib = {x.id for x in inventory(b) if x.type == "SubClassOf"}
    assert ia == ib and len(ia) == 1          # union members are a set: order ignored


def test_pruned_imports_are_reported_separately():
    lo = load(str(FIX / "imports" / "main.ttl"), allow_network=False)
    g = lo.merge()
    m = parse_ontology("x", graph=g)
    from owl2uml.load import annotate_model
    annotate_model(m, lo)
    postprocess(m)
    r = coverage.build(g, m)
    assert r["imported"]["totals"]["axioms"] > 0
    assert all(not row["imported"] for row in coverage.summary(r)["dropped"])


def test_cli_writes_report_and_key_panel(tmp_path, capsys):
    out = tmp_path / "c.svg"
    assert cli_main([str(FIX / "constructs.ttl"), "-o", str(out)]) == 0
    rep = json.loads((tmp_path / "c.coverage.json").read_text())
    assert rep["totals"]["axioms"] == len(rep["axioms"])
    svg = out.read_text()
    assert "Coverage" in svg and "drawn" in svg
    assert "coverage:" in capsys.readouterr().err
    assert cli_main([str(FIX / "constructs.ttl"), "-o", str(out), "--coverage-out", "-"]) == 0


def test_key_shows_left_out_reasons():
    g = Graph().parse(data="""@prefix : <http://x/> . @prefix owl: <http://www.w3.org/2002/07/owl#> .
        :A a owl:Class . :i a owl:NamedIndividual , :A .""", format="turtle")
    m, r = report(g)
    dot = to_dot(m, coverage=coverage.summary(r))
    assert "individuals" in dot and "left out" in dot


# --- property test: random small ontologies ------------------------------------

def _random_ontology(rng: random.Random) -> Graph:
    g = Graph()
    classes = [URIRef(f"{EX}C{i}") for i in range(rng.randint(2, 7))]
    props = [URIRef(f"{EX}p{i}") for i in range(rng.randint(1, 3))]
    for c in classes:
        g.add((c, RDF.type, OWL.Class))
        if rng.random() < 0.5:
            g.add((c, RDFS.label, Literal(f"class {c[-2:]}")))
    for p in props:
        g.add((p, RDF.type, OWL.ObjectProperty))
        if rng.random() < 0.4:
            g.add((p, RDF.type, rng.choice([OWL.TransitiveProperty, OWL.FunctionalProperty,
                                           OWL.SymmetricProperty])))
        if rng.random() < 0.5:
            g.add((p, RDFS.domain, rng.choice(classes)))
            g.add((p, RDFS.range, rng.choice(classes)))
    for _ in range(rng.randint(1, 10)):
        a, b = rng.sample(classes, 2)
        kind = rng.random()
        if kind < 0.35:
            g.add((a, RDFS.subClassOf, b))
        elif kind < 0.5:
            g.add((a, OWL.disjointWith, b))
        elif kind < 0.8:
            r = BNode()
            g.add((r, RDF.type, OWL.Restriction))
            g.add((r, OWL.onProperty, rng.choice(props)))
            g.add((r, rng.choice([OWL.someValuesFrom, OWL.allValuesFrom]), b))
            g.add((a, RDFS.subClassOf, r))
        elif kind < 0.9:
            u, lst = BNode(), BNode()
            Collection(g, lst, rng.sample(classes, min(2, len(classes))))
            g.add((u, OWL.unionOf, lst))
            g.add((a, RDFS.subClassOf, u))
        else:
            ind = URIRef(f"{EX}i{rng.randint(0, 99)}")
            g.add((ind, RDF.type, OWL.NamedIndividual))
            g.add((ind, RDF.type, a))
    return g


@pytest.mark.parametrize("seed", range(40))
def test_every_axiom_appears_exactly_once(seed):
    g = _random_ontology(random.Random(seed))
    _m, r = report(g)
    ids = [row["id"] for row in r["axioms"]]
    assert len(ids) == len(set(ids)), "an axiom was counted twice"
    expected = {x.id for x in inventory(g)}
    assert set(ids) == expected, "an axiom is missing from the report"
    for row in r["axioms"]:
        assert row["status"] in coverage.STATUSES
        if row["status"] == "dropped":
            assert row["reason"], row
    # every SubClassOf between two named classes is drawn
    for s, o in g.subject_objects(RDFS.subClassOf):
        if isinstance(o, URIRef):
            aid = axiom_id(g, "SubClassOf", s, o)
            assert next(x for x in r["axioms"] if x["id"] == aid)["status"] == "drawn"
