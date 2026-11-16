"""One diagram of what changed between two versions (spec WS4.2).

The two parsed models are merged into a union model; every class and line is
marked added, removed, changed or unchanged, and the reasoner's new or lost
direct superclasses are added as orange lines with a + or − badge. The
colours are applied to Graphviz's SVG by class names and an embedded
stylesheet, so the ordinary renderer draws the figure.
"""
from __future__ import annotations

import copy
import re

from ..legend import INFERRED_COLOR
from ..model import Edge, UModel

ADDED, REMOVED, CHANGED = "#2e8b57", "#c0392b", "#d4a017"
SCOPES = ("changed", "1hop", "all")

# status -> (colour, pen width, dashed)
LOOK = {"added": (ADDED, 2.5, False), "changed": (CHANGED, 2.5, False),
        "removed": (REMOVED, 1.6, True), "inferred-added": (INFERRED_COLOR, 2.2, False),
        "inferred-removed": (INFERRED_COLOR, 2.2, True)}


def _key(e: Edge) -> tuple:
    return (e.src, e.dst, e.kind, tuple(sorted(e.props)) if e.props else e.label)


def _index(m: UModel) -> dict[tuple, list[Edge]]:
    out: dict[tuple, list[Edge]] = {}
    for e in m.edges:
        if e.kind != "inferred":
            out.setdefault(_key(e), []).append(e)
    return out


def union(old: UModel, new: UModel, d: dict, scope: str = "1hop") -> tuple[UModel, dict, dict]:
    """The union model, plus {class id: status} and {edge index: status}."""
    if scope not in SCOPES:
        raise ValueError(f"--diff-scope must be one of {', '.join(SCOPES)}")
    u = copy.deepcopy(new)
    u.edges = []
    for g, grp in old.groups.items():
        u.groups.setdefault(g, grp)
    cstat: dict[str, str] = {}
    touched = {r["iri"] for r in d["entities"]["renamed"]} | \
        {r["iri"] for r in d["entities"]["deprecated"]} | \
        {r["subject"] for side in ("added", "removed") for r in d["axioms"][side]} | \
        set(d["inferred"]["unsatisfiable"]["added"]) | \
        set(d["inferred"]["unsatisfiable"]["removed"])
    for cid, c in old.classes.items():
        if cid not in u.classes:
            u.classes[cid] = copy.deepcopy(c)
            cstat[cid] = "removed"
    for cid, c in new.classes.items():
        cstat.setdefault(cid, "added" if cid not in old.classes else
                         "changed" if cid in touched else "")
    renamed = {r["iri"]: r["old"] for r in d["entities"]["renamed"]}
    for cid, was in renamed.items():
        if cid in u.classes:
            u.classes[cid].name = f"{u.classes[cid].name} (was {was})"

    estat: list[str] = []
    io, inew = _index(old), _index(new)
    for k, es in inew.items():
        e = copy.deepcopy(es[0])
        e.axioms = sorted({a for x in es for a in x.axioms})
        prev = io.get(k)
        e.old_axioms = sorted({a for x in prev or [] for a in x.axioms})
        st = "added" if not prev else \
            "changed" if set(e.axioms) != set(e.old_axioms) or e.label != prev[0].label else ""
        e.note = "; ".join(filter(None, [e.note, f"was: {prev[0].label}" if st == "changed"
                                          and prev[0].label != e.label else ""]))
        u.edges.append(e)
        estat.append(st)
    for k, es in io.items():
        if k not in inew:
            e = copy.deepcopy(es[0])
            e.old_axioms, e.axioms = sorted({a for x in es for a in x.axioms}), []
            u.edges.append(e)
            estat.append("removed")
    for side, badge in (("added", "+"), ("removed", "−")):
        for a, b in d["inferred"][side]:
            if a in u.classes and b in u.classes:
                u.edges.append(Edge(src=a, dst=b, kind="inferred", label=badge,
                                    note=f"{'newly' if badge == '+' else 'no longer'} inferred"))
                estat.append(f"inferred-{side}")
    for cid in d["inferred"]["unsatisfiable"]["new"]:
        if cid in u.classes:
            u.classes[cid].unsatisfiable = True
    return _scope(u, cstat, estat, scope)


def _scope(u: UModel, cstat: dict, estat: list[str], scope: str):
    core = {c for c, s in cstat.items() if s}
    for e, s in zip(u.edges, estat):
        if s:
            core |= {e.src, e.dst}
    keep = set(u.classes) if scope == "all" else set(core)
    if scope == "1hop":
        for e in u.edges:
            if e.src in core:
                keep.add(e.dst)
            if e.dst in core:
                keep.add(e.src)
        for cid in keep - core:
            u.classes[cid].context = True
    edges, stats = [], []
    for e, s in zip(u.edges, estat):
        if e.src in keep and e.dst in keep and (scope == "all" or s or
                                                 e.src in core or e.dst in core):
            edges.append(e)
            stats.append(s)
    u.classes = {k: v for k, v in u.classes.items() if k in keep}
    u.edges = edges
    return u, {k: v for k, v in cstat.items() if k in keep}, dict(enumerate(stats))


