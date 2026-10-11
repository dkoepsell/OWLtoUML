"""Command-line entry point: owl/ttl -> svg UML class diagram."""
from __future__ import annotations

import argparse
import sys

from .parse import parse_ontology
from .layout import layout
from .render import render_svg
from .dot import dot_available, render_dot_svg


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
    args = ap.parse_args(argv)

    out = args.output or _default_out(args.input)

    try:
        model = parse_ontology(args.input, fmt=args.format)
    except Exception as exc:  # noqa: BLE001 - surface parse errors clearly
        print(f"error: failed to parse '{args.input}': {exc}", file=sys.stderr)
        return 1

    if not model.classes:
        print("warning: no classes found in ontology; producing empty diagram",
              file=sys.stderr)

    use_dot = args.engine == "dot" or (args.engine == "auto" and dot_available())
    if args.engine == "dot" and not dot_available():
        print("error: --engine dot requested but graphviz 'dot' not found "
              "(run scripts/setup.sh)", file=sys.stderr)
        return 1

    if use_dot:
        svg = render_dot_svg(model)
        engine = "graphviz dot"
    else:
        w, h = layout(model)
        svg = render_svg(model, w, h)
        engine = "builtin"
    with open(out, "w", encoding="utf-8") as fh:
        fh.write(svg)
    print(f"engine: {engine}", file=sys.stderr)

    print(f"wrote {out}  ({len(model.classes)} classes, {len(model.edges)} relations)")
    return 0


def _default_out(inp: str) -> str:
    base = inp.rsplit(".", 1)[0] if "." in inp else inp
    return base + ".svg"


if __name__ == "__main__":
    raise SystemExit(main())
