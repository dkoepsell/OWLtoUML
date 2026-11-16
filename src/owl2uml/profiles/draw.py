"""DOT statements for a profile's layout hints: bands, lanes, motifs."""
from __future__ import annotations

from ..model import HIERARCHY_KINDS, UModel
from .loader import BANDS_ORDER


def _hierarchy(m: UModel) -> tuple[dict, dict]:
    up: dict[str, set[str]] = {}
    down: dict[str, set[str]] = {}
    for e in m.edges:
        if e.kind in HIERARCHY_KINDS:
            up.setdefault(e.src, set()).add(e.dst)
            down.setdefault(e.dst, set()).add(e.src)
    return up, down


def hint_lines(m: UModel, ids: dict[str, str]) -> list[str]:
    """Invisible structure that puts profile bands, lanes and motifs in place.
    Everything here takes part in ranking, so the two-pass skeleton keeps it."""
    r = m.render or {}
    out: list[str] = []
    up, down = _hierarchy(m)
    bands = r.get("bands") or {}
    order = [b for b in BANDS_ORDER if bands.get(b)] + \
        sorted(b for b in bands if b not in BANDS_ORDER and bands[b])
    # rankdir BT: "a -> b" puts b above a. A split point under each band's
    # lowest classes and above the next band's top classes.
    for k, (upper, lower) in enumerate(zip(order, order[1:])):
        split = f"band{k}"
        out.append(f'  {split} [shape=point, style=invis, width=0.01, label="", '
                   f'class="uml-band-split"];')
        hi = [c for c in bands[upper] if c in ids]
        lo = [c for c in bands[lower] if c in ids]
        hi_set, lo_set = set(hi), set(lo)
        for c in hi:
            if not (down.get(c, set()) & hi_set):          # a leaf of the upper band
                out.append(f"  {split} -> {ids[c]} [style=invis, weight=0];")
        for c in lo:
            if not (up.get(c, set()) & lo_set):            # a top class of the lower band
                out.append(f"  {ids[c]} -> {split} [style=invis, weight=0];")
    fixed = set(r.get("fixed") or [])
    for name, members in sorted((r.get("lanes") or {}).items()):
        # one row; a member related to another by the hierarchy cannot share it
        chosen: list[str] = []
        for c in members:
            if c in ids and c not in fixed and not any(
                    x in up.get(c, ()) or c in up.get(x, ()) for x in chosen):
                chosen.append(c)
        if len(chosen) > 1:
            out.append(f'  {{rank=same; {"; ".join(ids[c] for c in chosen)};}}'
                       f'  // lane: {name}')
    for k, motif in enumerate(r.get("motifs") or []):
        rows = [[ids[c] for c in row if c in ids] for row in motif["rows"]]
        # one group per column: Graphviz keeps it a straight vertical line
        for row in rows:
            for col, nid in enumerate(row):
                out.append(f'  {nid} [group="motif{k}c{col}"];')
        for row in rows:
            if not row:             # a partial figure (module view, diff) may lack a row
                continue
            out.append(f'  {{rank=same; {"; ".join(row)};}}  // motif: {motif["name"]}')
            # flat invisible edges fix the left-to-right order in the row
            for a, b in zip(row, row[1:]):
                out.append(f"  {a} -> {b} [style=invis, weight=20];")
        for above, below in zip(rows, rows[1:]):
            for a, b in zip(above, below):
                out.append(f"  {b} -> {a} [style=invis, weight=20];")
    return out + list(r.get("extra_dot") or [])   # e.g. the diff key (diff/render.py)


def edge_extra(e) -> str:
    """Extra DOT attributes for a styled line."""
    if e.style == "symmetric_pair":
        return ", dir=none"
    if e.style == "inverse_merged":
        return ", dir=both, arrowtail=vee"
    return ""
