"""Edit mode: diagram edits applied to the OWL graph (owl2uml/edit.py)."""
import io
import os
import sys

import pytest
from rdflib import Graph, URIRef
from rdflib.namespace import OWL, RDF, RDFS

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "src"))

from owl2uml import edit                              # noqa: E402
from owl2uml.parse import load_graph, parse_ontology  # noqa: E402

FX = os.path.join(HERE, "fixtures", "defined.ttl")
K = "http://example.org/kitchen/"
OBJ = "http://purl.obolibrary.org/obo/UP_0000002"


def load():
    return load_graph(FX)


def edges(g):
    m = parse_ontology(FX, graph=g)
    return {(e.kind, e.src, e.dst, e.label) for e in m.edges}


def kinds(g, src, dst):
    return {k for k, s, d, _ in edges(g) if s == src and d == dst}


def run(g, *ops):
    rep = edit.apply_edits(g, list(ops))
    assert not rep["skipped"], rep["skipped"]
    return rep


def test_retarget_subclass():
    g = load()
    run(g, {"op": "retarget", "edge": {"kind": "generalization", "src": K + "Cheese", "dst": K + "Topping"},
            "end": "dst", "to": K + "Dish"})
    assert "generalization" in kinds(g, K + "Cheese", K + "Dish")
    assert "generalization" not in kinds(g, K + "Cheese", K + "Topping")


def test_retarget_restriction_keeps_quantifier():
    g = load()
    run(g, {"op": "retarget", "edge": {"kind": "restriction", "src": K + "Dish", "dst": K + "Base",
                                       "prop": K + "hasBase", "quant": "some"},
            "end": "dst", "to": K + "Topping"})
    rs =[o for o in g.objects(URIRef(K + "Dish"), RDFS.subClassOf) if (o, OWL.onProperty, None) in g]
    assert len(rs) == 1
    assert g.value(rs[0], OWL.someValuesFrom) == URIRef(K + "Topping")
    assert g.value(rs[0], OWL.onProperty) == URIRef(K + "hasBase")


def test_retarget_association_range():
    g = load()
    run(g, {"op": "retarget", "edge": {"kind": "association", "src": K + "Dish", "dst": K + "Topping",
                                       "prop": K + "hasTopping"}, "end": "dst", "to": K + "Cheese"})
    assert set(g.objects(URIRef(K + "hasTopping"), RDFS.range)) == {URIRef(K + "Cheese")}


def test_delete_association_from_union_domain():
    g = load()
    run(g, {"op": "delete_edge", "edge": {"kind": "association", "src": K + "Topping", "dst": OBJ,
                                          "prop": K + "servedTo"}})
    assert "association" in kinds(g, K + "Dish", OBJ)
    assert "association" not in kinds(g, K + "Topping", OBJ)


def test_add_edges():
    g = load()
    run(g,
        {"op": "add_property", "iri": K + "pairsWith", "label": "pairs with"},
        {"op": "add_edge", "kind": "some", "src": K + "Cheese", "dst": K + "Meat", "prop": K + "pairsWith"},
        {"op": "add_edge", "kind": "only", "src": K + "Meat", "dst": K + "Cheese", "prop": K + "pairsWith"},
        {"op": "add_edge", "kind": "subclass", "src": K + "Base", "dst": K + "Topping"},
        {"op": "add_edge", "kind": "equivalent", "src": K + "Cheese", "dst": K + "Base"})
    assert "restriction" in kinds(g, K + "Cheese", K + "Meat")
    assert "restriction" in kinds(g, K + "Meat", K + "Cheese")
    assert "generalization" in kinds(g, K + "Base", K + "Topping")
    assert "equivalent" in kinds(g, K + "Cheese", K + "Base") | kinds(g, K + "Base", K + "Cheese")


def test_definition_member_add_and_remove():
    g = load()
    run(g, {"op": "add_edge", "kind": "definition", "src": K + "Meat", "dst": K + "Topping"})
    assert "definition" in kinds(g, K + "Meat", K + "Topping")
    run(g, {"op": "delete_edge", "edge": {"kind": "definition", "src": K + "Meat", "dst": K + "Topping"}})
    assert "definition" not in kinds(g, K + "Meat", K + "Topping")


def test_add_and_rename_class():
    g = load()
    rep = run(g, {"op": "add_class", "label": "Sauce bottle", "parent": K + "Topping"},
              {"op": "rename", "iri": K + "Meat", "label": "Charcuterie"})
    new = URIRef(rep["minted"][0])
    assert str(new).endswith("SauceBottle")
    assert (new, RDF.type, OWL.Class) in g
    assert (new, RDFS.subClassOf, URIRef(K + "Topping")) in g
    assert {str(o) for o in g.objects(URIRef(K + "Meat"), RDFS.label)} == {"Charcuterie"}


