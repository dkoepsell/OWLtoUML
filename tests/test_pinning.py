"""WS2.3: saved layouts (sidecar and layout ontology)."""
import json
import shutil
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from owl2uml import pinning  # noqa: E402
from owl2uml.cli import main as cli_main  # noqa: E402
from owl2uml.dot import dot_available  # noqa: E402

FIX = ROOT / "tests" / "fixtures" / "constructs.ttl"
ROBOT = "http://example.org/c#Robot"
needs_dot = pytest.mark.skipif(not dot_available(), reason="needs graphviz")


def test_parse_validates():
    ok = pinning.parse({"http://x/A": {"x": 1, "y": "2.5"}})
    assert ok["http://x/A"] == {"x": 1.0, "y": 2.5, "pinned": True}
    for bad in ([], {"http://x/A": {"x": 1}}, {"http://x/A": {"x": "nan", "y": 0}}):
        with pytest.raises(ValueError):
            pinning.parse(bad)


def test_layout_ontology_round_trip(tmp_path):
    lay = {"http://x/A": {"x": 10.0, "y": 20.0, "pinned": True},
           "http://x/B": {"x": 5.5, "y": -3.0, "pinned": False}}
    g = pinning.layout_ontology(lay, "http://x/onto")
    path = tmp_path / "onto-layout.ttl"
    g.serialize(str(path), format="turtle")
    text = path.read_text()
    assert "owl:imports <http://x/onto>" in text
    assert pinning.load(str(path)) == lay


@needs_dot
def test_sidecar_pins_survive_regeneration(tmp_path):
    onto = tmp_path / "c.ttl"
    shutil.copy(FIX, onto)
    out = tmp_path / "c.svg"
    assert cli_main([str(onto), "-o", str(out), "--save-layout", "--coverage-out", "-"]) == 0
    side = tmp_path / "c.layout.json"
    lay = json.loads(side.read_text())
    assert ROBOT in lay and not lay[ROBOT]["pinned"]
    # pin Robot 400 points to the right of where it was drawn
    want = lay[ROBOT]["x"] + 400
    lay[ROBOT] = {"x": want, "y": lay[ROBOT]["y"], "pinned": True}
    side.write_text(json.dumps(lay))
    assert cli_main([str(onto), "-o", str(out), "--coverage-out", "-"]) == 0
    from owl2uml.parse import parse_ontology
    from owl2uml.postprocess import postprocess
    m = parse_ontology(str(onto))
    postprocess(m)
    nodes = {f"n{i}": cid for i, cid in enumerate(m.classes)}
    svg = out.read_text()
    # positions are compared in layout space (Graphviz renormalizes the SVG)
    from owl2uml.dot import render_dot_svg
    m2 = parse_ontology(str(onto))
    postprocess(m2)
    render_dot_svg(m2, aspect=1.4, pins=pinning.pins(json.loads(side.read_text())))
    got = pinning.to_layout_space(pinning.from_svg(svg, nodes), m2.layout_origin)
    assert abs(got[ROBOT]["x"] - want) < 0.5


@needs_dot
def test_layout_in_ontology_flag(tmp_path):
    onto = tmp_path / "c.ttl"
    shutil.copy(FIX, onto)
    assert cli_main([str(onto), "-o", str(tmp_path / "c.svg"), "--layout-in-ontology",
                     "--coverage-out", "-"]) == 0
    lay = pinning.load(str(tmp_path / "c-layout.ttl"))
    assert ROBOT in lay
    assert "c-layout" not in onto.read_text()        # the ontology itself is untouched


@needs_dot
def test_web_render_applies_pins():
    sys.path.insert(0, str(ROOT / "src" / "webapp"))
    from server import app
    client = app.test_client()
    first = client.post("/api/render", data={"file": (FIX.open("rb"), "c.ttl")}).get_json()
    assert not first.get("error")
    pins = {ROBOT: {"x": 5000, "y": 100, "pinned": True}}
    res = client.post("/api/render", data={"file": (FIX.open("rb"), "c.ttl"),
                                           "layout_json": json.dumps(pins)}).get_json()
    assert not res.get("error") and res["svg"] != first["svg"]
    bad = client.post("/api/render", data={"file": (FIX.open("rb"), "c.ttl"),
                                           "layout_json": "{nope"})
    assert bad.status_code == 400
