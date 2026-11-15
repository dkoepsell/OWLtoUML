"""WS1.1: syntax detection, the OWL API loader, imports, loading by IRI."""
import functools
import http.server
import os
import subprocess
import sys
import threading
from pathlib import Path

import pytest
from rdflib import OWL, RDF, URIRef

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from owl2uml import tools  # noqa: E402
from owl2uml.cli import main as cli_main  # noqa: E402
from owl2uml.fetch import FetchError, fetch  # noqa: E402
from owl2uml.load import LoadError, annotate_model, load, sniff  # noqa: E402
from owl2uml.parse import parse_ontology  # noqa: E402
from owl2uml.postprocess import postprocess  # noqa: E402

FIX = ROOT / "tests" / "fixtures"
IMP = FIX / "imports"
PIZZA = ROOT / "examples" / "pizza.ttl"
needs_java = pytest.mark.skipif(tools.convert_cmd() is None, reason="needs Java + robot.jar")


@pytest.mark.parametrize("text,key", [
    (b"@prefix : <http://x/> .", "turtle"),
    (b"# comment\nPREFIX : <http://x/>", "turtle"),
    (b'<?xml version="1.0"?>\n<rdf:RDF xmlns:rdf="x">', "xml"),
    (b'<?xml version="1.0"?>\n<Ontology xmlns="http://www.w3.org/2002/07/owl#">', "owx"),
    (b"Prefix(:=<http://x/>)\nOntology(<http://x>)", "ofn"),
    (b"Prefix: : <http://x/>\nOntology: <http://x>", "omn"),
    (b"format-version: 1.2\nontology: x", "obo"),
    (b'{"@context": {}}', "json-ld"),
])
def test_sniff(text, key):
    assert sniff(text) == key


def test_closure_uses_local_directory_then_catalog():
    lo = load(str(IMP / "main.ttl"), allow_network=False)
    by = {i["iri"]: i for i in lo.imports}
    assert by["http://example.net/mid.owl"]["resolved_by"] == "local"
    assert by["http://example.net/mid.owl"]["version_iri"].endswith("2026-01-01/mid.owl")
    assert by["http://example.com/upper"]["resolved_by"] == "catalog"
    assert by["http://example.com/upper"]["depth"] == 2
    assert lo.origin["http://example.com/upper#Thing2"] == "http://example.com/upper"
    g = lo.merge()
    assert (URIRef("http://example.com/upper#Thing2"), RDF.type, OWL.Class) in g
    # only the main ontology header survives the merge
    assert set(g.subjects(RDF.type, OWL.Ontology)) == {URIRef("http://example.org/main")}


def test_import_modes():
    direct = load(str(IMP / "main.ttl"), imports="direct", allow_network=False)
    assert [i["iri"] for i in direct.imports] == ["http://example.net/mid.owl"]
    none = load(str(IMP / "main.ttl"), imports="none")
    assert none.imports == [] and len(none.imported) == 0


def test_missing_import_is_a_warning(tmp_path):
    f = tmp_path / "o.ttl"
    f.write_text("@prefix owl: <http://www.w3.org/2002/07/owl#> .\n"
                 "<http://x/o> a owl:Ontology ; owl:imports <http://x/gone.owl> .\n"
                 "<http://x/A> a owl:Class .\n")
    lo = load(str(f), allow_network=False)
    assert lo.imports[0]["resolved_by"] == "unresolved" and lo.warnings


def test_import_groups_in_the_key():
    lo = load(str(IMP / "main.ttl"), allow_network=False)
    m = parse_ontology("main", graph=lo.merge())
    annotate_model(m, lo)
    postprocess(m, prune=False)
    assert m.classes["http://example.com/upper#Thing2"].group == "upper"
    mid = m.groups["mid"]
    assert mid.upper and mid.version_iri.endswith("2026-01-01/mid.owl")


