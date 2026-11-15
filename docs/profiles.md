# Notation profiles

A profile tells owl2uml how to draw particular relations and kinds of class,
so a BFO or legal ontology reads in its own idiom (spec WS3). Every axiom a
profile takes off the drawing stays in the source panel: click the class or
line it was folded into.

```
owl2uml onto.owl --profile bfo,legal      # compose left to right
owl2uml onto.owl --profile auto           # pick from the ontology
owl2uml onto.owl --profile ./mine.yaml    # your own file (YAML or JSON)
```

In the web app, choose **Notation** on the start page.

## Bundled profiles

| Profile | Extends | What it does |
| --- | --- | --- |
| `core` | – | symmetric properties as one undirected line; a property and its declared inverse between the same classes as one line (one name at each end); properties drawn on 3+ lines with the same label are coloured and named once in the key |
| `bfo` | core | continuants in a band above occurrents; `inheres in` (and sub-properties such as `held by`) as a row in the dependent's box; lines to upper-level BFO classes and domain → range lines as rows in the box; BFO classes that only pass the hierarchy through are skipped (`--show-bfo full` keeps them); RO and BFO 2.0 relation IRIs treated as their BFO 2020 equivalents |
| `legal` | bfo | `correlative of` as a teal undirected line named in the key; Hohfeld's square (claim/duty, liberty/no-claim; power/liability, immunity/disability) with correlatives side by side and opposites diagonal; first- and second-order positions in two colours; defined legal acts in one row |

## Format

```yaml
profile: mine
extends: bfo                  # one name or a list
relation_styles:              # the last matching rule wins
  - match: {property: "https://example.org/p", subproperties: true}
    style: compartment        # directed | symmetric_pair | inverse_merged |
                              # compartment | containment | hidden
    label: bearer             # compartment: text before the colon
  - match: {characteristic: symmetric}     # symmetric | transitive | functional
    style: symmetric_pair
    stroke: categorical-5     # palette entry, or "#rrggbb"
    key: true                 # name it in the key instead of on every line
  - match: {target: upper}    # lines to imported upper-level classes
    style: compartment
  - match: {kind: association}   # domain -> range lines
    style: compartment
class_styles:
  - match: {subclass_of: "http://purl.obolibrary.org/obo/BFO_0000003"}
    band: occurrent           # continuant bands sit above occurrent ones
  - match: {subclass_of: "https://example.org/Act", defined: true}
    lane: acts                # one row
    color: "#4e79a7"
motifs:
  - name: hohfeld
    rows:                     # cells: an IRI, a label, or a list of either
      - [claim, duty]
      - [liberty, no-claim]
badges:
  hide_class_badge: true      # drop the "C" circle
  auto_key: 3                 # key properties drawn on 3+ identical lines
aliases:                      # treat one IRI as another when matching
  "http://purl.obolibrary.org/obo/RO_0000052": "http://purl.obolibrary.org/obo/BFO_0000197"
bfo_stub: true
```

An ontology can carry its own styling: annotate a property with
`<https://w3id.org/owl2uml/ns#style> "symmetric_pair"` (any style name). Those
rules are applied after every named profile.

## Always on

These apply with or without a profile (spec WS3.5):

* `ObjectInverseOf(P)` is drawn as P's declared inverse in the forward
  direction, or as P with the arrow reversed – never "inverse P".
* `p some B` and `p only B` on the same pair become one label `p ∃∀`.
* Line labels wrap at 22 characters (`--label-width N`, 0 to turn off).
