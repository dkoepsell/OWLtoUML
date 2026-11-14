"""Flow view: a process ontology drawn as a process.

The class view shows what kind of thing each class is. For an ontology of
processes it does not show the order in which they happen. This module reads
the same axioms a second way:

* a restriction on a *sequence* relation (``'issue PO' SubClassOf
  'immediately preceded by' some 'manager approval'``) becomes an arrow from
  one step to the next; on a non-immediate relation (``preceded by``) it
  becomes a *requirement*, drawn dashed: something that must come first;
* a restriction on a *lane* relation (``realizes some 'approver role'``)
  puts the step in that role's swimlane;
* a defined subclass of a step that adds a condition and its own sequence
  restriction (``'PO above threshold' EquivalentTo 'issue PO' and ('for
  amount' some decimal[> 10000])``, SubClassOf ``'preceded by' some
  'director approval'``) becomes a conditional requirement, labelled with
  the condition.

Instances of the steps linked by the immediate sequence relations (an event
log written as RDF) give the flow *as practiced*: how many cases took each
path, and the paths no axiom allows. SHACL shapes run over those instances
turn the open-world axioms into closed-world checks; each violation is
pinned to the step its focus node instantiates.

Which relations count as sequence, lane and case is configurable (see
DEFAULT_MAP and load_map); the defaults are the BFO 2020 and RO relations.
"""
from __future__ import annotations

import html
import json
import re
import subprocess
from collections import defaultdict
from dataclasses import dataclass, field

from rdflib import BNode, Graph, Literal, OWL, RDF, RDFS, URIRef
from rdflib.collection import Collection
from rdflib.namespace import XSD

from .parse import _build_labels, _display, _local
from .source import _Writer, _annotations, _class_axioms, _curie, _turtle, _axiom_sources, to_json, SCRIPT_ID

OBO = "http://purl.obolibrary.org/obo/"

# direction "preceded_by": the subject comes after the object;
# direction "precedes":    the subject comes before the object.
DEFAULT_MAP = {
    "sequence": {
        OBO + "RO_0002087": {"direction": "preceded_by", "immediate": True},   # immediately preceded by
        OBO + "RO_0002090": {"direction": "precedes", "immediate": True},      # immediately precedes
        OBO + "BFO_0000062": {"direction": "preceded_by", "immediate": False},  # preceded by
        OBO + "BFO_0000063": {"direction": "precedes", "immediate": False},     # precedes
    },
    "lane": [OBO + "BFO_0000055", OBO + "RO_0000057"],  # realizes, has participant
    "case": [],
}

_FACET_OPS = {XSD.minExclusive: ">", XSD.minInclusive: "≥", XSD.maxExclusive: "<", XSD.maxInclusive: "≤"}


def load_map(path: str | None) -> dict:
    """The relation mapping: DEFAULT_MAP, extended or overridden by a JSON
    file with the same keys, e.g.
    {"sequence": {"http://ex.org/next": {"direction": "precedes", "immediate": true}},
     "lane": ["http://ex.org/performedBy"], "case": ["http://ex.org/inCase"]}"""
    m = {"sequence": dict(DEFAULT_MAP["sequence"]), "lane": list(DEFAULT_MAP["lane"]),
         "case": list(DEFAULT_MAP["case"])}
    if path:
        with open(path, encoding="utf-8") as fh:
            user = json.load(fh)
        m["sequence"].update(user.get("sequence", {}))
        m["lane"] = list(dict.fromkeys(user.get("lane", []) + m["lane"]))
        m["case"] = list(dict.fromkeys(user.get("case", []) + m["case"]))
    return m


@dataclass
class FlowEdge:
    src: str
    dst: str
    kind: str                     # sequence | requirement | deviation
    label: str = ""
    axiom: str = ""
    cases: list = field(default_factory=list)      # case ids
    triples: list = field(default_factory=list)    # logged links, for deviations


