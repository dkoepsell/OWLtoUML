# `owl2uml claims`: what an ontology commits you to, in English

A diagram shows what an ontology says. `owl2uml claims` lists what it
commits its users to: the claims that follow from the axioms although nobody
wrote them down, the combinations the axioms allow, and the places where an
expected commitment is missing. Every claim is one plain-English sentence,
with its status, the IRIs it uses and, when it was inferred, one
justification, so it can go into a report or a test fixture as it stands.

```
owl2uml claims nao-full.owl
owl2uml claims nao-full.owl --expect my-intuitions.txt --tiers asserted,inferred,inherited
```

Two things to keep in mind when reading the output:

* **UNDETERMINED means "not settled by this ontology", not "false".** The
  ontology neither entails the claim nor rules it out. That is a finding in
  its own right: often it is a missing axiom, sometimes a deliberate
  distinction.
* **The candidate grammar is bounded.** The tool checks a fixed, finite set of
  candidate statements (below). A statement missing from the output may still
  be entailed: it may simply be outside the grammar, for example an
  existential nested two levels deep.

## Output

`--out-dir` (default `./claims-<input stem>/`) receives:

| File | Contents |
|---|---|
| `claims.jsonl` | one record per claim (the full form) |
| `claims.tsv` | id, status, tier, grammar, text, Manchester, definitional link, justification axiom ids, asserted axiom id |
| `claims.txt` | the sentences, grouped by status: ENTAILED, REFUTED, POSSIBLE, UNDETERMINED, ASSERTED |
| `report.json` | the signature size, checks planned and sent per grammar row, seconds per reasoner, warnings |

A record:

```json
{"id": "c0012", "status": "REFUTED", "tier": "inferred", "grammar": "G4",
 "text": "No resettable artifact is a bearer of a displaced answerability.",
 "manchester": "'resettable artifact' SubClassOf not ('bearer of' some 'displaced answerability')",
 "iris": ["http://purl.obolibrary.org/obo/BFO_0000196", "..."],
 "defn_linked": true,
 "justification": [
   {"axiom_id": "8044a683b12a", "manchester": "'displaced answerability' EquivalentTo answerability and ('answers for' some ('normative breach' and ('attributed to' some 'resettable artifact')))"},
   {"axiom_id": "9aca7f21b3f6", "manchester": "'resettable artifact' SubClassOf not ('bearer of' some answerability)"}],
 "reasoners": {"hermit": "REFUTED", "pellet": "REFUTED"}}
```

Axiom ids are the ones owl2uml's coverage report and diff use (axioms.py),
so a justification can be traced into the diagram's source panel.

## Statuses and tiers

| Status | Meaning |
|---|---|
| `ASSERTED` | a logical axiom stated on one of the ontology's own entities |
| `ENTAILED` | the candidate follows and is not asserted |
| `REFUTED` | the negation follows (disjointness, emptiness) |
| `POSSIBLE` | the class expression is satisfiable |
| `UNDETERMINED` | neither the candidate nor its negation follows |

| Tier | Which records | Default |
|---|---|---|
| `asserted` | ASSERTED | shown |
| `inferred` | ENTAILED or REFUTED, and not inherited | shown |
| `inherited` | ENTAILED or REFUTED, and also true of a strict named superclass of the subject | hidden |
| `possible` | POSSIBLE | shown |
| `undetermined` | UNDETERMINED | shown |

## Vocabulary

* **N**, native classes: named classes in a native namespace (`--native-ns`;
  default the namespace of the ontology IRI).
* **F**, filler classes: N plus every named class in a class position of an
  axiom on a native entity. For NAO this brings in `disposition`,
  `material entity`, `legal position` and the like, and leaves the rest of
  BFO out.
* **P**, properties: native object properties, the object properties native
  axioms use, and their told super-properties.

## Candidate grammar

| Row | Candidate | Statuses |
|---|---|---|
| G1 | A SubClassOf B, A in N, B in F | ENTAILED |
| G2 | A and B is empty, A in N, B in F | REFUTED |
| G3 | A SubClassOf p some B | ENTAILED |
| G4 | A and (p some B) is empty, where G3 fails | REFUTED |
| G5 | every non-atomic filler expression nested in a native axiom, and every native class | POSSIBLE, REFUTED |
| G6 | each line of `--expect` | ENTAILED, REFUTED, UNDETERMINED |

G5 reports an unsatisfiable native class as REFUTED ("There cannot be a
...") with a warning, and does not list the satisfiable ones (every class is
expected to be satisfiable).

UNDETERMINED is reported for G1 only by the near-miss rule (next section) and
for G6 lines. Everything else that is merely not entailed is the normal state
of most pairs and is not listed.

## Filtering

1. **Asserted duplicates.** A candidate that matches a told axiom of its
   subject (a told superclass, a conjunct of a definition, a told
   existential or negated existential, a told disjointness) is not repeated:
   the ASSERTED record states it.
2. **Inheritance.** A claim about A that also holds for a strict named
   superclass of A goes to the `inherited` tier. Disjointness is reported
   only for the most general pair.
