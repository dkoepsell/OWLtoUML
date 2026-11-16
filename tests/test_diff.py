"""WS4: visual version diff. A seeded set of 20 edits to a LOF-like ontology
(adds, removals, renames, a definition edit that moves inferred
superclasses, one that makes a class unsatisfiable); the diff must report
every one."""
import json
import sys
from pathlib import Path

import pytest
from rdflib import BNode, Graph, Literal, OWL, RDF, RDFS, URIRef
from rdflib.collection import Collection

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from owl2uml.cli import main  # noqa: E402
from owl2uml.diff import check  # noqa: E402
from owl2uml.diff.build import run  # noqa: E402
from owl2uml.dot import dot_available  # noqa: E402
from owl2uml.load import load  # noqa: E402
from owl2uml.reason import hermit_available  # noqa: E402

FIX = ROOT / "tests" / "fixtures" / "hohfeld.ttl"
L = "https://w3id.org/lof/"
IAO_REPLACED_BY = URIRef("http://purl.obolibrary.org/obo/IAO_0100001")
IAO_DEF = URIRef("http://purl.obolibrary.org/obo/IAO_0000115")


def u(local):
    return URIRef(L + local)


def cls(g, iri, label, *supers):
    g.add((iri, RDF.type, OWL.Class))
    g.add((iri, RDFS.label, Literal(label)))
    for s in supers:
        g.add((iri, RDFS.subClassOf, s))


def some(g, prop, filler):
    r = BNode()
    g.add((r, RDF.type, OWL.Restriction))
    g.add((r, OWL.onProperty, prop))
    g.add((r, OWL.someValuesFrom, filler))
    return r


def correlated(g, filler):
    """'correlated position' == legal position and (correlative of some filler)."""
    c, x, lst = u("T_corr"), BNode(), BNode()
    g.add((c, RDF.type, OWL.Class))
    g.add((c, RDFS.label, Literal("correlated position")))
    Collection(g, lst, [u("ODP003_0001000"), some(g, u("ODP003_0001102"), filler)])
    g.add((x, RDF.type, OWL.Class))
    g.add((x, OWL.intersectionOf, lst))
    g.add((c, OWL.equivalentClass, x))


def drop(g, s):
    for t in list(g.triples((s, None, None))):
        g.remove(t)