@dataclass
class FlowModel:
    steps: dict = field(default_factory=dict)      # iri -> {"label", "lane"}
    lanes: list = field(default_factory=list)      # [(iri or "", label)] in display order
    edges: list = field(default_factory=list)
    cases: dict = field(default_factory=dict)      # id -> {"label", "events": [(step iri, individual label, iri)]}
    findings: list = field(default_factory=list)
    has_events: bool = False
    shapes_run: bool = False
    ontology_iri: str = ""

    def summary(self) -> dict:
        return {"steps": len(self.steps), "lanes": len([l for l in self.lanes if l[0]]),
                "cases": len(self.cases), "findings": len(self.findings),
                "deviations": sum(1 for e in self.edges if e.kind == "deviation"),
                "shapes": self.shapes_run}


# --------------------------------------------------------------- helpers ---
def _items(g: Graph, node, pred) -> list:
    lst = g.value(node, pred)
    if lst is None:
        return []
    try:
        return list(Collection(g, lst))
    except Exception:  # noqa: BLE001
        return []


def _named_or_union(g: Graph, x) -> list:
    if isinstance(x, URIRef):
        return [x]
    return [m for m in _items(g, x, OWL.unionOf) if isinstance(m, URIRef)]


def _closure(g: Graph, mapping: dict) -> dict:
    """Sub-properties of a mapped sequence relation are sequence relations too."""
    seq = {URIRef(k): v for k, v in mapping["sequence"].items()}
    changed = True
    while changed:
        changed = False
        for p, sup in g.subject_objects(RDFS.subPropertyOf):
            if isinstance(p, URIRef) and sup in seq and p not in seq:
                seq[p] = seq[sup]
                changed = True
    return seq


def _num(v) -> str:
    try:
        f = float(v)
        return f"{int(f):,}" if f == int(f) else f"{f:,}"
    except Exception:  # noqa: BLE001
        return str(v)


def _condition(g: Graph, parts: list, w: _Writer, labels) -> str:
    """Readable condition from the non-base parts of a defining intersection."""
    out = []
    for x in parts:
        p = g.value(x, OWL.onProperty) if isinstance(x, BNode) else None
        f = g.value(x, OWL.someValuesFrom) if p is not None else None
        if f is not None and isinstance(f, BNode) and g.value(f, OWL.onDatatype) is not None:
            facets = []
            for r in _items(g, f, OWL.withRestrictions):
                for fp, op in _FACET_OPS.items():
                    v = g.value(r, fp)
                    if v is not None:
                        facets.append(f"{op} {_num(v)}")
            out.append(f"{_display(p, labels)} {' and '.join(facets)}")
        else:
            out.append(w.expr(x))
    return "if " + " and ".join(out)


def _case_key(s: str) -> str:
    return re.sub(r"[^A-Za-z0-9_-]", "_", s)


