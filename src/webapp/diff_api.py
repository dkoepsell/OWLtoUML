"""POST /api/diff: two uploaded versions of an ontology -> one diagram of what
changed, the change set and a Markdown summary (spec WS4)."""
from __future__ import annotations

from flask import jsonify, request

from owl2uml import reason
from owl2uml.diff.build import run
from owl2uml.diff.render import SCOPES
from owl2uml.diff.report import markdown
from owl2uml.dot import dot_available
from owl2uml.load import LoadError


def _suffix(f) -> str:
    return "." + f.filename.rsplit(".", 1)[-1] if f.filename and "." in f.filename else ".ttl"


def register(app, _load_upload, _pins, _profile, _int_form) -> None:
    """Add the route; the server passes its upload helpers (it runs both as
    a script and as the webapp.server module, so no import back)."""
    app.add_url_rule("/api/diff", "diff", lambda: _diff(_load_upload, _pins, _profile, _int_form),
                     methods=["POST"])


def _diff(_load_upload, _pins, _profile, _int_form):
    old, new = request.files.get("old"), request.files.get("new")
    if not old or not new:
        return jsonify(error="choose both versions: the older and the newer file"), 400
    if not dot_available():
        return jsonify(error="the diff view needs Graphviz on the server"), 500
    engine = request.form.get("reason") or "none"
    engine = engine if engine in reason.ENGINES else "none"
    scope = request.form.get("scope") or "1hop"
    scope = scope if scope in SCOPES else "1hop"
    imports = request.form.get("imports") or "closure"
    try:
        lo = _load_upload(old.read(), "old" + _suffix(old), None, imports)
        ln = _load_upload(new.read(), "new" + _suffix(new), None, imports)
        prof = _profile(request.form.get("profile") or "none", ln.merge())
        res = run(lo, ln, names=(old.filename or "old", new.filename or "new"), engine=engine,
                  profile=",".join(n for n in prof.names if n != "ontology") if prof else "",
                  scope=scope, pins=_pins(), screen=True,
                  label_width=_int_form("label_width", 22, 0, 80))
    except LoadError as exc:
        return jsonify(error=str(exc), syntax=exc.syntax, line=exc.line), 400
    except Exception as exc:  # noqa: BLE001
        return jsonify(error=f"diff failed: {exc}"), 400
    d = res.data
    return jsonify(svg=res.svg, engine="graphviz", view="diff", diff=d, summary=d["summary"],
                   markdown=markdown(d), classes=res.report.get("classes", 0),
                   edges=res.report.get("edges", 0), reasoning=None, groups=[])
