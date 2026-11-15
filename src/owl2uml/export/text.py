"""Text exports: PlantUML, ontopuml (IOF NOWL notation), Mermaid."""
from __future__ import annotations

import re

from ..model import HIERARCHY_KINDS, UModel

_LINE = re.compile(r"^(?P<p>.*?)(?: (?P<q>some|only|∃∀|value|self|min \d+|max \d+|exactly \d+))?"
                   r"(?P<neg> ¬)?(?: \[(?P<mult>[^\]]+)\])?$")
_BADGE = re.compile(r"\s*[⁻¹↔⁺]+$")
NOWL_LIB = "https://raw.githubusercontent.com/iofoundry/ontopuml/refs/heads/main/iof.iuml"


def _ids(m: UModel) -> dict[str, str]:
    return {cid: f"n{i}" for i, cid in enumerate(m.classes)}


def _q(text: str) -> str:
    return text.replace('"', "'").replace("\n", " ")


def restrictions(label: str, mult: str = "") -> list[dict]:
    """Split a (possibly merged) restriction label into its parts."""
    out = []
    for line in (label or "").split("\n"):
        mt = _LINE.match(line.strip())
        if not mt:
            continue
        q = mt.group("q") or ""
        out.append({"prop": _BADGE.sub("", mt.group("p")).strip(), "q": q,
                    "neg": bool(mt.group("neg")), "mult": mt.group("mult") or mult})
    return out


# --------------------------------------------------------------------------- PlantUML

_PUML_ARROWS = {
    "generalization": "--|>", "definition": "..|>", "inferred": "-[#D9822B]-|>",
    "association": "-->", "restriction": "..>", "equivalent": "..", "disjoint": "..",
    "member": "--", "self": "..>",
}


def plantuml(m: UModel, warnings: list, graph=None) -> str:
    ids = _ids(m)
    out = ["@startuml", "skinparam classAttributeIconSize 0", "skinparam shadowing false",
           "skinparam class {", "  BackgroundColor #F2F7F2", "  BorderColor #8A8780",
           "  ArrowColor #3A5A8C", "}", "hide empty methods", ""]
    for cid, c in m.classes.items():
        n = ids[cid]
        if c.kind in ("union", "complement", "disjoint"):
            out.append(f'circle "{_q(c.name)}" as {n}')
        elif c.kind == "individual":
            out.append(f'object "{_q(c.name)}" as {n}')
        elif c.kind == "enumeration" or c.stereotype == "enumeration":
            out.append(f'enum "{_q(c.name or "one of")}" as {n} {{')
            out += [f"  {_q(a.name)}" for a in c.attrs]
            out.append("}")
        else:
            st = c.stereotype or ("unsatisfiable" if c.unsatisfiable else
                                  "defined" if c.defined else "deprecated" if c.deprecated else "")
            stereo = f" <<{st}>>" if st else ""
            color = " #F6D5D1" if c.unsatisfiable else " #E8E6E0" if c.deprecated or c.context else ""
            body = [f"  {_q(a.label())}" for a in c.attrs]
            out.append(f'class "{_q(c.name)}" as {n}{stereo}{color}' + (" {" if body else ""))
            if body:
                out += body + ["}"]
    out.append("")
    for e in m.edges:
        if e.src not in ids or e.dst not in ids:
            continue
        a, b = ids[e.src], ids[e.dst]
        arrow = _PUML_ARROWS.get(e.kind, "-->")
        if e.kind == "disjoint":
            arrow = "-[#C0392B,dotted]-"
        mult = f' "{e.multiplicity}"' if e.multiplicity else ""
        label = e.label.replace("\n", "\\n") if e.label else ""
        out.append(f"{a} {arrow}{mult} {b}" + (f" : {label}" if label else ""))
    out.append("@enduml")
    return "\n".join(out) + "\n"


# --------------------------------------------------------------------------- ontopuml

def _curie(graph, iri: str) -> str:
    if graph is not None and not iri.startswith("_:"):
        try:
            c = graph.namespace_manager.normalizeUri(iri)
            if not c.startswith("<"):
                return c
        except Exception:  # noqa: BLE001
            pass
    tail = re.split(r"[#/]", iri.rstrip("/#"))[-1]
    return f":{tail}"