# --------------------------------------------------------------- extract ---
def extract(tbox: Graph, events: Graph | None = None, shapes: Graph | None = None,
            mapping: dict | None = None) -> FlowModel:
    mapping = mapping or load_map(None)
    g = Graph()
    for prefix, ns in tbox.namespaces():
        g.bind(prefix, ns, override=True)
    g += tbox
    if events is not None:
        g += events
    labels = _build_labels(g)
    w = _Writer(g, labels)
    seq = _closure(g, mapping)
    lane_props = {URIRef(p) for p in mapping["lane"]}
    case_props = {URIRef(p) for p in mapping["case"]}

    fm = FlowModel()
    onto = next(iter(tbox.subjects(RDF.type, OWL.Ontology)), None)
    fm.ontology_iri = str(onto) if onto is not None else ""

    designed: dict[tuple, FlowEdge] = {}
    lane: dict = {}

    def restrictions(c):
        for r in g.objects(c, RDFS.subClassOf):
            if isinstance(r, BNode):
                yield r
        for e in g.objects(c, OWL.equivalentClass):
            for part in _items(g, e, OWL.intersectionOf):
                if isinstance(part, BNode):
                    yield part

    named = [c for c in set(g.subjects(RDF.type, OWL.Class)) if isinstance(c, URIRef)]

    def conditional(d) -> bool:
        """A defined subclass of one named class (handled below)."""
        return any(len([x for x in _items(g, e, OWL.intersectionOf) if isinstance(x, URIRef)]) == 1
                   for e in g.objects(d, OWL.equivalentClass))

    for c in named:
        if conditional(c):
            continue
        for r in restrictions(c):
            p, f = g.value(r, OWL.onProperty), g.value(r, OWL.someValuesFrom)
            if p is None or f is None:
                continue
            if p in seq:
                d = seq[p]
                for x in _named_or_union(g, f):
                    a, b = (x, c) if d["direction"] == "preceded_by" else (c, x)
                    kind = "sequence" if d["immediate"] else "requirement"
                    key = (str(a), str(b), kind, "")
                    text = f"{w.name(c)} SubClassOf: {w.expr(r)}"
                    if key in designed:
                        designed[key].axiom += "\n" + text
                    else:
                        designed[key] = FlowEdge(str(a), str(b), kind, "", text)
            elif p in lane_props and c not in lane:
                roles = [x for x in _named_or_union(g, f)]
                if not roles and isinstance(f, BNode):
                    from .source import _named_in
                    roles = [x for x in _named_in(g, f) if (x, RDF.type, OWL.Class) in g]
                if roles:
                    lane[c] = roles[0]

    # Conditional requirements: defined subclasses of a step with their own
    # sequence restriction.
    for d in named:
        for e in g.objects(d, OWL.equivalentClass):
            parts = _items(g, e, OWL.intersectionOf)
            bases = [x for x in parts if isinstance(x, URIRef)]
            if len(bases) != 1:
                continue
            base, rest = bases[0], [x for x in parts if not isinstance(x, URIRef)]
            for r in g.objects(d, RDFS.subClassOf):
                p, f = g.value(r, OWL.onProperty), g.value(r, OWL.someValuesFrom)
                if p not in seq or f is None:
                    continue
                cond = _condition(g, rest, w, labels) if rest else ""
                for x in _named_or_union(g, f):
                    a, b = (x, base) if seq[p]["direction"] == "preceded_by" else (base, x)
                    note = g.value(d, RDFS.comment)
                    text = (f"{w.name(d)} EquivalentTo: {w.expr(e)}\n{w.name(d)} SubClassOf: {w.expr(r)}"
                            + (f"\n# {note}" if note else ""))
                    designed[(str(a), str(b), "requirement", cond)] = FlowEdge(str(a), str(b), "requirement", cond, text)

    # A requirement that repeats a sequence edge says nothing new.
    seq_pairs = {(k[0], k[1]) for k in designed if k[2] == "sequence"}
    designed = {k: v for k, v in designed.items()
                if not (k[2] == "requirement" and not k[3] and (k[0], k[1]) in seq_pairs)}

    steps = {URIRef(s) for k in designed for s in k[:2]}

    # ---- instances: the flow as practiced --------------------------------
    observed: dict[tuple, list] = defaultdict(list)
    ind_step: dict = {}
    case_of: dict = {}
    if events is not None:
        step_set = set(steps)
        for ind, t in g.subject_objects(RDF.type):
            if isinstance(t, URIRef) and t in step_set and ind not in ind_step:
                ind_step[ind] = t
        links = []
        for p, d in seq.items():
            if not d["immediate"]:
                continue
            for s, o in g.subject_objects(p):
                if s in ind_step and o in ind_step:
                    links.append((o, s) if d["direction"] == "preceded_by" else (s, o))
        # Cases: the connected chains of events. Each chain is named by a
        # value all its events share and no other chain has (e.g. an "in
        # case" link), or by a mapped case relation, else by its first event.
        parent = {i: i for i in ind_step}

        def find(x):
            while parent[x] != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x
        for a, b in links:
            ra, rb = find(a), find(b)
            if ra != rb:
                parent[rb] = ra
        comps: dict = defaultdict(list)
        for i in ind_step:
            comps[find(i)].append(i)
        nexts, has_prev = defaultdict(list), set()
        for a, b in links:
            nexts[a].append(b)
            has_prev.add(b)
        skip = {RDF.type, RDFS.label} | set(seq)
        shared_by: dict = defaultdict(set)      # (p, value) -> components
        common: dict = {}
        for root, members in comps.items():
            cand = None
            for m in members:
                vals = {(p, o) for p, o in g.predicate_objects(m) if p not in skip and not isinstance(o, Literal)}
                cand = vals if cand is None else cand & vals
            common[root] = cand or set()
            for pv in common[root]:
                shared_by[pv].add(root)
        case_of = {}
        for root, members in comps.items():
            name = None
            for p in case_props:
                vals = {g.value(m, p) for m in members} - {None}
                if len(vals) == 1:
                    v = vals.pop()
                    name = str(g.value(v, RDFS.label) or _local(v))
            if name is None:
                uniq = sorted((pv for pv in common[root] if len(shared_by[pv]) == 1), key=lambda pv: str(pv))
                if uniq:
                    v = uniq[0][1]
                    name = str(g.value(v, RDFS.label) or _local(v))
            mset = set(members)
            start = [m for m in members if m not in has_prev] or members[:1]
            order, seen, cur = [], set(), start[0]
            while cur is not None and cur not in seen:
                order.append(cur)
                seen.add(cur)
                nx = [n for n in nexts.get(cur, []) if n in mset]
                cur = nx[0] if nx else None
            order += [m for m in members if m not in seen]
            cid = name or str(g.value(order[0], RDFS.label) or _local(order[0]))
            fm.cases[cid] = {"label": cid, "events": [(str(ind_step[x]), _display(x, labels), str(x)) for x in order]}
            for x in order:
                case_of[x] = cid
        for a, b in links:
            observed[(str(ind_step[a]), str(ind_step[b]))].append((case_of.get(a, ""), a, b))
        fm.has_events = bool(ind_step)

    # ---- assemble edges --------------------------------------------------
    for (a, b, kind, cond), e in designed.items():
        e.label = cond
        if kind == "sequence":
            e.cases = sorted({c for c, _, _ in observed.get((a, b), [])})
        fm.edges.append(e)
    for (a, b), lst in observed.items():
        if (a, b) in seq_pairs:
            continue
        name = lambda t: w.name(URIRef(t))
        fm.edges.append(FlowEdge(a, b, "deviation", f"{len(lst)} case{'s' if len(lst) != 1 else ''}",
                                 f"# No axiom puts {name(b)} immediately after {name(a)}.\n# Logged:\n" +
                                 "\n".join(f"{_curie(g, y)} follows {_curie(g, x)}  # {c}" for c, x, y in lst),
                                 sorted({c for c, _, _ in lst})))
        steps |= {URIRef(a), URIRef(b)}

    # ---- steps and lanes --------------------------------------------------
    for s in steps:
        s = URIRef(s)
        fm.steps[str(s)] = {"label": _display(s, labels), "lane": str(lane.get(s, "")),
                            "cases": sorted({c for c, ev in fm.cases.items() if any(st == str(s) for st, _, _ in ev["events"])})}
    lane_ids = list(dict.fromkeys(fm.steps[k]["lane"] for k in fm.steps))
    fm.lanes = [(l, _display(URIRef(l), labels) if l else "") for l in lane_ids]

    # ---- SHACL ----------------------------------------------------------------
    if shapes is not None and events is not None:
        fm.shapes_run = True
        fm.findings = _run_shacl(g, shapes, ind_step, case_of, labels)
    return fm


