"""`owl2uml claims`: acceptance fixtures F1-F6, A1, N1-N6 and G6 (SPEC-OWLTOUML-CLAIMS).

The reference ontology is tests/fixtures/nao.ttl: NAO's native axioms and the
BFO 2020 / LOF ODP003 terms they use, rebuilt from the o2u-source block of an
owl2uml diagram of nao-full.owl (scripts/nao_fixture.py). The F fixtures were
derived by hand before any reasoner ran; a disagreement here is hard stop H5
in the spec, so fix the code or report it, never the expected sentence.

Needs Java with robot.jar (HermiT, explanations) and owlready2 (Pellet).
"""
import json
import os
import re
import subprocess
import sys

import pytest

HERE = os.path.dirname(__file__)
ROOT = os.path.join(HERE, "..")
sys.path.insert(0, os.path.join(ROOT, "src"))

from owl2uml.claims import classify, signature             # noqa: E402
from owl2uml.claims.cli import main as claims_main, svg_source_iri   # noqa: E402
from owl2uml.claims.verbalize import Verbalizer            # noqa: E402
from owl2uml.load import load                              # noqa: E402

NAO = os.path.join(HERE, "fixtures", "nao.ttl")
EXPECT = os.path.join(HERE, "fixtures", "nao-expect.txt")
GOLDEN = os.path.join(ROOT, "examples", "claims-nao")
needs_reasoners = pytest.mark.skipif(
    not (classify.available("hermit") and classify.available("pellet")),
    reason="Java with robot.jar (HermiT) and owlready2 (Pellet) needed")
EM_DASH = "\u2014"

F = {
    "F1": ("REFUTED", "No irreversibly accountable agent is a resettable artifact."),
    "F2": ("REFUTED", "No resettable artifact is a bearer of a displaced answerability."),
    "F3": ("ENTAILED", "Every answerability is occasioned by some normative breach."),
    "F4": ("ENTAILED", "Every repeat breach is preceded by some normative breach."),
    "F5": ("POSSIBLE",
           "There can be a normative breach that is attributed to some resettable artifact."),
    "F6": ("UNDETERMINED", "The ontology neither entails nor rules out that every irreversibly "
                           "accountable agent is an accountable agent."),
    "A1": ("ASSERTED", "Every answerability answers for some normative breach."),
}
N1 = "Every repeat breach is attributed to some material entity."


def _run(out_dir, *extra):
    code = claims_main([NAO, "--imports", "none", "--out-dir", str(out_dir), *extra])
    assert code == 0
    with open(os.path.join(out_dir, "claims.jsonl"), encoding="utf-8") as fh:
        return [json.loads(line) for line in fh]


@pytest.fixture(scope="module")
def default_run(tmp_path_factory):
    out = tmp_path_factory.mktemp("claims-default")
    return out, _run(out)


@pytest.fixture(scope="module")
def full_run(tmp_path_factory):
    out = tmp_path_factory.mktemp("claims-full")
    return out, _run(out, "--tiers", "asserted,inferred,inherited,possible,undetermined",
                     "--expect", EXPECT)


def _by_text(recs):
    return {r["text"]: r for r in recs}


# ---- positive fixtures -------------------------------------------------------

@needs_reasoners
@pytest.mark.parametrize("key", sorted(F))
def test_fixture_in_default_output(default_run, key):
    status, text = F[key]
    rec = _by_text(default_run[1]).get(text)
    assert rec is not None, f"{key} missing: {text}"
    assert rec["status"] == status
    assert rec["reasoners"] in ({}, {"hermit": status, "pellet": status})


@needs_reasoners
def test_f2_survives_reduction_through_definitional_link(default_run):
    rec = _by_text(default_run[1])[F["F2"][1]]
    assert rec["defn_linked"] is True and rec["tier"] == "inferred"


@needs_reasoners
def test_property_weakenings_are_kept(default_run):
    for key in ("F3", "F4"):
        assert _by_text(default_run[1])[F[key][1]]["grammar"] == "G3"


