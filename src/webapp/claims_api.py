"""POST /api/claims: the uploaded ontology's claims as English sentences
(``owl2uml claims``, docs/claims.md), for the web app's Claims panel.

The claims run starts two Java reasoners, so it runs in a subprocess with a
wall-clock limit, and one at a time per server (a second request gets 429).
"""
from __future__ import annotations

import fcntl
import json
import os
import subprocess
import sys
import tempfile

from flask import jsonify, request

from owl2uml.claims.signature import native_namespace
from owl2uml.load import LoadError

TIMEOUT = float(os.environ.get("CLAIMS_TIMEOUT_S", "100"))      # under gunicorn's 120 s
MAX_CHECKS = int(os.environ.get("CLAIMS_MAX_CHECKS", "30000"))   # NAO plans ~22,800
LOCK = os.path.join(tempfile.gettempdir(), "o2u-claims.lock")
SRC = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

HARD_STOPS = {
    4: "The ontology is inconsistent, so no claims were computed.",
    5: "HermiT and Pellet disagree on some checks, so nothing was adjudicated.",
    6: "The ontology is too large for the web claims check (over {n} reasoner checks "
       "planned). Run `owl2uml claims` locally with a larger --max-probes.",
}


def _suffix(f) -> str:
    return "." + f.filename.rsplit(".", 1)[-1] if f.filename and "." in f.filename else ".ttl"


def register(app, _load_upload) -> None:
    app.add_url_rule("/api/claims", "claims", lambda: _claims(_load_upload), methods=["POST"])


def _claims(_load_upload):
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

    lock = open(LOCK, "w")  # noqa: SIM115 - held for the whole run
    try:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            return jsonify(error="Another claims check is running on the server. "
                                 "Try again in a minute."), 429
        with tempfile.TemporaryDirectory(prefix="o2u-webclaims-") as tmp:
            path = os.path.join(tmp, "ontology.ttl")
            g.serialize(path, format="turtle")
            out = os.path.join(tmp, "out")
            cmd = [sys.executable, "-c",
                   "import sys; sys.path.insert(0, sys.argv[1]); "
                   "from owl2uml.claims.cli import main; sys.exit(main(sys.argv[2:]))",
                   SRC, path, "--out-dir", out, "--format", "jsonl,txt",
                   "--imports", "none", "--offline", "--max-probes", str(MAX_CHECKS)]
            ns = _native_ns(g, loaded.ontology_iri)
            if ns:
                cmd += ["--native-ns", ns]
            try:
                proc = subprocess.run(cmd, capture_output=True, text=True, timeout=TIMEOUT)
            except subprocess.TimeoutExpired:
                return jsonify(error=f"The claims check took longer than {TIMEOUT:.0f} s and was "
                                     "stopped. Run `owl2uml claims` locally for this ontology."), 504
            return _result(proc, out)
    finally:
        lock.close()


def _native_ns(g, ontology_iri: str) -> str:
    """The ontology IRI's namespace; without one, the namespace most of the
    named classes share (an upload has no file path to fall back on)."""
    if ontology_iri:
        return native_namespace(ontology_iri)
    from collections import Counter
    from rdflib import OWL, RDF, URIRef
    counts = Counter(native_namespace(str(c)) for c in g.subjects(RDF.type, OWL.Class)
                     if isinstance(c, URIRef))
    return counts.most_common(1)[0][0] if counts else ""


def _read(path: str) -> str | None:
    try:
        with open(path, encoding="utf-8") as fh:
            return fh.read()
    except OSError:
        return None


def _result(proc, out: str):
    msgs = [ln[len("warning: "):] for ln in proc.stderr.splitlines() if ln.startswith("warning: ")]
    if proc.returncode != 0:
        errs = [ln[len("error: "):] for ln in proc.stderr.splitlines() if ln.startswith("error: ")]
        msg = HARD_STOPS.get(proc.returncode, "").format(n=MAX_CHECKS)
        detail = _read(os.path.join(out, "inconsistency.txt")) or ""
        return jsonify(error=msg or (errs[-1] if errs else proc.stderr.strip()[-500:]
                                     or f"claims failed (exit {proc.returncode})"),
                       detail=detail, warnings=msgs), 400
    jl = _read(os.path.join(out, "claims.jsonl")) or ""
    recs = [json.loads(ln) for ln in jl.splitlines() if ln.strip()]
    report = json.loads(_read(os.path.join(out, "report.json")) or "{}")
    return jsonify(claims=recs, report=report, txt=_read(os.path.join(out, "claims.txt")) or "",
                   jsonl=jl, warnings=msgs)
