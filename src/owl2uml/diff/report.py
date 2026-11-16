"""Markdown summary of a version diff, for pull-request comments (WS4.3)."""
from __future__ import annotations

MAX_ROWS = 40


def _name(d: dict, iri: str) -> str:
    return d.get("labels", {}).get(iri) or iri.rsplit("#", 1)[-1].rsplit("/", 1)[-1]


def _list(title: str, rows: list[str]) -> list[str]:
    if not rows:
        return []
    out = [f"<details><summary>{title} ({len(rows)})</summary>", ""]
    out += [f"- {r}" for r in rows[:MAX_ROWS]]
    if len(rows) > MAX_ROWS:
        out.append(f"- … and {len(rows) - MAX_ROWS} more (see diff.json)")
    return out + ["", "</details>", ""]


def markdown(d: dict, title: str = "Ontology changes", image: str = "",
             failed: list[dict] | None = None) -> str:
    s, e, a, i = d["summary"], d["entities"], d["axioms"], d["inferred"]
    n = lambda iri: f"`{_name(d, iri)}`"  # noqa: E731
    lines = [f"### {title}", ""]
    if d.get("old", {}).get("name") or d.get("new", {}).get("name"):
        lines += [f"{d['old'].get('name', 'old')} → {d['new'].get('name', 'new')}", ""]
    if failed:
        lines += ["**Checks failed:** " + "; ".join(f"{f['condition']} ({f['detail']})"
                                                   for f in failed), ""]
    lines += [
        "| | added | removed | other |", "| --- | ---: | ---: | --- |",
        f"| entities | {s['added']} | {s['removed']} | {s['renamed']} renamed, "
        f"{s['deprecated']} deprecated |",
        f"| logical axioms | {s['axioms_added']} | {s['axioms_removed']} | |",
        f"| annotations | {s['annotations_added']} | {s['annotations_removed']} | |",
    ]
    if i["engine"] != "none":
        lines.append(f"| inferred ({i['engine']}) | {s['inferred_added']} | "
                     f"{s['inferred_removed']} | {s['moved']} classes moved, "
                     f"{s['unsatisfiable']} unsatisfiable"
                     + (", **inconsistent**" if s["inconsistent"] else "") + " |")
    lines.append("")
    if i.get("error"):
        lines += [f"> reasoner failed: {i['error']}", ""]
    if image:
        lines += [f"![diagram of the changes]({image})", ""]
    lines += _list("Classes whose inferred position moved",
                   [n(m["iri"]) + (f" now under {', '.join(n(x) for x in m['gained'])}"
                                   if m["gained"] else "")
                    + (f"; no longer under {', '.join(n(x) for x in m['lost'])}"
                       if m["lost"] else "") for m in i["moved"]])
    lines += _list("Newly unsatisfiable", [n(x) for x in i["unsatisfiable"]["added"]])
    lines += _list("Added", [f"{r['kind']} `{r['label']}`" for r in e["added"]])
    lines += _list("Removed", [f"{r['kind']} `{r['label']}`"
                               + ("" if r["was_deprecated"] else " (not deprecated first)")
                               for r in e["removed"]])
    lines += _list("Renamed", [f"`{r['old']}` → `{r['new']}`" for r in e["renamed"]] +
                   [f"`{r['old_label']}` → `{r['new_label'] or r['new']}` (term replaced by)"
                    for r in e["replaced"]])
    lines += _list("Deprecated", [f"`{r['label']}`" for r in e["deprecated"]])
    lines += _list("Possible renames (similar labels)",
                   [f"`{r['old_label']}` → `{r['new_label']}` ({r['score']:.2f})"
                    for r in e["suggested_renames"]])
    lines += _list("Axioms added", [f"`{r['text']}`" for r in a["added"]])
    lines += _list("Axioms removed", [f"`{r['text']}`" for r in a["removed"]])
    lines += _list("New classes without a parent", [n(x) for x in d["orphans"]])
    return "\n".join(lines).rstrip() + "\n"
