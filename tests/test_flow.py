"""Flow view: processes drawn from sequence relations, lanes from roles,
the practiced flow from logged instances, SHACL findings on the steps."""
import html
import json
import os
import re
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET

import pytest
from rdflib import Graph

HERE = os.path.dirname(__file__)
SRC = os.path.join(HERE, "..", "src")
sys.path.insert(0, SRC)

from owl2uml.flow import extract, load_map, render_flow_svg   # noqa: E402
from owl2uml.source import SCRIPT_ID                          # noqa: E402

FX = os.path.join(HERE, "fixtures")
P2P, EVENTS, SHAPES = (os.path.join(FX, f) for f in ("flow_p2p.ttl", "flow_events.ttl", "flow_shapes.ttl"))
needs_graphviz = pytest.mark.skipif(not (shutil.which("dot") and shutil.which("neato")), reason="Graphviz needed")


def g(path):
    return Graph().parse(path)


def label_edges(fm, kind):
    return {(fm.steps[e.src]["label"], fm.steps[e.dst]["label"], e.label) for e in fm.edges if e.kind == kind}


def test_designed_flow_from_axioms():
    fm = extract(g(P2P))
    assert len(fm.steps) == 10
    assert sorted(n for _, n in fm.lanes) == ["approver role", "finance role", "procurement role",
                                              "receiving role", "requester role"]
    seq = label_edges(fm, "sequence")
    assert ("budget check", "manager approval", "") in seq
    # a union of predecessors gives one arrow per member
    assert {("manager approval", "issue purchase order", ""), ("director approval", "issue purchase order", ""),
            ("collect three quotes", "issue purchase order", "")} <= seq
    req = label_edges(fm, "requirement")
    assert ("director approval", "issue purchase order", "if for amount > 10,000") in req
    assert ("collect three quotes", "issue purchase order", "if for amount > 25,000") in req
    assert ("issue purchase order", "invoice received", "") in req
    # 'preceded by' three-way match repeats the sequence arrow, so it is not drawn twice
    assert not any(a == "three-way match" and b == "release payment" for a, b, _ in req)
    # the defined classes that carry the conditions are not steps themselves
    assert "PO above director threshold" not in {s["label"] for s in fm.steps.values()}
    assert not fm.cases and not fm.findings


def test_practiced_flow_and_cases():
    fm = extract(g(P2P), g(EVENTS))
    assert len(fm.cases) == 15 and "C-1045" in fm.cases
    steps = [fm.steps[s]["label"] for s, _, _ in fm.cases["C-1045"]["events"]]
    assert steps[-2:] == ["release payment", "three-way match"]
    dev = {(a, b) for a, b, _ in label_edges(fm, "deviation")}
    assert ("invoice received", "release payment") in dev
    assert ("invoice received", "issue purchase order") in dev
    assert len(dev) == 5
    counts = {(fm.steps[e.src]["label"], fm.steps[e.dst]["label"]): len(e.cases)
              for e in fm.edges if e.kind == "sequence"}
    assert counts[("raise request", "budget check")] == 15
    assert counts[("manager approval", "director approval")] == 5


def test_shacl_findings_on_steps():
    fm = extract(g(P2P), g(EVENTS), g(SHAPES))
    got = {(f["rule"].split()[0], f["case"], fm.steps[f["step"]]["label"]) for f in fm.findings}
    assert got == {("N1", "C-1045", "release payment"), ("N3", "C-1043", "issue purchase order"),
                   ("N4", "C-1044", "issue purchase order"), ("N7", "C-1049", "invoice received")}


def test_custom_vocabulary_mapping(tmp_path):
    fm = extract(g(os.path.join(FX, "flow_custom.ttl")), g(os.path.join(FX, "flow_custom.ttl")),
                 mapping=load_map(os.path.join(FX, "flow_custom_map.json")))
    assert label_edges(fm, "sequence") == {("take order", "prepare dish", ""), ("prepare dish", "serve", "")}
    assert sorted(n for _, n in fm.lanes) == ["cook", "waiter"]
    assert len(fm.cases) == 2
    assert {(a, b) for a, b, _ in label_edges(fm, "deviation")} == {("take order", "serve")}


def test_nothing_to_draw_without_sequence_relations():
    assert not extract(g(os.path.join(FX, "source.ttl"))).steps


@needs_graphviz
def test_render_swimlanes_and_source():
    fm = extract(g(P2P), g(EVENTS), g(SHAPES))
    svg = render_flow_svg(fm, tbox=g(P2P))
    ET.fromstring(svg.encode("utf-8"))
    assert svg.count('class="o2u-lane"') == 5
    assert "REQUESTER ROLE" in svg
    src = json.loads(re.search(r'id="%s">(.*?)</script>' % SCRIPT_ID, svg, re.S).group(1))
    assert src["view"] == "flow" and len(src["findings"]) == 4
    for n in src["nodes"]:
        assert f'id="{n}"' in svg
    kinds = {e["kind"] for e in src["edges"].values()}
    assert kinds == {"sequence", "requirement", "deviation"}
    key = src["cases"]["C-1045"]["key"]
    assert html.unescape(svg).count(f"o2u-c-{key}") >= 8   # Graphviz writes "-" as &#45;
    assert 'class="o2u-designed"' not in svg    # events given: opens as practiced


@needs_graphviz
def test_designed_only_svg_starts_designed():
    svg = render_flow_svg(extract(g(P2P)), tbox=g(P2P))
    assert 'class="o2u-designed"' in svg and 'class="edge o2u-dev' not in html.unescape(svg)


@needs_graphviz
def test_cli_flow(tmp_path):
    env = dict(os.environ, PYTHONPATH=SRC)
    out = tmp_path / "f.svg"
    r = subprocess.run([sys.executable, "-m", "owl2uml.cli", P2P, "--events", EVENTS, "--shapes", SHAPES,
                        "--interactive", "-o", str(out)], env=env, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    assert "10 steps in 5 lanes, 15 cases, 5 undesigned paths, 4 SHACL findings" in r.stdout
    assert "OwlUmlInteract.attach" in out.read_text(encoding="utf-8")
    r = subprocess.run([sys.executable, "-m", "owl2uml.cli", os.path.join(FX, "source.ttl"), "--flow",
                        "-o", str(tmp_path / "x.svg")], env=env, capture_output=True, text=True)
    assert r.returncode == 1 and "no process steps" in r.stderr


@needs_graphviz
def test_server_flow():
    sys.path.insert(0, os.path.join(SRC, "webapp"))
    flask = pytest.importorskip("flask")  # noqa: F841
    import server
    c = server.app.test_client()
    with open(P2P, "rb") as a, open(EVENTS, "rb") as b, open(SHAPES, "rb") as s:
        r = c.post("/api/render", data={"file": (a, "p2p.ttl"), "events": (b, "events.ttl"),
                                        "shapes": (s, "shapes.ttl"), "view": "flow"},
                   content_type="multipart/form-data")
    d = r.get_json()
    assert r.status_code == 200, d
    assert d["view"] == "flow" and d["flow"]["findings"] == 4 and len(d["cases"]) == 15
