"""Flask web UI: upload an OWL/TTL ontology, get an interactive UML SVG.

Layout is done server-side with Graphviz (scales to large ontologies);
the browser handles pan/zoom/search.
"""
from __future__ import annotations

import json
import os
import re
import sys

from flask import Flask, Response, request, jsonify, send_from_directory

# Make the sibling `owl2uml` package importable.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from owl2uml.parse import parse_ontology            # noqa: E402
from owl2uml.load import IMPORT_MODES, LoadError, annotate_model, load  # noqa: E402
from owl2uml.fetch import FetchError, fetch          # noqa: E402
from owl2uml import reason                         # noqa: E402
from owl2uml.postprocess import postprocess       # noqa: E402
from owl2uml.dot import dot_available, render_dot_svg  # noqa: E402
from owl2uml.layout import layout                  # noqa: E402
from owl2uml.render import render_svg              # noqa: E402
from owl2uml.source import build_source            # noqa: E402
from owl2uml import edit as editing               # noqa: E402

STATIC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")

app = Flask(__name__, static_folder=STATIC, static_url_path="/static")
# Upload cap. Override with MAX_UPLOAD_MB (default 25 MB — safe for a public
# endpoint; keep it <= nginx client_max_body_size).
_max_mb = int(os.environ.get("MAX_UPLOAD_MB", "25"))
app.config["MAX_CONTENT_LENGTH"] = _max_mb * 1024 * 1024
# Wall-clock budget for loading one ontology (conversion, imports, fetching).
LOAD_TIMEOUT = float(os.environ.get("LOAD_TIMEOUT_S", "60"))


@app.errorhandler(413)
def too_large(_exc):
    return jsonify(error=f"the upload is larger than the {_max_mb} MB limit"), 413


def _load_upload(data: bytes, name: str, fmt=None, imports: str = "closure"):
    """Load uploaded bytes like the CLI does. Imports may come from the network
    (public hosts only); there is no local directory or catalog on the server."""
    return load(data=data, name=name, fmt=fmt, imports=imports, allow_network=True,
                allow_private=False, timeout=LOAD_TIMEOUT, max_bytes=_max_mb * 2**20)


@app.post("/api/fetch")
def fetch_iri():
    """Fetch an ontology by IRI (w3id, PURL, ...) for the browser to render as
    if it had been uploaded. Public http(s) hosts only."""
    iri = (request.form.get("iri") or "").strip()
    if not iri:
        return jsonify(error="no IRI given"), 400
    try:
        got = fetch(iri, max_bytes=_max_mb * 2**20, timeout=LOAD_TIMEOUT, allow_private=False)
    except FetchError as exc:
        return jsonify(error=str(exc)), 400
    tail = got.url.split("?", 1)[0].rstrip("/").rsplit("/", 1)[-1] or "ontology"
    if "." not in tail:
        tail += {"xml": ".owl", "owx": ".owx", "ofn": ".ofn", "omn": ".omn",
                 "json-ld": ".jsonld"}.get(got.syntax or "", ".ttl" if got.syntax else ".owl")
    resp = Response(got.data, mimetype="application/octet-stream")
    resp.headers["X-Filename"] = re.sub(r"[^A-Za-z0-9._-]+", "_", tail)
    resp.headers["X-Final-Url"] = got.url
    return resp


@app.get("/")
def index():
    return send_from_directory(STATIC, "index.html")


@app.get("/about")
def about():
    """Scholarly basis for the OWL→UML translation algorithms."""
    return send_from_directory(STATIC, "about.html")


@app.post("/api/render")
def render():
    fmt = request.form.get("format") or None
    fmt = None if fmt in (None, "", "auto") else fmt

    suffix = ".ttl"
    data: bytes | None = None
    if "file" in request.files:
        f = request.files["file"]
        if f.filename and "." in f.filename:
            suffix = "." + f.filename.rsplit(".", 1)[-1]
        data = f.read()
    elif request.form.get("text"):
        data = request.form["text"].encode("utf-8")

    if not data:
        return jsonify(error="no ontology provided"), 400
    if request.form.get("view") == "flow":
        return _render_flow(data, suffix, fmt)
    try:
        ops = _load_edits()
    except ValueError as exc:
        return jsonify(error=str(exc)), 400

    imports = request.form.get("imports") or "closure"
    imports = imports if imports in IMPORT_MODES else "closure"
    edit_report = None
    try:
        loaded = _load_upload(data, "upload" + suffix, fmt, imports)
        if ops:
            # edits change the uploaded ontology only, never its imports
            edit_report = editing.apply_edits(loaded.graph, ops)
        graph = loaded.merge()
        model = parse_ontology("upload" + suffix, graph=graph)
        annotate_model(model, loaded)
        engine_req = request.form.get("reason") or "none"
        if engine_req not in reason.ENGINES:
            engine_req = "none"
        inf = reason.classify(graph, engine_req)
        reason.apply(model, inf)
        # "keep_unused=1" keeps imported upper-level classes the ontology
        # never reaches (left out by default).
        report = postprocess(model, prune=request.form.get("keep_unused") not in ("1", "true", "on"))
    except LoadError as exc:
        return jsonify(error=str(exc), syntax=exc.syntax, line=exc.line), 400
    except Exception as exc:  # noqa: BLE001
        return jsonify(error=f"parse failed: {exc}"), 400

    try:
        if dot_available():
            # The OWL behind each class and line, for the source panel
            # ("source=0" leaves it out).
            src = None
            if request.form.get("source") not in ("0", "false", "off"):
                try:
                    src = build_source(graph, model)
                except Exception:  # noqa: BLE001 - the diagram matters more
                    src = None
            svg = render_dot_svg(model, source=src)
            engine = "graphviz"
        else:
            w, h = layout(model)
            svg = render_svg(model, w, h)
            engine = "builtin"
    except Exception as exc:  # noqa: BLE001
        return jsonify(error=f"render failed: {exc}"), 500

    return jsonify(
        svg=svg,
        engine=engine,
        classes=len(model.classes),
        edges=len(model.edges),
        pruned=report["pruned"],
        reasoning=inf.report(),
        edits=edit_report,
        loader=loaded.report(),
        groups=[
            {"name": g.name, "color": g.color, "count": g.count, "upper": g.upper,
             "iri": g.iri, "version_iri": g.version_iri}
            for g in sorted(model.groups.values(), key=lambda g: (g.upper, g.name))
        ],
    )


