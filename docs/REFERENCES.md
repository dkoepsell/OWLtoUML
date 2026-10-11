# Scholarly basis for the translation algorithms

This tool performs three distinct algorithmic jobs. Each rests on an
established body of research. The references below support the *approaches*
taken in the code; the implementation uses simplified variants where noted.

## 1. OWL/RDFS → UML mapping (`src/owl2uml/parse.py`)

The mapping rules — OWL classes → UML classes, `rdfs:subClassOf` →
generalization, `owl:ObjectProperty` with a class range → association,
`owl:DatatypeProperty` → attribute, `rdfs:label` for readable names — follow
the correspondences formalized in the ontology-to-UML literature.

- **OMG (2014).** *Ontology Definition Metamodel (ODM), Version 1.1.* Object
  Management Group. — The canonical, standardized mapping between OWL/RDFS and
  UML/MOF. The most authoritative reference for the parse rules.
- **Brockmans, S., Volz, R., Eberhart, A., & Löffler, P. (2004).** "Visual
  Modeling of OWL DL Ontologies Using UML." *ISWC 2004*, LNCS 3298, 198–213.
  Springer.
- **Cranefield, S. (2001).** "UML and the Semantic Web." *Proc. Int'l Semantic
  Web Working Symposium (SWWS).* — Early mapping of RDF/ontology classes and
  properties to UML class diagrams.
- **Baclawski, K., Kokar, M. K., Kogut, P. A., Hart, L., Smith, J., Letkowski,
  J., & Emery, P. (2002).** "Extending the Unified Modeling Language for
  ontology development." *Software and Systems Modeling*, 1(2), 142–156.
- **Kogut, P., Cranefield, S., Hart, L., et al. (2002).** "UML for ontology
  development." *The Knowledge Engineering Review*, 17(1), 61–64.
- **Gašević, D., Djurić, D., & Devedžić, V. (2009).** *Model Driven Engineering
  and Ontology Development* (2nd ed.). Springer.

## 2. Layer assignment / layered layout (`src/owl2uml/layout.py`, Graphviz `dot`)

`_assign_layers` computes each class's rank as `1 + max(parent depths)` over
generalization edges — textbook **longest-path layering** within the Sugiyama
layered-drawing framework, which is also what Graphviz `dot` implements.

- **Sugiyama, K., Tagawa, S., & Toda, M. (1981).** "Methods for visual
  understanding of hierarchical system structures." *IEEE Trans. Systems, Man,
  and Cybernetics*, 11(2), 109–125. — Origin of hierarchical/layered layout.
- **Gansner, E. R., Koutsofios, E., North, S. C., & Vo, K.-P. (1993).** "A
  technique for drawing directed graphs." *IEEE Trans. Software Engineering*,
  19(3), 214–230. — The algorithm behind `dot` (rank assignment, ordering,
  positioning).
- **Di Battista, G., Eades, P., Tamassia, R., & Tollis, I. G. (1999).** *Graph
  Drawing: Algorithms for the Visualization of Graphs.* Prentice Hall. —
  Standard reference; describes longest-path layering directly.

## 3. Scalable force-directed fallback (`sfdp`, in `src/owl2uml/dot.py`)

Above ~500 classes the renderer switches from `dot` to `sfdp`, a multilevel
force-directed engine.

- **Hu, Y. (2005).** "Efficient, high-quality force-directed graph drawing."
  *The Mathematica Journal*, 10(1), 37–71. — The multilevel algorithm `sfdp`
  is based on.
- **Fruchterman, T. M. J., & Reingold, E. M. (1991).** "Graph drawing by
  force-directed placement." *Software: Practice and Experience*, 21(11),
  1129–1164.

## Tooling

- **Ellson, J., Gansner, E., Koutsofios, L., North, S. C., & Woodhull, G.
  (2002).** "Graphviz — Open Source Graph Drawing Tools." *Graph Drawing
  (GD 2001)*, LNCS 2265, 483–484. Springer.

---

*Caveat:* the code implements simplified versions of these methods (e.g.
longest-path layering rather than `dot`'s full network-simplex ranking in its
own built-in layout pass). The **ODM** and **Brockmans et al.** are the primary
references for the core OWL→UML claim.