def test_minted_iri_uses_class_namespace():
    # not the ontology IRI (kitchen.owl#) nor the imported OBO namespace
    assert edit.mint_iri(load(), "Sauce") == URIRef(K + "Sauce")


def test_minted_iri_avoids_clash():
    g = load()
    rep = run(g, {"op": "add_class", "label": "cheese"})
    assert rep["minted"][0] != K + "Cheese"


def test_delete_class_leaves_nothing_dangling():
    g = load()
    run(g, {"op": "delete_class", "iri": K + "Base"})
    base = URIRef(K + "Base")
    assert (base, None, None) not in g and (None, None, base) not in g
    # the "hasBase some Base" restriction went with it
    assert not [o for o in g.objects(URIRef(K + "Dish"), RDFS.subClassOf)
                if g.value(o, OWL.onProperty) == URIRef(K + "hasBase")]
    # no orphan blank nodes
    for s in set(g.subjects()):
        if not isinstance(s, URIRef):
            assert (None, None, s) in g, f"orphan blank node {s}"


def test_bad_ops_are_skipped_not_fatal():
    g = load()
    rep = edit.apply_edits(g, [
        {"op": "nope"},
        {"op": "delete_edge", "edge": {"kind": "generalization", "src": K + "Dish", "dst": K + "Meat"}},
        {"op": "add_edge", "kind": "inferred", "src": K + "Dish", "dst": K + "Meat"},
        {"op": "rename", "iri": "not an iri", "label": "x"},
        {"op": "rename", "iri": K + "Dish", "label": "Plate"},
    ])
    assert rep["applied"] == 1
    assert [s["i"] for s in rep["skipped"]] == [0, 1, 2, 3]


def test_too_many_ops():
    with pytest.raises(edit.EditError):
        edit.apply_edits(Graph(), [{"op": "rename"}] * (edit.MAX_OPS + 1))


@pytest.mark.parametrize("fmt", ["turtle", "xml"])
def test_serialize_round_trip(fmt):
    g = load()
    run(g, {"op": "add_edge", "kind": "subclass", "src": K + "Base", "dst": K + "Topping"})
    data = edit.serialize(g, fmt)
    g2 = Graph().parse(data=data, format=fmt)
    assert (URIRef(K + "Base"), RDFS.subClassOf, URIRef(K + "Topping")) in g2
    assert any("owl2uml" in str(c) for c in g2.objects(None, RDFS.comment))


def _client():
    sys.path.insert(0, os.path.join(HERE, "..", "src", "webapp"))
    pytest.importorskip("flask")
    import server
    return server.app.test_client()


def test_server_export():
    import json
    with open(FX, "rb") as f:
        body = f.read()
    ops = [{"op": "add_edge", "kind": "subclass", "src": K + "Base", "dst": K + "Topping"}]
    res = _client().post("/api/export", data={
        "file": (io.BytesIO(body), "defined.ttl"), "edits": json.dumps(ops), "fmt": "turtle"},
        content_type="multipart/form-data")
    assert res.status_code == 200, res.data[:300]
    assert "defined-edited.ttl" in res.headers.get("Content-Disposition", "")
    g2 = Graph().parse(data=res.data, format="turtle")
    assert (URIRef(K + "Base"), RDFS.subClassOf, URIRef(K + "Topping")) in g2


def test_server_render_with_edits():
    import json
    from owl2uml.dot import dot_available
    if not dot_available():
        pytest.skip("graphviz not installed")
    with open(FX, "rb") as f:
        body = f.read()
    ops = [{"op": "add_class", "label": "Sauce"}, {"op": "nope"}]
    res = _client().post("/api/render", data={
        "file": (io.BytesIO(body), "defined.ttl"), "edits": json.dumps(ops)},
        content_type="multipart/form-data")
    data = res.get_json()
    assert res.status_code == 200, data
    assert data["edits"]["applied"] == 1 and len(data["edits"]["skipped"]) == 1
    assert "Sauce" in data["svg"]


def test_server_rejects_bad_edits_json():
    with open(FX, "rb") as f:
        body = f.read()
    res = _client().post("/api/export", data={
        "file": (io.BytesIO(body), "defined.ttl"), "edits": "{not json"},
        content_type="multipart/form-data")
    assert res.status_code == 400
