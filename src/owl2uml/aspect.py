"""Aspect-ratio control for Graphviz `dot` layouts (spec WS2.1).

Class hierarchies come out wide and shallow: many siblings on one rank. To
reach a target width/height ratio (the browser window's, or ``--aspect``),
these steps run in order, each only while the drawing is still too far off:

1. stagger leaves: subclasses without subclasses of their own, under a
   parent with many of them, alternate between 1..3 ranks below it (what
   Graphviz's ``unflatten -l 3`` does; unflatten itself staggers the wrong
   end of our bottom-to-top edges, so it is done here);
2. wrap wide ranks: a rank holding more than ``max_rank_width`` classes is
   split into rows with invisible edges;
3. turn the layout sideways (rankdir RL) when that is closer to the target,
   e.g. for a drawing that is far too tall.

``fit`` measures each candidate with ``dot -Tplain`` and returns the DOT
options of the best one plus a report of what it did.
"""
from __future__ import annotations

import math
import subprocess
from dataclasses import dataclass, field

from .model import HIERARCHY_KINDS, UModel

DEFAULT_TARGET = 1.4
TOLERANCE = 1.15        # accept ratios within target/1.15 .. target*1.15
STAGGER = 3
MIN_WRAP = 6             # never wrap ranks into rows narrower than this
LEAF_MIN = 4             # stagger only parents with at least this many leaf children


@dataclass
class LayoutOptions:
    """Extra DOT settings to_dot applies (see dot.to_dot)."""
    minlen: dict[int, int] = field(default_factory=dict)   # edge index -> minlen
    invisible: list[tuple[str, str]] = field(default_factory=list)  # (lower, upper) node ids
    # UML tree-style generalizations: (parent node id, [[edge index, ...] per row]).
    # Each row of children joins a junction point; junctions chain to the parent.
    trees: list[tuple[str, list[list[int]]]] = field(default_factory=list)
    rankdir: str = "BT"
    nodesep: float = 0.3
    ranksep: float = 0.55


def parse_target(value) -> float | None:
    """'auto' -> 1.4; '16:9' or '1.78' -> 1.78; None/'off' -> None."""
    if value in (None, "", "off", "none"):
        return None
    if value == "auto":
        return DEFAULT_TARGET
    s = str(value)
    if ":" in s:
        a, b = s.split(":", 1)
        r = float(a) / float(b)
    else:
        r = float(s)
    if not 0.1 <= r <= 10:
        raise ValueError(f"aspect ratio {s} is out of range (0.1 to 10)")
    return r


BAND = (0.5, 2.0)        # what a figure (print, export) keeps
SCREEN_BAND = (0.5, 3.0)  # on screen: a wide window may be filled


def _ok(ratio: float, target: float, band: tuple = BAND) -> bool:
    """Not too far from the target, and inside the band."""
    return max(band[0], target / TOLERANCE) <= ratio <= min(band[1], target * TOLERANCE)


def _miss(ratio: float, target: float) -> float:
    return abs(math.log(ratio / target))


def plain_layout(dot_bin: str, env, text: str, timeout: float = 45):
    """(width, height, {node id: (x, y)}) from `dot -Tplain`, in inches."""
    out = subprocess.run([dot_bin, "-Tplain"], input=text.encode("utf-8"), env=env,
                         capture_output=True, timeout=timeout).stdout.decode("utf-8", "replace")
    w = h = 0.0
    pos = {}
    for line in out.splitlines():
        parts = line.split()
        if parts[:1] == ["graph"] and len(parts) >= 4:
            w, h = float(parts[2]), float(parts[3])
        elif parts[:1] == ["node"] and len(parts) >= 4:
            pos[parts[1].strip('"')] = (float(parts[2]), float(parts[3]))
    return w, h, pos


def stagger_leaves(m: UModel, ids: dict[str, str]) -> dict[int, int]:
    """minlen per hierarchy-edge index, alternating 1..STAGGER for leaf children."""
    has_child = {e.dst for e in m.edges if e.kind in HIERARCHY_KINDS}
    by_parent: dict[str, list[int]] = {}
    for i, e in enumerate(m.edges):
        if e.kind in HIERARCHY_KINDS and e.src not in has_child and e.src in ids and e.dst in ids:
            by_parent.setdefault(e.dst, []).append(i)
    out = {}
    for _parent, idx in by_parent.items():
        if len(idx) < LEAF_MIN:
            continue
        idx.sort(key=lambda i: m.classes[m.edges[i].src].name.lower())
        for k, i in enumerate(idx):
            out[i] = 1 + k % STAGGER
    return out


