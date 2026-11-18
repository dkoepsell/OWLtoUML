"""``owl2uml claims INPUT``: the ontology's claims as English sentences.

Writes claims.jsonl (the full records), claims.tsv and claims.txt (both
projections of it) and report.json (check counts, timings, warnings) into
--out-dir. See docs/claims.md.

Exit codes: 0 done; 1 load or reasoner failure; 2 usage (including an SVG
given as input); 4 H2 inconsistent ontology; 5 H3 reasoners disagree;
6 H4 check budget exceeded.
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import os
import re
import sys
import tempfile
import time

from ..load import IMPORT_MODES, LOADERS, load
from . import DEFAULT_TIERS, TIERS, analyze, classify, explain, records, signature
from .expect import ExpectError, load as load_expect
from .verbalize import Verbalizer

EXIT_LOAD, EXIT_USAGE, EXIT_INCONSISTENT, EXIT_DISAGREE, EXIT_BUDGET = 1, 2, 4, 5, 6
DEFAULT_MAX_CHECKS = 50000
FORMATS = ("jsonl", "tsv", "txt")


def _stem(path: str) -> str:
    base = os.path.basename(path.rstrip("/"))
    return base.rsplit(".", 1)[0] if "." in base else base


def svg_source_iri(path: str) -> str | None:
    """The ontology an owl2uml SVG was drawn from, if the path is such an SVG."""
    try:
        with open(path, "rb") as fh:
            head = fh.read(4096).decode("utf-8", "replace")
    except OSError:
        return None
    if not (path.lower().endswith(".svg") or "<svg" in head):
        return None
    with open(path, encoding="utf-8", errors="replace") as fh:
        text = fh.read()
    m = re.search(r'id="o2u-source"[^>]*>\s*(\{.*?\})\s*</script>', text, re.S)
    if m:
        try:
            return json.loads(m.group(1)).get("ontology") or ""
        except ValueError:
            pass
    m = re.search(r'"ontology"\s*:\s*"([^"]+)"', text)
    return m.group(1) if m else ""


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(
        prog="owl2uml claims",
        description="List what an ontology asserts, entails, allows and leaves open, as plain-"
                    "English sentences with their status, IRIs and justifications. "
                    "Needs Java with ROBOT (HermiT) and owlready2 (Pellet).")
    ap.add_argument("input", help="the ontology (any syntax owl2uml reads; not an SVG)")
    ap.add_argument("--out-dir", metavar="DIR",
                    help="where to write the claims (default ./claims-<input stem>/)")
    ap.add_argument("--format", default=",".join(FORMATS), metavar="LIST",
                    help="any of jsonl, tsv, txt (default: all three)")
    ap.add_argument("--native-ns", nargs="+", metavar="IRI",
                    help="namespaces whose classes are the ontology's own (default: the "
                         "namespace of the ontology IRI)")
    ap.add_argument("--tiers", default=",".join(DEFAULT_TIERS), metavar="LIST",
                    help=f"tiers to write: {', '.join(TIERS)} (default: all but inherited)")
    ap.add_argument("--reduce", choices=("none", "filler"), default="filler",
                    help="drop claims a stronger claim implies (filler, default) or keep all")
    ap.add_argument("--expect", metavar="FILE",
                    help="candidate axioms in Manchester syntax, one per line (G6)")
    ap.add_argument("--reasoners", default="hermit,pellet", metavar="LIST",
                    help="reasoners to run and cross-check (default hermit,pellet)")
    ap.add_argument("--max-probes", type=int, default=DEFAULT_MAX_CHECKS, metavar="N",
                    help="stop before reasoning when the planned checks exceed N "
                         f"(default {DEFAULT_MAX_CHECKS})")
    ap.add_argument("--max-explain", type=int, default=200, metavar="N",
                    help="justifications to compute at most (default 200)")
    ap.add_argument("--no-explain", action="store_true", help="skip justifications")
    ap.add_argument("--verb-map", metavar="FILE",
                    help="TSV: property IRI or label -> verb phrase (e.g. 'is a bearer of')")
    ap.add_argument("--article-map", metavar="FILE", help="TSV: label -> article")
    ap.add_argument("--imports", choices=IMPORT_MODES, default="closure")
    ap.add_argument("--catalog", metavar="FILE")
    ap.add_argument("--loader", choices=LOADERS, default="auto")
    ap.add_argument("--offline", action="store_true", help="never fetch imports")
    ap.add_argument("-f", "--input-format", dest="fmt", help="input syntax, as for owl2uml -f")
    args = ap.parse_args(argv)

    src = svg_source_iri(args.input)
    if src is not None:
        where = f" Run claims on its source ontology instead: {src}" if src else ""
        print(f"error: {args.input} is an owl2uml diagram, not an ontology. A diagram is a "
              f"projection that leaves axioms out, so claims are never computed from it.{where}",
              file=sys.stderr)
        return EXIT_USAGE
    tiers = [t.strip() for t in args.tiers.split(",") if t.strip()]
    fmts = [f.strip() for f in args.format.split(",") if f.strip()]
    engines = [e.strip() for e in args.reasoners.split(",") if e.strip()]
    for name, got, known in (("--tiers", tiers, TIERS), ("--format", fmts, FORMATS),
                             ("--reasoners", engines, classify.ENGINES)):
        bad = [x for x in got if x not in known]
        if bad or not got:
            print(f"error: {name}: unknown {', '.join(bad) or '(empty)'} "
                  f"(choose from {', '.join(known)})", file=sys.stderr)
            return EXIT_USAGE
    out_dir = args.out_dir or os.path.join(".", f"claims-{_stem(args.input)}")

    try:
        loaded = load(args.input, fmt=args.fmt, imports=args.imports, loader=args.loader,
                      catalog=args.catalog, allow_network=not args.offline)
        g = loaded.merge()
    except Exception as exc:  # noqa: BLE001
        print(f"error: failed to load '{args.input}': {exc}", file=sys.stderr)
        return EXIT_LOAD
    for w in loaded.warnings:
        print(f"warning: {w}", file=sys.stderr)
    namespaces = args.native_ns or [signature.native_namespace(loaded.ontology_iri or args.input)]
    sig = signature.build(g, namespaces)
    if not sig.native:
        print(f"error: no classes in the native namespace(s) {', '.join(namespaces)}; "
              "set --native-ns", file=sys.stderr)
        return EXIT_USAGE
    v = Verbalizer(g, args.verb_map, args.article_map)
    try:
        expect = load_expect(args.expect, g) if args.expect else []
    except (OSError, ExpectError) as exc:
        print(f"error: --expect: {exc}", file=sys.stderr)
        return EXIT_USAGE
    for c in expect:
        c["lhs_text"], c["rhs_text"] = v.m(c["lhs"], c["graph"]), v.m(c["rhs"], c["graph"])

    planned = analyze.plan(sig, len(expect))
    print(f"claims: {len(sig.native)} native classes, {len(sig.fillers)} filler classes, "
          f"{len(sig.props)} properties; at most {sum(planned.values())} checks planned",
          file=sys.stderr)
    if sum(planned.values()) > args.max_probes:
        print(f"error: H4: {sum(planned.values())} checks planned, over --max-probes "
              f"{args.max_probes}. Per grammar row: "
              + ", ".join(f"{k} {n}" for k, n in planned.items()), file=sys.stderr)
        return EXIT_BUDGET
    missing = [e for e in engines if not classify.available(e)]
    if missing:
        print(f"error: reasoner(s) not available: {', '.join(missing)}. HermiT needs Java and "
              "robot.jar (scripts/setup.sh); Pellet needs owlready2. Use --reasoners to choose.",
              file=sys.stderr)
        return EXIT_LOAD

    os.makedirs(out_dir, exist_ok=True)
    t0 = time.time()
    with tempfile.TemporaryDirectory(prefix="o2u-claims-") as tmp:
        path = classify.ontology_file(g, tmp)
        checker = analyze.Checker(path, engines)
        try:
            an = analyze.run(g, sig, checker, expect)
        except analyze.HardStop as stop:
            return _hard_stop(stop, out_dir, path, v, engines)
        except (RuntimeError, OSError) as exc:
            print(f"error: {exc}", file=sys.stderr)
            return EXIT_LOAD

        recs = [records.claim_record(v, c, sig) for c in an.claims]
        recs += records.asserted_records(g, sig, v)
        recs = [r for r in recs if r["tier"] in tiers]
        recs = _dedupe(recs)
        recs.sort(key=lambda r: (records.STATUS_ORDER[r["status"]], r["grammar"], r["text"]))
        for i, r in enumerate(recs, 1):
            r["id"] = f"c{i:04d}"

        explained = 0
        wanted = [r for r in recs if "_query" in r]
        if wanted and not args.no_explain:
            if not explain.available():
                print("warning: no explainer (needs Java and robot.jar); justifications skipped",
                      file=sys.stderr)
            else:
                batch = wanted[:args.max_explain]
                try:
                    got = explain.explain(path, [(r["id"], r["_query"]) for r in batch], v)
                except (RuntimeError, OSError) as exc:
                    print(f"warning: {exc}", file=sys.stderr)
                    got = {}
                for r in batch:
                    r["justification"] = got.get(r["id"])
                    explained += r["justification"] is not None
        for r in recs:
            q = r.pop("_query", None)
            if q is not None and "justification" not in r:
                r["justification"], r["justification_skipped"] = None, True

    report = {
        "ontology": loaded.ontology_iri, "source": args.input,
        "native_namespaces": namespaces,
        "signature": {"native": len(sig.native), "fillers": len(sig.fillers),
                      "properties": len(sig.props), "nested": len(sig.nested)},
        "checks_planned": planned, "checks_sent": an.checks,
        "reasoners": {e: round(s, 2) for e, s in an.seconds.items()},
        "seconds_total": round(time.time() - t0, 2),
        "records": _counts(recs), "explained": explained,
        "warnings": an.warnings,
    }
    _write(out_dir, recs, fmts, report)
    for w in an.warnings:
        print(f"warning: {w}", file=sys.stderr)
    c = report["records"]
    print(f"wrote {out_dir}/  ({len(recs)} records: "
          + ", ".join(f"{n} {k}" for k, n in c.items()) + f"; {explained} justified)")
    return 0


def _dedupe(recs: list[dict]) -> list[dict]:
    """One record per (status, text); G6 wins over a generated twin."""
    best: dict = {}
    for r in recs:
        k = (r["status"], r["text"])
        if k not in best or r["grammar"] == "G6":
            best[k] = r
    return list(best.values())


def _counts(recs: list[dict]) -> dict:
    out: dict = {}
    for r in recs:
        out[r["status"]] = out.get(r["status"], 0) + 1
    return {k: out[k] for k in records.STATUS_ORDER if k in out}


FIELDS = ("id", "status", "tier", "grammar", "text", "manchester", "iris", "defn_linked",
          "justification", "justification_skipped", "axiom_id", "expect_line", "reasoners")


def _write(out_dir: str, recs: list[dict], fmts: list[str], report: dict) -> None:
    if "jsonl" in fmts:
        with open(os.path.join(out_dir, "claims.jsonl"), "w", encoding="utf-8") as fh:
            for r in recs:
                fh.write(json.dumps({k: r[k] for k in FIELDS if k in r}, ensure_ascii=False) + "\n")
    if "tsv" in fmts:
        buf = io.StringIO()
        w = csv.writer(buf, delimiter="\t", lineterminator="\n")
        w.writerow(["id", "status", "tier", "grammar", "text", "manchester", "defn_linked",
                    "justification", "axiom_id"])
        for r in recs:
            just = ";".join(a["axiom_id"] for a in r.get("justification") or [])
            w.writerow([r["id"], r["status"], r["tier"], r["grammar"], r["text"], r["manchester"],
                        str(r["defn_linked"]).lower(), just, r.get("axiom_id", "")])
        with open(os.path.join(out_dir, "claims.tsv"), "w", encoding="utf-8") as fh:
            fh.write(buf.getvalue())
    if "txt" in fmts:
        lines = []
        for status in records.STATUS_ORDER:
            group = [r for r in recs if r["status"] == status]
            if group:
                lines.append(f"{status} ({len(group)})")
                lines += [r["text"] for r in group]
                lines.append("")
        with open(os.path.join(out_dir, "claims.txt"), "w", encoding="utf-8") as fh:
            fh.write("\n".join(lines))
    with open(os.path.join(out_dir, "report.json"), "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=2, ensure_ascii=False)
        fh.write("\n")


def _hard_stop(stop: analyze.HardStop, out_dir: str, path: str, v, engines) -> int:
    if stop.code == "H2":
        why = None
        try:
            why = explain.inconsistency(path, v) if explain.available() else None
        except (RuntimeError, OSError):
            pass
        with open(os.path.join(out_dir, "inconsistency.txt"), "w", encoding="utf-8") as fh:
            fh.write("The ontology is inconsistent: no claims were computed.\n")
            if why:
                fh.write("\nOne justification:\n")
                fh.writelines(f"  {a['manchester']}\n" for a in why)
        print(f"error: H2: the ontology is inconsistent; see {out_dir}/inconsistency.txt",
              file=sys.stderr)
        return EXIT_INCONSISTENT
    if stop.code == "H3":
        batch, rows = stop.detail
        texts = {q[1]: " ".join(q[2:]) for q in batch.queries}
        names = {f"c{n}": iri for iri, n in batch.classes.items()}
        names.update({f"p{n}": iri for iri, n in batch.props.items()})

        def readable(term: str) -> str:
            return re.sub(r"\b([cp]\d+)\b", lambda m: f"<{names.get(m.group(1), m.group(1))}>", term)

        with open(os.path.join(out_dir, "reasoner-disagreement.tsv"), "w", encoding="utf-8") as fh:
            fh.write("check\t" + "\t".join(engines) + "\n")
            for qid, vals in rows:
                fh.write(readable(texts.get(qid, qid)) + "\t"
                         + "\t".join(str(vals.get(e)) for e in engines) + "\n")
        print(f"error: H3: the reasoners disagree on {len(rows)} checks; see "
              f"{out_dir}/reasoner-disagreement.tsv. Nothing was adjudicated.", file=sys.stderr)
        return EXIT_DISAGREE
    print(f"error: {stop}", file=sys.stderr)
    return EXIT_LOAD