def _run_shacl(data: Graph, shapes: Graph, ind_step: dict, case_of: dict, labels) -> list:
    from pyshacl import validate
    SH = "http://www.w3.org/ns/shacl#"
    _conforms, report, _ = validate(data, shacl_graph=shapes, advanced=True, inference="none")
    out = []
    for r in report.subjects(RDF.type, URIRef(SH + "ValidationResult")):
        focus = report.value(r, URIRef(SH + "focusNode"))
        shape = report.value(r, URIRef(SH + "sourceShape"))
        sev = report.value(r, URIRef(SH + "resultSeverity"))
        rule = shapes.value(shape, RDFS.label) or (_local(shape) if isinstance(shape, URIRef) else "shape")
        out.append({
            "rule": str(rule),
            "message": str(report.value(r, URIRef(SH + "resultMessage")) or ""),
            "focus": _display(focus, labels) if isinstance(focus, URIRef) else str(focus),
            "step": str(ind_step.get(focus, "")),
            "case": case_of.get(focus, ""),
            "severity": _local(sev) if isinstance(sev, URIRef) else "Violation",
        })
    out.sort(key=lambda f: (f["rule"], f["case"]))
    return out


# ---------------------------------------------------------------- render ---
LANE_H = 100.0       # points
LANE_LABEL_W = 120.0
STEP_COLOR = "#9aa3b4"
SEQ_COLOR = "#5b6578"
REQ_COLOR = "#2f5fd0"
DEV_COLOR = "#d9822b"
BAD = "#c2412d"

