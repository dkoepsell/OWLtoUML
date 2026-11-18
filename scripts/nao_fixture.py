"""Rebuild tests/fixtures/nao.ttl from an owl2uml diagram of nao-full.owl.

The diagram embeds (o2u-source) the Turtle of every class and property it
draws or lists, which covers NAO's native axioms and the BFO 2020 / LOF ODP003
terms they use. Terms referenced but not described get a declaration (and
the label the diagram knows for them). Usage:

    python3 scripts/nao_fixture.py nao-full.svg tests/fixtures/nao.ttl
"""
import json, re, sys
from rdflib import Graph, OWL, RDF, RDFS, URIRef, Literal, BNode
s = open(sys.argv[1], encoding="utf-8").read()
j = json.loads(re.search(r'id="o2u-source">(.*?)</script>', s, re.S).group(1))
pre = """@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .
@prefix obo: <http://purl.obolibrary.org/obo/> .
@prefix nao: <https://sool.davidkoepsell.com/nao/NAO_> .
@prefix skos: <http://www.w3.org/2004/02/skos/core#> .
@prefix dc: <http://purl.org/dc/elements/1.1/> .
"""
g = Graph()
seen = set()
for e in list(j["classes"].values()) + list(j["props"].values()):
    if e["iri"] in seen:
        continue
    seen.add(e["iri"])
    part = Graph(); part.parse(data=pre + e["ttl"], format="turtle")
    # fresh blank nodes per snippet so snippets never share structure
    m = {}
    for t in part:
        g.add(tuple(m.setdefault(x, BNode()) if isinstance(x, BNode) else x for x in t))
labels = dict(j.get("objprops", {}))
props = {o for o in g.objects(None, OWL.onProperty) if isinstance(o, URIRef)}
props |= {o for p in g.subjects(RDF.type, OWL.ObjectProperty) for o in g.objects(p, RDFS.subPropertyOf)}
props |= {o for o in g.objects(None, OWL.inverseOf) if isinstance(o, URIRef)}
for p in props:
    if (p, RDF.type, OWL.ObjectProperty) not in g:
        g.add((p, RDF.type, OWL.ObjectProperty))
        if str(p) in labels:
            g.add((p, RDFS.label, Literal(labels[str(p)], lang="en")))
cls = set()
for pred in (OWL.someValuesFrom, OWL.allValuesFrom, RDFS.subClassOf, OWL.equivalentClass,
             OWL.disjointWith, OWL.complementOf):
    cls |= {o for o in g.objects(None, pred) if isinstance(o, URIRef)}
for pred in (RDFS.domain, RDFS.range):
    cls |= {o for o in g.objects(None, pred) if isinstance(o, URIRef)}
for c in cls:
    if c != OWL.Thing and (c, RDF.type, OWL.Class) not in g:
        g.add((c, RDF.type, OWL.Class))
ont = URIRef("https://sool.davidkoepsell.com/nao/nao-full.owl")
g.add((ont, RDF.type, OWL.Ontology))
g.add((ont, RDFS.comment, Literal(
    "Test fixture: NAO's native axioms and the BFO 2020 / LOF ODP003 terms they use, "
    "rebuilt from the o2u-source block of an owl2uml diagram of nao-full.owl. "
    "Not the full ontology: imported terms NAO does not use are absent.")))
for k, v in (("owl", OWL), ("rdfs", RDFS), ("obo", "http://purl.obolibrary.org/obo/"),
             ("nao", "https://sool.davidkoepsell.com/nao/NAO_"),
             ("skos", "http://www.w3.org/2004/02/skos/core#"), ("dc", "http://purl.org/dc/elements/1.1/"),
             ("lof", "https://w3id.org/lof/")):
    g.bind(k, v)
g.serialize(sys.argv[2], format="turtle")
print(len(g), "triples;", len(list(g.subjects(RDF.type, OWL.Class))), "classes;",
      len(list(g.subjects(RDF.type, OWL.ObjectProperty))), "object properties")