def sibling_trees(m: UModel, ids: dict[str, str], width: int) -> list:
    """Rows of at most ``width`` leaf children for every parent with more."""
    has_child = {e.dst for e in m.edges if e.kind in HIERARCHY_KINDS}
    fixed = set(m.render.get("fixed") or ())   # a profile motif keeps its places
    by_parent: dict[str, list[int]] = {}
    for i, e in enumerate(m.edges):
        if e.kind == "generalization" and not e.genset and e.src not in has_child \
                and e.src not in fixed \
                and e.src in ids and e.dst in ids and e.src != e.dst:
            by_parent.setdefault(e.dst, []).append(i)
    out = []
    for parent, idx in sorted(by_parent.items()):
        if len(idx) <= width:
            continue
        idx.sort(key=lambda i: m.classes[m.edges[i].src].name.lower())
        out.append((ids[parent], [idx[k:k + width] for k in range(0, len(idx), width)]))
    return out


def wrap_ranks(pos: dict[str, tuple], max_width: int,
               fixed: frozenset = frozenset()) -> list[tuple[str, str]]:
    """Invisible (lower, upper) edges splitting every rank wider than max_width."""
    ranks: dict[float, list[tuple[float, str]]] = {}
    for nid, (x, y) in pos.items():
        if nid.startswith("n") and nid not in fixed:
            ranks.setdefault(round(y, 1), []).append((x, nid))
    edges = []
    for row in ranks.values():
        if len(row) <= max_width:
            continue
        row.sort()
        chunks = [row[i:i + max_width] for i in range(0, len(row), max_width)]
        for upper, lower in zip(chunks, chunks[1:]):
            for j, (_x, nid) in enumerate(lower):
                edges.append((nid, upper[min(j, len(upper) - 1)][1]))
    return edges


def fit(m: UModel, render_text, dot_bin: str, env, target: float,
        max_rank_width: int = 12, band: tuple = BAND) -> tuple[LayoutOptions, dict]:
    """Choose layout options for ``target`` width/height.

    ``render_text(opts) -> str`` produces the DOT for a set of options.
    """
    tried = []

    def attempt(opts: LayoutOptions, steps: list[str]):
        w, h, pos = plain_layout(dot_bin, env, render_text(opts))
        ratio = w / h if h else 1.0
        tried.append((opts, list(steps), ratio))
        return ratio, pos

    opts, steps = LayoutOptions(), []
    ratio, pos = attempt(opts, steps)
    start = ratio
    if not _ok(ratio, target, band) and ratio > target:
        ids = {cid: f"n{i}" for i, cid in enumerate(m.classes)}
        width = max_rank_width
        while not _ok(ratio, target, band) and ratio > target and width >= 2:
            trees = sibling_trees(m, ids, width)
            if trees:
                opts = LayoutOptions(trees=trees)
                steps = [f"sibling rows of {width}"]
                ratio, pos = attempt(opts, steps)
            width = width - 1 if width <= 4 else int(width * 0.7)
        # Wrapping moves classes off their hierarchy level, so it is used
        # sparingly: never below MIN_WRAP classes per row.
        width = max_rank_width
        while not _ok(ratio, target, band) and ratio > target and width >= MIN_WRAP:
            extra = wrap_ranks(pos, width, frozenset(
                f"n{i}" for i, c in enumerate(m.classes) if c in set(m.render.get("fixed") or ())))
            if extra:
                opts = LayoutOptions(trees=opts.trees, invisible=opts.invisible + extra)
                steps = steps + [f"wrapped ranks wider than {width}"]
                ratio, pos = attempt(opts, steps)
            width = MIN_WRAP if width > MIN_WRAP and int(width * 0.7) < MIN_WRAP \
                else int(width * 0.7)
    if ratio < 0.5:
        # far too tall: a sideways layout. Never for a wide one -- class
        # hierarchies read top-down, and wrapping has already done its best.
        attempt(LayoutOptions(rankdir="RL"), ["laid out sideways"])
    # The first acceptable layout is the least changed one; otherwise the
    # closest to the target.
    good = [t for t in tried if _ok(t[2], target, band)]
    opts, steps, ratio = good[0] if good else min(
        tried, key=lambda t: (not band[0] <= t[2] <= band[1], _miss(t[2], target)))
    report = {"target": round(target, 2), "start": round(start, 2), "ratio": round(ratio, 2),
              "steps": steps, "within_band": band[0] <= ratio <= band[1]}
    return opts, report
