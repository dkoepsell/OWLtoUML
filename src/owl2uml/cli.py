"""Command-line entry point: owl/ttl -> svg UML class diagram."""
from __future__ import annotations

import argparse
import os
import re
import sys

from .parse import load_graph, parse_ontology, property_view
from .load import IMPORT_MODES, LOADERS, annotate_model, load
from . import coverage, modules, pinning, reason
from .aspect import parse_target
from .postprocess import postprocess
from .layout import layout
from .render import render_svg
from .dot import dot_available, render_dot_svg
from .source import build_source, inline_viewer


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="owl2uml",
        description="Convert an OWL/RDFS ontology to a UML class diagram in SVG. "
                    "Reads RDF/XML, Turtle, N3, N-Triples, JSON-LD and TriG, and "
                    "with Java + ROBOT also OWL/XML, Manchester, Functional and OBO.",
    )
    ap.add_argument("input", nargs="?", help="path to the ontology file")
    ap.add_argument("--iri", metavar="URL",
                    help="load the ontology from an http(s) IRI instead of a file "
                         "(e.g. a w3id or PURL)")
    ap.add_argument("--imports", choices=IMPORT_MODES, default="closure",
                    help="which owl:imports to load: none, the direct ones, or the "
                         "whole closure (default). Looked up in the catalog, then the "
                         "ontology's directory, then the network")
    ap.add_argument("--catalog", metavar="FILE",
                    help="XML catalog for imports (default: catalog-v001.xml next to "
                         "the ontology)")
    ap.add_argument("--offline", action="store_true",
                    help="never fetch imports over the network")
    ap.add_argument("--loader", choices=LOADERS, default="auto",
                    help="'robot' sends every syntax through the OWL API (Java); "
                         "'rdflib' never starts Java; 'auto' (default) uses rdflib for "
                         "RDF syntaxes and the OWL API for the rest")
    ap.add_argument("-o", "--output", help="output .svg path (default: <input>.svg)")
    ap.add_argument("-f", "--format",
                    help="input syntax: turtle, xml, n3, nt, json-ld, trig, owx, omn, "
                         "ofn or obo; detected from the content if omitted")
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
    ap.add_argument("--show-definitions", action="store_true",
                    help="print each class's definition (IAO_0000115, skos:definition "
                         "or rdfs:comment) under its name")
    ap.add_argument("--draw-chains", action="store_true",
                    help="add property chains (p ⊒ q ∘ r) to the labels of lines "
                         "drawn for p")
    ap.add_argument("--property-view", action="store_true",
                    help="draw the property hierarchy (sub-properties, inverses, "
                         "domains, ranges, characteristics) instead of the classes")
    ap.add_argument("--aspect", default="auto",
                    help="target width:height of the figure, e.g. 1.4, 16:9 or 'auto' "
                         "(1.4); 'off' keeps Graphviz's own layout")
    ap.add_argument("--max-rank-width", type=int, default=12, metavar="N",
                    help="when the figure is too wide, wrap ranks of more than N "
                         "classes (default 12)")
    ap.add_argument("--coverage-out", metavar="FILE",
                    help="where to write the coverage report: what happened to every "
                         "axiom (default: <output>.coverage.json; '-' for none)")
    exp = ap.add_argument_group("exports")
    exp.add_argument("--export", metavar="FMT[,FMT]",
                     help="also write the figure as svg-static, pdf, png, tikz, plantuml, "
                          "ontopuml, mermaid or graphml (<output>.<ext>)")
    exp.add_argument("--dpi", type=int, default=200, help="PNG resolution (default 200)")
    exp.add_argument("--page-width", type=float, default=6.5, metavar="IN",
                     help="page width for the print checks of static exports (default 6.5)")
    exp.add_argument("--strict", action="store_true",
                     help="print-check warnings fail the run (non-zero exit), for CI")
    lay = ap.add_argument_group("saved layout")
    lay.add_argument("--layout", metavar="FILE",
                     help="saved positions to keep (.layout.json sidecar or a layout "
                          "ontology); default: <input>.layout.json when it exists")
    lay.add_argument("--save-layout", action="store_true",
                     help="write every class's position to the sidecar, keeping the "
                          "pins already in it")
    lay.add_argument("--layout-in-ontology", action="store_true",
                     help="also write the layout as annotations in <input>-layout.ttl, "
                          "an ontology that imports this one (never the ontology itself)")
    mods = ap.add_argument_group("modules")
    mods.add_argument("--view", metavar="module=ID",
                      help="draw one module plus its context (direct superclasses and "
                           "the far ends of its restrictions, greyed)")
    mods.add_argument("--all-modules", action="store_true",
                      help="write one SVG per module (<output>-<module>.svg) plus an "
                           "overview of the modules (<output>-modules.svg)")
    mods.add_argument("--list-modules", action="store_true",
                      help="print the modules found and exit")
    mods.add_argument("--module-property", metavar="IRI",
                      help="annotation property naming a class's module (default "
                           "https://w3id.org/lof/module); else IRI prefixes, imports, or "
                           "community detection")
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
    if bool(args.input) == bool(args.iri):
        ap.error("give either an input file or --iri (not both)")

    out = args.output or _default_out(args.input or _iri_stem(args.iri))
    if args.flow or args.events or args.shapes:
        return _flow(args, out)

    try:
        loaded = _load(args)
        graph = loaded.merge()
        if args.property_view:
            model = property_view(graph)
        else:
            model = parse_ontology(args.input or args.iri, graph=graph)
            annotate_model(model, loaded)
    except Exception as exc:  # noqa: BLE001 - surface parse errors clearly
        print(f"error: failed to load '{args.input or args.iri}': {exc}", file=sys.stderr)
        return 1
    _report_load(loaded)

    inf = reason.classify(graph, args.reason if not args.property_view else "none")
    reason.apply(model, inf)
    report = postprocess(model, prune=not args.keep_unused)

    if not model.classes:
        print("warning: no classes found in ontology; producing empty diagram",
              file=sys.stderr)

    cov = None
    if not args.property_view:
        cov = coverage.build(graph, model, definitions=args.show_definitions)
        cov_out = args.coverage_out or out.rsplit(".", 1)[0] + ".coverage.json"
        if cov_out != "-":
            with open(cov_out, "w", encoding="utf-8") as fh:
                fh.write(coverage.to_json(cov))
        print(f"coverage: {coverage.headline(cov)}"
              + (f" (see {cov_out})" if cov_out != "-" else ""), file=sys.stderr)

    if args.view or args.all_modules or args.list_modules:
        found = modules.assign(model, graph, args.module_property)
        if args.list_modules:
            for mid, info in found.items():
                kind = " (imported)" if info["upper"] else ""
                print(f"{mid}\t{len(info['members'])} classes\t{info['source']}{kind}")
            return 0
    if args.engine == "dot" and not dot_available():
        print("error: --engine dot requested but graphviz 'dot' not found "
              "(run scripts/setup.sh)", file=sys.stderr)
        return 1
    try:
        if args.all_modules:
            stem = out.rsplit(".", 1)[0]
            figures = [(f"{stem}-modules.svg", modules.overview(model))]
            figures += [(f"{stem}-{_safe(mid)}.svg", modules.view(model, mid))
                        for mid, info in model.modules.items() if not info["upper"]]
            for path, fig in figures:
                _write(path, _render(args, graph, fig, None))
                print(f"wrote {path}  ({len(fig.classes)} classes)")
            return 0
        if args.view:
            kind, _, mid = args.view.partition("=")
            if kind != "module" or not mid:
                print("error: --view expects module=ID (see --list-modules)", file=sys.stderr)
                return 1
            model, cov = modules.view(model, mid), None
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    try:
        saved = _saved_layout(args)
    except (OSError, ValueError) as exc:
        print(f"error: layout: {exc}", file=sys.stderr)
        return 1
    svg = _render(args, graph, model, cov, pinning.pins(saved))
    _write(out, svg)
    if args.export and not _exports(args, graph, model, svg, out):
        return 1
    if args.save_layout or args.layout_in_ontology:
        _store_layout(args, model, svg, saved)

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
        tbox = _load(args).merge()
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


