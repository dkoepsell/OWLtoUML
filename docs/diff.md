# Version diff

`owl2uml diff OLD NEW` draws one diagram of what changed between two versions
of an ontology, asserted and inferred (spec WS4).

```
owl2uml diff lof-0.2.0.owl lof-0.3.0.owl                 # lof-0.3.0-diff.svg/.json/.md
owl2uml diff old.owl new.owl --profile bfo,legal --export png
owl2uml diff old.owl new.owl --fail-on unsatisfiable,removed-without-deprecation
```

In the web app, choose **Compare with older version** on the start page, then
open the newer version as usual.

## What is compared

| Layer | How |
| --- | --- |
| Entities | added, removed, renamed (same IRI, new label), deprecated; a deprecated term with `IAO_0100001` (term replaced by) is reported as renamed to its replacement; a removed and an added entity with labels more than 90% alike are listed as a *possible* rename only |
| Asserted axioms | by the stable axiom ids of the coverage report: blank-node restrictions are compared by structure, so the same axiom in another file or syntax is the same axiom. Declarations are left to the entity layer; annotation changes are counted apart from logical ones |
| Inferred | both versions are classified (`--reason`, default `auto`; `none` skips it). Direct superclass links the reasoner adds (or no longer adds) that nobody asserted, newly unsatisfiable classes, inconsistency, and every class whose set of superclasses changed ("moved") |

## The diagram

* green outline / line: added · red dashed: removed (drawn from the old version) ·
  amber: changed (renamed, deprecated, or an axiom on that line or class changed;
  a renamed class reads "new name (was old name)") · orange with **+** or **−**:
  newly inferred or no longer inferred superclass · red class: unsatisfiable.
* `--diff-scope 1hop` (default) draws the changes plus their neighbours, greyed;
  `changed` only the changes; `all` the whole ontology.
* Positions come from the old version's `.layout.json` when there is one
  (`--layout` to choose another), so unchanged classes stay where readers know them.
* A box beside the key gives the counts per category and the classes that moved.
* Click a coloured class or line: the source panel shows the old and the new
  OWL side by side.

## Outputs

| File | What |
| --- | --- |
| `<out>.svg` | the diagram, with both versions' source embedded (`--interactive` inlines the viewer) |
| `<out>.json` | the change set by layer, the summary counts, the `--fail-on` result |
| `<out>.md` | a Markdown summary for pull requests |
| `<out>.png`, `<out>-static.svg`, `<out>.pdf` | with `--export png,svg-static,pdf` |

`--fail-on` takes any of `unsatisfiable`, `inconsistent`, `new-orphans` (classes
whose only parent is now owl:Thing), `removed-without-deprecation` and
`coverage-drop` (fewer axioms shown than before); when one holds the command
exits with status 3.

## GitHub Action

`action/` in this repository is a composite action. In the ontology's repository:

```yaml
on: [pull_request, push]
permissions:
  contents: write          # the PNG for the comment, docs/diagrams on main
  pull-requests: write     # the comment
jobs:
  diagram:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with: {fetch-depth: 0}
      - uses: <owner>/OWLtoUML/action@main
        with:
          ontology: src/ontology/lof-edit.owl     # default: src/ontology/*-edit.*
          profile: bfo,legal
          reason: hermit
          modules: true
          fail-on: unsatisfiable,new-orphans
```

On a pull request it checks out the base commit beside the head, runs
`owl2uml diff`, uploads the figures as the `owl2uml-diff` artifact, writes the
summary to the job summary and posts one comment on the pull request (updated
on later pushes) with the PNG and the summary. The PNG is committed to the
`owl2uml-images` branch so the comment can show it (`image-branch: ""` turns
this off; in a private repository the image shows only to people who can read
the repository). With `fail-on`, the job fails after the comment is posted.

On a push to the default branch it redraws the ontology into `docs/diagrams/`
(`docs-dir`), with one figure per module when `modules: true`, and commits the
figures when they changed.

ODK repositories need no `ontology` input: `src/ontology/<name>-edit.*` is
found, and imports are resolved through the `catalog-v001.xml` next to it.
