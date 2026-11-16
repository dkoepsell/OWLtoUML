"""Run a version diff end to end: parse both versions, compare, draw.

Shared by ``owl2uml diff`` (diff/cli.py), the web app and the CI action.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .. import coverage as cov_mod
from ..dot import render_dot_svg
from ..load import annotate_model
from ..parse import parse_ontology
from ..postprocess import postprocess
from ..source import build_source, manchester
from . import axioms as ax_layer
from .compare import compare
from .entities import entities
from .render import key_lines, mark_svg, restyler, union


@dataclass
class Result:
    data: dict                       # diff.json
    svg: str = ""
    model: object = None             # the union UModel that was drawn
    graphs: tuple = ()
    report: dict = field(default_factory=dict)


def _model(loaded, graph, name: str, profile, show_bfo: str):
    from ..profiles import load as load_profile
    m = parse_ontology(name, graph=graph)
    annotate_model(m, loaded)
    prof = load_profile(profile, graph) if profile and profile != "none" else None
    postprocess(m, prune=True, profile=prof, graph=graph, show_bfo=show_bfo)
    return m


def run(old, new, names=("old", "new"), engine: str = "auto", profile: str = "",
        scope: str = "1hop", pins: dict | None = None, label_width: int = 22,
        source: bool = True, screen: bool = False, show_bfo: str = "stub",
        draw: bool = True) -> Result:
    """``old`` and ``new`` are load.Loaded results."""
    go, gn = old.merge(), new.merge()
    if profile == "auto":
        from ..profiles import detect
        profile = ",".join(detect(gn))
    mo = _model(old, go, names[0], profile, show_bfo)
    mn = _model(new, gn, names[1], profile, show_bfo)
    cov = (cov_mod.build(go, mo), cov_mod.build(gn, mn))
    d = compare(go, gn, engine, coverage=cov)
    d["old"] = {"name": names[0], "iri": mo.ontology_iri}
    d["new"] = {"name": names[1], "iri": mn.ontology_iri}
    d["scope"] = scope
    d["labels"] = _labels(d, go, gn)
    res = Result(data=d, graphs=(go, gn))
    if not draw:
        return res
    u, cstat, estat = union(mo, mn, d, scope)
    u.render = dict(u.render, extra_dot=key_lines(d), restyle=restyler(u, cstat, estat))
    src = _source(go, gn, u, cstat, estat) if source else None
    svg = render_dot_svg(u, source=src, pins=pins, label_width=label_width, screen=screen)
    res.svg, res.model = mark_svg(svg, u, cstat, estat), u
    res.report = {"classes": len(u.classes), "edges": len(u.edges),
                  "changed_classes": sum(1 for s in cstat.values() if s),
                  "changed_edges": sum(1 for s in estat.values() if s)}
    return res


def _labels(d: dict, go, gn) -> dict:
    want = set(d["orphans"]) | set(d["inferred"]["unsatisfiable"]["new"]) | \
        set(d["inferred"]["unsatisfiable"]["removed"])
    for m in d["inferred"]["moved"]:
        want |= {m["iri"], *m["gained"], *m["lost"]}
    for a, b in d["inferred"]["added"] + d["inferred"]["removed"]:
        want |= {a, b}
    eo, en = entities(go), entities(gn)
    return {i: (en.get(i) or eo.get(i) or {}).get("label", i.rsplit("/", 1)[-1])
            for i in sorted(want)}


def _source(go, gn, u, cstat: dict, estat: dict) -> dict:
    """The new version's source panel, with the old version for removed
    classes and an OLD | NEW comparison for everything that changed."""
    sn, so = build_source(gn, u), build_source(go, u)
    for cid, st in cstat.items():
        if st == "removed" and cid in so["classes"]:
            sn["classes"][cid] = so["classes"][cid]
    io, inew = ax_layer.index(go), ax_layer.index(gn)
    to, tn = ax_layer.Texts(go), ax_layer.Texts(gn)

    def texts(ids, idx, t) -> str:
        return "\n".join(t(idx[i]) for i in ids if i in idx)

    nodes = {}
    for cid, st in cstat.items():
        if not st:
            continue
        old = manchester(so["classes"][cid]) if st != "added" and cid in so["classes"] else ""
        new = manchester(sn["classes"][cid]) if st != "removed" and cid in sn["classes"] else ""
        nodes[cid] = {"status": st, "old": old, "new": new}
    edges = {}
    names = {cid: c.name for cid, c in u.classes.items()}
    for i, e in enumerate(u.edges):
        st = estat.get(i, "")
        if not st:
            continue
        if e.kind == "inferred":
            line = f"{names.get(e.src)} SubClassOf {names.get(e.dst)}  # inferred"
            old, new = (line, "") if st == "inferred-removed" else ("", line)
        else:
            old = texts(getattr(e, "old_axioms", []), io, to)
            new = texts(e.axioms, inew, tn)
        edges[f"e{i}"] = {"status": st, "old": old, "new": new}
    sn["diff"] = {"nodes": nodes, "edges": edges}
    return sn