def _exports(args, graph, model, svg: str, out: str) -> bool:
    from .export import FORMATS, export, layout_json
    from .printcheck import check
    stem = out.rsplit(".", 1)[0]
    fmts = [f.strip() for f in args.export.split(",") if f.strip()]
    printed = {"svg-static", "pdf", "png", "tikz"}
    screen_svg, screen_drawing = svg, dict(model.drawing)
    if set(fmts) & printed and model.drawing:
        # Static figures are drawn for print: compact key on its own row,
        # classes where the screen version has them.
        nodes = {f"n{i}": cid for i, cid in enumerate(model.classes)}
        here = pinning.to_layout_space(pinning.from_svg(svg, nodes), model.layout_origin)
        svg = _render(args, graph, model, None,
                      {k: (v["x"], v["y"]) for k, v in here.items()}, for_print=True)
        named = sum(1 for c in model.classes.values() if c.kind == "class")
        found = check(svg, layout_json(model), named, args.page_width)
        for w in found["warnings"]:
            print(f"print check: {w}", file=sys.stderr)
        if not found["warnings"]:
            print(f"print check: ok at {args.page_width:g} in (smallest text "
                  f"{found['min_font_pt']} pt)", file=sys.stderr)
        elif args.strict:
            print("error: print checks failed (--strict)", file=sys.stderr)
            return False
    print_svg, print_drawing = svg, dict(model.drawing)
    for fmt in fmts:
        svg, model.drawing = (print_svg, print_drawing) if fmt in printed \
            else (screen_svg, screen_drawing)
        if fmt not in FORMATS:
            print(f"error: unknown export format '{fmt}' ({', '.join(FORMATS)})", file=sys.stderr)
            return False
        try:
            x = export(model, fmt, svg=svg, dpi=args.dpi, graph=graph)
        except (RuntimeError, ValueError) as exc:
            print(f"error: {fmt} export failed: {exc}", file=sys.stderr)
            return False
        suffix = "-static" if fmt == "svg-static" else "-nowl" if fmt == "ontopuml" else ""
        path = f"{stem}{suffix}.{x.ext}"
        with open(path, "wb") as fh:
            fh.write(x.data)
        for w in x.warnings:
            print(f"warning: {fmt}: {w}", file=sys.stderr)
        print(f"wrote {path}")
    return True


