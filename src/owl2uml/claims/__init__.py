"""``owl2uml claims``: what an ontology says, entails, allows and leaves open, in English.

A diagram shows what an ontology *says*. This package lists what it commits
its users to: claims that follow from the axioms though nobody wrote them
down, combinations the axioms allow, and places where an expected commitment
is missing. Each claim is a plain-English sentence with its status, the IRIs
it uses and, when the claim is inferred, one justification.

Method (docs/claims.md):

1. ``signature``  native classes N, filler classes F, properties P.
2. ``classify``   batched satisfiability and subsumption checks in one JVM
                  per reasoner and pass (O2uProbe). HermiT and Pellet answer
                  every batch and must agree on every answer.
3. ``analyze``    the bounded candidate grammar (G1 to G6), then statuses
                  and tiers: asserted duplicates, inheritance, filler
                  reduction, the near-miss rule for UNDETERMINED.
5. ``explain``    one justification per inferred claim (O2uExplain, OWL API).
6. ``verbalize``  deterministic English templates over rdfs:label.

Nothing here touches the render path.
"""
from __future__ import annotations

STATUSES = ("ENTAILED", "REFUTED", "POSSIBLE", "UNDETERMINED", "ASSERTED")
TIERS = ("asserted", "inferred", "inherited", "possible", "undetermined")
DEFAULT_TIERS = ("asserted", "inferred", "possible", "undetermined")
PROBE_NS = "urn:owltouml:probe#"