def restyler(u: UModel, cstat: dict, estat: dict):
    """A to_dot hook that colours each class and line by its diff status in
    the DOT itself, so every export (SVG, PNG, PDF, TikZ) shows it."""
    by_node = {f"n{i}": cstat.get(cid, "") for i, cid in enumerate(u.classes)}

    def node(line: str, st: str) -> str:
        ink, pen, dashed = LOOK[st]
        if "label=<" in line:       # an HTML table: its outer border
            extra = ' style="dashed"' if dashed else ""
            return line.replace('border="1" color="#A0A0A0"',
                                f'border="{round(pen)}" color="{ink}"{extra}', 1)
        return re.sub(r'(?<![a-z])color="[^"]*"', f'color="{ink}"', line, count=1)

    def edge(line: str, st: str) -> str:
        ink, pen, dashed = LOOK[st]
        line = re.sub(r'(?<![a-z])color="[^"]*"', f'color="{ink}"', line, count=1)
        line = re.sub(r'fontcolor="[^"]*"', f'fontcolor="{ink}"', line)
        line = re.sub(r"penwidth=[0-9.]+, ", "", line)
        line = line.replace("style=dashed, ", "").replace(", style=dashed", "")
        return line.replace("[", f"[penwidth={pen}, " + ("style=dashed, " if dashed else ""), 1)

    def restyle(lines: list[str]) -> list[str]:
        out = []
        for ln in lines:
            m = re.match(r"  (n\d+) \[", ln)
            e = re.search(r'id="e(\d+)"', ln) if " -> " in ln else None
            if m and by_node.get(m.group(1)):
                ln = node(ln, by_node[m.group(1)])
            elif e and estat.get(int(e.group(1))):
                ln = edge(ln, estat[int(e.group(1))])
            out.append(ln)
        return out
    return restyle


def mark_svg(svg: str, u: UModel, cstat: dict, estat: dict) -> str:
    """Add each class's and line's diff status to its SVG class (for the viewer)."""
    nid = {f"n{i}": cid for i, cid in enumerate(u.classes)}

    def mark(m: re.Match) -> str:
        gid = m.group(1)
        st = cstat.get(nid[gid], "") if gid in nid else \
            estat.get(int(gid[1:]), "") if gid.startswith("e") and gid[1:].isdigit() else ""
        return m.group(0) + (f"diff-{st} " if st else "")

    return re.sub(r'<g id="([ne]\d+)" class="', mark, svg)


def key_lines(d: dict) -> list[str]:
    """A DOT node with the diff's key and counts (the summary header)."""
    s = d["summary"]
    rows = [("Added", ADDED, f"{s['added']} entities, {s['axioms_added']} axioms"),
            ("Removed", REMOVED, f"{s['removed']} entities, {s['axioms_removed']} axioms"),
            ("Changed", CHANGED, f"{s['renamed']} renamed, {s['deprecated']} deprecated"),
            ("Inferred +/−", INFERRED_COLOR, f"+{s['inferred_added']} / −{s['inferred_removed']}"
             f", {s['moved']} moved, {s['unsatisfiable_new']} newly unsatisfiable")]
    cells = "".join(
        f'<tr><td bgcolor="{c}" width="14" height="10" fixedsize="true"></td>'
        f'<td align="left"><b>{t}</b></td><td align="left">{_h(v)}</td></tr>'
        for t, c, v in rows)
    moved = d["inferred"]["moved"][:8]
    if moved:
        names = ", ".join(_h(d.get("labels", {}).get(m["iri"], m["iri"].rsplit("/", 1)[-1]))
                          for m in moved)
        more = f" … +{len(d['inferred']['moved']) - 8}" if len(d["inferred"]["moved"]) > 8 else ""
        cells += f'<tr><td></td><td align="left" colspan="2">Moved: {names}{more}</td></tr>'
    title = _h(f"{d.get('old', {}).get('name', 'old')} → {d.get('new', {}).get('name', 'new')}")
    label = (f'<table border="1" color="#a0a0a0" cellborder="0" cellspacing="2" cellpadding="2" '
             f'bgcolor="#ffffff"><tr><td colspan="3"><b>{title}</b></td></tr>{cells}</table>')
    return [f'  diffkey [shape=plaintext, label=<{label}>, fontsize=10, id="diffkey", '
            f'class="o2u-diff-key"];']


def _h(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