def _saved_layout(args) -> dict:
    path = args.layout or (str(pinning.sidecar_path(args.input)) if args.input else None)
    if not path or not os.path.exists(path):
        if args.layout:
            raise OSError(f"no such file: {args.layout}")
        return {}
    saved = pinning.load(path)
    print(f"layout: {len(pinning.pins(saved))} pinned classes from {path}", file=sys.stderr)
    return saved


def _store_layout(args, model, svg: str, saved: dict) -> None:
    """Sidecar with every class's current position (pins kept), and/or the
    layout ontology."""
    nodes = {f"n{i}": cid for i, cid in enumerate(model.classes)}
    now = pinning.to_layout_space(pinning.from_svg(svg, nodes), model.layout_origin)
    for iri, v in saved.items():
        if v.get("pinned"):
            now[iri] = v
    if not args.input:
        print("warning: --save-layout needs an input file to sit next to", file=sys.stderr)
        return
    if args.save_layout:
        path = args.layout if args.layout and args.layout.endswith(".json") \
            else str(pinning.sidecar_path(args.input))
        pinning.save(path, now)
        print(f"wrote {path}  ({len(now)} positions)", file=sys.stderr)
    if args.layout_in_ontology:
        path = args.input.rsplit(".", 1)[0] + "-layout.ttl"
        pinning.layout_ontology(now, model.ontology_iri).serialize(path, format="turtle")
        print(f"wrote {path}  (layout ontology importing {model.ontology_iri or 'the input'})",
              file=sys.stderr)


def _render(args, graph, model, cov, pins=None, for_print=False) -> str:
    """SVG for ``model``: Graphviz when available, else the builtin layout."""
    if not (args.engine == "dot" or (args.engine == "auto" and dot_available())):
        print("engine: builtin", file=sys.stderr)
        w, h = layout(model)
        return render_svg(model, w, h)
    src = None if (args.no_source or args.property_view) else build_source(graph, model)
    svg = render_dot_svg(model, legend=not args.no_legend,
                         compact_labels=args.compact_labels, source=src,
                         definitions=args.show_definitions, chains=args.draw_chains,
                         coverage=coverage.summary(cov) if cov else None,
                         aspect=parse_target(args.aspect),
                         max_rank_width=args.max_rank_width, pins=pins, for_print=for_print)
    lr = model.layout_report
    if lr:
        how = ", ".join(lr["steps"]) or "no change needed"
        print(f"aspect: {lr['start']}:1 -> {lr['ratio']}:1 (target {lr['target']}; {how})"
              + ("" if lr["within_band"] else " - still outside 1:2..2:1"), file=sys.stderr)
    return inline_viewer(svg) if args.interactive else svg


def _write(path: str, text: str) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)


def _safe(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", name) or "module"


def _load(args):
    return load(args.input or args.iri, fmt=args.format, imports=args.imports,
                loader=args.loader, catalog=args.catalog, allow_network=not args.offline)


def _report_load(loaded) -> None:
    """Say which loader ran, and what happened to each import."""
    ok = [i for i in loaded.imports if not i["error"]]
    imp = f", {len(ok)} of {len(loaded.imports)} imports loaded" if loaded.imports else ""
    print(f"loader: {loaded.loader} ({loaded.syntax} syntax){imp}", file=sys.stderr)
    for w in loaded.warnings:
        print(f"warning: {w}", file=sys.stderr)


def _iri_stem(iri: str) -> str:
    tail = iri.rstrip("/#").rsplit("/", 1)[-1] or "ontology"
    return tail


def _default_out(inp: str) -> str:
    base = inp.rsplit(".", 1)[0] if "." in inp else inp
    return base + ".svg"


if __name__ == "__main__":
    raise SystemExit(main())