def _load_edits() -> list:
    """The edit-mode op list from the "edits" form field ([] when absent)."""
    raw = request.form.get("edits")
    if not raw:
        return []
    try:
        ops = json.loads(raw)
    except ValueError as exc:
        raise ValueError(f"edits: not valid JSON ({exc})") from None
    if not isinstance(ops, list):
        raise ValueError("edits: expected a list of operations")
    if len(ops) > editing.MAX_OPS:
        raise ValueError(f"edits: too many operations (max {editing.MAX_OPS})")
    return ops


_EXPORT = {"turtle": ("ttl", "text/turtle"), "xml": ("owl", "application/rdf+xml")}


@app.post("/api/export")
def export():
    """The uploaded ontology with the edit-mode ops applied, as a draft OWL file."""
    f = request.files.get("file")
    if not f:
        return jsonify(error="no ontology provided"), 400
    try:
        ops = _load_edits()
    except ValueError as exc:
        return jsonify(error=str(exc)), 400
    fmt = request.form.get("format") or None
    fmt = None if fmt in (None, "", "auto") else fmt
    out = request.form.get("fmt") or ("xml" if _suffix(f) in (".owl", ".rdf", ".xml") else "turtle")
    if out not in _EXPORT:
        return jsonify(error=f"unknown export format: {out}"), 400
    try:
        graph = _parse_upload(f.read(), _suffix(f), fmt)
        report = editing.apply_edits(graph, ops)
        body = editing.serialize(graph, out)
    except Exception as exc:  # noqa: BLE001
        return jsonify(error=f"export failed: {exc}"), 400
    ext, mime = _EXPORT[out]
    stem = (f.filename or "ontology").rsplit(".", 1)[0] or "ontology"
    stem = re.sub(r"[^A-Za-z0-9._-]+", "_", stem)
    resp = Response(body, mimetype=mime)
    resp.headers["Content-Disposition"] = f'attachment; filename="{stem}-edited.{ext}"'
    resp.headers["X-Edits-Applied"] = str(report["applied"])
    resp.headers["X-Edits-Skipped"] = str(len(report["skipped"]))
    return resp


def _parse_upload(data: bytes, suffix: str, fmt=None, imports: str = "none"):
    """The uploaded ontology as one graph (with its imports merged, if asked)."""
    return _load_upload(data, "upload" + suffix, fmt, imports).merge()


def _suffix(f) -> str:
    return "." + f.filename.rsplit(".", 1)[-1] if f.filename and "." in f.filename else ".ttl"


def _render_flow(data: bytes, suffix: str, fmt):
    """Flow view: the processes in swimlanes, optionally with logged events
    ("events" files) and SHACL rules ("shapes" file) checked against them."""
    from rdflib import Graph
    from owl2uml.flow import extract, load_map, render_flow_svg
    if not dot_available():
        return jsonify(error="the flow view needs Graphviz on the server"), 500
    try:
        tbox = _parse_upload(data, suffix, fmt, request.form.get("imports") or "closure")
        events = None
        for f in request.files.getlist("events"):
            events = events if events is not None else Graph()
            events += _parse_upload(f.read(), _suffix(f))
        shapes = None
        if "shapes" in request.files and request.files["shapes"].filename:
            f = request.files["shapes"]
            shapes = _parse_upload(f.read(), _suffix(f))
        fm = extract(tbox, events, shapes, load_map(None))
    except Exception as exc:  # noqa: BLE001
        return jsonify(error=f"parse failed: {exc}"), 400
    if not fm.steps:
        return jsonify(error="No process steps found. The flow view needs classes linked by "
                             "sequence relations, such as 'immediately preceded by' some X "
                             "(BFO/RO), on processes. Try the Classes view."), 400
    try:
        svg = render_flow_svg(fm, source=request.form.get("source") not in ("0", "false", "off"), tbox=tbox)
    except Exception as exc:  # noqa: BLE001
        return jsonify(error=f"render failed: {exc}"), 500
    s = fm.summary()
    return jsonify(svg=svg, engine="graphviz (flow)", view="flow", classes=s["steps"],
                   edges=len(fm.edges), flow=s, cases=sorted(fm.cases), pruned=0,
                   reasoning=None, groups=[])


def main() -> None:
    port = int(os.environ.get("PORT", "5000"))
    host = os.environ.get("HOST", "127.0.0.1")
    print(f"owl2uml web UI on http://{host}:{port}  (engine: "
          f"{'graphviz' if dot_available() else 'builtin'}; reasoner: "
          f"{'hermit' if reason.hermit_available() else 'owlrl'})")
    app.run(host=host, port=port, debug=False, threaded=True)


if __name__ == "__main__":
    main()