def ontopuml(m: UModel, warnings: list, graph=None) -> str:
    """IOF NOWL notation (github.com/iofoundry/ontopuml). See
    docs/ontopuml-mapping.md for what each diagram element becomes."""
    ids = _ids(m)
    out = ["@startuml", f"!include {NOWL_LIB}", ""]
    named = {cid: c for cid, c in m.classes.items() if c.kind == "class"}
    for cid in named:
        out.append(f'class({ids[cid]}, "{_curie(graph, cid)}")')
    for cid, c in m.classes.items():
        if c.kind == "individual":
            out.append(f'individual({ids[cid]}, "{_curie(graph, cid)}")')
    members: dict[str, list[str]] = {}
    for e in m.edges:
        if e.kind == "member":
            members.setdefault(e.src, []).append(e.dst)
    for cid, c in m.classes.items():
        if c.kind == "union":
            items = ", ".join(f'"{ids[x]}"' for x in members.get(cid, []))
            out.append(f"union({ids[cid]}, '[{items}]')")
        elif c.kind == "complement" and members.get(cid):
            out.append(f"complement({ids[cid]}, {ids[members[cid][0]]})")
        elif c.stereotype == "enumeration":
            items = ", ".join(f'"{_q(a.name)}"' for a in c.attrs)
            out.append(f"oneOf({ids[cid]}, '[{items}]')")
    out.append("")
    defined: dict[str, list[str]] = {}
    r = 0
    for e in m.edges:
        if e.src not in ids or e.dst not in ids:
            continue
        a, b = ids[e.src], ids[e.dst]
        if e.kind in ("generalization", "inferred"):
            out.append(f"subClass({a}, {b})")
        elif e.kind == "definition":
            defined.setdefault(e.src, []).append(b)
        elif e.kind == "equivalent":
            out.append(f"equivalent({a}, {b})")
        elif e.kind == "disjoint":
            if m.classes[e.src].kind != "disjoint":
                out.append(f"disjoint({a}, {b})")
        elif e.kind in ("restriction", "self"):
            props = list(e.props)
            for k, part in enumerate(restrictions(e.label, e.multiplicity)):
                r += 1
                rid = f"r{r}"
                prop = _curie(graph, props[min(k, len(props) - 1)]) if props else part["prop"]
                target = b
                if part["neg"]:
                    out.append(f"complement(c{r}, {b})")
                    target = f"c{r}"
                if part["mult"]:
                    word, n = _card(part["mult"])
                    out.append(f"someCard({rid}, {prop}, {target}, {word}, {n})")
                elif part["q"] in ("some", "only"):
                    out.append(f"{part['q']}({rid}, {prop}, {target})")
                elif part["q"] == "∃∀":
                    # merged on the diagram (spec WS3.5): both restrictions
                    out.append(f"some({rid}, {prop}, {target})")
                    out.append(f"subClass({a}, {rid})")
                    rid = f"r{r}a"
                    out.append(f"only({rid}, {prop}, {target})")
                else:
                    warnings.append(f"{part['q'] or 'restriction'} on {prop}: "
                                    "no NOWL macro; written as a comment")
                    out.append(f"' {m.classes[e.src].name} {part['prop']} {part['q']} "
                               f"{m.classes[e.dst].name}")
                    continue
                out.append(f"subClass({a}, {rid})")
        elif e.kind == "association":
            out.append(f"' domain/range: {_q(e.label)} ({m.classes[e.src].name} -> "
                       f"{m.classes[e.dst].name})")
    # disjoint groups: one disjoint() per pair
    for cid, c in m.classes.items():
        if c.kind == "disjoint":
            ends = [ids[e.dst] for e in m.edges if e.src == cid]
            out += [f"disjoint({x}, {y})" for i, x in enumerate(ends) for y in ends[i + 1:]]
    for cid, parts in defined.items():
        r += 1
        items = ", ".join(f'"{p}"' for p in parts)
        out.append(f"intersection(d{r}, '[{items}]')")
        out.append(f"equivalent({ids[cid]}, d{r})")
    out.append("@enduml")
    return "\n".join(out) + "\n"


def _card(mult: str) -> tuple[str, str]:
    if mult.endswith("..*"):
        return "min", mult[:-3]
    if mult.startswith("0.."):
        return "max", mult[3:]
    return "exactly", mult


# --------------------------------------------------------------------------- Mermaid

def mermaid(m: UModel, warnings: list, graph=None) -> str:
    """Mermaid classDiagram (GitHub READMEs). A subset: what it cannot show
    is listed in ``warnings``."""
    ids = _ids(m)
    out = ["classDiagram"]
    lost = set()
    for cid, c in m.classes.items():
        n = ids[cid]
        name = c.name or c.stereotype or c.kind
        out.append(f'  class {n}["{_q(name)}"]')
        st = c.stereotype or ("defined" if c.defined else "")
        if st:
            out.append(f"  <<{st}>> {n}")
        for a in c.attrs:
            out.append(f"  {n} : {_q(a.label())}")
        if c.kind in ("union", "complement", "disjoint"):
            lost.add(f"{c.kind} nodes are drawn as plain classes")
        if c.deprecated or c.context or c.unsatisfiable:
            lost.add("colours (deprecated, context, unsatisfiable) are not kept")
    for e in m.edges:
        if e.src not in ids or e.dst not in ids:
            continue
        a, b = ids[e.src], ids[e.dst]
        label = f" : {_q(e.label)}" if e.label else ""
        if e.kind in HIERARCHY_KINDS:
            out.append(f"  {b} <|-- {a}{label if e.kind != 'generalization' else ''}")
            if e.kind != "generalization":
                lost.add("defined-as and inferred subclass lines look like plain ones")
            if e.genset:
                lost.add("generalization sets {disjoint, complete} are not shown")
        elif e.kind == "association":
            out.append(f"  {a} --> {b}{label}")
        elif e.kind in ("restriction", "self"):
            card = f' "{e.multiplicity}"' if e.multiplicity else ""
            out.append(f"  {a} ..>{card} {b}{label}")
        elif e.kind in ("disjoint", "member", "equivalent"):
            out.append(f"  {a} .. {b}{label or (' : ' + e.kind)}")
            if e.kind == "disjoint":
                lost.add("disjointness is a plain dotted line")
    warnings.extend(sorted(lost))
    return "\n".join(out) + "\n"