FLOW_STYLE = """<style class="o2u-style o2u-flow-style">
svg.o2u-designed g.o2u-dev { display: none; }
svg.o2u-designed g.o2u-seq text { display: none; }
svg.o2u-designed g.o2u-seq path { stroke-width: 1.3px; }
svg.o2u-case-on g.node:not(.o2u-on), svg.o2u-case-on g.edge:not(.o2u-on) { opacity: 0.14; }
svg.o2u-case-on g.edge.o2u-on path { stroke: #2f5fd0; }
svg.o2u-case-on g.edge.o2u-on polygon { stroke: #2f5fd0; fill: #2f5fd0; }
.o2u-lane-label { font: 600 10px Helvetica, Arial, sans-serif; letter-spacing: 0.06em; fill: #5b6578; }
</style>"""


def _node_label(label: str, findings: int) -> str:
    border = BAD if findings else STEP_COLOR
    badge = (f'<TR><TD BGCOLOR="#fbe9e6"><FONT POINT-SIZE="9" COLOR="{BAD}"><B>{findings} finding'
             f'{"s" if findings > 1 else ""}</B></FONT></TD></TR>') if findings else ""
    return (f'<<TABLE BORDER="{2 if findings else 1}" CELLBORDER="0" CELLSPACING="0" CELLPADDING="4" '
            f'COLOR="{border}" BGCOLOR="white" STYLE="rounded"><TR><TD><FONT POINT-SIZE="8" COLOR="#5b6578">'
            f'«process»</FONT></TD></TR><TR><TD><B>{html.escape(label)}</B></TD></TR>{badge}</TABLE>>')


def _dot(src: str, *args: str) -> str:
    return subprocess.run(["dot", *args], input=src.encode("utf-8"), capture_output=True, check=True).stdout.decode("utf-8")


