"""Source panel data: the OWL behind each class and line, embedded in the SVG."""
import json
import os
import re
import subprocess
import sys
import xml.etree.ElementTree as ET

HERE = os.path.dirname(__file__)
SRC = os.path.join(HERE, "..", "src")
sys.path.insert(0, SRC)

from owl2uml.parse import load_graph, parse_ontology   # noqa: E402
from owl2uml.postprocess import postprocess            # noqa: E402
from owl2uml import reason                             # noqa: E402
from owl2uml.source import build_source, embed, manchester, SCRIPT_ID  # noqa: E402
from owl2uml.dot import render_dot_svg                 # noqa: E402

FIX = os.path.join(HERE, "fixtures", "source.ttl")
L = "http://example.org/law/"


def model(inferred=()):
    g = load_graph(FIX)
    m = parse_ontology(FIX, graph=g)
    if inferred:
        # Stand in for a reasoner, so the test needs no Java.
        inf = reason.Inference(engine="test", subsumptions={(L + a, L + b) for a, b in inferred})
        reason.apply(m, inf)
    postprocess(m)
    return g, m


def by_label(data, label):
    return next(c for c in data["classes"].values() if c["label"] == label)


def test_class_entries():
    g, m = model()
    d = build_source(g, m)
    act = by_label(d, "legal act")
    assert act["curie"] == "Act" or act["iri"] == L + "Act"
    assert act["ann"][0] == ["definition", "A process that changes legal content."]
    assert any(a["k"] == "SubClassOf" and a["m"] == "process" for a in act["ax"])
    assert by_label(d, "process")["curie"] == "BFO:0000015"
    order = by_label(d, "legal order")
    kinds = {a["k"]: a["m"] for a in order["ax"]}
    assert kinds["SubClassOf"] == "'has recognition criterion' some 'recognition criterion'"
    assert "'legal content'" in kinds["DisjointWith"]
    assert "owl:Restriction" in order["ttl"] and "@prefix" not in order["ttl"]
    rep = by_label(d, "repeal")
    assert rep["ax"][0]["m"] == "'legal act' and (repeals some 'legal content')"


def test_manchester_frame():
    g, m = model()
    text = manchester(by_label(build_source(g, m), "repeal"))
    assert text.splitlines()[0] == "Class: repeal"
    assert "    EquivalentTo:" in text


def test_every_drawn_line_has_a_source():
    g, m = model()
    d = build_source(g, m)
    assert set(d["nodes"].values()) == set(m.classes)
    for eid, e in d["edges"].items():
        if e["kind"] == "association":
            assert e["props"], eid
            assert all(p in d["props"] for p in e["props"])
        else:
            assert e["axioms"], (eid, e)


def test_inferred_line_lists_its_premises():
    g, m = model(inferred=[("Repeal", "Amending")])
    d = build_source(g, m)
    inf = [e for e in d["edges"].values() if e["kind"] == "inferred"]
    assert len(inf) == 1
    pr = inf[0]["premises"]
    owners = {c for c, _ in pr["classes"]}
    assert owners == {L + "Repeal", L + "Amending"}
    assert L + "repeals" in pr["props"]
    rep = d["props"][L + "repeals"]
    assert any(a["k"] == "SubPropertyOf" and a["m"] == "amends" for a in rep["ax"])


def test_embedded_json_is_safe_and_round_trips():
    g, m = model()
    d = build_source(g, m)
    svg = render_dot_svg(m, source=d)
    block = re.search(r'<script type="application/json" id="%s">(.*?)</script>' % SCRIPT_ID,
                      svg, re.S).group(1)
    assert "<" not in block and "&" not in block
    root = ET.fromstring(svg.encode("utf-8"))   # still well-formed XML
    assert root.tag.endswith("svg")
    back = json.loads(block)
    assert "</script>" in by_label(back, "legal act")["ann"][1][1]
    # Node and edge keys match the ids Graphviz wrote.
    for key in list(back["nodes"])[:3] + list(back["edges"])[:3]:
        assert f'id="{key}"' in svg


def test_no_source_when_not_asked():
    g, m = model()
    assert SCRIPT_ID not in render_dot_svg(m)
    assert embed("<svg a='1'><g/></svg>", {"x": 1}).startswith("<svg a='1'>\n<script")


def test_cli_interactive(tmp_path):
    out = tmp_path / "law.svg"
    env = dict(os.environ, PYTHONPATH=SRC)
    subprocess.run([sys.executable, "-m", "owl2uml.cli", FIX, "--interactive", "-o", str(out)],
                   check=True, env=env, capture_output=True)
    text = out.read_text(encoding="utf-8")
    assert SCRIPT_ID in text and "OwlUmlInteract.attach(document.documentElement" in text
    ET.fromstring(text.encode("utf-8"))
    out2 = tmp_path / "bare.svg"
    subprocess.run([sys.executable, "-m", "owl2uml.cli", FIX, "--no-source", "-o", str(out2)],
                   check=True, env=env, capture_output=True)
    bare = out2.read_text(encoding="utf-8")
    assert SCRIPT_ID not in bare and "OwlUmlInteract" not in bare