@needs_reasoners
def test_f5_comes_from_g5_and_f6_from_the_near_miss_rule(default_run):
    recs = _by_text(default_run[1])
    assert recs[F["F5"][1]]["grammar"] == "G5"
    assert recs[F["F6"][1]]["grammar"] == "G1"


@needs_reasoners
def test_inferred_records_carry_justifications_with_known_axiom_ids(default_run):
    from owl2uml.axioms import inventory
    ids = {a.id for a in inventory(load(NAO, imports="none").merge())}
    inferred = [r for r in default_run[1] if r["tier"] == "inferred"]
    assert inferred
    for r in inferred:
        assert r["justification"], r["text"]
        assert {a["axiom_id"] for a in r["justification"]} <= ids
    f2 = _by_text(default_run[1])[F["F2"][1]]["justification"]
    assert any("resettable artifact' SubClassOf not ('bearer of' some answerability)"
               in a["manchester"] for a in f2)


@needs_reasoners
def test_asserted_records_carry_their_axiom_id(default_run):
    a1 = _by_text(default_run[1])[F["A1"][1]]
    assert re.fullmatch(r"[0-9a-f]{12}", a1["axiom_id"])


# ---- negative fixtures -------------------------------------------------------

@needs_reasoners
def test_n1_inherited_hidden_by_default(default_run, full_run):
    assert N1 not in _by_text(default_run[1])
    rec = _by_text(full_run[1]).get(N1)
    assert rec is not None and rec["tier"] == "inherited" and rec["status"] == "ENTAILED"


@needs_reasoners
def test_n2_no_probe_iris_anywhere(default_run, full_run):
    for out, _ in (default_run, full_run):
        for name in os.listdir(out):
            with open(os.path.join(out, name), encoding="utf-8") as fh:
                assert "urn:owltouml:probe" not in fh.read(), name


@needs_reasoners
def test_n3_no_bfo_only_subjects(default_run, full_run):
    g = load(NAO, imports="none").merge()
    v = Verbalizer(g)
    sig = signature.build(g, ["https://sool.davidkoepsell.com/nao/"])
    bfo_labels = {v.label(c) for c in sig.fillers if not sig.is_native(c)}
    for out, recs in (default_run, full_run):
        for r in recs:
            m = re.match(r"(?:Every|No) (.+?) (?:is|has|answers|realizes|records|responds|"
                         r"violates|wrongs)\b", r["text"])
            if m and r["status"] != "ASSERTED":
                assert m.group(1) not in bfo_labels, r["text"]
    assert "Every disposition is a realizable entity." not in _by_text(full_run[1])


@needs_reasoners
def test_n4_no_em_dash_in_outputs(default_run, full_run):
    for out, _ in (default_run, full_run):
        for name in os.listdir(out):
            with open(os.path.join(out, name), encoding="utf-8") as fh:
                assert EM_DASH not in fh.read(), name


def test_n4_no_em_dash_in_this_feature():
    paths = [os.path.join(ROOT, "docs", "claims.md"), __file__, EXPECT,
             os.path.join(ROOT, "scripts", "nao_fixture.py"),
             os.path.join(ROOT, "src", "owl2uml", "java", "O2uProbe.java"),
             os.path.join(ROOT, "src", "owl2uml", "java", "O2uExplain.java")]
    pkg = os.path.join(ROOT, "src", "owl2uml", "claims")
    paths += [os.path.join(pkg, n) for n in os.listdir(pkg) if n.endswith(".py")]
    if os.path.isdir(GOLDEN):
        paths += [os.path.join(GOLDEN, n) for n in os.listdir(GOLDEN)]
    for p in paths:
        with open(p, encoding="utf-8") as fh:
            assert EM_DASH not in fh.read(), p


def test_n6_svg_input_is_refused(tmp_path, capsys):
    svg = tmp_path / "nao-full.svg"
    svg.write_text('<svg xmlns="http://www.w3.org/2000/svg"><script type="application/json" '
                   'id="o2u-source">{"version":1,"ontology":"https://sool.davidkoepsell.com/nao/'
                   'nao-full.owl"}</script></svg>', encoding="utf-8")
    assert svg_source_iri(str(svg)) == "https://sool.davidkoepsell.com/nao/nao-full.owl"
    assert claims_main([str(svg)]) != 0
    assert "https://sool.davidkoepsell.com/nao/nao-full.owl" in capsys.readouterr().err


