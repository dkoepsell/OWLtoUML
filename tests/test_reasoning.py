"""Reasoner integration: inferred subclass edges, unsatisfiable classes."""
import html
import os
import shutil
import sys

import pytest

HERE = os.path.dirname(__file__)
sys.path.insert(0, os.path.join(HERE, "..", "src"))

from owl2uml.parse import load_graph, parse_ontology   # noqa: E402
from owl2uml.postprocess import postprocess            # noqa: E402
from owl2uml import reason                             # noqa: E402
from owl2uml.dot import render_dot_svg                 # noqa: E402

FIX = os.path.join(HERE, "fixtures", "reasoning.ttl")
K = "http://example.org/kitchen/"
needs_hermit = pytest.mark.skipif(not reason.hermit_available(),
                                  reason="owlready2 and Java needed for HermiT")


def run(engine):
    g = load_graph(FIX)
    m = parse_ontology(FIX, graph=g)
    inf = reason.classify(g, engine)
    reason.apply(m, inf)
    postprocess(m)
    inferred = {(e.src[len(K):], e.dst[len(K):]) for e in m.edges if e.kind == "inferred"}
    return m, inf, inferred


def test_none_engine_adds_nothing():
    m, inf, inferred = run("none")
    assert inf.engine == "none" and not inferred


def test_owlrl_rule_level_inference():
    m, inf, inferred = run("owlrl")
    assert not inf.error
    assert ("Snack", "Dish") in inferred          # via equivalence to Nibble
    assert ("Nibble", "Dish") not in inferred     # asserted, so not redrawn


@needs_hermit
def test_hermit_classifies_defined_class():
    m, inf, inferred = run("hermit")
    assert not inf.error
    assert ("CheesyDish", "ToppedDish") in inferred
    assert m.classes[K + "CheesyDish"].inferred_placed
    # direct only: CheesyDish -> Dish is implied via ToppedDish and asserted anyway
    assert ("CheesyDish", "Dish") not in inferred


@needs_hermit
def test_hermit_flags_unsatisfiable():
    m, inf, _ = run("hermit")
    assert K + "Cheeseburger" in inf.unsatisfiable
    assert m.classes[K + "Cheeseburger"].unsatisfiable


@needs_hermit
def test_inconsistent_ontology_is_reported(tmp_path):
    p = tmp_path / "bad.ttl"
    p.write_text(open(FIX).read() + "\n:b a :Cheese , :Meat .\n")
    g = load_graph(str(p))
    inf = reason.classify(g, "hermit")
    assert inf.inconsistent and not inf.subsumptions


def test_bad_engine_output_never_crashes(monkeypatch):
    def boom(_g):
        raise RuntimeError("no reasoner here")
    monkeypatch.setattr(reason, "_owlrl", boom)
    inf = reason.classify(load_graph(FIX), "owlrl")
    assert "no reasoner here" in inf.error


@pytest.mark.skipif(not shutil.which("dot"), reason="graphviz not installed")
def test_svg_has_inferred_hooks_and_style():
    m, inf, inferred = run("owlrl")
    svg = html.unescape(render_dot_svg(m))
    assert 'class="edge rel-inferred"' in svg
    assert "inferred-placed" in svg
    assert '<style class="o2u-style">' in svg


def test_auto_falls_back_to_owlrl_without_java(monkeypatch):
    monkeypatch.setattr(reason, "hermit_available", lambda: False)
    inf = reason.classify(load_graph(FIX), "auto")
    assert inf.engine == "owlrl" and not inf.error
