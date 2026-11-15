"""Load an ontology, in any OWL 2 syntax and with its imports, into rdflib (WS1.1).

* RDF syntaxes (Turtle, RDF/XML, N3, N-Triples, JSON-LD, TriG) are read by
  rdflib directly; no JVM is started.
* OWL/XML, Manchester, Functional and OBO are converted to Turtle by the
  O2uConvert helper on the OWL API inside robot.jar (``tools.convert_cmd``).
  ``loader="robot"`` sends RDF/XML and Turtle through it too.
* ``imports``: ``none``, ``direct`` or ``closure`` (default). Each import is
  looked up in the XML catalog, then the local directory, then the network.
  A failed import is a warning, not an error: the ontology still draws.

The main ontology's triples (``Loaded.graph``) are kept apart from the
imported ones (``Loaded.imported``) so edits apply to the main ontology only;
``Loaded.merge()`` adds the imports in place before modelling.
"""
from __future__ import annotations

import functools
import os
import re
import subprocess
import tempfile
import time
import urllib.parse
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path

from rdflib import Graph, OWL, RDF, URIRef

from . import tools
from .fetch import Catalog, FetchError, fetch

# key -> (display name, rdflib format or None, O2uConvert syntax or None)
SYNTAXES = {
    "turtle": ("Turtle", "turtle", "ttl"),
    "xml": ("RDF/XML", "xml", "rdfxml"),
    "n3": ("N3", "n3", None),
    "nt": ("N-Triples", "nt", None),
    "json-ld": ("JSON-LD", "json-ld", None),
    "trig": ("TriG", "trig", None),
    "owx": ("OWL/XML", None, "owx"),
    "omn": ("Manchester", None, "omn"),
    "ofn": ("Functional", None, "ofn"),
    "obo": ("OBO", None, "obo"),
}
_ALIASES = {
    "ttl": "turtle", "rdf": "xml", "rdfxml": "xml", "rdf/xml": "xml", "application/rdf+xml": "xml",
    "jsonld": "json-ld", "ntriples": "nt", "n-triples": "nt", "owl/xml": "owx", "owlxml": "owx",
    "manchester": "omn", "functional": "ofn", "ofn": "ofn", "fss": "ofn",
}
_EXTENSIONS = {
    ".ttl": "turtle", ".rdf": "xml", ".xml": "xml", ".n3": "n3", ".nt": "nt",
    ".jsonld": "json-ld", ".json": "json-ld", ".trig": "trig",
    ".owx": "owx", ".omn": "omn", ".ofn": "ofn", ".obo": "obo",
}
IMPORT_MODES = ("none", "direct", "closure")
LOADERS = ("auto", "robot", "rdflib")
_DECLARED = (OWL.Class, OWL.ObjectProperty, OWL.DatatypeProperty, OWL.AnnotationProperty,
             OWL.NamedIndividual)


class LoadError(ValueError):
    """A load failure; ``syntax`` and ``line`` say where, when known."""

    def __init__(self, message: str, syntax: str | None = None, line: int | None = None):
        super().__init__(message)
        self.syntax, self.line = syntax, line


@dataclass
class Loaded:
    graph: Graph                      # the main ontology only
    imported: Graph                   # every resolved import, merged
    source: str                       # path or IRI it was loaded from
    syntax: str                       # display name, e.g. "Manchester"
    loader: str                       # "rdflib" or "robot"
    ontology_iri: str = ""
    version_iri: str = ""
    imports: list[dict] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    origin: dict[str, str] = field(default_factory=dict)   # entity IRI -> import ontology IRI

    def merge(self) -> Graph:
        """Add the imported triples to ``graph`` (in place) and return it."""
        if len(self.imported):
            self.graph += self.imported
            self.imported = Graph()
        return self.graph

    def report(self) -> dict:
        return {"loader": self.loader, "syntax": self.syntax, "source": self.source,
                "ontology_iri": self.ontology_iri, "version_iri": self.version_iri,
                "imports": self.imports, "warnings": self.warnings}


# --------------------------------------------------------------------------
# syntax detection

def normalize_format(fmt: str | None) -> str | None:
    if not fmt or fmt == "auto":
        return None
    key = _ALIASES.get(fmt.lower(), fmt.lower())
    if key not in SYNTAXES:
        raise LoadError(f"unknown input format '{fmt}' (known: {', '.join(SYNTAXES)})")
    return key