def test_n6_through_the_owl2uml_entry_point(tmp_path):
    svg = tmp_path / "x.svg"
    svg.write_text('<svg><script type="application/json" id="o2u-source">'
                   '{"ontology":"http://example.org/o.owl"}</script></svg>', encoding="utf-8")
    r = subprocess.run([sys.executable, "-c", "import sys; sys.path.insert(0, 'src'); "
                        "from owl2uml.cli import main; sys.exit(main())", "claims", str(svg)],
                       cwd=ROOT, capture_output=True, text=True)
    assert r.returncode == 2 and "http://example.org/o.owl" in r.stderr


# ---- G6 ------------------------------------------------------------------------

@needs_reasoners
def test_g6_expect_gives_the_f6_record(full_run):
    rec = _by_text(full_run[1])[F["F6"][1]]
    assert rec["status"] == "UNDETERMINED" and rec["grammar"] == "G6"
    assert rec["expect_line"] == 2


@needs_reasoners
def test_g6_entailed_and_undetermined_disjointness(full_run):
    recs = _by_text(full_run[1])
    assert recs["Every sanction responds to some normative breach."]["status"] == "ENTAILED"
    assert recs["The ontology neither entails nor rules out that no resettable artifact is an "
                "accountable agent."]["status"] == "UNDETERMINED"


# ---- hard stops ------------------------------------------------------------------

def test_h4_budget_stops_before_reasoning(tmp_path, capsys):
    code = claims_main([NAO, "--imports", "none", "--out-dir", str(tmp_path / "o"),
                        "--max-probes", "100"])
    assert code == 6
    err = capsys.readouterr().err
    assert "H4" in err and "G3" in err
    assert not (tmp_path / "o").exists()


@needs_reasoners
def test_h2_inconsistent_ontology(tmp_path):
    bad = tmp_path / "bad.ttl"
    bad.write_text("""@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix : <http://example.org/bad/> .
<http://example.org/bad/onto> a owl:Ontology .
:A a owl:Class . :B a owl:Class ; owl:disjointWith :A .
:x a owl:NamedIndividual, :A, :B .
""", encoding="utf-8")
    out = tmp_path / "o"
    assert claims_main([str(bad), "--out-dir", str(out)]) == 4
    text = (out / "inconsistency.txt").read_text(encoding="utf-8")
    assert "inconsistent" in text and "DisjointWith" in text
    assert not (out / "claims.jsonl").exists()


# ---- verbalization -----------------------------------------------------------------

def test_verb_phrase_rules():
    g = load(NAO, imports="none").merge()
    v = Verbalizer(g)
    obo = "http://purl.obolibrary.org/obo/"
    nao = "https://sool.davidkoepsell.com/nao/NAO_"
    from rdflib import URIRef
    assert v.verb_phrase(URIRef(nao + "0001100")) == "is attributed to"
    assert v.verb_phrase(URIRef(obo + "BFO_0000196")) == "is a bearer of"
    assert v.verb_phrase(URIRef(nao + "0001102")) == "answers for"
    assert v.verb_phrase(URIRef(obo + "BFO_0000057")) == "has as participant"
    assert v.verb_phrase(URIRef(obo + "BFO_0000194")) == "is specifically depended on by"


def test_verb_map_overrides(tmp_path):
    vm = tmp_path / "verbs.tsv"
    vm.write_text("bearer of\tbears\n", encoding="utf-8")
    g = load(NAO, imports="none").merge()
    from rdflib import URIRef
    v = Verbalizer(g, verb_map=str(vm))
    assert v.verb_phrase(URIRef("http://purl.obolibrary.org/obo/BFO_0000196")) == "bears"


# ---- golden output -------------------------------------------------------------------

@needs_reasoners
def test_golden_claims_txt(default_run):
    out, _ = default_run
    with open(os.path.join(out, "claims.txt"), encoding="utf-8") as fh:
        got = fh.read()
    with open(os.path.join(GOLDEN, "claims.txt"), encoding="utf-8") as fh:
        assert got == fh.read()
