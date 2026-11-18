"""One justification per inferred claim (spec section 5.5), via O2uExplain.

The helper writes each justification axiom as a one-axiom Turtle document,
so the axiom gets the same stable id (axioms.py) as in owl2uml's coverage
ledger, and the same Manchester rendering as in the source panel.
"""
from __future__ import annotations

import os
import subprocess
import tempfile

from rdflib import Graph

from .. import tools
from ..axioms import inventory
from .records import manchester
from .verbalize import Verbalizer

_SKIP = {"Declaration", "AnnotationAssertion"}


def available() -> bool:
    return tools.explain_cmd() is not None


def explain(ontology_path: str, queries: list[tuple[str, str]], v: Verbalizer,
            timeout: float = 3600) -> dict:
    """{query id: [{"axiom_id", "manchester"}] or None (not entailed / failed)}."""
    cmd = tools.explain_cmd()
    if cmd is None or not queries:
        return {}
    with tempfile.TemporaryDirectory(prefix="o2u-explain-") as tmp:
        q, o = os.path.join(tmp, "queries.txt"), os.path.join(tmp, "out.txt")
        with open(q, "w", encoding="utf-8") as fh:
            for qid, axiom in queries:
                fh.write(f"{qid}\t{axiom}\n")
        r = subprocess.run(cmd + [ontology_path, q, o], capture_output=True, timeout=timeout)
        if r.returncode != 0 or not os.path.exists(o):
            err = [ln for ln in r.stderr.decode("utf-8", "replace").splitlines()
                   if ln.strip() and "Picked up" not in ln]
            raise RuntimeError("explainer failed: " + " ".join(err[-5:]))
        with open(o, encoding="utf-8") as fh:
            text = fh.read()
    return parse(text, v)


def parse(text: str, v: Verbalizer) -> dict:
    out: dict = {}
    for block in text.split("@@ENTRY\t")[1:]:
        head, _, body = block.partition("\n")
        qid, _, n = head.partition("\t")
        if int(n or -1) < 0:
            out[qid] = None
            continue
        axioms = []
        for chunk in body.split("@@AXIOM\n")[1:]:
            ttl = chunk.split("@@END")[0]
            g = Graph()
            g.parse(data=ttl, format="turtle")
            for ax in inventory(g):
                if ax.type in _SKIP:
                    continue
                axioms.append({"axiom_id": ax.id, "manchester": manchester(g, ax, v)})
        axioms.sort(key=lambda a: a["manchester"])
        out[qid] = axioms
    return out


def inconsistency(ontology_path: str, v: Verbalizer) -> list[dict] | None:
    got = explain(ontology_path, [("!inconsistent", "")], v)
    return got.get("!inconsistent")