def sniff(data: bytes) -> str | None:
    """Guess the syntax from the first few KB of a document."""
    text = data[:8192].decode("utf-8", "replace").lstrip("﻿")
    body = "\n".join(ln for ln in text.splitlines()
                     if ln.strip() and not ln.lstrip().startswith(("#", "//")))
    s = body.lstrip()
    if s.startswith(("{", "[")):
        return "json-ld" if s.startswith("{") or '"@' in s[:2000] else "obo"
    if s.startswith("<"):
        if re.search(r"<(rdf:)?RDF\b", text):
            return "xml"
        if re.search(r"<Ontology\b", text) and "http://www.w3.org/2002/07/owl#" in text:
            return "owx"
        return "xml" if s.startswith("<?xml") else "turtle"
    if re.match(r"(Prefix\s*\(|Ontology\s*\()", s):
        return "ofn"
    if re.match(r"(Prefix:|Ontology:|Class:|ObjectProperty:)", s):
        return "omn"
    if re.match(r"(format-version:|data-version:|ontology:|\[Term\]|\[Typedef\])", s):
        return "obo"
    if re.match(r"(@prefix|@base|PREFIX\s|BASE\s)", s, re.I):
        return "turtle"
    return None


def _guess(data: bytes, name: str, fmt: str | None, hint: str | None = None) -> str | None:
    return (normalize_format(fmt) or sniff(data) or hint
            or _EXTENSIONS.get(os.path.splitext(name.lower())[1]))


# --------------------------------------------------------------------------
# parsing one document

_LINE = (re.compile(r"\bline[\s:]+(\d+)", re.I), re.compile(r":(\d+):\d+:"))


def _line_of(text: str) -> int | None:
    for rx in _LINE:
        m = rx.search(text)
        if m and int(m.group(1)) > 0:
            return int(m.group(1))
    return None


def _error(key: str, detail: str) -> LoadError:
    name = SYNTAXES[key][0] if key in SYNTAXES else key
    detail = " ".join(detail.split())
    if len(detail) > 400:
        detail = detail[:400] + "…"
    line = _line_of(detail)
    where = f" at line {line}" if line else ""
    return LoadError(f"{name} syntax error{where}: {detail}", syntax=name, line=line)


def _rdflib(data: bytes, key: str, base: str | None) -> Graph:
    g = Graph()
    g.parse(data=data, format=SYNTAXES[key][1], publicID=base)
    return g


def _helper(data: bytes, key: str, deadline: float, copies: dict | None = None) -> Graph:
    """Convert with O2uConvert (OWL API) and read the Turtle it writes.
    ``copies`` maps import IRIs to local RDF/XML files the OWL API may read."""
    cmd = tools.convert_cmd()
    name, _, syntax = SYNTAXES[key]
    if cmd is None:
        raise LoadError(f"{name} syntax needs Java and ROBOT on the server/PATH "
                        "(run scripts/setup.sh), or re-export the ontology as RDF/XML or Turtle",
                        syntax=name)
    with tempfile.TemporaryDirectory(prefix="o2u-") as tmp:
        src, out = Path(tmp, "in." + syntax), Path(tmp, "out.ttl")
        src.write_bytes(data)
        try:
            extra = [f"{iri}={path}" for iri, path in (copies or {}).items()]
            r = subprocess.run(cmd + [syntax, str(src), str(out)] + extra, capture_output=True,
                               timeout=max(1.0, deadline - time.monotonic()))
        except subprocess.TimeoutExpired:
            raise LoadError(f"timed out converting {name} syntax", syntax=name) from None
        if r.returncode != 0 or not out.exists():
            msg = r.stderr.decode("utf-8", "replace")
            raise _error(key, _helper_detail(msg) or msg.strip() or "conversion failed")
        g = Graph()
        g.parse(str(out), format="turtle")
        return g


def _helper_detail(stderr: str) -> str:
    """The informative part of an OWL API parse failure."""
    lines = [ln.strip() for ln in stderr.splitlines() if ln.strip()]
    for i, ln in enumerate(lines):
        if ln.startswith(("Encountered", "Was expecting")) or re.search(r"\bline \d+", ln, re.I):
            if "Problem parsing" in ln:
                continue
            return " ".join(lines[i:i + 4])
    head = next((ln for ln in lines if ln.startswith("O2U-ERROR:")), "")
    return head.replace("O2U-ERROR:", "").strip()


