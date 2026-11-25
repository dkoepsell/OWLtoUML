"""Scratchpad: OWL text sent as a form field, and the render rate limit."""
import os
import re
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
STATIC = os.path.join(HERE, "..", "src", "webapp", "static")
sys.path.insert(0, os.path.join(HERE, "..", "src"))
sys.path.insert(0, os.path.join(HERE, "..", "src", "webapp"))

TTL = """@prefix : <http://example.org/scratch#> .
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
:A a owl:Class .
:B a owl:Class ; rdfs:subClassOf :A .
"""


@pytest.fixture
def server(monkeypatch):
    pytest.importorskip("flask")
    import server as srv
    monkeypatch.setattr(srv, "RENDER_RATE", 0)
    srv._hits.clear()
    return srv


def post(client, text, **env):
    return client.post("/api/render", data={"text": text, "imports": "none"},
                       environ_base=env)


def test_text_renders(server):
    res = post(server.app.test_client(), TTL)
    assert res.status_code == 200, res.data[:300]
    data = res.get_json()
    assert data["classes"] == 2 and "<svg" in data["svg"]


def test_text_syntax_error_names_the_line(server):
    bad = TTL + ":C a owl:Class ; rdfs:subClassOf undeclared:X .\n"
    res = post(server.app.test_client(), bad)
    assert res.status_code == 400
    assert re.search(r"\bline \d+", res.get_json()["error"])


def test_empty_text_is_refused(server):
    res = post(server.app.test_client(), "")
    assert res.status_code == 400


def test_rate_limit(server, monkeypatch):
    monkeypatch.setattr(server, "RENDER_RATE", 2)
    c = server.app.test_client()
    assert post(c, TTL).status_code == 200
    assert post(c, TTL).status_code == 200
    res = post(c, TTL)
    assert res.status_code == 429 and "wait" in res.get_json()["error"]


def test_rate_limit_per_forwarded_client_behind_local_proxy(server, monkeypatch):
    monkeypatch.setattr(server, "RENDER_RATE", 1)
    c = server.app.test_client()
    local = {"REMOTE_ADDR": "127.0.0.1"}
    assert post(c, TTL, HTTP_X_FORWARDED_FOR="203.0.113.5", **local).status_code == 200
    assert post(c, TTL, HTTP_X_FORWARDED_FOR="203.0.113.6", **local).status_code == 200
    assert post(c, TTL, HTTP_X_FORWARDED_FOR="203.0.113.5", **local).status_code == 429


def test_forwarded_header_ignored_from_the_open_web(server, monkeypatch):
    monkeypatch.setattr(server, "RENDER_RATE", 1)
    c = server.app.test_client()
    pub = {"REMOTE_ADDR": "8.8.8.8"}
    assert post(c, TTL, HTTP_X_FORWARDED_FOR="203.0.113.5", **pub).status_code == 200
    # a spoofed header does not buy a fresh allowance
    assert post(c, TTL, HTTP_X_FORWARDED_FOR="203.0.113.9", **pub).status_code == 429


def test_page_has_every_element_the_scratchpad_uses():
    with open(os.path.join(STATIC, "scratchpad.js"), encoding="utf-8") as f:
        js = f.read()
    with open(os.path.join(STATIC, "index.html"), encoding="utf-8") as f:
        html = f.read()
    assert "/static/scratchpad.js" in html
    ids = set(re.findall(r'el\("([A-Za-z]+)"\)', js))
    assert ids, "no element ids found in scratchpad.js"
    missing = [i for i in sorted(ids) if f'id="{i}"' not in html]
    assert not missing, missing
