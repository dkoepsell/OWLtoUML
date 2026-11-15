"""WS2.4 exports and WS2.5 print checks."""
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from owl2uml.cli import main as cli_main  # noqa: E402
from owl2uml.dot import dot_available, render_dot_svg  # noqa: E402
from owl2uml.export import FORMATS, export, layout_json, static_svg  # noqa: E402
from owl2uml.export.text import restrictions  # noqa: E402
from owl2uml.parse import load_graph, parse_ontology  # noqa: E402
from owl2uml.postprocess import postprocess  # noqa: E402
from owl2uml.printcheck import check  # noqa: E402

FIX = ROOT / "tests" / "fixtures" / "constructs.ttl"
pytestmark = pytest.mark.skipif(not dot_available(), reason="needs graphviz")


@pytest.fixture(scope="module")
def drawn():
    g = load_graph(str(FIX))
    m = parse_ontology("x", graph=g)
    postprocess(m)
    svg = render_dot_svg(m)
    return m, svg, g


def test_every_format(drawn):
    m, svg, g = drawn
    for fmt in FORMATS:
        x = export(m, fmt, svg=svg, graph=g)
        assert x.data, fmt
    assert export(m, "pdf", svg=svg).data.startswith(b"%PDF")
    assert export(m, "png", svg=svg).data.startswith(b"\x89PNG")


def test_png_dpi_scales(drawn):
    m, svg, _ = drawn
    small = export(m, "png", svg=svg, dpi=72).data
    big = export(m, "png", svg=svg, dpi=144).data
    assert len(big) > len(small)


def test_static_svg_drops_script_and_source():
    svg = '<svg><script>x()</script><g id="n0"/><script id="o2u-source" type="application/json">{}</script></svg>'
    out = static_svg(svg)
    assert "<script" not in out and 'id="n0"' in out


def test_tikz_document(drawn):
    m, svg, _ = drawn
    tex = export(m, "tikz", svg=svg).data.decode()
    assert tex.count(r"\begin{tikzpicture}") == 1 and r"\end{document}" in tex
    assert r"\tikzset{" in tex and "o2u disjoint" in tex
    assert r"$\sqcup$" in tex and r"\node[o2u anon]" in tex
    assert tex.count("{") == tex.count("}")       # balanced braces


def test_graphml_is_valid_xml_with_positions(drawn):
    m, svg, _ = drawn
    root = ET.fromstring(export(m, "graphml", svg=svg).data)
    ns = {"g": "http://graphml.graphdrawing.org/xmlns", "y": "http://www.yworks.com/xml/graphml"}
    nodes = root.findall(".//g:node", ns)
    assert len(nodes) == len(m.classes)
    assert root.find(".//y:Geometry", ns).get("x") is not None


def test_plantuml_and_ontopuml(drawn):
    m, svg, g = drawn
    puml = export(m, "plantuml", svg=svg).data.decode()
    assert puml.startswith("@startuml") and puml.rstrip().endswith("@enduml")
    assert "--|>" in puml and 'circle "⊔"' in puml and "<<deprecated>>" in puml
    nowl = export(m, "ontopuml", svg=svg, graph=g).data.decode()
    assert "!include https://raw.githubusercontent.com/iofoundry/ontopuml" in nowl
    assert "someCard(" in nowl and "union(" in nowl and "disjoint(" in nowl
    assert "subClass(" in nowl and "oneOf(" in nowl


def test_mermaid_warns_on_loss(drawn):
    m, svg, _ = drawn
    x = export(m, "mermaid", svg=svg)
    assert x.data.decode().startswith("classDiagram")
    assert any("disjoint" in w for w in x.warnings)


def test_restriction_label_parsing():
    parts = restrictions("knows ↔ only ¬\nhasParent [2]")
    assert parts[0] == {"prop": "knows", "q": "only", "neg": True, "mult": ""}
    assert parts[1]["prop"] == "hasParent" and parts[1]["mult"] == "2"


def test_print_check(drawn):
    m, svg, _ = drawn
    wide = check(svg, layout_json(m), 17, page_width=2.0)
    assert any("pt at 2 in" in w for w in wide["warnings"])
    roomy = check(svg, layout_json(m), 17, page_width=100.0)
    assert not any("smallest text" in w for w in roomy["warnings"])


def test_cli_export_and_strict(tmp_path):
    out = tmp_path / "c.svg"
    assert cli_main([str(FIX), "-o", str(out), "--export", "pdf,mermaid",
                     "--coverage-out", "-"]) == 0
    assert (tmp_path / "c.pdf").exists() and (tmp_path / "c.mmd").exists()
    assert cli_main([str(FIX), "-o", str(out), "--export", "pdf", "--strict",
                     "--page-width", "1", "--coverage-out", "-"]) == 1
    assert cli_main([str(FIX), "-o", str(out), "--export", "nope",
                     "--coverage-out", "-"]) == 1


def test_web_export():
    sys.path.insert(0, str(ROOT / "src" / "webapp"))
    from server import app
    c = app.test_client()
    r = c.post("/api/render", data={"file": (FIX.open("rb"), "c.ttl"), "fmt": "pdf"})
    assert r.status_code == 200 and r.data.startswith(b"%PDF")
    assert r.headers["X-Extension"] == "pdf"
    bad = c.post("/api/render", data={"file": (FIX.open("rb"), "c.ttl"), "fmt": "doc"})
    assert bad.status_code == 400