def parse_document(data: bytes, name: str = "", fmt: str | None = None, loader: str = "auto",
                   base: str | None = None, deadline: float | None = None,
                   hint: str | None = None, copies: dict | None = None) -> tuple[Graph, str, str]:
    """Parse one document. Returns (graph, syntax key, loader used)."""
    deadline = deadline or time.monotonic() + 60
    explicit = normalize_format(fmt)
    key = _guess(data, name, fmt, hint)
    if key and (SYNTAXES[key][1] is None or (loader == "robot" and SYNTAXES[key][2])):
        return _helper(data, key, deadline, copies), key, "robot"
    if loader == "robot" and key is None and tools.convert_cmd():
        for k in ("owx", "ofn", "omn", "obo"):
            try:
                return _helper(data, k, deadline), k, "robot"
            except LoadError:
                continue
    first: LoadError | None = None
    order = [key] if key else []
    if not explicit:
        order += [k for k in ("turtle", "xml", "json-ld", "n3", "nt", "trig")
                  if k not in order]
    for k in order:
        if SYNTAXES[k][1] is None:
            continue
        try:
            return _rdflib(data, k, base), k, "rdflib"
        except Exception as exc:  # noqa: BLE001 - rdflib raises many types
            first = first or _error(k, str(exc))
    if not explicit and key is None and tools.convert_cmd():
        for k in ("ofn", "omn", "owx"):
            try:
                return _helper(data, k, deadline), k, "robot"
            except LoadError:
                continue
    raise first or LoadError("could not recognise the ontology syntax")


# --------------------------------------------------------------------------
# imports

def _ontology_ids(g: Graph) -> tuple[str, str, list[str]]:
    """(ontology IRI, version IRI, imported IRIs) of a single-ontology graph."""
    onts = sorted((o for o in g.subjects(RDF.type, OWL.Ontology) if isinstance(o, URIRef)),
                  key=str)
    if not onts:
        imps = sorted({str(o) for o in g.objects(None, OWL.imports)})
        return "", "", imps
    o = onts[0]
    ver = next((str(v) for v in g.objects(o, OWL.versionIRI)), "")
    imps = sorted({str(i) for i in g.objects(o, OWL.imports) if isinstance(i, URIRef)})
    return str(o), ver, imps


def _local_candidates(iri: str, base_dir: str) -> list[str]:
    tail = urllib.parse.urlsplit(iri).path.rstrip("/").rsplit("/", 1)[-1]
    if not tail:
        return []
    names = [tail] if "." in tail else [tail + e for e in (".owl", ".ttl", ".ofn", ".omn", ".obo")]
    return [os.path.join(base_dir, n) for n in names]


def load(source: str | None = None, *, data: bytes | None = None, name: str = "",
         fmt: str | None = None, imports: str = "closure", loader: str = "auto",
         catalog: str | None = None, allow_network: bool = True, allow_private: bool = True,
         timeout: float = 60.0, max_bytes: int = 25 * 2**20, max_imports: int = 50) -> Loaded:
    """Load ``source`` (a path or an http(s) IRI), or ``data`` named ``name``."""
    if imports not in IMPORT_MODES:
        raise LoadError(f"--imports must be one of {', '.join(IMPORT_MODES)}")
    if loader not in LOADERS:
        raise LoadError(f"--loader must be one of {', '.join(LOADERS)}")
    deadline = time.monotonic() + timeout
    base_dir, base, hint = None, None, None
    if data is None:
        if not source:
            raise LoadError("no ontology given")
        if re.match(r"https?://", source):
            got = _fetch(source, max_bytes, deadline, allow_private)
            data, base, hint, name = got.data, got.url, got.syntax, name or got.url
        else:
            p = Path(source)
            if not p.is_file():
                raise LoadError(f"no such file: {source}")
            if p.stat().st_size > max_bytes:
                raise LoadError(f"{source} is larger than the {max_bytes // 2**20} MB limit")
            data, name = p.read_bytes(), name or p.name
            base_dir, base = str(p.resolve().parent), p.resolve().as_uri()
    out = Loaded(graph=Graph(), imported=Graph(), source=source or name, syntax="", loader="")
    resolve = functools.partial(_resolve_imports, out, mode=imports,
                                cat=_catalog(catalog, base_dir, out), base_dir=base_dir,
                                allow_network=allow_network, allow_private=allow_private,
                                deadline=deadline, max_bytes=max_bytes, max_imports=max_imports)
    docs, early = [], []
    if imports != "none" and _guess(data, name, fmt, hint) == "omn":
        # Manchester rejects names declared only in an import, so its imports
        # are resolved before parsing and handed to the OWL API as local copies.
        early = sorted(set(_OMN_IMPORT.findall(data.decode("utf-8", "replace"))))
        docs = resolve(early) if early else []
    with tempfile.TemporaryDirectory(prefix="o2u-imports-") as tmp:
        copies = _write_copies(docs, tmp)
        graph, key, used = parse_document(data, name, fmt, loader, base, deadline, hint, copies)
    iri, ver, direct = _ontology_ids(graph)
    out.graph, out.syntax, out.loader = graph, SYNTAXES[key][0], used
    out.ontology_iri, out.version_iri = iri, ver
    if imports != "none" and direct and not early:
        docs = resolve(direct)
    _absorb(out, docs)
    return out


_OMN_IMPORT = re.compile(r"^\s*Import:\s*<([^>]+)>", re.M)


