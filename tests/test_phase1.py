"""Defined classes, restrictions, groups, pruning and edge merging."""
import os
import re
import shutil
import sys

import pytest

HERE = os.path.dirname(__file__)
sys.path.insert(0, os.path.join(HERE, "..", "src"))

from owl2uml.parse import parse_ontology            # noqa: E402
from owl2uml.postprocess import postprocess         # noqa: E402
from owl2uml.dot import to_dot, render_dot_svg      # noqa: E402
from owl2uml.layout import layout                   # noqa: E402
from owl2uml.render import render_svg               # noqa: E402

FIX = os.path.join(HERE, "fixtures", "defined.ttl")
PIZZA = os.path.join(HERE, "..", "examples", "pizza.ttl")
K = "http://example.org/kitchen/"
UP = "http://purl.obolibrary.org/obo/UP_"


def edges(m, kind):
    return {(e.src.rsplit("/", 1)[-1], e.dst.rsplit("/", 1)[-1], e.label)
            for e in m.edges if e.kind == kind}


def model(prune=True):
    m = parse_ontology(FIX)
    postprocess(m, prune=prune)
    return m


def test_defined_class_is_connected():
    m = model()
    assert m.classes[K + "CheesyDish"].defined
    assert ("CheesyDish", "Dish", "") in edges(m, "definition")
    assert ("CheesyDish", "Cheese", "hasTopping some") in edges(m, "restriction")


def test_union_filler_and_datatype_restriction():
    m = model()
    r = edges(m, "restriction")
    assert ("MixedDish", "Cheese", "hasTopping some") in r
    assert ("MixedDish", "Meat", "hasTopping some") in r
    attrs = [(a.name, a.type) for a in m.classes[K + "LabelledDish"].attrs]
    assert ("hasLabel some", "string") in attrs


def test_named_equivalence():
    assert ("Nibble", "Snack", "≡") in edges(model(), "equivalent") or \
           ("Snack", "Nibble", "≡") in edges(model(), "equivalent")


def test_union_domain_expanded():
    a = edges(model(), "association")
    assert ("Dish", "UP_0000002", "servedTo") in a
    assert ("Topping", "UP_0000002", "servedTo") in a


def test_restriction_supersedes_matching_association():
    m = model()
    assert ("Dish", "Base", "hasBase some") in edges(m, "restriction")
    assert ("Dish", "Base", "hasBase") not in edges(m, "association")


def test_groups_and_upper_level():
    m = model(prune=False)
    assert m.groups["UP"].upper
    assert not m.groups["kitchen"].upper
    assert m.groups["kitchen"].color != m.groups["UP"].color


def test_pruning_keeps_backbone_drops_unused():
    m = model()
    assert UP + "0000004" not in m.classes          # never reached
    assert UP + "0000001" in m.classes              # ancestor of used classes
    assert UP + "0000003" not in m.classes
    assert UP + "0000004" in model(prune=False).classes


def test_single_namespace_keeps_classic_look():
    m = parse_ontology(PIZZA)
    report = postprocess(m)
    assert report["pruned"] == 0
    assert len(m.groups) == 1
    assert "legend" not in to_dot(m)


def test_merged_labels_use_dot_escape():
    src = to_dot(model(), xlabels=False)
    for line in src.splitlines():
        if "->" in line:
            assert line.count('"') % 2 == 0   # no raw newline inside a quoted label


def test_builtin_renderer_handles_new_kinds():
    m = model()
    w, h = layout(m)
    svg = render_svg(m, w, h)
    assert "stroke-dasharray" in svg and "&#171;defined&#187;" in svg


@pytest.mark.skipif(not shutil.which("dot"), reason="graphviz not installed")
def test_graphviz_render_has_hooks():
    import html
    svg = html.unescape(render_dot_svg(model()))   # Graphviz writes "-" as &#45;
    assert 'class="node uml-class grp-kitchen defined"' in svg
    assert 'class="edge rel-definition"' in svg
    assert re.search(r'id="legend"', svg)
