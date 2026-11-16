"""WS3: notation profiles, inverse and label hygiene."""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from owl2uml import coverage, twopass  # noqa: E402
from owl2uml.dot import dot_available, render_dot_svg, to_dot  # noqa: E402
from owl2uml.load import load  # noqa: E402
from owl2uml.parse import parse_ontology  # noqa: E402
from owl2uml.pinning import from_svg  # noqa: E402
from owl2uml.postprocess import merge_quantifiers, postprocess  # noqa: E402
from owl2uml.profiles import ProfileError, detect, label_count  # noqa: E402
from owl2uml.profiles import load as load_profile  # noqa: E402

FIX = ROOT / "tests" / "fixtures" / "hohfeld.ttl"
LOF = "https://w3id.org/lof/"


def model(profile=None, show_bfo="stub"):
    g = load(str(FIX)).graph
    m = parse_ontology(str(FIX), graph=g)
    report = postprocess(m, profile=load_profile(profile, g) if profile else None, graph=g,
                         show_bfo=show_bfo)
    return m, g, report


def names(m, e):
    return m.classes[e.src].name, m.classes[e.dst].name


# --------------------------------------------------------------- loading

def test_compose_and_extends(tmp_path):
    g = load(str(FIX)).graph
    p = load_profile("legal", g)
    assert p.names[:3] == ["core", "bfo", "legal"] and "ontology" in p.names
    assert p.bfo_stub and p.motifs and p.aliases
    # an ontology's own o2u:style comes last, so it wins
    assert p.relation_styles[-1]["source"] == "ontology"
    bad = tmp_path / "bad.yaml"
    bad.write_text("profile: x\nrelation_styles:\n  - match: {property: p}\n    style: zigzag\n")
    with pytest.raises(ProfileError):
        load_profile(str(bad))
    with pytest.raises(ProfileError):
        load_profile("no-such-profile")


def test_json_profile_file(tmp_path):
    f = tmp_path / "mine.json"
    f.write_text('{"profile": "mine", "extends": "core", "badges": {"hide_class_badge": true}}')
    p = load_profile(str(f))
    assert p.names == ["core", "mine"] and p.badges["hide_class_badge"]


def test_detect():
    assert detect(load(str(FIX)).graph) == ["bfo", "legal"]


# --------------------------------------------------------------- WS3.5 hygiene

def test_inverse_without_named_inverse_reverses_the_arrow():
    m, _, _ = model()
    e = next(e for e in m.edges if "confers" in e.label)
    assert names(m, e) == ("legal act", "legal position")
    assert not any("inverse" in e.label for e in m.edges)


def test_exists_forall_merge():
    assert merge_quantifiers("p some\np only\nq some") == "p ∃∀\nq some"
    m, _, _ = model()
    e = next(e for e in m.edges if names(m, e) == ("claim", "duty"))
    assert "∃∀" in e.label and "some" not in e.label


def test_label_width_wraps_line_labels():
    m, _, _ = model()
    e = next(e for e in m.edges if "gives rise to" in e.label)
    e.label = "a rather long property name indeed some"
    assert "a rather long property\\nname indeed some" in to_dot(m, label_width=22)
    assert "a rather long property name indeed some" in to_dot(m, label_width=0)


# --------------------------------------------------------------- styles

def test_symmetric_pair_is_one_undirected_line():
    m, _, _ = model("legal")
    pairs = [e for e in m.edges if e.style == "symmetric_pair"]
    assert len(pairs) == 4                     # one per correlative pair, not eight
    assert all(len(e.axioms) >= 4 for e in pairs)   # both directions, some and only
    assert "dir=none" in to_dot(m)


def test_inverse_merged_and_compartment_and_hidden():
    m, _, report = model("legal")
    e = next(e for e in m.edges if e.style == "inverse_merged")
    assert "gives rise to" in e.label and "arises from" in e.tail_label
    pos = m.classes[LOF + "ODP003_0001000"]
    assert any(a.label().startswith("held by") and a.type == "legal person" for a in pos.attrs)
    assert not any("on behalf of" in x.label for x in m.edges)      # o2u:style hidden
    assert report["profile"]["hidden"] == 1


