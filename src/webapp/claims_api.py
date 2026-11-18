"""/api/claims: the uploaded ontology's claims as English sentences
(``owl2uml claims``, docs/claims.md), for the web app's Claims panel.

POST /api/claims starts a background job (claims_job.py) and returns its id;
GET /api/claims/<id> reports progress and, once done, the claims. The
reasoners can take minutes on an ordinary ontology, longer than one HTTP
request may last. Runs are serialised (two Java reasoners per run). An
ontology over the check budget, or one the reasoners do not finish in time,
still gets its assertions, with a note saying why the inferences are missing.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import uuid
from collections import Counter

from flask import jsonify, request
from rdflib import OWL, RDF, URIRef

from owl2uml.claims import analyze, signature
from owl2uml.load import LoadError

TIMEOUT = float(os.environ.get("CLAIMS_TIMEOUT_S", "600"))
MAX_CHECKS = int(os.environ.get("CLAIMS_MAX_CHECKS", "500000"))
JOBS = os.path.join(tempfile.gettempdir(), "o2u-claims-jobs")
LOCK = os.path.join(tempfile.gettempdir(), "o2u-claims.lock")
KEEP_S = 3600                         # finished jobs are removed after an hour
RUNNER = os.path.join(os.path.dirname(os.path.abspath(__file__)), "claims_job.py")
_ID = re.compile(r"^[0-9a-f]{32}$")

HARD_STOPS = {
    4: "The ontology is inconsistent, so no claims were computed.",
    5: "HermiT and Pellet disagree on some checks, so nothing was adjudicated.",
}


def _suffix(f) -> str:
    return "." + f.filename.rsplit(".", 1)[-1] if f.filename and "." in f.filename else ".ttl"


def register(app, _load_upload) -> None:
    app.add_url_rule("/api/claims", "claims", lambda: _start(_load_upload), methods=["POST"])
    app.add_url_rule("/api/claims/<job>", "claims_job", _status, methods=["GET"])


def _native_ns(g, ontology_iri: str) -> str:
    """The ontology IRI's namespace; without one, the namespace most of the
    named classes share (an upload has no file path to fall back on)."""
    if ontology_iri:
        return signature.native_namespace(ontology_iri)
    counts = Counter(signature.native_namespace(str(c)) for c in g.subjects(RDF.type, OWL.Class)
                     if isinstance(c, URIRef))
    return counts.most_common(1)[0][0] if counts else ""


def _sweep() -> None:
    now = time.time()
    try:
        names = os.listdir(JOBS)
    except OSError:
        return
    for name in names:
        path = os.path.join(JOBS, name)
        try:
            if now - os.path.getmtime(path) > KEEP_S:
                shutil.rmtree(path, ignore_errors=True)
        except OSError:
            pass


def _start(_load_upload):
    f = request.files.get("file")
    if not f:
        return jsonify(error="no ontology uploaded"), 400
    fmt = request.form.get("format") or None
    fmt = None if fmt in (None, "", "auto") else fmt
    imports = request.form.get("imports") or "closure"
    try:
        loaded = _load_upload(f.read(), "upload" + _suffix(f), fmt, imports)
        g = loaded.merge()
    except LoadError as exc:
        return jsonify(error=str(exc), syntax=exc.syntax, line=exc.line), 400
    except Exception as exc:  # noqa: BLE001
        return jsonify(error=f"parse failed: {exc}"), 400

    ns = _native_ns(g, loaded.ontology_iri)
    sig = signature.build(g, [ns]) if ns else None
    if not sig or not sig.native:
        return jsonify(error="The ontology declares no classes of its own, so there are no "
                             "claims to list."), 400
    planned = sum(analyze.plan(sig, 0).values())
    mode, note = "full", None
    if planned > MAX_CHECKS:
        mode = "assertions"
        note = (f"The ontology is too large for the web reasoner check ({planned:,} checks "
                f"planned, the limit is {MAX_CHECKS:,}), so only the assertions are listed. "
                "Run `owl2uml claims` locally for the inferences.")

    _sweep()
    job = uuid.uuid4().hex
    path = os.path.join(JOBS, job)
    os.makedirs(path, exist_ok=True)
    g.serialize(os.path.join(path, "ontology.ttl"), format="turtle")
    meta = {"mode": mode, "note": note, "planned": planned, "native_ns": ns,
            "classes": len(sig.native), "max_checks": max(MAX_CHECKS, planned),
            "timeout": TIMEOUT, "lock": LOCK, "created": time.time()}
    with open(os.path.join(path, "meta.json"), "w", encoding="utf-8") as fh:
        json.dump(meta, fh)
    with open(os.path.join(path, "state.json"), "w", encoding="utf-8") as fh:
        json.dump({"state": "queued", "mode": mode}, fh)
    subprocess.Popen([sys.executable, RUNNER, path], stdin=subprocess.DEVNULL,  # noqa: S603
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    return jsonify(job=job, mode=mode, planned=planned, classes=len(sig.native),
                   timeout=TIMEOUT), 202


def _read(path: str) -> str | None:
    try:
        with open(path, encoding="utf-8") as fh:
            return fh.read()
    except OSError:
        return None


def _status(job: str):
    if not _ID.match(job):
        return jsonify(error="unknown claims job"), 404
    path = os.path.join(JOBS, job)
    meta = json.loads(_read(os.path.join(path, "meta.json")) or "null")
    st = json.loads(_read(os.path.join(path, "state.json")) or "null")
    if meta is None or st is None:
        return jsonify(error="This claims job has expired. Open the ontology again."), 404
    now = time.time()
    base = {"job": job, "state": st["state"], "mode": st.get("mode", meta["mode"]),
            "planned": meta["planned"], "classes": meta["classes"], "timeout": meta["timeout"],
            "elapsed": round(now - (st.get("started") or meta["created"]), 1),
            "waited": round(now - meta["created"], 1)}
    if st["state"] != "done":
        return jsonify(base)

    out = os.path.join(path, "out")
    log = _read(os.path.join(path, "stderr.log")) or ""
    warnings = [ln[len("warning: "):] for ln in log.splitlines() if ln.startswith("warning: ")]
    rc = st.get("rc")
    if rc != 0:
        errs = [ln[len("error: "):] for ln in log.splitlines() if ln.startswith("error: ")]
        msg = HARD_STOPS.get(rc) or (errs[-1] if errs else st.get("crash")) \
            or f"the claims check failed (exit {rc})"
        detail = _read(os.path.join(out, "inconsistency.txt")) or ""
        return jsonify(error=msg, detail=detail, warnings=warnings, **base), 200
    jl = _read(os.path.join(out, "claims.jsonl")) or ""
    return jsonify(claims=[json.loads(ln) for ln in jl.splitlines() if ln.strip()],
                   report=json.loads(_read(os.path.join(out, "report.json")) or "{}"),
                   txt=_read(os.path.join(out, "claims.txt")) or "", jsonl=jl,
                   warnings=warnings, note=st.get("note"), **base)