def render_flow_svg(fm: FlowModel, source: bool = True, tbox: Graph | None = None) -> str:
    """Swimlane diagram: ranks (left to right) from Graphviz, lanes (top to
    bottom) from the steps' roles, edges routed by neato on those positions."""
    ids = {s: f"n{i}" for i, s in enumerate(sorted(fm.steps, key=lambda s: fm.steps[s]["label"]))}
    nfind = defaultdict(int)
    for f in fm.findings:
        nfind[f["step"]] += 1
    lane_ix = {l: i for i, (l, _n) in enumerate(fm.lanes)}

    # pass 1: ranks from the designed sequence (or, failing that, all edges)
    rank_edges = [e for e in fm.edges if e.kind == "sequence"] or fm.edges
    p1 = ["digraph r { rankdir=LR; nodesep=0.3; ranksep=0.55; node [shape=plain fontname=Helvetica fontsize=11];"]
    for s, i in ids.items():
        p1.append(f'{i} [label={_node_label(fm.steps[s]["label"], nfind[s])}];')
    for e in rank_edges:
        p1.append(f"{ids[e.src]} -> {ids[e.dst]};")
    p1.append("}")
    plain = _dot("\n".join(p1), "-Tplain")
    pos, size = {}, {}
    for line in plain.splitlines():
        parts = line.split()
        if parts and parts[0] == "node":
            pos[parts[1]] = float(parts[2]) * 72
            size[parts[1]] = (float(parts[4]) * 72, float(parts[5]) * 72)

    # Lanes top to bottom in order of their first step.
    first = {}
    for s, n in ids.items():
        l = fm.steps[s]["lane"]
        first[l] = min(first.get(l, 1e9), pos[n])
    fm.lanes.sort(key=lambda ln: first.get(ln[0], 1e9))
    lane_ix = {l: i for i, (l, _n) in enumerate(fm.lanes)}

    # pass 2: lanes. Steps of one lane that would overlap go on sub-rows.
    rows: dict[int, list] = defaultdict(list)    # lane -> [[right edge of last node per row]]
    place = {}
    for s in sorted(ids, key=lambda s: pos[ids[s]]):
        n = ids[s]
        li = lane_ix[fm.steps[s]["lane"]]
        x, (wd, _h) = pos[n], size[n]
        row = next((r for r, right in enumerate(rows[li]) if x - wd / 2 > right + 18), None)
        if row is None:
            rows[li].append(0)
            row = len(rows[li]) - 1
        rows[li][row] = x + wd / 2
        place[n] = (x, li, row)
    heights = [LANE_H * max(1, len(rows[i])) for i in range(len(fm.lanes))]
    tops, y = [], 0.0
    for h in reversed(heights):
        tops.insert(0, y + h)
        y += h
    total_h = y
    xs = [pos[n] for n in pos]
    left, right = min(xs) - max(w for w, _ in size.values()) / 2 - LANE_LABEL_W, max(xs) + max(w for w, _ in size.values()) / 2 + 30
    # neato -n2 keeps coordinates as given, so start the drawing at x = 0
    place = {n: (x - left, li, row) for n, (x, li, row) in place.items()}
    left, right = 0.0, right - left

    out = ['digraph flow {', 'splines=curved; outputorder=edgesfirst; fontname="Helvetica";',
           'node [shape=plain fontname="Helvetica" fontsize=11]; edge [fontname="Helvetica" fontsize=9 arrowsize=0.7];']
    for s, n in ids.items():
        x, li, row = place[n]
        yy = tops[li] - LANE_H / 2 - row * LANE_H
        cls = " ".join(["o2u-step"] + [f"o2u-c-{_case_key(c)}" for c in fm.steps[s]["cases"]])
        out.append(f'{n} [id="{n}" class="{cls}" pos="{x:.1f},{yy:.1f}!" label={_node_label(fm.steps[s]["label"], nfind[s])}];')
    # corners so the drawing's bounding box covers the lanes
    out.append(f'_tl [id="_tl" shape=point style=invis width=0 label="" pos="{left:.1f},{total_h:.1f}!"];')
    out.append(f'_br [id="_br" shape=point style=invis width=0 label="" pos="{right:.1f},0!"];')
    for i, e in enumerate(fm.edges):
        cases = " ".join(f"o2u-c-{_case_key(c)}" for c in e.cases)
        a, b = ids[e.src], ids[e.dst]
        if e.kind == "sequence":
            pw = 1.0 + min(len(e.cases), 12) * 0.35 if fm.has_events else 1.3
            lab = f' xlabel="{len(e.cases)}" fontcolor="#5b6578"' if fm.has_events else ""
            out.append(f'{a} -> {b} [id="e{i}" class="o2u-seq {cases}" color="{SEQ_COLOR}" penwidth={pw:.2f}{lab}];')
        elif e.kind == "requirement":
            lab = html.escape(e.label or "must come before", quote=True)
            # leave and enter from below, so a rule does not lie on top of the sequence it constrains
            out.append(f'{a} -> {b} [id="e{i}" class="o2u-req" style=dashed color="{REQ_COLOR}" fontcolor="{REQ_COLOR}" '
                       f'arrowhead=empty tailport=s headport=s label="{lab}"];')
        else:
            out.append(f'{a} -> {b} [id="e{i}" class="o2u-dev {cases}" style=dashed color="{DEV_COLOR}" '
                       f'fontcolor="{DEV_COLOR}" penwidth=1.6 label="{html.escape(e.label)}"];')
    out.append("}")
    svg = subprocess.run(["neato", "-n2", "-Tsvg"], input="\n".join(out).encode("utf-8"),
                         capture_output=True, check=True).stdout.decode("utf-8")

    # lane bands behind everything (Graphviz SVG puts y up as negative)
    bands = []
    for i, (l, name) in enumerate(fm.lanes):
        top, h = tops[i], heights[i]
        fill = "#eceef3" if i % 2 == 0 else "#f6f7f9"
        bands.append(f'<rect class="o2u-lane" x="{left:.1f}" y="{-top:.1f}" width="{right - left:.1f}" height="{h:.1f}" '
                     f'fill="{fill}" stroke="#d8dce5" stroke-width="0.6"/>')
        if name:
            bands.append(f'<text class="o2u-lane-label" x="{left + 10:.1f}" y="{-top + h / 2 + 3:.1f}">'
                         f'{html.escape(name.upper())}</text>')
    m = re.search(r'(<g id="graph0"[^>]*>\s*<title>[^<]*</title>\s*<polygon[^>]*/>)', svg)
    if m:
        svg = svg[:m.end()] + "\n" + "\n".join(bands) + svg[m.end():]
    i = svg.find(">", svg.find("<svg")) + 1
    svg = svg[:i] + "\n" + FLOW_STYLE + svg[i:]
    if not fm.has_events:
        svg = svg.replace("<svg ", '<svg class="o2u-designed" ', 1)
    if source:
        from .source import embed
        svg = embed(svg, flow_source(fm, ids, tbox))
    return svg


