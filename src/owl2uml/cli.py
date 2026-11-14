"""Command-line entry point: owl/ttl -> svg UML class diagram."""
from __future__ import annotations

import argparse
import sys

from .parse import load_graph, parse_ontology
from . import reason
from .postprocess import postprocess
from .layout import layout
from .render import render_svg
from .dot import dot_available, render_dot_svg
from .source import build_source, inline_viewer


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="owl2uml",
        description="Convert an OWL/RDFS ontology (.owl/.ttl/.rdf) to a UML "
                    "class diagram in SVG.",
    )
    ap.add_argument("input", help="path to the ontology file")
    ap.add_argument("-o", "--output", help="output .svg path (default: <input>.svg)")
    ap.add_argument("-f", "--format",
                    help="rdflib input format (turtle, xml, n3, ...); "
                         "auto-detected from extension if omitted")
    ap.add_argument("-e", "--engine", choices=["auto", "dot", "builtin"],
                    default="auto",
                    help="layout engine: 'dot' (graphviz, scalable), 'builtin' "
                         "(pure-python), or 'auto' (dot if available)")
    ap.add_argument("--keep-unused", action="store_true",
                    help="keep imported upper-level classes (e.g. BFO) that the "
                         "ontology's own classes never reach; by default they are "
                         "left out")
    ap.add_argument("--no-legend", action="store_true",
                    help="omit the colour/line-style key")
    ap.add_argument("--compact-labels", choices=["auto", "on", "off"], default="auto",
                    help="place relation labels after layout so they do not widen "
                         "the diagram (auto: 40+ classes)")
    ap.add_argument("--reason", choices=list(reason.ENGINES), default="none",
                    help="classify with a reasoner and draw what it infers in orange: "
                         "'hermit' (OWL 2 DL, needs Java), 'owlrl' (OWL 2 RL, pure "
                         "Python), 'auto' (hermit if available, else owlrl)")
    ap.add_argument("--no-source", action="store_true",
                    help="do not embed the OWL source of each class and line "
                         "(clicking a class then shows no source panel)")
    ap.add_argument("--interactive", action="store_true",
                    help="inline the viewer script, so the SVG opened in a browser "
                         "supports hover, pin, drag, zoom, the source panel (s) and "
                         "the inferred toggle (i)")
    flow = ap.add_argument_group("flow view (process ontologies)")
    flow.add_argument("--flow", action="store_true",
                      help="draw the processes as a flow in swimlanes instead of a class "
                           "diagram: sequence relations become arrows, roles become lanes")
    flow.add_argument("--events", action="append", default=[], metavar="FILE",
                      help="instances of the process steps (an event log as RDF); draws the "
                           "flow as practiced. Repeatable")
    flow.add_argument("--shapes", metavar="FILE",
                      help="SHACL shapes to check the events against; violations are "
                           "pinned to their steps")
    flow.add_argument("--flow-map", metavar="FILE",
                      help="JSON mapping of which relations count as sequence, lane and "
                           "case (default: BFO 2020 and RO relations)")
    args = ap.parse_args(argv)

    out = args.output or _default_out(args.input)
    if args.flow or args.events or args.shapes:
        return _flow(args, out)

    try:
        graph = load_graph(args.input, fmt=args.format)
        model = parse_ontology(args.input, graph=graph)
    except Exception as exc:  # noqa: BLE001 - surface parse errors clearly
        print(f"error: failed to parse '{args.input}': {exc}", file=sys.stderr)
        return 1

    inf = reason.classify(graph, args.reason)
    reason.apply(model, inf)
    report = postprocess(model, prune=not args.keep_unused)

    if not model.classes:
        print("warning: no classes found in ontology; producing empty diagram",
              file=sys.stderr)

    use_dot = args.engine == "dot" or (args.engine == "auto" and dot_available())
    if args.engine == "dot" and not dot_available():
        print("error: --engine dot requested but graphviz 'dot' not found "
              "(run scripts/setup.sh)", file=sys.stderr)
        return 1

    if use_dot:
        src = None if args.no_source else build_source(graph, model)
        svg = render_dot_svg(model, legend=not args.no_legend,
                             compact_labels=args.compact_labels, source=src)
        if args.interactive:
            svg = inline_viewer(svg)
        engine = "graphviz dot"
    else:
        w, h = layout(model)
        svg = render_svg(model, w, h)
        engine = "builtin"
    with open(out, "w", encoding="utf-8") as fh:
        fh.write(svg)
    print(f"engine: {engine}", file=sys.stderr)

    pruned = f", {report['pruned']} unused imported classes left out" if report["pruned"] else ""
    if args.reason != "none":
        r = inf.report()
        if r["error"]:
            print(f"reasoner ({r['engine']}) failed: {r['error']}", file=sys.stderr)
        elif r["inconsistent"]:
            print(f"reasoner ({r['engine']}): ontology is INCONSISTENT; "
                  "no classification drawn", file=sys.stderr)
        else:
            print(f"reasoner ({r['engine']}, {r['seconds']}s): {r['inferred']} inferred "
                  f"subclass relations drawn, {r['unsatisfiable']} unsatisfiable classes, "
                  f"{r['equivalences']} inferred equivalences", file=sys.stderr)
    print(f"wrote {out}  ({len(model.classes)} classes, {len(model.edges)} relations{pruned})")
    return 0


def _flow(args, out: str) -> int:
    from rdflib import Graph
    from .flow import extract, load_map, render_flow_svg
    from .source import inline_viewer
    if not dot_available():
        print("error: the flow view needs graphviz (dot and neato)", file=sys.stderr)
        return 1
    try:
        tbox = load_graph(args.input, fmt=args.format)
        events = None
        for path in args.events:
            events = events if events is not None else Graph()
            events += load_graph(path)
        shapes = load_graph(args.shapes) if args.shapes else None
        fm = extract(tbox, events, shapes, load_map(args.flow_map))
    except Exception as exc:  # noqa: BLE001
        print(f"error: {exc}", file=sys.stderr)
        return 1
    if not fm.steps:
        print("error: no process steps found. The flow view needs classes linked by sequence "
              "relations (e.g. 'immediately preceded by' some X); see --flow-map.", file=sys.stderr)
        return 1
    if args.shapes and not args.events:
        print("note: --shapes checks instances; without --events there is nothing to check", file=sys.stderr)
    svg = render_flow_svg(fm, source=not args.no_source, tbox=tbox)
    if args.interactive:
        svg = inline_viewer(svg)
    with open(out, "w", encoding="utf-8") as fh:
        fh.write(svg)
    s = fm.summary()
    extra = (f", {s['cases']} cases, {s['deviations']} undesigned paths" if fm.has_events else "") + \
            (f", {s['findings']} SHACL findings" if s["shapes"] else "")
    print(f"wrote {out}  (flow: {s['steps']} steps in {s['lanes']} lanes{extra})")
    return 0


def _default_out(inp: str) -> str:
    base = inp.rsplit(".", 1)[0] if "." in inp else inp
    return base + ".svg"


if __name__ == "__main__":
    raise SystemExit(main())
