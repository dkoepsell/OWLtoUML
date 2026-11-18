"""/api/claims: the web app's Claims panel (src/webapp/claims_api.py), run as
a background job that the page polls."""
import os
import sys
import time

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "..", "src")
sys.path.insert(0, SRC)
sys.path.insert(0, os.path.join(SRC, "webapp"))

from owl2uml.claims import classify  # noqa: E402

needs_reasoners = pytest.mark.skipif(
    not (classify.available("hermit") and classify.available("pellet")),
    reason="Java with robot.jar (HermiT) and owlready2 (Pellet) needed")
NAO = os.path.join(HERE, "fixtures", "nao.ttl")
PIZZA = os.path.join(HERE, "..", "examples", "pizza.ttl")


@pytest.fixture(scope="module")
def client():
    import server
    return server.app.test_client()


def _run(client, path, name, wait=240):
    with open(path, "rb") as fh:
        r = client.post("/api/claims", data={"file": (fh, name)},
                        content_type="multipart/form-data")
    assert r.status_code == 202, r.get_json()
    start = r.get_json()
    deadline = time.time() + wait
    while time.time() < deadline:
        d = client.get(f"/api/claims/{start['job']}").get_json()
        assert d["state"] in ("queued", "running", "done")
        if d["state"] == "done":
            return start, d
        time.sleep(0.5)
    raise AssertionError("claims job did not finish")


def test_no_file(client):
    r = client.post("/api/claims", data={}, content_type="multipart/form-data")
    assert r.status_code == 400 and "no ontology" in r.get_json()["error"]


def test_unknown_job(client):
    assert client.get("/api/claims/nope").status_code == 404
    assert client.get("/api/claims/" + "0" * 32).status_code == 404


@needs_reasoners
def test_nao_claims(client):
    start, d = _run(client, NAO, "nao.ttl")
    assert start["mode"] == "full" and start["classes"] == 23
    assert "error" not in d, d
    assert len(d["claims"]) == 81
    assert d["report"]["records"]["REFUTED"] == 3
    texts = {c["text"] for c in d["claims"]}
    assert "No irreversibly accountable agent is a resettable artifact." in texts
    assert d["txt"].startswith("ENTAILED (") and d["note"] is None


@needs_reasoners
def test_no_ontology_iri_uses_class_namespace(client):
    """pizza.ttl declares no ontology IRI; the classes' namespace is used."""
    _, d = _run(client, PIZZA, "pizza.ttl")
    assert any(c["text"] == "Every CheeseTopping is a PizzaTopping." for c in d["claims"])


def test_over_budget_lists_assertions(client, monkeypatch):
    """Too large for the reasoners: the assertions, and a note saying why."""
    from webapp import claims_api
    monkeypatch.setattr(claims_api, "MAX_CHECKS", 100)
    start, d = _run(client, NAO, "nao.ttl")
    assert start["mode"] == "assertions"
    assert d["report"]["assertions_only"] is True
    assert {c["status"] for c in d["claims"]} == {"ASSERTED"} and len(d["claims"]) == 65
    assert "too large" in d["note"]