def flow_source(fm: FlowModel, ids: dict, tbox: Graph | None) -> dict:
    """The source block for the panel (same shape as source.build_source,
    with flow edge kinds, findings and cases)."""
    g = tbox if tbox is not None else Graph()
    labels = _build_labels(g)
    w = _Writer(g, labels)
    classes = {}
    for s in fm.steps:
        t = URIRef(s)
        classes[s] = {"iri": s, "curie": _curie(g, t), "label": fm.steps[s]["label"], "name": w.name(t),
                      "frame": "Class", "ann": _annotations(g, t, labels), "ax": _class_axioms(g, t, w),
                      "ttl": _turtle(g, _axiom_sources(g, t)), "lane": dict(fm.lanes).get(fm.steps[s]["lane"], ""),
                      "findings": [j for j, f in enumerate(fm.findings) if f["step"] == s]}
    edges = {f"e{i}": {"src": e.src, "dst": e.dst, "kind": e.kind, "label": e.label, "text": e.axiom,
                       "cases": e.cases} for i, e in enumerate(fm.edges)}
    cases = {c: {"key": _case_key(c), "events": [[st, lab] for st, lab, _ in v["events"]],
                 "findings": [j for j, f in enumerate(fm.findings) if f["case"] == c]} for c, v in fm.cases.items()}
    return {"version": 1, "view": "flow", "ontology": fm.ontology_iri,
            "nodes": {n: s for s, n in ids.items()}, "classes": classes, "props": {}, "edges": edges,
            "findings": fm.findings, "cases": cases, "summary": fm.summary()}