def seeded():
    """(old, new, expectations)."""
    old = Graph().parse(FIX)
    cls(old, u("T_obsolete"), "obsolete position", u("ODP003_0001000"))
    correlated(old, u("ODP003_0001009"))        # first-order positions are correlated
    new = Graph()
    for t in old:
        new.add(t)
    # 1-3 added entities
    cls(new, u("T_testimony"), "testimony right", u("ODP003_0001001"))
    cls(new, u("T_attorney"), "power of attorney", u("ODP003_0001005"))
    new.add((u("T_waives"), RDF.type, OWL.ObjectProperty))
    new.add((u("T_waives"), RDFS.label, Literal("waives")))
    # 4-5 removed without deprecation: a class and a property
    drop(new, u("T_obsolete"))
    drop(new, u("ODP009_0001100"))
    # 6-7 renamed (same IRI, new label)
    new.set((u("ODP003_0001001"), RDFS.label, Literal("claim-right")))
    new.set((u("ODP001_0001000"), RDFS.label, Literal("legal action")))
    # 8 deprecated, replaced by a new class
    new.add((u("ODP003_0001003"), OWL.deprecated, Literal(True)))
    new.add((u("ODP003_0001003"), IAO_REPLACED_BY, u("T_privilege")))
    cls(new, u("T_privilege"), "privilege", u("ODP003_0001009"))
    # 9 a changed axiom on an existing line: duty's "only" restriction removed
    for r in list(new.objects(u("ODP003_0001002"), RDFS.subClassOf)):
        if (r, OWL.allValuesFrom, None) in new:
            new.remove((u("ODP003_0001002"), RDFS.subClassOf, r))
    # 10 a new restriction (line)
    new.add((u("ODP009_0001003"), RDFS.subClassOf,
             some(new, u("ODP003_0001103"), u("ODP001_0001000"))))
    # 11 an asserted move: no-claim under second-order instead of first-order
    new.remove((u("ODP003_0001004"), RDFS.subClassOf, u("ODP003_0001009")))
    new.add((u("ODP003_0001004"), RDFS.subClassOf, u("ODP003_0001010")))
    # 12 disjointness of the two orders, and 13 a class under both: unsatisfiable
    new.add((u("ODP003_0001009"), OWL.disjointWith, u("ODP003_0001010")))
    cls(new, u("T_hybrid"), "hybrid position", u("ODP003_0001001"), u("ODP003_0001005"))
    # 14 domain and range for 'confers' (an association line)
    new.add((u("ODP002_0001100"), RDFS.domain, u("ODP001_0001000")))
    new.add((u("ODP002_0001100"), RDFS.range, u("ODP003_0001000")))
    # 15 'held by' no longer functional
    new.remove((u("ODP003_0001100"), RDF.type, OWL.FunctionalProperty))
    # 16 a definition added
    new.add((u("ODP003_0001005"), IAO_DEF, Literal("The ability to change legal relations.")))
    # 17 the definition of 'correlated position' edited: inferred superclasses move
    for x in list(new.objects(u("T_corr"), OWL.equivalentClass)):
        new.remove((u("T_corr"), OWL.equivalentClass, x))
    correlated(new, u("ODP003_0001010"))
    # 18 property renamed
    new.set((u("ODP002_0001100"), RDFS.label, Literal("grants")))
    # 19 a restriction removed: legal position no longer 'arises from' a legal act
    for r in list(new.objects(u("ODP003_0001000"), RDFS.subClassOf)):
        if (r, OWL.onProperty, u("ODP001_0001104")) in new:
            new.remove((u("ODP003_0001000"), RDFS.subClassOf, r))
    # 20 a data property added
    new.add((u("T_date"), RDF.type, OWL.DatatypeProperty))
    new.add((u("T_date"), RDFS.label, Literal("effective date")))
    new.add((u("T_date"), RDFS.domain, u("ODP001_0001000")))
    return old, new


def _files(tmp_path):
    old, new = seeded()
    po, pn = tmp_path / "old.ttl", tmp_path / "new.ttl"
    old.serialize(po, format="turtle")
    new.serialize(pn, format="turtle")
    return po, pn


def _diff(tmp_path, engine="none", draw=False, **kw):
    po, pn = _files(tmp_path)
    return run(load(str(po), imports="none"), load(str(pn), imports="none"),
               engine=engine, draw=draw, **kw)


def test_entity_layer_reports_every_entity_edit(tmp_path):
    d = _diff(tmp_path).data
    e = d["entities"]
    added = {r["iri"] for r in e["added"]}
    assert {L + "T_testimony", L + "T_attorney", L + "T_waives", L + "T_privilege",
            L + "T_hybrid", L + "T_date"} <= added                       # 1-3, 8, 13, 20
    removed = {r["iri"]: r for r in e["removed"]}
    assert set(removed) == {L + "T_obsolete", L + "ODP009_0001100"}    # 4-5
    assert not any(r["was_deprecated"] for r in removed.values())
    renamed = {r["iri"]: (r["old"], r["new"]) for r in e["renamed"]}
    assert renamed[L + "ODP003_0001001"] == ("claim", "claim-right")    # 6
    assert renamed[L + "ODP001_0001000"] == ("legal act", "legal action")   # 7
    assert renamed[L + "ODP002_0001100"] == ("confers", "grants")       # 18
    assert e["replaced"] == [{"old": L + "ODP003_0001003", "new": L + "T_privilege",
                              "kind": "class", "old_label": "liberty",
                              "new_label": "privilege"}]                # 8
    assert d["summary"]["renamed"] == 4


