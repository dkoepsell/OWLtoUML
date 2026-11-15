"""WS2.1: aspect-ratio control."""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from owl2uml.aspect import parse_target, stagger_leaves, wrap_ranks  # noqa: E402
from owl2uml.dot import dot_available, render_dot_svg  # noqa: E402
from owl2uml.model import Edge, UModel  # noqa: E402


def wide_model(n=24):
    """One parent with n leaf children: a single very wide rank."""
    m = UModel()
    m.cls("P", "Parent")
    for i in range(n):
        m.cls(f"C{i}", f"child number {i}")
        m.edges.append(Edge(src=f"C{i}", dst="P", kind="generalization"))
    return m


def test_parse_target():
    assert parse_target("auto") == 1.4
    assert parse_target("16:9") == pytest.approx(16 / 9)
    assert parse_target("off") is None
    with pytest.raises(ValueError):
        parse_target("100")


def test_stagger_alternates_leaf_ranks():
    m = wide_model(6)
    mins = stagger_leaves(m, {cid: f"n{i}" for i, cid in enumerate(m.classes)})
    assert sorted(set(mins.values())) == [1, 2, 3]


def test_wrap_ranks_splits_wide_rows():
    pos = {f"n{i}": (float(i), 1.0) for i in range(10)}
    extra = wrap_ranks(pos, 4)
    assert len(extra) == 6            # rows of 4, 4, 2: the last 6 hang below


@pytest.mark.skipif(not dot_available(), reason="needs graphviz")
@pytest.mark.parametrize("target", [1.4, 1.0])
def test_wide_hierarchy_reaches_the_target_band(target):
    m = wide_model(12)
    svg = render_dot_svg(m, aspect=target)
    r = m.layout_report
    assert r["start"] > 3 and 0.5 <= r["ratio"] <= 2.0, r
    assert 'style="background-color:#f7f5ef"' in svg


@pytest.mark.skipif(not dot_available(), reason="needs graphviz")
def test_extreme_fan_out_improves():
    """24 siblings under one parent: wrapping cannot fully fix it (Graphviz
    reserves room for the long lines), but the figure gets far less wide."""
    m = wide_model(24)
    render_dot_svg(m, aspect=1.4)
    r = m.layout_report
    assert r["ratio"] < r["start"] / 5, r