3. **Filler reduction** (`--reduce filler`, the default). `A SubClassOf p some
   B` is dropped when `A SubClassOf p some B'` holds for a more specific B'
   in F; `A and p some B` is empty is dropped when it holds for a more
   general B'. Property weakenings (`answers for` to `occasioned by`) are
   kept: they show what the property hierarchy commits you to.
   **Exception:** a claim relating A and B is never dropped when B's
   definition mentions A or A's definition mentions B (`defn_linked`). This
   keeps "No resettable artifact is a bearer of a displaced answerability",
   which follows from a stronger asserted axiom but says what the definition
   of displaced answerability implies.
4. **Near misses (UNDETERMINED).** A SubClassOf B is reported as UNDETERMINED
   when A and B are both native defined classes with the same named genus,
   every `p some F` in B's definition is matched in A's by `p some F'` with F'
   a sibling of F (a shared direct told parent) and F' not under F, and A
   SubClassOf B is neither entailed nor refuted.

## English

Templates only, so the same ontology always gives the same sentences.
Labels come from `rdfs:label` (else the IRI fragment), lowercased unless a
capital follows the first character. A property label becomes a verb phrase:

1. a participle, optionally after an adverb, takes "is": *attributed to*,
   *specifically depended on by*;
2. a relational noun ending in *of* takes "is a": *is a bearer of*;
3. *has* plus a noun takes "has as": *has as participant*;
4. anything else is used as it stands: *answers for*, *realizes*.

`--verb-map` (TSV: property IRI or label, then phrase) and `--article-map`
(TSV: label, then article) override the rules.

| Form | Sentence |
|---|---|
| A SubClassOf B | Every A is a B. |
| A and B empty | No A is a B. (a native class first; two native classes in label order) |
| A SubClassOf p some B | Every A *p* some B. |
| A and p some B empty | No A *p* a B. |
| C satisfiable | There can be *C*. |
| C empty | There cannot be *C*. |
| undetermined | The ontology neither entails nor rules out that every A is a B. |
| A EquivalentTo G and R | An A is defined as a G that *R*. |
| p Domain D | Only a D *p* anything. |
| p Range R | Whatever something *p* is an R. |
| p SubPropertyOf q | For any x and y: if x *p* y, then x *q* y. |
| other axiom types | Asserted: *Manchester* |

## `--expect`

One candidate per line, Manchester syntax, entities by label (quoted when it
has spaces), CURIE or `<IRI>`; `SubClassOf`, `EquivalentTo` or
`DisjointWith`; `and`, `or`, `not`, `some`, `only`, `value`, `min`, `max`,
`exactly`, `inverse (p)`. Lines starting with `#` are skipped.

```
'irreversibly accountable agent' SubClassOf 'accountable agent'
sanction SubClassOf 'responds to' some 'normative breach'
```

A G6 record replaces a generated record with the same sentence.

## How it reasons

The tool does not classify the ontology once with probe classes added
(a complement probe per filler and property made HermiT run out of memory on
NAO). It sends batched checks to the `O2uProbe` helper, which keeps one
reasoner alive for a whole batch:

1. consistency; the named superclasses and the satisfiability of every named
   class; whether each `p some B` is satisfiable; whether each native A can
   stand in p at all (`A and p some Thing`); G5; G6;
2. G2 and G3;
3. G4, only where G3 failed (when A cannot stand in p at all, G4 holds for
   every filler without a check);
4. the inheritance checks of the filtering step, only for claims that hold.

Every batch goes to every reasoner in `--reasoners` (default `hermit,pellet`:
HermiT from robot.jar with OWL API 4, Pellet 2.3 as bundled with owlready2
with OWL API 3; the same helper source is compiled against each). Any
disagreement stops the run (below). On NAO about 17,000 checks take about
15 seconds.

Justifications come from the `O2uExplain` helper (OWL API explanation
library with HermiT), at most `--max-explain` of them; the rest are marked
`"justification_skipped": true`.

## Hard stops

| Code | Exit | When | What you get |
|---|---|---|---|
| H2 | 4 | the ontology is inconsistent | `inconsistency.txt` with one justification; no claims |
| H3 | 5 | the reasoners disagree on any check | `reasoner-disagreement.tsv`; nothing is adjudicated |
| H4 | 6 | the planned checks exceed `--max-probes` (default 50,000) | the counts per grammar row, before any reasoning |

`--max-probes` bounds the planned checks, which is the worst case
(|N|x|F| + 2|N|x|P|x|F| + ...). NAO plans about 22,800 and sends about
17,000 including the inheritance checks.

An SVG is refused (exit 2) with the IRI of the ontology it was drawn from: a
diagram leaves axioms out, so claims are never computed from one.

## Requirements

Java, `robot.jar` (`scripts/setup.sh`, or `OWL2UML_ROBOT_JAR`) for HermiT and
the explanations, and `owlready2` for Pellet. `--reasoners hermit` runs
without Pellet.

## Reference output

`examples/claims-nao/` is the default output for `tests/fixtures/nao.ttl`,
NAO's native axioms and the BFO and ODP003 terms they use, rebuilt from an
owl2uml diagram of `nao-full.owl` by `scripts/nao_fixture.py`.
`tests/test_claims.py` checks the acceptance fixtures against it.