def test_axiom_layer_reports_every_axiom_edit(tmp_path):
    a = _diff(tmp_path).data["axioms"]
    add = "\n".join(r["text"] for r in a["added"])
    rem = "\n".join(r["text"] for r in a["removed"])
    assert "duty SubClassOf 'correlative of' only claim" in rem          # 9
    assert "'legal person' SubClassOf 'exercised in' some 'legal act'" in add or \
        "'legal person' SubClassOf 'exercised in' some 'legal action'" in add   # 10
    assert "no-claim SubClassOf 'second-order legal position'" in add    # 11
    assert "no-claim SubClassOf 'first-order legal position'" in rem
    assert "DisjointWith" in add                                         # 12
    assert "Domain" in add and "Range" in add                            # 14
    assert "FunctionalProperty('held by')" in rem                  # 15
    assert "The ability to change legal relations." in add               # 16
    assert "'arises from' some" in rem                                   # 19
    assert "correlative of' some 'second-order" in add                   # 17
    assert "correlative of' some 'first-order" in rem


@pytest.mark.skipif(not hermit_available(), reason="needs Java + owlready2 (HermiT)")
def test_inferred_layer_moves_and_unsatisfiable(tmp_path):
    d = _diff(tmp_path, engine="hermit").data
    i = d["inferred"]
    assert not i["error"]
    assert i["unsatisfiable"]["added"] == [L + "T_hybrid"]               # 12-13
    corr = L + "T_corr"
    moved = {m["iri"]: m for m in i["moved"]}
    # 17: the edited definition moves the second-order positions under it
    # and the first-order ones out
    into = [c for c, m in moved.items() if corr in m["gained"]]
    out = [c for c, m in moved.items() if corr in m["lost"]]
    assert len(into) >= 3 and len(out) >= 3
    assert [L + "ODP003_0001005", corr] in i["added"]
    assert check(d, ["unsatisfiable"])[0]["iris"] == [L + "T_hybrid"]


def test_fail_on_conditions(tmp_path):
    d = _diff(tmp_path).data
    hit = {f["condition"] for f in check(d, ["removed-without-deprecation", "new-orphans",
                                             "inconsistent", "coverage-drop"])}
    assert "removed-without-deprecation" in hit and "inconsistent" not in hit
    with pytest.raises(ValueError):
        check(d, ["nonsense"])


def test_no_changes(tmp_path):
    from owl2uml.diff import changed
    p = load(str(FIX), imports="none")
    d = run(p, load(str(FIX), imports="none"), engine="none", draw=False).data
    assert not changed(d) and d["axioms"] == {"added": [], "removed": []}


@pytest.mark.skipif(not dot_available(), reason="needs graphviz")
def test_diagram_marks_changes(tmp_path):
    res = _diff(tmp_path, draw=True)
    svg, m = res.svg, res.model
    ids = {cid: f"n{i}" for i, cid in enumerate(m.classes)}
    assert f'<g id="{ids[L + "T_testimony"]}" class="diff-added ' in svg
    assert f'<g id="{ids[L + "T_obsolete"]}" class="diff-removed ' in svg
    assert f'<g id="{ids[L + "ODP003_0001001"]}" class="diff-changed ' in svg
    assert "(was claim)" in svg
    assert 'class="diff-changed edge' in svg or "diff-changed edge" in svg
    assert 'id="diffkey"' in svg
    src = json.loads(svg.split('id="o2u-source">', 1)[1].split("</script>", 1)[0])
    node = src["diff"]["nodes"][L + "ODP003_0001004"]
    assert "first-order" in node["old"] and "second-order" in node["new"]
    # scope: 'changed' draws fewer classes than 'all'
    few = _diff(tmp_path, draw=True, scope="changed").model
    every = _diff(tmp_path, draw=True, scope="all").model
    assert len(few.classes) < len(m.classes) <= len(every.classes)


@pytest.mark.skipif(not dot_available(), reason="needs graphviz")
def test_cli_writes_outputs_and_fails_on(tmp_path):
    po, pn = _files(tmp_path)
    out = tmp_path / "d.svg"
    rc = main(["diff", str(po), str(pn), "-o", str(out), "--reason", "none",
               "--fail-on", "removed-without-deprecation", "--export", "png"])
    assert rc == 3
    d = json.loads((tmp_path / "d.json").read_text())
    assert d["fail_on"]["failed"][0]["condition"] == "removed-without-deprecation"
    md = (tmp_path / "d.md").read_text()
    assert "| entities |" in md and "Checks failed" in md
    assert (tmp_path / "d.png").stat().st_size > 1000
    assert main(["diff", str(po), str(pn), "-o", str(out), "--reason", "none"]) == 0
