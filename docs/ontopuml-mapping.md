# OWL → UML diagram elements in ontopuml (IOF NOWL notation)

`--export ontopuml` (web: Download → ontopuml) writes a PlantUML file that
includes the IOF NOWL library (<https://github.com/iofoundry/ontopuml>) and
calls its macros. Each diagram element maps as follows.

| OWL → UML element | OWL it comes from | NOWL call |
| --- | --- | --- |
| class box | `owl:Class` | `class(nN, "prefix:Name")` |
| object box (underlined) | named individual (`hasValue`) | `individual(nN, "prefix:name")` |
| solid hollow arrow | `rdfs:subClassOf` | `subClass(A, B)` |
| orange hollow arrow | subclass inferred by the reasoner | `subClass(A, B)` |
| dashed hollow arrows (defined class) | `owl:equivalentClass` intersection | `intersection(dN, '[...]')` + `equivalent(A, dN)` |
| dashed ≡ line | `owl:equivalentClass` between named classes | `equivalent(A, B)` |
| dashed blue arrow, "p some" / "p only" | existential / universal restriction | `some(rN, p, B)` / `only(rN, p, B)` + `subClass(A, rN)` |
| multiplicity at the arrowhead | (qualified) cardinality | `someCard(rN, p, B, min\|max\|exactly, n)` + `subClass(A, rN)` |
| ¬ on a restriction label | complement filler | `complement(cN, B)` used as the filler |
| ⊔ node | `owl:unionOf` | `union(uN, '[...]')` + `subClass(A, uN)` |
| ¬ node | `owl:complementOf` | `complement(cN, B)` + `subClass(A, cN)` |
| «enumeration» box | `owl:oneOf` | `oneOf(C, '[...]')` |
| red dotted ⊥ line or ⊥ node | `owl:disjointWith`, `AllDisjointClasses` | `disjoint(A, B)` for each pair |
| blue domain → range arrow | `rdfs:domain` / `rdfs:range` | comment (no NOWL macro) |
| "p value x" restriction | `owl:hasValue` | comment, with a warning |
| "p self" loop | `owl:hasSelf` | comment, with a warning |

Elements written as comments are listed as warnings when the file is made.
