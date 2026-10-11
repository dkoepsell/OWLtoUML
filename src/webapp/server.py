"""Flask web UI: upload an OWL/TTL ontology, get an interactive UML SVG.

Layout is done server-side with Graphviz (scales to large ontologies);
the browser handles pan/zoom/search.
"""
from __future__ import annotations

import os
import sys
import tempfile

from flask import Flask, request, jsonify, send_from_directory

# Make the sibling `owl2uml` package importable.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from owl2uml.parse import parse_ontology          # noqa: E402
from owl2uml.dot import dot_available, render_dot_svg  # noqa: E402
from owl2uml.layout import layout                  # noqa: E402
from owl2uml.render import render_svg              # noqa: E402

STATIC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")

app = Flask(__name__, static_folder=STATIC, static_url_path="/static")
# Upload cap. Override with MAX_UPLOAD_MB (default 25 MB — safe for a public
# endpoint; keep it <= nginx client_max_body_size).
_max_mb = int(os.environ.get("MAX_UPLOAD_MB", "25"))
app.config["MAX_CONTENT_LENGTH"] = _max_mb * 1024 * 1024


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

    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(
            delete=False, suffix=suffix, mode="wb"
        ) as tmp:
            tmp.write(data)
            tmp_path = tmp.name

        model = parse_ontology(tmp_path, fmt=fmt)
    except Exception as exc:  # noqa: BLE001
        return jsonify(error=f"parse failed: {exc}"), 400
    finally:
        if tmp_path and os.path.exists(tmp_path):
            os.unlink(tmp_path)

    try:
        if dot_available():
            svg = render_dot_svg(model)
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
    )


def main() -> None:
    port = int(os.environ.get("PORT", "5000"))
    host = os.environ.get("HOST", "127.0.0.1")
    print(f"owl2uml web UI on http://{host}:{port}  (engine: "
          f"{'graphviz' if dot_available() else 'builtin'})")
    app.run(host=host, port=port, debug=False, threaded=True)


if __name__ == "__main__":
    main()