def test_unknown_syntax_names_the_line(tmp_path):
    f = tmp_path / "bad.ttl"
    f.write_text("@prefix : <http://x/> .\n\n:a :b :c ;; .\n:d :e\n")
    with pytest.raises(LoadError) as err:
        load(str(f))
    assert err.value.syntax == "Turtle"
    assert "Turtle syntax error" in str(err.value)


@needs_java
def test_manchester_with_imports_matches_turtle():
    lo = load(str(IMP / "animal.omn"), allow_network=False)
    assert lo.loader == "robot" and lo.syntax == "Manchester"
    assert {i["resolved_by"] for i in lo.imports} == {"local", "catalog"}
    assert (URIRef("http://example.org/main#Dog"), RDF.type, OWL.Class) in lo.merge()


@needs_java
def test_owl_api_error_has_syntax_and_line(tmp_path):
    f = tmp_path / "bad.omn"
    f.write_text("Prefix: : <http://x/>\nOntology: <http://x>\nClass: :A\n"
                 "    SubClassOf: :B and and\n")
    with pytest.raises(LoadError) as err:
        load(str(f))
    assert err.value.syntax == "Manchester" and err.value.line == 4


def _shape(m):
    return ({c.id for c in m.classes.values()},
            sorted((e.src, e.dst, e.kind, e.label) for e in m.edges))


@needs_java
@pytest.mark.parametrize("ext", ["owx", "omn", "ofn", "owl"])
def test_same_diagram_from_every_syntax(tmp_path, ext):
    """WS1 acceptance: the drawn model does not depend on the input syntax.
    (OBO is left out: OBO cannot carry every OWL axiom, so it is lossy.)"""
    out = tmp_path / f"pizza.{ext}"
    subprocess.run(tools.robot_cmd() + ["convert", "--input", str(PIZZA), "--output", str(out)],
                   check=True, capture_output=True, timeout=120)
    want = parse_ontology("p", graph=load(str(PIZZA)).merge())
    got = parse_ontology("p", graph=load(str(out)).merge())
    postprocess(want)
    postprocess(got)
    assert _shape(got) == _shape(want)


# --- loading by IRI -----------------------------------------------------------

@pytest.fixture()
def server():
    class Handler(http.server.SimpleHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_GET(self):
            if self.path == "/w3id/main":
                self.send_response(303)
                self.send_header("Location", "/main.ttl")
                self.end_headers()
                return
            super().do_GET()

        def guess_type(self, path):
            return "text/turtle" if str(path).endswith((".ttl", ".owl")) else super().guess_type(path)

    httpd = http.server.ThreadingHTTPServer(
        ("127.0.0.1", 0), functools.partial(Handler, directory=str(IMP)))
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()


def test_load_by_iri_follows_redirects(server):
    lo = load(server + "/w3id/main", allow_private=True)
    assert lo.ontology_iri == "http://example.org/main"
    assert lo.source.endswith("/w3id/main")
    # imports of a remote ontology have no local directory: they go to the network
    assert all(i["resolved_by"] in ("network", "unresolved") for i in lo.imports)


def test_fetch_refuses_private_addresses_for_the_server(server):
    with pytest.raises(FetchError, match="private or local"):
        fetch(server + "/main.ttl", max_bytes=2**20, timeout=5, allow_private=False)
    with pytest.raises(FetchError, match="only http"):
        fetch("file:///etc/passwd", max_bytes=2**20, timeout=5)


def test_fetch_size_cap(server):
    with pytest.raises(FetchError, match="larger than"):
        fetch(server + "/main.ttl", max_bytes=10, timeout=5)


def test_cli_iri(server, tmp_path, capsys):
    out = tmp_path / "o.svg"
    assert cli_main(["--iri", server + "/main.ttl", "-o", str(out), "--imports", "none"]) == 0
    assert out.exists()
    assert "loader: rdflib (Turtle syntax)" in capsys.readouterr().err


def test_cli_needs_exactly_one_source():
    with pytest.raises(SystemExit):
        cli_main([str(PIZZA), "--iri", "http://example.org/x"])
    assert os.path.exists(PIZZA)