def test_label_count_drops_at_least_40_percent():
    plain, _, _ = model()
    styled, _, _ = model("bfo,legal")
    assert label_count(styled) <= 0.6 * label_count(plain)


def test_no_axiom_lost():
    """Every collapsed axiom stays drawn or in the source panel."""
    m0, g, _ = model()
    m1, _, _ = model("bfo,legal")
    before = {r["id"]: r["status"] for r in coverage.build(g, m0)["axioms"]}
    after = {r["id"]: r["status"] for r in coverage.build(g, m1)["axioms"]}
    assert [i for i, s in after.items() if s == "dropped" and before[i] != "dropped"] == []


def test_bfo_stub_and_full():
    m, _, report = model("bfo")
    assert "http://purl.obolibrary.org/obo/BFO_0000020" not in m.classes
    e = next(e for e in m.edges if e.style == "collapsed" and
             m.classes[e.src].name == "legal position")
    assert "specifically dependent continuant" in e.note
    full, _, _ = model("bfo", show_bfo="full")
    assert "http://purl.obolibrary.org/obo/BFO_0000020" in full.classes


def test_classes_coloured_by_order_and_key_rows():
    m, _, _ = model("legal")
    assert m.classes[LOF + "ODP003_0001001"].color != m.classes[LOF + "ODP003_0001005"].color
    dot = to_dot(m)
    assert "Notation" in dot and "correlative of" in dot


# --------------------------------------------------------------- layout

pytestmark_dot = pytest.mark.skipif(not dot_available(), reason="needs graphviz")


def _positions(m, svg):
    nodes = {f"n{i}": cid for i, cid in enumerate(m.classes)}
    return {cid: (p["x"], p["y"]) for cid, p in from_svg(svg, nodes).items()}


@pytestmark_dot
def test_hohfeld_square_and_bands():
    m, _, _ = model("bfo,legal")
    pos = _positions(m, render_dot_svg(m))
    c = {n: pos[LOF + f"ODP003_000100{n}"] for n in range(1, 9)}
    # rows: claim duty power liability / liberty no-claim immunity disability
    for top, bottom in ((1, 3), (2, 4), (5, 7), (6, 8)):
        assert abs(c[top][0] - c[bottom][0]) < 10          # same column
        assert c[top][1] > c[bottom][1]                    # layout space: y up
    for a, b in ((1, 2), (3, 4), (5, 6), (7, 8)):
        assert abs(c[a][1] - c[b][1]) < 1 and c[a][0] < c[b][0]   # correlatives side by side
    # continuants above occurrents
    assert pos[LOF + "ODP003_0001000"][1] > pos[LOF + "ODP001_0001000"][1]


@pytestmark_dot
def test_pinned_classes_carry_their_tree_junctions():
    """Print figures pin the classes where the screen had them; the tree
    junctions must follow, or trunks end below their children."""
    text = """digraph G { graph [rankdir=BT];
  p [shape=box]; a [shape=box]; b [shape=box];
  j0_0 [shape=point];
  a -> j0_0 [id="e0"];
  b -> j0_0 [id="e1"];
  j0_0 -> p [id="t0_0"];
}"""
    from owl2uml.tools import graphviz
    dot, env = graphviz("dot")
    pins = {"p": (100.0, 500.0), "a": (40.0, 100.0), "b": (160.0, 100.0)}
    out = twopass.positioned(text, dot, env, pins=pins)
    j = next(ln for ln in out.splitlines() if ln.strip().startswith("j0_0 ["))
    x, y = (float(v) for v in j.split('pos="', 1)[1].split("!", 1)[0].split(","))
    assert x == 100.0 and 100 < y < 500


def test_motif_rows_missing_from_a_partial_figure():
    """A module view or diff may show none of a motif's classes: no empty
    rank=same statement (a Graphviz syntax error)."""
    m, _, _ = model("legal")
    m.classes = {k: v for k, v in m.classes.items() if "ODP003_000100" not in k}
    m.edges = [e for e in m.edges if e.src in m.classes and e.dst in m.classes]
    assert "rank=same; ;" not in to_dot(m)