def _write_copies(docs: list, tmp: str) -> dict:
    """RDF/XML files of the resolved imports, keyed by the IRI they were imported as."""
    copies = {}
    for n, (requested, _src, g) in enumerate(docs):
        path = os.path.join(tmp, f"import{n}.owl")
        g.serialize(path, format="xml")
        copies[requested] = path
    return copies


def _absorb(out: Loaded, docs: list) -> None:
    """Merge resolved imports into ``out.imported`` and record where each
    entity not declared in the main ontology comes from."""
    main_decl = {str(s) for t in _DECLARED for s in out.graph.subjects(RDF.type, t)}
    for _requested, src, g in docs:
        for t in _DECLARED:
            for s in g.subjects(RDF.type, t):
                k = str(s)
                if isinstance(s, URIRef) and k not in main_decl and k not in out.origin:
                    out.origin[k] = src
        for t in g:
            if not (t[1] == RDF.type and t[2] == OWL.Ontology) and t[1] not in (
                    OWL.imports, OWL.versionIRI):
                out.imported.add(t)


def _fetch(url, max_bytes, deadline, allow_private):
    left = deadline - time.monotonic()
    if left <= 0:
        raise LoadError(f"time limit reached before loading {url}")
    try:
        return fetch(url, max_bytes=max_bytes, timeout=min(left, 30.0),
                     allow_private=allow_private)
    except FetchError as exc:
        raise LoadError(str(exc)) from None


def _catalog(path: str | None, base_dir: str | None, out: Loaded) -> Catalog | None:
    path = path or (os.path.join(base_dir, "catalog-v001.xml") if base_dir else None)
    if not path or not os.path.exists(path):
        return None
    try:
        return Catalog(path)
    except Exception as exc:  # noqa: BLE001 - a broken catalog is not fatal
        out.warnings.append(f"could not read catalog {path}: {exc}")
        return None


def _resolve_imports(out: Loaded, direct: list[str], *, mode: str, cat: Catalog | None,
                     base_dir: str | None, allow_network: bool, allow_private: bool,
                     deadline: float, max_bytes: int, max_imports: int) -> list:
    """Load the imports, breadth first. Returns [(requested IRI, ontology IRI, graph)]."""
    docs = []
    seen = {out.ontology_iri, *direct}
    queue = deque((iri, base_dir, 1) for iri in direct)
    while queue:
        iri, where, depth = queue.popleft()
        info = {"iri": iri, "ontology_iri": "", "version_iri": "", "depth": depth,
                "resolved_by": "unresolved", "location": "", "error": ""}
        out.imports.append(info)
        if len(out.imports) > max_imports:
            info["error"] = f"skipped: more than {max_imports} imports"
            continue
        try:
            g, info["resolved_by"], info["location"], next_dir = _load_import(
                iri, cat, where, allow_network, allow_private, deadline, max_bytes)
        except LoadError as exc:
            info["error"] = str(exc)
            out.warnings.append(f"import {iri} not loaded: {exc}")
            continue
        oiri, ver, nested = _ontology_ids(g)
        info["ontology_iri"], info["version_iri"] = oiri, ver
        docs.append((iri, oiri or iri, g))
        if mode == "closure":
            for n in nested:
                if n not in seen:
                    seen.add(n)
                    queue.append((n, next_dir, depth + 1))
    return docs


def _load_import(iri, cat, where, allow_network, allow_private, deadline, max_bytes):
    """Returns (graph, how, location, directory for nested lookups)."""
    if time.monotonic() > deadline:
        raise LoadError("time limit reached")
    target = cat.resolve(iri) if cat else None
    if target and "://" not in target:
        if not os.path.exists(target):
            raise LoadError(f"catalog points to a missing file: {target}")
        return _parse_file(target, deadline), "catalog", target, os.path.dirname(target)
    if where:
        for cand in _local_candidates(iri, where):
            if os.path.isfile(cand):
                return _parse_file(cand, deadline), "local", cand, os.path.dirname(cand)
    url = target or iri
    if not allow_network:
        raise LoadError("not in the catalog or local directory, and network loading is off")
    got = _fetch(url, max_bytes, deadline, allow_private)
    g, _, _ = parse_document(got.data, got.url, None, "auto", got.url, deadline, got.syntax)
    return g, "network", got.url, where


def _parse_file(path: str, deadline: float) -> Graph:
    p = Path(path)
    g, _, _ = parse_document(p.read_bytes(), p.name, None, "auto", p.resolve().as_uri(), deadline)
    return g


def annotate_model(m, loaded: Loaded) -> None:
    """Copy what the loader learned onto a UModel built from ``loaded``."""
    if loaded.ontology_iri:
        m.ontology_iri = loaded.ontology_iri
    m.imports = list(loaded.imports)
    m.import_of = dict(loaded.origin)
