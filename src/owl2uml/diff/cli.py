"""``owl2uml diff OLD NEW``: one diagram of what changed (spec WS4)."""
from __future__ import annotations

import argparse
import json
import os
import sys

from ..load import IMPORT_MODES, LOADERS, load
from .. import pinning, reason
from .compare import FAIL_ON, changed, check
from .render import SCOPES
from .report import markdown

EXIT_FAILED = 3     # a --fail-on condition holds


def _stem(path: str) -> str:
    base = os.path.basename(path)
    return base.rsplit(".", 1)[0] if "." in base else base


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(
        prog="owl2uml diff",
        description="Draw what changed between two versions of an ontology: added (green), "
                    "removed (red, dashed), changed (amber), newly inferred or no longer "
                    "inferred (orange, + or −). Also writes diff.json and a Markdown summary.")
    ap.add_argument("old", help="the older version (any syntax owl2uml reads)")
    ap.add_argument("new", help="the newer version")
    ap.add_argument("-o", "--output", help="output SVG (default: <new>-diff.svg)")
    ap.add_argument("--diff-scope", choices=SCOPES, default="1hop",
                    help="changed elements only, plus their neighbours greyed (1hop, "
                         "default), or the whole ontology (all)")
    ap.add_argument("--reason", choices=list(reason.ENGINES), default="auto",
                    help="reasoner for the inferred layer (default auto; none skips it)")
    ap.add_argument("--profile", default="none", metavar="NAMES",
                    help="notation profiles, as for owl2uml (e.g. bfo,legal or auto)")
    ap.add_argument("--layout", metavar="FILE",
                    help="positions to keep (default: <old>.layout.json when it exists), so "
                         "unchanged classes stay where readers know them")
    ap.add_argument("--json", metavar="FILE", help="change set (default <output>.json)")
    ap.add_argument("--markdown", metavar="FILE",
                    help="summary for pull requests (default <output>.md)")
    ap.add_argument("--export", metavar="FMT[,FMT]",
                    help="also write svg-static and/or png (for PR comments) or pdf")
    ap.add_argument("--dpi", type=int, default=150, help="PNG resolution (default 150)")
    ap.add_argument("--fail-on", default="", metavar="LIST",
                    help=f"exit {EXIT_FAILED} when any holds: {', '.join(FAIL_ON)}")
    ap.add_argument("--interactive", action="store_true",
                    help="inline the viewer script into the SVG")
    ap.add_argument("--no-source", action="store_true", help="do not embed the OWL source")
    ap.add_argument("--label-width", type=int, default=22, metavar="N")
    ap.add_argument("--imports", choices=IMPORT_MODES, default="closure")
    ap.add_argument("--loader", choices=LOADERS, default="auto")
    ap.add_argument("--offline", action="store_true", help="never fetch imports")
    args = ap.parse_args(argv)
    conditions = [c.strip() for c in args.fail_on.split(",") if c.strip()]
    bad = [c for c in conditions if c not in FAIL_ON]
    if bad:
        ap.error(f"unknown --fail-on condition(s): {', '.join(bad)} (one of {', '.join(FAIL_ON)})")

    out = args.output or _stem(args.new) + "-diff.svg"
    stem = out.rsplit(".", 1)[0]
    from .build import run
    try:
        old, new = (load(p, imports=args.imports, loader=args.loader,
                         allow_network=not args.offline) for p in (args.old, args.new))
        pins = _pins(args)
        res = run(old, new, names=(os.path.basename(args.old), os.path.basename(args.new)),
                  engine=args.reason, profile=args.profile, scope=args.diff_scope, pins=pins,
                  label_width=args.label_width, source=not args.no_source)
    except Exception as exc:  # noqa: BLE001 - one clear line
        print(f"error: {exc}", file=sys.stderr)
        return 1
    d = res.data
    failed = check(d, conditions)
    d["fail_on"] = {"checked": conditions, "failed": failed}
    svg = res.svg
    if args.interactive:
        from ..source import inline_viewer
        svg = inline_viewer(svg)
    _write(out, svg)
    jpath, mpath = args.json or stem + ".json", args.markdown or stem + ".md"
    _write(jpath, json.dumps(d, indent=1, ensure_ascii=False))
    _write(mpath, markdown(d, failed=failed))
    print(f"wrote {out}, {jpath}, {mpath}")
    if args.export and not _exports(args, res, stem):
        return 1
    s = d["summary"]
    print(f"diff: {s['added']} added, {s['removed']} removed, {s['renamed']} renamed, "
          f"{s['deprecated']} deprecated; axioms +{s['axioms_added']} −{s['axioms_removed']}; "
          f"inferred +{s['inferred_added']} −{s['inferred_removed']}, {s['moved']} moved, "
          f"{s['unsatisfiable']} unsatisfiable"
          + ("" if changed(d) else " (no changes)"), file=sys.stderr)
    if d["inferred"].get("error"):
        print(f"reasoner failed: {d['inferred']['error']}", file=sys.stderr)
    for f in failed:
        print(f"fail-on {f['condition']}: {f['detail']}", file=sys.stderr)
    return EXIT_FAILED if failed else 0


def _pins(args) -> dict:
    path = args.layout or str(pinning.sidecar_path(args.old))
    if not os.path.exists(path):
        if args.layout:
            raise OSError(f"no such file: {args.layout}")
        return {}
    saved = pinning.pins(pinning.load(path))
    print(f"layout: {len(saved)} positions from {path}", file=sys.stderr)
    return saved


def _exports(args, res, stem: str) -> bool:
    from ..export import export
    for fmt in (f.strip() for f in args.export.split(",") if f.strip()):
        if fmt not in ("svg-static", "png", "pdf"):
            print(f"error: diff exports are svg-static, png or pdf (not {fmt})", file=sys.stderr)
            return False
        try:
            x = export(res.model, fmt, svg=res.svg, dpi=args.dpi, graph=res.graphs[1])
        except (RuntimeError, ValueError) as exc:
            print(f"error: {fmt} export failed: {exc}", file=sys.stderr)
            return False
        path = f"{stem}{'-static' if fmt == 'svg-static' else ''}.{x.ext}"
        with open(path, "wb") as fh:
            fh.write(x.data)
        print(f"wrote {path}")
    return True


def _write(path: str, text: str) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)
