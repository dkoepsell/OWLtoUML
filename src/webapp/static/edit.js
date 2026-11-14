/* owl2uml edit mode.
 *
 * Edits are kept as a list of steps (each a list of semantic ops naming
 * classes and properties by IRI; see src/owl2uml/edit.py). The server applies
 * them on "Re-layout" (/api/render) and "Export OWL" (/api/export); until then
 * they are drawn here as a draft overlay: dashed lines, faded deletions, new
 * class boxes. Steps survive re-renders and are kept per file in localStorage.
 */
"use strict";
(function () {
  const NS = "http://www.w3.org/2000/svg";
  const KINDS = [
    ["subclass", "is a (subclass of)"],
    ["some", "property some"],
    ["only", "property only"],
    ["domain_range", "property domain → range"],
    ["equivalent", "equivalent to"],
  ];
  const NEEDS_PROP = new Set(["some", "only", "domain_range"]);
  const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  const local = (iri) => iri.replace(/^.*[#/]/, "");

  function create(opts) {
    let steps = [];      // [[op, ...], ...]
    let redoStack = [];
    let baked = 0;       // steps[0..baked) are already drawn by the server
    let key = null;      // localStorage key for the current file
    let cx = null;       // per-render context: {svg, it, src, layer, overlay, ...}
    let sel = null;      // {type: "edge", eid} | {type: "node", iri}
    let on = false;

    const ops = () => steps.flat();
    const changed = () => {
      try { if (key) localStorage.setItem(key, JSON.stringify(steps)); } catch (_) {}
      if (cx) draw();
      if (opts.onChange) opts.onChange(steps.length, ops().length);
    };
    function push(step) { steps.push(step); redoStack = []; changed(); }

    // ---- IRIs ----------------------------------------------------------------
    // New IRIs go where most of this ontology's classes live (keep in step with
    // edit.py _namespace), else under the ontology IRI.
    function namespace() {
      const counts = new Map();
      for (const iri of Object.keys(cx.src.classes)) {
        if (/^http:\/\/purl\.obolibrary\.org\/obo\//.test(iri) && cx.src.ontology && !cx.src.ontology.startsWith("http://purl.obolibrary.org/obo/")) continue;
        const ns = iri.replace(/[^#/]*$/, "");
        counts.set(ns, (counts.get(ns) || 0) + 1);
      }
      let best = null;
      for (const [ns, n] of counts) if (!best || n > counts.get(best)) best = ns;
      if (best) return best;
      const o = cx.src.ontology;
      return o ? (/[#/]$/.test(o) ? o : o + "#") : "http://example.org/draft#";
    }
    function mint(label, lower) {
      let name = (label.match(/[A-Za-z0-9]+/g) || ["New"]).map((w) => w[0].toUpperCase() + w.slice(1)).join("");
      if (lower) name = name[0].toLowerCase() + name.slice(1);
      if (/^\d/.test(name)) name = "_" + name;
      const taken = new Set([...Object.keys(cx.src.classes), ...Object.keys(cx.src.objprops || {}),
        ...ops().map((o) => o.iri).filter(Boolean)]);
      let iri = namespace() + name, n = 2;
      while (taken.has(iri)) iri = namespace() + name + n++;
      return iri;
    }
    const nidOf = (iri) => cx.iriToNid.get(iri);
    function labelOf(iri) {
      let l = null;
      for (const o of ops()) if ((o.op === "add_class" || o.op === "rename" || o.op === "add_property") && o.iri === iri) l = o.label;
      if (l) return l;
      const c = cx.src.classes[iri];
      return (c && (c.label || c.name)) || (cx.src.objprops || {})[iri] || local(iri);
    }

    // ---- geometry --------------------------------------------------------------
    function toLayer(ev) {
      return new DOMPoint(ev.clientX, ev.clientY).matrixTransform(cx.layer.getScreenCTM().inverse());
    }
    function boxOf(iri) {
      const nid = nidOf(iri);
      if (nid) return cx.it.nodeBox(nid);
      const d = cx.drafts.get(iri);
      return d ? { x: d.x, y: d.y, width: d.w, height: d.h } : null;
    }
    function border(b, tx, ty) {   // where the line from b's centre to (tx,ty) leaves b
      const cx_ = b.x + b.width / 2, cy = b.y + b.height / 2, dx = tx - cx_, dy = ty - cy;
      if (!dx && !dy) return { x: cx_, y: cy };
      const s = Math.min(dx ? b.width / 2 / Math.abs(dx) : Infinity, dy ? b.height / 2 / Math.abs(dy) : Infinity);
      return { x: cx_ + dx * s, y: cy + dy * s };
    }
    function el(tag, attrs, parent) {
      const e = document.createElementNS(NS, tag);
      for (const k in attrs) e.setAttribute(k, attrs[k]);
      if (parent) parent.appendChild(e);
      return e;
    }
    function line(a, b, label, cls) {
      const A = boxOf(a), B = boxOf(b);
      if (!A || !B) return;
      const p = border(A, B.x + B.width / 2, B.y + B.height / 2), q = border(B, A.x + A.width / 2, A.y + A.height / 2);
      const g = el("g", { class: "o2u-draft-edge " + (cls || "") }, cx.overlay);
      el("line", { x1: p.x, y1: p.y, x2: q.x, y2: q.y, "marker-end": "url(#o2u-draft-arrow)" }, g);
      if (label) {
        const t = el("text", { x: (p.x + q.x) / 2, y: (p.y + q.y) / 2 - 4, "text-anchor": "middle" }, g);
        t.textContent = label;
      }
    }
    function edgeLabel(e) {
      if (e.kind === "generalization" || e.kind === "subclass") return "";
      if (e.kind === "equivalent") return "≡";
      const p = e.prop ? labelOf(e.prop) : "";
      return e.quant ? `${p} ${e.quant}` : e.kind === "some" || e.kind === "only" ? `${p} ${e.kind}` : p;
    }

    // ---- draft overlay -----------------------------------------------------------
    function resetMarks() {
      cx.svg.querySelectorAll(".o2u-deleted, .o2u-moved, .o2u-sel").forEach((n) => n.classList.remove("o2u-deleted", "o2u-moved", "o2u-sel"));
      for (const [t, txt] of cx.renamed) t.textContent = txt;
      cx.renamed.clear();
      cx.overlay.textContent = "";
    }
    function edgesMatching(spec) {   // drawn edge ids for an edge spec
      return Object.entries(cx.src.edges).filter(([, e]) => e.src === spec.src && e.dst === spec.dst &&
        (e.kind === spec.kind || (spec.kind === "generalization" && e.kind === "definition"))).map(([id]) => id);
    }
    function markEdge(spec, cls) {
      for (const id of edgesMatching(spec)) { const g = cx.svg.getElementById(id); if (g) g.classList.add(cls); }
    }
    function draw() {
      if (!cx) return;
      resetMarks();
      const pending = steps.slice(baked).flat();
      // new classes first, so lines can reach them
      cx.drafts.forEach((d, iri) => { if (!pending.some((o) => o.op === "add_class" && o.iri === iri)) cx.drafts.delete(iri); });
      for (const o of pending) if (o.op === "add_class") {
        const label = labelOf(o.iri), w = Math.max(90, label.length * 7.5 + 30), h = 30;
        const d = cx.drafts.get(o.iri) || { x: o.pos ? o.pos.x : 0, y: o.pos ? o.pos.y : 0 };
        Object.assign(d, { w, h }); cx.drafts.set(o.iri, d);
        const g = el("g", { class: "o2u-draft-class", "data-iri": o.iri }, cx.overlay);
        el("rect", { x: d.x, y: d.y, width: w, height: h, rx: 3 }, g);
        el("text", { x: d.x + w / 2, y: d.y + 19, "text-anchor": "middle" }, g).textContent = label;
        if (o.parent) line(o.iri, o.parent, "", "gen");
      }
      for (const o of pending) {
        if (o.op === "rename" && nidOf(o.iri)) {
          const g = cx.it.nodeEl(nidOf(o.iri));
          const texts = [...g.querySelectorAll("text")];
          const old = labelOfOriginal(o.iri);
          const t = texts.find((x) => x.textContent.trim() === old) || texts.find((x) => x.getAttribute("font-weight") === "bold") || texts[0];
          if (t) { if (!cx.renamed.has(t)) cx.renamed.set(t, t.textContent); t.textContent = o.label; }
        } else if (o.op === "delete_class" && nidOf(o.iri)) {
          cx.it.nodeEl(nidOf(o.iri)).classList.add("o2u-deleted");
          for (const [id, e] of Object.entries(cx.src.edges))
            if (e.src === o.iri || e.dst === o.iri) { const g = cx.svg.getElementById(id); if (g) g.classList.add("o2u-deleted"); }
        } else if (o.op === "delete_class") {
          const d = cx.overlay.querySelector(`[data-iri="${CSS.escape(o.iri)}"]`);
          if (d) d.classList.add("o2u-deleted");
        } else if (o.op === "add_edge") {
          line(o.src, o.dst, edgeLabel(o), o.kind === "subclass" ? "gen" : "");
        } else if (o.op === "delete_edge") {
          markEdge(o.edge, "o2u-deleted");
        } else if (o.op === "retarget") {
          markEdge(o.edge, "o2u-moved");
          const e = Object.assign({}, o.edge, { [o.end]: o.to });
          line(e.src, e.dst, edgeLabel(e), e.kind === "generalization" ? "gen" : "");
        }
      }
      if (sel && sel.type === "edge") { const g = cx.svg.getElementById(sel.eid); if (g) g.classList.add("o2u-sel"); handles(); }
      if (sel && sel.type === "node" && nidOf(sel.iri)) cx.it.nodeEl(nidOf(sel.iri)).classList.add("o2u-sel");
    }
    function labelOfOriginal(iri) { const c = cx.src.classes[iri]; return c ? (c.name || c.label) : ""; }

    // ---- interaction ----------------------------------------------------------------
    let gesture = null;   // {type: "connect"|"retarget", from, fixed, end, eid, temp}

    function startGesture(ev, g) {
      gesture = g;
      const b = boxOf(g.fixed);
      g.temp = el("line", { class: "o2u-temp", x1: b.x + b.width / 2, y1: b.y + b.height / 2, x2: b.x + b.width / 2, y2: b.y + b.height / 2 }, cx.overlay);
      document.addEventListener("pointermove", gMove);
      document.addEventListener("pointerup", gUp);
      ev.preventDefault();
      ev.stopPropagation();
    }
    function gMove(ev) {
      const p = toLayer(ev);
      gesture.temp.setAttribute("x2", p.x);
      gesture.temp.setAttribute("y2", p.y);
    }
    function targetAt(ev) {
      const hit = document.elementFromPoint(ev.clientX, ev.clientY);
      const d = hit && hit.closest && hit.closest(".o2u-draft-class");
      if (d) return d.getAttribute("data-iri");
      const nid = cx.it.nodeAtPoint(ev.clientX, ev.clientY);
      return nid ? cx.src.nodes[nid] : null;
    }
    function gUp(ev) {
      document.removeEventListener("pointermove", gMove);
      document.removeEventListener("pointerup", gUp);
      const g = gesture; gesture = null;
      g.temp.remove();
      const to = targetAt(ev);
      if (!to) return;
      if (g.type === "connect") { if (to !== g.fixed) newEdgePopover(ev, g.fixed, to); return; }
      // retarget: pick which axiom of a merged line moves
      const parts = partsOf(g.eid);
      const go = (spec) => { if (spec[g.end] !== to) push([{ op: "retarget", edge: spec, end: g.end, to }]); };
      if (parts.length === 1) go(parts[0]);
      else choosePart(ev, parts, (chosen) => chosen.forEach(go));
    }

    function partsOf(eid) {
      const e = cx.src.edges[eid];
      const base = { kind: e.kind, src: e.src, dst: e.dst };
      if (e.kind === "restriction" && e.parts && e.parts.length) return e.parts.map((p) => Object.assign({}, base, p));
      if (e.kind === "association" && e.props && e.props.length) return e.props.map((p) => Object.assign({}, base, { prop: p }));
      return [base];
    }
    const partName = (p) => edgeLabel(p) || (p.kind === "definition" ? "definition member" : p.kind === "generalization" ? "subclass of" : p.kind);

    function handles() {
      const ends = cx.it.edgeEnds(sel.eid);
      if (!ends) return;
      const e = cx.src.edges[sel.eid];
      [["src", ends.from, e.dst], ["dst", ends.to, e.src]].forEach(([end, pt, fixed]) => {
        const h = el("circle", { class: "o2u-handle", cx: pt.x, cy: pt.y, r: 6 }, cx.overlay);
        h.addEventListener("pointerdown", (ev) => startGesture(ev, { type: "retarget", end, eid: sel.eid, fixed }));
        h.addEventListener("mousedown", (ev) => ev.stopPropagation());
      });
    }

    const hooks = {
      nodeDown(ev, nid) {
        if (!on) return false;
        sel = { type: "node", iri: cx.src.nodes[nid] };
        draw();
        if (!ev.altKey) return false;
        startGesture(ev, { type: "connect", fixed: cx.src.nodes[nid] });
        return true;
      },
      moved() { if (on && steps.length > baked) draw(); else if (on && sel && sel.type === "edge") draw(); },
      edgeClick(eid) {
        if (!on || !cx.src.edges[eid] || cx.src.edges[eid].kind === "inferred") return false;
        sel = { type: "edge", eid };
        draw();
        return true;
      },
    };

    function onOverlayDown(ev) {     // drag or connect from a draft class
      const d = ev.target.closest && ev.target.closest(".o2u-draft-class");
      if (!d || !on) return;
      const iri = d.getAttribute("data-iri");
      sel = { type: "node", iri };
      if (ev.altKey) return startGesture(ev, { type: "connect", fixed: iri });
      ev.stopPropagation(); ev.preventDefault();
      const box = cx.drafts.get(iri), p0 = toLayer(ev), start = { x: box.x, y: box.y };
      const mv = (e2) => { const p = toLayer(e2); box.x = start.x + p.x - p0.x; box.y = start.y + p.y - p0.y; draw(); };
      const up = () => {
        document.removeEventListener("pointermove", mv); document.removeEventListener("pointerup", up);
        const o = ops().find((x) => x.op === "add_class" && x.iri === iri);
        if (o) { o.pos = { x: box.x, y: box.y }; changed(); }
      };
      document.addEventListener("pointermove", mv); document.addEventListener("pointerup", up);
    }

    function onDbl(ev) {
      if (!on || !cx || !cx.svg.contains(ev.target)) return;
      ev.preventDefault(); ev.stopPropagation();
      const d = ev.target.closest(".o2u-draft-class");
      const g = ev.target.closest("g.node");
      const iri = d ? d.getAttribute("data-iri") : g ? cx.src.nodes[cx.it.idOf(g)] : null;
      if (iri) {
        popover(ev, `<label>Rename<input name="label" value="${esc(labelOf(iri))}"></label>`, (f) => {
          const label = f.label.value.trim();
          if (label && label !== labelOf(iri)) push([{ op: "rename", iri, label }]);
        });
      } else addClassAt(ev, toLayer(ev));
    }
    function addClassAt(ev, pos) {
      const parents = [...Object.keys(cx.src.classes)].sort((a, b) => labelOf(a).localeCompare(labelOf(b)));
      popover(ev, `<label>New class<input name="label" placeholder="Name" required></label>
        <label>Subclass of<select name="parent"><option value="">(none)</option>${parents.map((p) => `<option value="${esc(p)}">${esc(labelOf(p))}</option>`).join("")}</select></label>`, (f) => {
        const label = f.label.value.trim();
        if (!label) return;
        const op = { op: "add_class", iri: mint(label), label, pos: { x: pos.x, y: pos.y } };
        if (f.parent.value) op.parent = f.parent.value;
        push([op]);
      });
    }

    function onKey(ev) {
      if (!on || /^(INPUT|TEXTAREA|SELECT)$/.test(ev.target.tagName)) return;
      const mod = ev.ctrlKey || ev.metaKey;
      if (mod && ev.key.toLowerCase() === "z") { ev.preventDefault(); ev.shiftKey ? redo() : undo(); return; }
      if (mod && ev.key.toLowerCase() === "y") { ev.preventDefault(); redo(); return; }
      if ((ev.key === "Delete" || ev.key === "Backspace") && sel) { ev.preventDefault(); deleteSelected(ev); }
      if (ev.key === "Escape") { sel = null; closePop(); if (cx) draw(); }
    }
    function deleteSelected(ev) {
      if (sel.type === "edge") {
        const parts = partsOf(sel.eid);
        const go = (chosen) => { push(chosen.map((edge) => ({ op: "delete_edge", edge }))); sel = null; draw(); };
        if (parts.length === 1) go(parts);
        else choosePart(ev, parts, go);
      } else if (sel.type === "node") {
        const iri = sel.iri;
        const fresh = ops().some((o) => o.op === "add_class" && o.iri === iri);
        if (!fresh && !confirm(`Delete class "${labelOf(iri)}" and every axiom that mentions it?`)) return;
        push([{ op: "delete_class", iri }]);
        sel = null; draw();
      }
    }

    // ---- popovers ----------------------------------------------------------------------
    const pop = () => document.getElementById("editPop");
    function closePop() { const p = pop(); if (p) { p.hidden = true; p.innerHTML = ""; } }
    function popover(ev, inner, onOk) {
      const p = pop();
      p.innerHTML = `<form>${inner}<div class="edit-pop-btns"><button type="button" data-x>Cancel</button><button class="primary">OK</button></div></form>`;
      p.hidden = false;
      p.style.left = Math.min(ev.clientX + 8, window.innerWidth - 320) + "px";
      p.style.top = Math.min(ev.clientY + 8, window.innerHeight - p.offsetHeight - 8) + "px";
      const f = p.querySelector("form");
      f.addEventListener("submit", (e) => { e.preventDefault(); onOk(f.elements); closePop(); });
      p.querySelector("[data-x]").addEventListener("click", closePop);
      const first = f.querySelector("input, select");
      if (first) { first.focus(); if (first.select) first.select(); }
    }
    function choosePart(ev, parts, cb) {
      popover(ev, `<div class="edit-pop-title">Which part of this line?</div>` + parts.map((p, i) =>
        `<label class="chk"><input type="checkbox" name="p${i}" checked> ${esc(partName(p))}</label>`).join(""), (f) => {
        const chosen = parts.filter((_, i) => f["p" + i].checked);
        if (chosen.length) cb(chosen);
      });
    }
    function newEdgePopover(ev, src, dst) {
      const props = Object.assign({}, cx.src.objprops || {});
      for (const o of ops()) if (o.op === "add_property") props[o.iri] = o.label;
      const opts_ = Object.entries(props).sort((a, b) => a[1].localeCompare(b[1]))
        .map(([iri, l]) => `<option value="${esc(l)}">${esc(local(iri))}</option>`).join("");
      popover(ev, `<div class="edit-pop-title">${esc(labelOf(src))} → ${esc(labelOf(dst))}</div>
        <label>Relation<select name="kind">${KINDS.map(([k, l]) => `<option value="${k}">${l}</option>`).join("")}</select></label>
        <label class="propRow" hidden>Property<input name="prop" list="o2uProps" placeholder="existing or new name"></label>
        <datalist id="o2uProps">${opts_}</datalist>`, (f) => {
        const kind = f.kind.value, step = [];
        let prop;
        if (NEEDS_PROP.has(kind)) {
          const name = f.prop.value.trim();
          if (!name) return;
          prop = Object.keys(props).find((iri) => props[iri] === name || local(iri) === name || iri === name);
          if (!prop) { prop = mint(name, true); step.push({ op: "add_property", iri: prop, label: name }); }
        }
        const op = { op: "add_edge", kind, src, dst };
        if (prop) op.prop = prop;
        step.push(op);
        push(step);
      });
      const f = pop().querySelector("form");
      const sync = () => { f.querySelector(".propRow").hidden = !NEEDS_PROP.has(f.kind.value); };
      f.kind.addEventListener("change", sync);
      sync();
    }

    // ---- undo / redo -----------------------------------------------------------------
    function undo() {
      if (!steps.length) return;
      redoStack.push(steps.pop());
      if (baked > steps.length) { baked = steps.length; opts.onStale && opts.onStale(); }
      sel = null; changed();
    }
    function redo() { if (redoStack.length) { steps.push(redoStack.pop()); changed(); } }

    // ---- lifecycle ------------------------------------------------------------------
    function attach(svg, it) {
      detach();
      const src = it.source && it.source();
      if (!src || src.view === "flow") return false;
      const layer = it.layer();
      const overlay = el("g", { class: "o2u-draft" }, layer);
      const defs = el("defs", {}, overlay);
      const m = el("marker", { id: "o2u-draft-arrow", markerWidth: 12, markerHeight: 12, refX: 10, refY: 5, orient: "auto", markerUnits: "userSpaceOnUse" }, defs);
      el("path", { d: "M0,0 L10,5 L0,10", fill: "none" }, m);
      const iriToNid = new Map(Object.entries(src.nodes).map(([n, i]) => [i, n]));
      cx = { svg, it, src, layer, overlay, iriToNid, drafts: new Map(), renamed: new Map() };
      overlay.addEventListener("pointerdown", onOverlayDown);
      overlay.addEventListener("mousedown", (ev) => { if (ev.target.closest(".o2u-draft-class, .o2u-handle")) ev.stopPropagation(); });
      // A click on empty canvas drops the selection.
      svg.addEventListener("click", (ev) => {
        if (!on || !cx || !sel || ev.target.closest("g.node, g.edge, .o2u-draft-class, .o2u-handle")) return;
        sel = null; draw();
      });
      svg.classList.toggle("o2u-editing", on);
      draw();
      return true;
    }
    function detach() { if (cx) { cx.overlay.remove(); cx = null; } sel = null; closePop(); }

    document.addEventListener("keydown", onKey);
    document.addEventListener("dblclick", onDbl, true);

    return {
      hooks,
      attach,
      detach,
      setOn(v) {
        on = !!v; sel = null; closePop();
        if (cx) { cx.svg.classList.toggle("o2u-editing", on); draw(); }
      },
      isOn: () => on,
      // Bind the edit list to a file; returns saved steps found for it (not yet loaded).
      bindFile(file) {
        steps = []; redoStack = []; baked = 0;
        key = file ? `o2u-edits:${file.name}:${file.size}:${file.lastModified}` : null;
        let saved = null;
        try { saved = key && JSON.parse(localStorage.getItem(key) || "null"); } catch (_) {}
        if (opts.onChange) opts.onChange(0, 0);
        return Array.isArray(saved) && saved.length ? saved : null;
      },
      load(saved) { steps = saved; baked = 0; changed(); },
      ops,
      count: () => steps.length,
      markBaked() { baked = steps.length; },
      undo, redo,
      addClass(ev) {
        if (!cx) return;
        const r = cx.svg.getBoundingClientRect();
        const fake = { clientX: r.left + r.width / 2, clientY: r.top + r.height / 2 };
        addClassAt(ev && ev.clientX ? ev : fake, toLayer(fake));
      },
      // Mark skipped ops (from the server report) so the user can see them.
      skipped(list) { return (list || []).map((s) => `#${s.i + 1} ${s.op || "?"}: ${s.reason}`); },
    };
  }

  window.OwlUmlEdit = { create };
})();
