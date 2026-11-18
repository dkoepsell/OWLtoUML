"""POST /api/claims: the web app's Claims panel (src/webapp/claims_api.py)."""
import os
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "..", "src")
sys.path.insert(0, SRC)
sys.path.insert(0, os.path.join(SRC, "webapp"))

from owl2uml.claims import classify  # noqa: E402

needs_reasoners = pytest.mark.skipif(
    not (classify.available("hermit") and classify.available("pellet")),
    reason="Java with robot.jar (HermiT) and owlready2 (Pellet) needed")


@pytest.fixture(scope="module")
def client():
    import server
    return server.app.test_client()


def _post(client, path, name):
    with open(path, "rb") as fh:
        return client.post("/api/claims", data={"file": (fh, name)},
                           content_type="multipart/form-data")


def test_no_file(client):
    r = client.post("/api/claims", data={}, content_type="multipart/form-data")
    assert r.status_code == 400 and "no ontology" in r.get_json()["error"]


@needs_reasoners
def test_nao_claims(client):
    r = _post(client, os.path.join(HERE, "fixtures", "nao.ttl"), "nao.ttl")
    d = r.get_json()
    assert r.status_code == 200, d
    assert len(d["claims"]) == 81
    assert d["report"]["records"]["REFUTED"] == 3
    texts = {c["text"] for c in d["claims"]}
    assert "No irreversibly accountable agent is a resettable artifact." in texts
    assert d["txt"].startswith("ENTAILED (")


@needs_reasoners
def test_no_ontology_iri_uses_class_namespace(client):
    """pizza.ttl declares no ontology IRI; the classes' namespace is used."""
    r = _post(client, os.path.join(HERE, "..", "examples", "pizza.ttl"), "pizza.ttl")
    d = r.get_json()
    assert r.status_code == 200, d
    assert any(c["text"] == "Every CheeseTopping is a PizzaTopping." for c in d["claims"])
