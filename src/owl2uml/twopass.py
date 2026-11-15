"""Compact two-pass Graphviz layout.

`dot` gives space to every line it lays out, including restriction and
association lines that do not decide where a class goes (constraint=false)
and their labels, so a richly axiomatized ontology spreads far wider than
its hierarchy needs. Instead:

1. lay out the *skeleton* (classes, the key, and the lines that rank them:
   subclass, definition, ⊥ groups, tree junctions) with `dot -Tjson`;
2. pin every node there, keep the skeleton's own line routes (shared
   arrowheads of generalization sets included), and let `neato -n2` route
   only the remaining lines around the fixed boxes.

Aspect fitting (aspect.py) measures the skeleton, which is also cheaper.
"""
from __future__ import annotations

import json
import re
import subprocess

_NODE = re.compile(r"^\s*(\w+) \[")
_EDGE_ID = re.compile(r'\bid="([^"]+)"')


def skeleton(text: str) -> str:
    """The DOT text without the lines that do not take part in ranking."""
    return "\n".join(ln for ln in text.splitlines()
                     if not (" -> " in ln and "constraint=false" in ln))


def _positions(dot_bin: str, env, skel: str, timeout: float):
    out = subprocess.run([dot_bin, "-Tjson"], input=skel.encode("utf-8"), env=env,
                         capture_output=True, timeout=timeout)
    if out.returncode != 0 and not out.stdout:
        return None
    data = json.loads(out.stdout)
    objs = data.get("objects", [])
    nodes = {o["name"]: o["pos"] for o in objs if "pos" in o}
    heights = {o["name"]: (float(o.get("width", 0)) * 72, float(o.get("height", 0)) * 72)
               for o in objs if "pos" in o}
    edges = {e["id"]: e["pos"] for e in data.get("edges", []) if "id" in e and "pos" in e}
    return nodes, edges, heights


_JUNCTION = re.compile(r"^j\d+_\d+$")
_ARROW = re.compile(r"^\s*(\w+) -> (\w+) \[")


def _key_below(nodes: dict, sizes: dict, moved: set) -> None:
    """With the classes pinned, the key goes under them, at the left."""
    if "legend" not in nodes or "legend" in moved:
        return
    pts = [(float(nodes[n].split(",")[0]), float(nodes[n].split(",")[1]), *sizes.get(n, (0, 0)))
           for n in moved if n in nodes]
    if not pts:
        return
    left = min(x - w / 2 for x, _y, w, _h in pts)
    bottom = min(y - h / 2 for _x, y, _w, h in pts)
    w, h = sizes.get("legend", (0, 0))
    nodes["legend"] = f"{left + w / 2:.2f},{bottom - 24 - h / 2:.2f}"
    moved.add("legend")


def _follow_junctions(text: str, nodes: dict, heights: dict, moved: set) -> None:
    """Tree junctions (aspect.sibling_trees) are not pinned with the classes:
    once their children have moved, put each one just above its row of
    children, straight under the parent, and route its lines afresh."""
    kids: dict[str, list[str]] = {}
    up: dict[str, str] = {}
    for ln in text.splitlines():
        m = _ARROW.match(ln)
        if m and "style=invis" not in ln:
            a, b = m.groups()
            if _JUNCTION.match(b):
                kids.setdefault(b, []).append(a)
            if _JUNCTION.match(a):
                up[a] = b

    def xy(n):
        x, y = nodes[n].split(",")[:2]
        return float(x), float(y)

    for j in sorted(kids, key=lambda j: [int(k) for k in j[1:].split("_")]):
        if j not in nodes or not (set(kids[j]) & moved):
            continue
        top = max(xy(c)[1] + heights.get(c, (0, 0))[1] / 2 for c in kids[j] if c in nodes)
        root = up.get(j)
        while root and _JUNCTION.match(root):
            root = up.get(root)
        x = xy(root)[0] if root in nodes else xy(j)[0]
        nodes[j] = f"{x:.2f},{top + 14:.2f}"
        moved.add(j)


def positioned(text: str, dot_bin: str, env, timeout: float = 45,
               pins: dict[str, tuple] | None = None) -> str | None:
    """The DOT text with every node pinned (pass 1) and the skeleton's line
    routes kept, ready for ``neato -n2`` in any output format; None when
    pass 1 fails. ``pins`` maps node ids to saved (x, y) positions
    (pinning.py); they replace dot's, and lines touching a pinned node are
    routed afresh."""
    pos = _positions(dot_bin, env, skeleton(text), timeout)
    if not pos:
        return None
    nodes, edges, heights = pos
    moved = set()
    for nid, (x, y) in (pins or {}).items():
        if nid in nodes:
            nodes[nid] = f"{x:.2f},{y:.2f}"
            moved.add(nid)
    if moved:
        _follow_junctions(text, nodes, heights, moved)
        _key_below(nodes, heights, moved)
    lines = []
    for ln in text.splitlines():
        m = _NODE.match(ln)
        if m and " -> " not in ln and m.group(1) in nodes:
            ln = ln.replace("[", f'[pos="{nodes[m.group(1)]}!", ', 1)
        elif " -> " in ln:
            e = _EDGE_ID.search(ln)
            ends = {t.strip() for t in ln.split("[", 1)[0].split("->")}
            if e and e.group(1) in edges and not (ends & moved):
                ln = ln.replace("[", f'[pos="{edges[e.group(1)]}", ', 1)
        lines.append(ln)
    return "\n".join(lines)


def run(program: str, args: list[str], text: str, env, fmt: str, timeout: float = 60,
        extra: list[str] | None = None) -> bytes:
    """Run a Graphviz program on DOT text, returning the output bytes."""
    out = subprocess.run([program, *args, f"-T{fmt}", *(extra or [])],
                         input=text.encode("utf-8"), env=env, capture_output=True,
                         timeout=timeout)
    if not out.stdout:
        raise RuntimeError(out.stderr.decode("utf-8", "replace") or f"no {fmt} output")
    return out.stdout
