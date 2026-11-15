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
    nodes = {o["name"]: o["pos"] for o in data.get("objects", []) if "pos" in o}
    edges = {e["id"]: e["pos"] for e in data.get("edges", []) if "id" in e and "pos" in e}
    return nodes, edges


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
    nodes, edges = pos
    moved = set()
    for nid, (x, y) in (pins or {}).items():
        if nid in nodes:
            nodes[nid] = f"{x:.2f},{y:.2f}"
            moved.add(nid)
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
