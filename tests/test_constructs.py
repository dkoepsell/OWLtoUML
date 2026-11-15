"""WS1.2: every OWL 2 construct in the spec's table is drawn or reported."""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from owl2uml.dot import dot_available, render_dot_svg, to_dot  # noqa: E402
from owl2uml.parse import load_graph, parse_ontology, property_view  # noqa: E402
from owl2uml.postprocess import postprocess  # noqa: E402
from owl2uml.source import build_source  # noqa: E402

FIX = ROOT / "tests" / "fixtures" / "constructs.ttl"
C = "http://example.org/c#"


@pytest.fixture(scope="module")
def model():
    m = parse_ontology(str(FIX))
    postprocess(m)
    return m


def edges(m, kind, src=None, dst=None):
    return [e for e in m.edges if e.kind == kind
            and (src is None or e.src == C + src) and (dst is None or e.dst == C + dst)]


def anon(m, kind):
    return [c for c in m.classes.values() if c.kind == kind]


def test_disjoint_pair_and_group(model):
    assert edges(model, "disjoint", "Person", "Organization")[0].label == "⊥"
    hub = anon(model, "disjoint")
    assert len(hub) == 1
    members = {e.dst for e in model.edges if e.src == hub[0].id}
    assert members == {C + "Person", C + "Organization", C + "Robot"}


def test_disjoint_union_is_a_generalization_set(model):
    gs = [e for e in model.edges if e.genset and e.dst == C + "Vehicle"]
    assert {e.src for e in gs} == {C + "Car", C + "Bike"}
    assert len({e.genset for e in gs}) == 1
    assert any(e.label == "{disjoint, complete}" for e in gs)


def test_union_and_complement_nodes(model):
    (u,) = anon(model, "union")
    assert u.owner == C + "Owner" and u.name == "⊔"
    assert {e.dst for e in model.edges if e.src == u.id and e.kind == "member"} == \
        {C + "Person", C + "Organization"}
    assert edges(model, "generalization", "Owner") and \
        edges(model, "generalization", "Owner")[0].dst == u.id
    (n,) = anon(model, "complement")
    assert n.owner == C + "NonPerson"
    # complement as a restriction filler: a ¬ badge on the label
    (r,) = edges(model, "restriction", "Hermit", "Person")
    assert r.label.endswith("¬") and "only" in r.label


def test_cardinality_becomes_multiplicity(model):
    (r,) = [e for e in edges(model, "restriction", "Person", "Person") if "hasParent" in e.label]
    assert r.multiplicity == "2"
    org = model.classes[C + "Organization"]
    assert any(a.name.startswith("hasMember") and "[1..*]" in a.name for a in org.attrs)


def test_has_self_loop_and_facets(model):
    (s,) = edges(model, "self", "Person", "Person")
    assert "knows" in s.label and "self" in s.label
    person = model.classes[C + "Person"]
    assert any(a.type == "integer [>= 0]" for a in person.attrs)


def test_has_value_individual_and_one_of(model):
    red = model.classes[C + "red"]
    assert red.kind == "individual" and red.name == "red : Color"
    assert edges(model, "restriction", "RedCar", "red")[0].label.startswith("hasColor")
    color = model.classes[C + "Color"]
    assert color.stereotype == "enumeration" and [a.name for a in color.attrs] == ["red", "green"]


def test_property_badges_and_key(model):
    r = [e for e in model.edges if "hasColor" in e.label][0]
    assert "¹" in r.label                       # functional
    knows = model.properties[C + "knows"]
    assert "↔" in knows["name"] and knows["characteristics"] == ["symmetric"]
    parent = model.properties[C + "hasParent"]
    assert parent["super"] == ["hasAncestor"] and parent["inverse"] == ["hasChild"]
    assert model.properties[C + "hasGrandparent"]["chains"] == ["hasParent ∘ hasParent"]


def test_deprecated_definition_and_punning(model):
    old = model.classes[C + "Automaton"]
    assert old.deprecated and old.definition == "Old name for robot."
    assert model.classes[C + "Person"].definition.startswith("A human being")
    assert any(n["kind"] == "punning" and n["iri"] == C + "Car" for n in model.notes)


def test_anonymous_nodes_have_no_group(model):
    assert all(c.group == "" for c in model.classes.values()
               if c.kind in ("union", "complement", "disjoint"))


def test_dot_styles(model):
    dot = to_dot(model, definitions=True, chains=True)
    assert 'class="rel-disjoint"' in dot and "style=dotted" in dot
    assert "samehead=" in dot and 'headlabel="2"' in dot
    assert "anon-union" in dot and "<s>" in dot            # deprecated name struck through
    assert "A human being" in dot                           # --show-definitions
    assert "⊒ hasParent ∘ hasParent" in dot                 # --draw-chains


@pytest.mark.skipif(not dot_available(), reason="needs graphviz")
def test_renders_and_every_line_has_a_source(model):
    g = load_graph(str(FIX))
    src = build_source(g, model)
    svg = render_dot_svg(model, source=src)
    assert "<svg" in svg
    for eid, info in src["edges"].items():
        if info["kind"] in ("restriction", "generalization", "disjoint", "member", "definition"):
            assert info.get("axioms"), (eid, info)


def test_property_view():
    m = property_view(load_graph(str(FIX)))
    assert m.classes[C + "hasParent"].stereotype == "object property"
    assert any(e.kind == "generalization" and e.src == C + "hasParent"
               and e.dst == C + "hasAncestor" for e in m.edges)
    assert any(e.label == "inverse of" for e in m.edges)
    chain = m.classes[C + "hasGrandparent"].attrs
    assert any(a.name == "chain" and a.type == "hasParent ∘ hasParent" for a in chain)
