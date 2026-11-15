/* OWL → UML diagram interaction for Graphviz SVG output.
 *
 *   hover a class   → highlight it, its relations and its neighbours
 *   click a class   → pin that focus (shift-click adds/removes classes)
 *   click it again  → quickly: widen the focus by one more hop; later: unpin
 *   click a line    → jump to the class at its far end
 *   drag a class    → move it; connected lines follow
 *   p               → flow view: switch between the process as practiced
 *                     (from logged events) and as designed (axioms only)
 *   s               → show/hide the source panel: the OWL a clicked class or
 *                     line was drawn from (when the SVG embeds it, see
 *                     owl2uml/source.py)
 *   Esc             → clear focus
 *
 * No dependencies. Used by the web viewer and inlined into downloaded SVGs
 * (attach(svg, {standalone: true}) adds wheel-zoom and background panning).
 * The graph is read from Graphviz's <title> elements ("n3", "n3->n7"), so it
 * also works on SVGs exported before ids/classes were added.
 */
(function (global) {
  "use strict";

  const DRAG_PX = 4;      // movement below this is a click, not a drag
  const REPEAT_MS = 400;  // second click on a pinned class within this widens focus

  const CSS = `
g.node { cursor: grab; }
g.node.oi-drag { cursor: grabbing; }
g.edge { cursor: pointer; }
.oi-hit { fill: none; stroke: transparent; stroke-width: 12px; pointer-events: stroke; }
svg.oi-focus g.node:not(.oi-hl), svg.oi-focus g.edge:not(.oi-hl) { opacity: 0.12; }
svg.oi-focus g.edge.oi-hl path:not(.oi-hit) { stroke-width: 2.6px; }
g.node.oi-sel { filter: drop-shadow(0 0 5px #f0a800) drop-shadow(0 0 2px #f0a800); }
.o2u-src { box-sizing: border-box; height: 100%; display: flex; flex-direction: column;
  background: #fffdf8; border: 1px solid #c9c4b6; border-radius: 8px;
  box-shadow: 0 6px 24px rgba(0,0,0,.18); font: 13px/1.45 Helvetica, Arial, sans-serif; color: #2b2a27; }
.o2u-src[hidden] { display: none; }
.o2u-src * { box-sizing: border-box; }
.o2u-src-head { display: flex; align-items: flex-start; gap: 8px; padding: 10px 12px 4px; }
.o2u-src-title { flex: 1; font-size: 15px; font-weight: 600; word-break: break-word; }
.o2u-src-kind { font-size: 11px; color: #6b675e; text-transform: uppercase; letter-spacing: .04em; }
.o2u-src button { font: inherit; font-size: 12px; border: 1px solid #c9c4b6; background: #f3f0e7;
  border-radius: 5px; padding: 2px 8px; cursor: pointer; color: inherit; }
.o2u-src button:hover { background: #e9e4d6; }
.o2u-src button.on { background: #2b2a27; color: #fff; border-color: #2b2a27; }
.o2u-src-x { border: none !important; background: none !important; font-size: 18px !important; line-height: 1; }
.o2u-src-id { padding: 0 12px 8px; font-size: 12px; color: #6b675e; word-break: break-all; }
.o2u-src-id a { color: #3a5a8c; }
.o2u-src-tabs { display: flex; gap: 4px; padding: 0 12px 8px; border-bottom: 1px solid #e3dfd3; }
.o2u-src-tabs .o2u-copy { margin-left: auto; }
.o2u-src-body { flex: 1; overflow: auto; padding: 10px 12px 14px; }
.o2u-src-body p { margin: 0 0 8px; }
.o2u-src-body h4 { margin: 12px 0 4px; font-size: 11px; color: #6b675e; text-transform: uppercase; letter-spacing: .04em; }
.o2u-src-body dl { margin: 0; }
.o2u-src-body dt { font-size: 11px; color: #6b675e; margin-top: 6px; }
.o2u-src-body dd { margin: 0; }
.o2u-src-body pre { margin: 0; white-space: pre-wrap; word-break: break-word;
  font: 12px/1.45 Menlo, Consolas, monospace; background: #f6f4ee; border-radius: 5px; padding: 8px; }
.o2u-ax { margin: 0 0 6px; padding: 6px 8px; background: #f6f4ee; border-radius: 5px;
  font: 12px/1.45 Menlo, Consolas, monospace; word-break: break-word; }
.o2u-ax b { font-family: Helvetica, Arial, sans-serif; font-size: 11px; color: #6b675e; font-weight: 600; margin-right: 6px; }
.o2u-ax.inf { border-left: 3px solid #d9822b; }
.o2u-refs { margin-top: 2px; }
.o2u-ref { display: inline-block; margin: 2px 4px 0 0; padding: 0 6px; border-radius: 9px;
  background: #e8eef7; color: #3a5a8c; font-size: 11px; cursor: pointer; }
.o2u-ref.prop { background: #eef3ea; color: #47663a; }
.o2u-note { font-size: 12px; color: #6b675e; }
.o2u-ax.find { border-left: 3px solid #c2412d; font-family: Helvetica, Arial, sans-serif; }
.o2u-ax.find .o2u-why { color: #6b675e; font-size: 11px; }
.o2u-case { display: inline-block; margin: 2px 4px 0 0; padding: 0 7px; border-radius: 9px; background: #e8eef7;
  color: #3a5a8c; font: 11px Menlo, Consolas, monospace; cursor: pointer; border: 0; }
.o2u-case.on { background: #2f5fd0; color: #fff; }
.o2u-ev { display: grid; grid-template-columns: 22px 1fr; gap: 6px; font-size: 12px; padding: 2px 0; }
.o2u-ev i { color: #6b675e; font-style: normal; text-align: right; }
.o2u-src-fo { overflow: visible; }
`;

  const titleOf = (g) => {
    const t = g.querySelector("title");
    return t ? t.textContent.trim() : "";
  };

  // Path data / point lists → tokens: command letters kept as strings,
  // coordinates paired into [x, y]. Graphviz only emits absolute commands.
  function tokens(s) {
    const raw = s.match(/[A-Za-z]|-?\d*\.?\d+(?:e[-+]?\d+)?/g) || [];
    const out = [];
    let x = null;
    for (const t of raw) {
      if (/^[A-Za-z]$/.test(t)) out.push(t);
      else if (x === null) x = +t;
      else { out.push([x, +t]); x = null; }
    }
    return out;
  }
  const fmt = (p) => p[0].toFixed(2) + "," + p[1].toFixed(2);
  const pairs = (toks) => toks.filter(Array.isArray);

  function attach(svg, opts) {
    opts = opts || {};
    const doc = svg.ownerDocument;
    const nodes = new Map();  // title → {id, g, base, off:[dx,dy], edges:[]}
    const edges = [];

    if (!svg.querySelector("style.oi-style")) {
      const st = doc.createElementNS("http://www.w3.org/2000/svg", "style");
      st.setAttribute("class", "oi-style");
      st.textContent = CSS;
      svg.insertBefore(st, svg.firstChild);
    }

    svg.querySelectorAll("g.node").forEach((g) => {
      const id = titleOf(g);
      if (id) nodes.set(id, { id, g, base: g.getAttribute("transform") || "", off: [0, 0], edges: [] });
    });

    svg.querySelectorAll("g.edge").forEach((g) => {
      const m = titleOf(g).match(/^(.+?)->(.+)$/);
      if (!m || !nodes.has(m[1]) || !nodes.has(m[2])) return;
      g.querySelectorAll("path.oi-hit").forEach((p) => p.remove());
      const paths = [...g.querySelectorAll("path")];
      if (!paths.length) return;
      // A wide transparent twin makes thin lines easy to hover and click.
      const hit = paths[0].cloneNode(false);
      hit.setAttribute("class", "oi-hit");
      hit.removeAttribute("stroke-dasharray");
      paths[0].parentNode.insertBefore(hit, paths[0]);
      paths.unshift(hit);

      const e = {
        g, s: m[1], t: m[2],
        paths: paths.map((el) => {
          const d = el.getAttribute("d");
          const toks = tokens(d);
          return { el, d, toks, n: pairs(toks).length };
        }),
        polys: [...g.querySelectorAll("polygon")].map((el) => ({
          el, points: el.getAttribute("points"), pts: pairs(tokens(el.getAttribute("points"))),
        })),
        texts: [...g.querySelectorAll("text")].map((el) => ({
          el, x: +el.getAttribute("x"), y: +el.getAttribute("y"),
        })),
      };
      const ps = pairs(e.paths[1].toks);
      e.end = ps[ps.length - 1];
      e.prev = ps[ps.length - 2] || ps[0];
      edges.push(e);
      nodes.get(e.s).edges.push(e);
      if (e.t !== e.s) nodes.get(e.t).edges.push(e);
    });

    // ---- geometry ---------------------------------------------------------
    function placeNode(n) {
      n.g.setAttribute("transform",
        (n.base ? n.base + " " : "") + `translate(${n.off[0]} ${n.off[1]})`);
    }

    // Each control point moves by a blend of the two endpoint offsets, so the
    // curve keeps its shape and both ends stay attached to their classes.
    function redraw(e) {
      const a = nodes.get(e.s).off, b = nodes.get(e.t).off;
      const at = (f) => [a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f];
      let prevNew = null;
      for (const p of e.paths) {
        let i = 0;
        const last = Math.max(p.n - 1, 1);
        const out = p.toks.map((t) => {
          if (!Array.isArray(t)) return t;
          const o = at(i++ / last);
          return [t[0] + o[0], t[1] + o[1]];
        });
        p.el.setAttribute("d", out.map((t) => (Array.isArray(t) ? fmt(t) : t)).join(" "));
        const op = pairs(out);
        prevNew = op[op.length - 2] || op[0];
      }
      // Arrowheads sit at the head end: rotate them to the new final tangent.
      const endNew = [e.end[0] + b[0], e.end[1] + b[1]];
      const rot =
        Math.atan2(endNew[1] - prevNew[1], endNew[0] - prevNew[0]) -
        Math.atan2(e.end[1] - e.prev[1], e.end[0] - e.prev[0]);
      const c = Math.cos(rot), s = Math.sin(rot);
      for (const p of e.polys) {
        p.el.setAttribute("points", p.pts.map(([x, y]) => {
          const dx = x - e.end[0], dy = y - e.end[1];
          return fmt([endNew[0] + dx * c - dy * s, endNew[1] + dx * s + dy * c]);
        }).join(" "));
      }
      const mid = at(0.5);
      for (const t of e.texts) {
        t.el.setAttribute("x", (t.x + mid[0]).toFixed(2));
        t.el.setAttribute("y", (t.y + mid[1]).toFixed(2));
      }
    }

    // Graphviz paints the canvas as the top-level graph's first polygon.
    const graphG = svg.querySelector("g.graph");
    const bg = graphG && graphG.querySelector(":scope > polygon");
    const bgPoints = bg && bg.getAttribute("points");
    const PAD = 12;  // canvas margin kept around classes moved past its edge

    // Centre and size of each class box, including its drag offset.
    const boxes = () => [...nodes.values()].map((n) => {
      const b = n.g.getBBox();
      return { n, x: b.x + b.width / 2 + n.off[0], y: b.y + b.height / 2 + n.off[1], w: b.width, h: b.height };
    });
    const extent = (bs) => [
      Math.min(...bs.map((b) => b.x - b.w / 2)), Math.min(...bs.map((b) => b.y - b.h / 2)),
      Math.max(...bs.map((b) => b.x + b.w / 2)), Math.max(...bs.map((b) => b.y + b.h / 2)),
    ];

    // Enlarge the background so it still covers every class (never shrinks
    // below Graphviz's original canvas).
    function fitCanvas(tight) {
      if (!bg) return;
      // tight: hug the classes (after a squeeze), else never shrink below
      // Graphviz's original canvas. The key is a node too, so it stays inside.
      const o = tight ? [] : pairs(tokens(bgPoints));
      const [x0, y0, x1, y1] = extent(boxes());
      const l = Math.min(x0 - PAD, ...o.map((p) => p[0])), r = Math.max(x1 + PAD, ...o.map((p) => p[0]));
      const t = Math.min(y0 - PAD, ...o.map((p) => p[1])), b = Math.max(y1 + PAD, ...o.map((p) => p[1]));
      bg.setAttribute("points", [[l, b], [l, t], [r, t], [r, b], [l, b]].map(fmt).join(" "));
    }

    // Stretch class positions along one axis so the drawing takes on the given
    // width/height ratio (e.g. the window's). A one-axis stretch keeps every
    // class on the same side of every other -- ranks, order, arrow directions
    // -- and only adds space, so nothing new overlaps. Builds on the current
    // positions, so dragged classes keep their relative placement.
    function spread(aspect) {
      const bs = boxes();
      if (bs.length < 2 || !(aspect > 0)) return false;
      const [x0, y0, x1, y1] = extent(bs);
      const W = x1 - x0, H = y1 - y0;
      const ax = W / H > aspect ? "y" : "x";
      const cs = bs.map((b) => b[ax]);
      const lo = Math.min(...cs), hi = Math.max(...cs), span = hi - lo;
      if (span < 1) return false;
      // Box sizes at the two ends don't stretch; only the gaps between centres do.
      const want = ax === "y" ? W / aspect : H * aspect;
      const k = (want - ((ax === "y" ? H : W) - span)) / span;
      if (k < 1.02) return false;
      const mid = (lo + hi) / 2, i = ax === "y" ? 1 : 0;
      for (const b of bs) {
        b.n.off[i] += (b[ax] - mid) * (k - 1);
        placeNode(b.n);
      }
      edges.forEach(redraw);
      fitCanvas();
      return true;
    }

    // Stretch (or squeeze) the gaps between classes by kx horizontally and ky
    // vertically, about the drawing's centre. Box sizes stay; only centres
    // move, so arrangement and ranks are kept. Used by the width/height
    // sliders, which pass the change since their last position.
    function stretch(kx, ky) {
      const bs = boxes();
      if (bs.length < 2) return false;
      const [x0, y0, x1, y1] = extent(bs);
      const mx = (x0 + x1) / 2, my = (y0 + y1) / 2;
      for (const b of bs) {
        b.n.off[0] += (b.x - mx) * (kx - 1);
        b.n.off[1] += (b.y - my) * (ky - 1);
        placeNode(b.n);
      }
      edges.forEach(redraw);
      fitCanvas(true);
      return true;
    }

    // Canvas rectangle in root <svg> coordinates (for a download's viewBox).
    function bounds() {
      if (!bg) return null;
      const r = bg.getBBox();
      const t = graphG.transform.baseVal.consolidate();
      const m = t ? t.matrix : svg.createSVGMatrix();
      const a = new DOMPoint(r.x, r.y).matrixTransform(m);
      const c = new DOMPoint(r.x + r.width, r.y + r.height).matrixTransform(m);
      return { x: Math.min(a.x, c.x), y: Math.min(a.y, c.y), width: Math.abs(c.x - a.x), height: Math.abs(c.y - a.y) };
    }

    function reset() {
      nodes.forEach((n) => {
        n.off = [0, 0];
        if (n.base) n.g.setAttribute("transform", n.base);
        else n.g.removeAttribute("transform");
      });
      edges.forEach((e) => {
        e.paths.forEach((p) => p.el.setAttribute("d", p.d));
        e.polys.forEach((p) => p.el.setAttribute("points", p.points));
        e.texts.forEach((t) => { t.el.setAttribute("x", t.x); t.el.setAttribute("y", t.y); });
      });
      if (bg) bg.setAttribute("points", bgPoints);
    }

    // ---- focus ------------------------------------------------------------
    let marked = [];
    let pinned = new Set();
    let hops = 1;
    let lastPin = { id: null, at: 0 };

    function mark(el, cls) { el.classList.add(cls); marked.push(el); }
    function unmarkAll() {
      marked.forEach((el) => el.classList.remove("oi-hl", "oi-sel"));
      marked = [];
      svg.classList.remove("oi-focus");
    }

    function showNodes(ids, depth) {
      unmarkAll();
      if (!ids.size) return;
      const seen = new Set(ids);
      let frontier = [...ids];
      for (let h = 0; h < depth && frontier.length; h++) {
        const next = [];
        for (const id of frontier) {
          for (const e of nodes.get(id).edges) {
            mark(e.g, "oi-hl");
            const o = e.s === id ? e.t : e.s;
            if (!seen.has(o)) { seen.add(o); next.push(o); }
          }
        }
        frontier = next;
      }
      seen.forEach((id) => mark(nodes.get(id).g, "oi-hl"));
      ids.forEach((id) => mark(nodes.get(id).g, "oi-sel"));
      svg.classList.add("oi-focus");
    }

    function showEdge(e) {
      unmarkAll();
      mark(e.g, "oi-hl");
      mark(nodes.get(e.s).g, "oi-hl");
      mark(nodes.get(e.t).g, "oi-hl");
      svg.classList.add("oi-focus");
    }

    const restore = () => showNodes(pinned, hops);

    // ---- flow view: one case's path, designed vs practiced -----------------
    let caseOn = "";
    function showCase(id) {
      caseOn = id || "";
      // a case's path replaces any pinned focus, which would fade parts of it
      if (caseOn && pinned.size) { pinned = new Set(); hops = 1; restore(); }
      svg.classList.toggle("o2u-case-on", !!caseOn);
      svg.querySelectorAll(".o2u-on").forEach((g) => g.classList.remove("o2u-on"));
      if (!caseOn || !source || !source.cases || !source.cases[caseOn]) return;
      svg.querySelectorAll(".o2u-c-" + source.cases[caseOn].key).forEach((g) => g.classList.add("o2u-on"));
    }

    // ---- source panel (the OWL behind a class or line) --------------------
    const source = readSource(svg);
    const nodeOf = new Map();  // class IRI -> node title
    if (source) Object.entries(source.nodes).forEach(([n, iri]) => nodeOf.set(iri, n));
    let panel = null;
    if (source) {
      const host = opts.sourceHost || (opts.standalone ? overlayHost(svg) : null);
      if (host) {
        panel = sourcePanel(host, source, {
          goClass(iri) {
            const n = nodeOf.get(iri);
            if (!n) return false;
            pinned = new Set([n]); hops = 1; restore();
            navigate(nodes.get(n).g);
            panel.showClass(iri);
            return true;
          },
          showCase,
        });
      }
    }

    function pin(id, additive) {
      const now = Date.now();
      if (additive) {
        pinned.has(id) ? pinned.delete(id) : pinned.add(id);
      } else if (pinned.size === 1 && pinned.has(id)) {
        if (lastPin.id === id && now - lastPin.at < REPEAT_MS) hops++;
        else { pinned = new Set(); hops = 1; }
      } else {
        pinned = new Set([id]);
        hops = 1;
      }
      lastPin = { id, at: now };
      restore();
      if (panel && pinned.has(id)) panel.showClass(source.nodes[id]);
      if (opts.onFocus) opts.onFocus([...pinned], hops);
    }

    function clear() { pinned = new Set(); hops = 1; restore(); if (panel) panel.hide(); if (caseOn) showCase(""); }

    function navigate(g) {
      if (opts.onNavigate) return opts.onNavigate(g);
      // Standalone: shift the viewBox so the class is centred.
      const r = g.getBoundingClientRect(), c = svg.getBoundingClientRect();
      const k = svg.getScreenCTM().a;
      const vb = svg.viewBox.baseVal;
      vb.x -= ((c.left + c.width / 2) - (r.left + r.width / 2)) / k;
      vb.y -= ((c.top + c.height / 2) - (r.top + r.height / 2)) / k;
      svg.dispatchEvent(new Event("o2u-view"));
    }

    // ---- events -----------------------------------------------------------
    let drag = null;   // pointer pressed on a class
    let press = null;  // pointer pressed anywhere (to tell clicks from pans)

    const nodeAt = (t) => { const g = t.closest && t.closest("g.node"); return g && nodes.get(titleOf(g)); };
    const edgeAt = (t) => { const g = t.closest && t.closest("g.edge"); return g && edges.find((e) => e.g === g); };
    const local = (ev, el) =>
      new DOMPoint(ev.clientX, ev.clientY).matrixTransform(el.getScreenCTM().inverse());

    // Capture phase on the <svg>: stops the pan library (listening on the same
    // element, bubble phase) from starting a pan when a class is pressed.
    function swallow(ev) { if (nodeAt(ev.target)) ev.stopPropagation(); }
    const swallowed = ["mousedown", "touchstart", "dblclick"];
    swallowed.forEach((t) => svg.addEventListener(t, swallow, true));

    function onDown(ev) {
      press = { x: ev.clientX, y: ev.clientY };
      const n = nodeAt(ev.target);
      if (!n || ev.button > 0) return;
      ev.stopPropagation();
      // Edit mode may take the press (e.g. to draw a new line from this class).
      if (opts.edit && opts.edit.nodeDown && opts.edit.nodeDown(ev, n.id)) return;
      const p = local(ev, n.g.parentNode);
      drag = { n, x: p.x, y: p.y, off: n.off.slice(), moved: false, shift: ev.shiftKey };
      doc.addEventListener("pointermove", onMove);
      doc.addEventListener("pointerup", onUp);
    }

    function onMove(ev) {
      if (!drag) return;
      if (!drag.moved) {
        if (Math.hypot(ev.clientX - press.x, ev.clientY - press.y) < DRAG_PX) return;
        drag.moved = true;
        drag.n.g.classList.add("oi-drag");
      }
      const p = local(ev, drag.n.g.parentNode);
      drag.n.off = [drag.off[0] + p.x - drag.x, drag.off[1] + p.y - drag.y];
      placeNode(drag.n);
      drag.n.edges.forEach(redraw);
      if (opts.edit && opts.edit.moved) opts.edit.moved(drag.n.id);
      fitCanvas();
    }

    function onUp() {
      doc.removeEventListener("pointermove", onMove);
      doc.removeEventListener("pointerup", onUp);
      if (!drag) return;
      drag.n.g.classList.remove("oi-drag");
      if (!drag.moved) pin(drag.n.id, drag.shift);
      drag = null;
    }

    function onClick(ev) {
      const moved = press && Math.hypot(ev.clientX - press.x, ev.clientY - press.y) >= DRAG_PX;
      if (moved || nodeAt(ev.target)) return;
      const e = edgeAt(ev.target);
      if (!e) { if (pinned.size) clear(); return; }
      // In edit mode a click selects the line instead of following it.
      if (opts.edit && opts.edit.edgeClick && opts.edit.edgeClick(e.g.id, ev)) {
        showEdge(e);
        if (panel && e.g.id) panel.showEdge(e.g.id);
        return;
      }
      // Jump to whichever end is farther from where the line was clicked.
      const dist = (id) => {
        const r = nodes.get(id).g.getBoundingClientRect();
        return Math.hypot(r.left + r.width / 2 - ev.clientX, r.top + r.height / 2 - ev.clientY);
      };
      const far = dist(e.s) > dist(e.t) ? e.s : e.t;
      navigate(nodes.get(far).g);
      if (!pinned.size) showEdge(e);
      if (panel && e.g.id) panel.showEdge(e.g.id);
    }

    function onOver(ev) {
      if (drag || pinned.size) return;
      const n = nodeAt(ev.target);
      if (n) return showNodes(new Set([n.id]), 1);
      const e = edgeAt(ev.target);
      if (e) showEdge(e);
    }

    function onOut(ev) {
      if (drag || pinned.size) return;
      const from = ev.target.closest && ev.target.closest("g.node, g.edge");
      if (from && !(ev.relatedTarget && from.contains(ev.relatedTarget))) unmarkAll();
    }

    function onKey(ev) {
      if (ev.key === "Escape") clear();
      const typing = ev.target && /^(INPUT|TEXTAREA|SELECT)$/.test(ev.target.tagName);
      if (ev.key === "s" && panel && !typing && !ev.ctrlKey && !ev.metaKey) panel.toggle();
      // l: save the layout (a .layout.json sidecar) -- for downloaded SVGs;
      // the web app has its own button.
      if (ev.key === "l" && !typing && !ev.ctrlKey && !ev.metaKey && !opts.app) saveLayout();
      if (ev.key === "p" && source && source.view === "flow" && !typing && !ev.ctrlKey && !ev.metaKey)
        svg.classList.toggle("o2u-designed");
    }

    svg.addEventListener("pointerdown", onDown, true);
    svg.addEventListener("click", onClick);
    svg.addEventListener("mouseover", onOver);
    svg.addEventListener("mouseout", onOut);
    doc.addEventListener("keydown", onKey);

    if (opts.standalone) standalone(svg);

    // Where every class is now, keyed by IRI, in Graphviz points (y up) -- the
    // .layout.json sidecar format (owl2uml/pinning.py). Moved classes are pinned.
    function layout() {
      if (!source || !source.nodes) return {};
      const out = {};
      for (const b of boxes()) {
        const iri = source.nodes[b.n.id];
        if (!iri || iri.startsWith("_:")) continue;
        out[iri] = { x: +b.x.toFixed(2), y: +(-b.y).toFixed(2),
                     pinned: Math.abs(b.n.off[0]) + Math.abs(b.n.off[1]) > 0.5 };
      }
      return out;
    }

    // Save the layout as a file (works in a downloaded SVG opened on its own).
    function saveLayout(name) {
      const blob = new Blob([JSON.stringify(layout(), null, 1)], { type: "application/json" });
      const a = doc.createElementNS("http://www.w3.org/1999/xhtml", "a");
      a.href = URL.createObjectURL(blob);
      a.download = name || "diagram.layout.json";
      (doc.body || doc.documentElement).appendChild(a);
      a.click();
      a.remove();
      setTimeout(() => URL.revokeObjectURL(a.href), 1000);
    }

    return {
      layout,
      saveLayout,
      pin: (id) => { pinned = new Set([id]); hops = 1; restore(); if (panel) panel.showClass(source.nodes[id]); },
      panel: () => panel,
      source: () => source,
      showCase: (id) => { showCase(id); if (panel && id) panel.showCase(id); },
      idOf: (g) => titleOf(g),
      // ---- for edit mode (static/edit.js) ----
      // The <g> that holds the classes: draft drawings go in its coordinates.
      layer: () => { const n = nodes.values().next().value; return n ? n.g.parentNode : svg; },
      nodeIds: () => [...nodes.keys()],
      nodeEl: (id) => nodes.has(id) ? nodes.get(id).g : null,
      nodeAtPoint: (x, y) => {
        const n = nodeAt(doc.elementFromPoint(x, y) || svg);
        return n ? n.id : null;
      },
      // A class's box in layer coordinates, including any drag offset.
      nodeBox: (id) => {
        const n = nodes.get(id);
        if (!n) return null;
        const b = n.g.getBBox();
        return { x: b.x + n.off[0], y: b.y + n.off[1], width: b.width, height: b.height };
      },
      // First and last point of a drawn line, in layer coordinates.
      edgeEnds: (eid) => {
        const e = edges.find((x) => x.g.id === eid);
        if (!e) return null;
        const p = e.paths[1].el, len = p.getTotalLength();
        const a = p.getPointAtLength(0), b = p.getPointAtLength(len);
        return { s: e.s, t: e.t, from: { x: a.x, y: a.y }, to: { x: b.x, y: b.y } };
      },
      edgeIds: () => edges.map((e) => e.g.id).filter(Boolean),
      clear,
      reset,
      spread,
      stretch,
      bounds,
      destroy() {
        swallowed.forEach((t) => svg.removeEventListener(t, swallow, true));
        svg.removeEventListener("pointerdown", onDown, true);
        svg.removeEventListener("click", onClick);
        svg.removeEventListener("mouseover", onOver);
        svg.removeEventListener("mouseout", onOut);
        doc.removeEventListener("keydown", onKey);
        if (panel) panel.destroy();
        onUp();
      },
    };
  }

  // Wheel-zoom and drag-to-pan for an SVG opened on its own in a browser,
  // done by editing the viewBox (no svg-pan-zoom available there).
  function standalone(svg) {
    // "i" shows/hides what a reasoner inferred (edges of class rel-inferred).
    svg.ownerDocument.addEventListener("keydown", (ev) => {
      if (ev.key === "i") svg.classList.toggle("hide-inferred");
    });
    svg.setAttribute("width", "100%");
    svg.setAttribute("height", "100%");
    svg.style.width = "100vw";
    svg.style.height = "100vh";
    const vb = svg.viewBox.baseVal;
    const toUser = (ev) =>
      new DOMPoint(ev.clientX, ev.clientY).matrixTransform(svg.getScreenCTM().inverse());

    svg.addEventListener("wheel", (ev) => {
      ev.preventDefault();
      const k = ev.deltaY > 0 ? 1.15 : 1 / 1.15;
      const p = toUser(ev);
      vb.x = p.x - (p.x - vb.x) * k;
      vb.y = p.y - (p.y - vb.y) * k;
      vb.width *= k;
      vb.height *= k;
      svg.dispatchEvent(new Event("o2u-view"));
    }, { passive: false });

    let pan = null;
    svg.addEventListener("mousedown", (ev) => {
      pan = { x: ev.clientX, y: ev.clientY, vx: vb.x, vy: vb.y, k: svg.getScreenCTM().a };
    });
    svg.ownerDocument.addEventListener("mousemove", (ev) => {
      if (!pan) return;
      vb.x = pan.vx - (ev.clientX - pan.x) / pan.k;
      vb.y = pan.vy - (ev.clientY - pan.y) / pan.k;
      svg.dispatchEvent(new Event("o2u-view"));
    });
    svg.ownerDocument.addEventListener("mouseup", () => { pan = null; });
  }

  // ---- source panel -------------------------------------------------------
  // The SVG may carry the OWL its classes and lines were drawn from, as JSON
  // in <script type="application/json" id="o2u-source"> (owl2uml/source.py):
  //   classes/props: iri → {iri, curie, label, name, frame, ann:[[name, value]],
  //                         ax:[{k, m, refs}], ttl}
  //   nodes: "n3" → class IRI;  edges: "e12" → {src, dst, kind, label,
  //                         axioms:[[iri, i]] | props:[iri] | premises:{classes, props}}
  function readSource(svg) {
    const el = svg.querySelector("script#o2u-source, script[id='o2u-source']");
    if (!el) return null;
    try { return JSON.parse(el.textContent); } catch (_) { return null; }
  }

  const an = (w) => (/^[aeiou]/i.test(w) ? "an " : "a ") + w;
  const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

  // Manchester-syntax frame (mirrors owl2uml.source.manchester).
  function frame(ent, only) {
    const lines = [`${ent.frame}: ${ent.name}`];
    if (!only) {
      const parts = [`rdfs:label ${JSON.stringify(ent.label)}`]
        .concat(ent.ann.map(([n, v]) => `${n} ${JSON.stringify(v)}`));
      lines.push("    Annotations:");
      parts.forEach((a, i) => lines.push(`        ${a}${i < parts.length - 1 ? "," : ""}`));
    }
    const axs = only ? only.map((i) => ent.ax[i]) : ent.ax;
    const kinds = [...new Set(axs.map((a) => a.k))];
    for (const k of kinds) {
      const same = axs.filter((a) => a.k === k);
      lines.push(`    ${k}:`);
      same.forEach((a, i) => lines.push(`        ${a.m}${i < same.length - 1 ? "," : ""}`));
    }
    return lines.join("\n");
  }

  // A <foreignObject> pinned to the window's right edge, for an SVG opened on
  // its own (no HTML page around it). Re-placed after every zoom or pan.
  function overlayHost(svg) {
    const doc = svg.ownerDocument;
    const fo = doc.createElementNS("http://www.w3.org/2000/svg", "foreignObject");
    fo.setAttribute("class", "o2u-src-fo");
    const div = doc.createElementNS("http://www.w3.org/1999/xhtml", "div");
    div.style.height = "100%";
    fo.appendChild(div);
    svg.appendChild(fo);
    const W = 420, M = 12;
    function place() {
      const ctm = svg.getScreenCTM();
      if (!ctm) return;
      const r = svg.getBoundingClientRect();
      const vw = Math.min(r.width, doc.documentElement.clientWidth || r.width);
      const vh = Math.min(r.height, (doc.defaultView && doc.defaultView.innerHeight) || r.height);
      const w = Math.min(W, vw - 2 * M);
      const p = new DOMPoint(r.left + vw - w - M, r.top + M).matrixTransform(ctm.inverse());
      fo.setAttribute("x", 0);
      fo.setAttribute("y", 0);
      fo.setAttribute("width", w);
      fo.setAttribute("height", Math.max(200, vh - 2 * M));
      fo.setAttribute("transform", `translate(${p.x} ${p.y}) scale(${1 / ctm.a})`);
    }
    svg.addEventListener("o2u-view", place);
    (doc.defaultView || window).addEventListener("resize", place);
    return { el: div, fo, place };
  }

  function sourcePanel(host, src, hooks) {
    // XHTML namespace: in a standalone SVG the document is XML, where a plain
    // createElement("div") would not be laid out as HTML.
    const box = (host.el || host).ownerDocument.createElementNS("http://www.w3.org/1999/xhtml", "div");
    const root = host.el || host;
    box.className = "o2u-src";
    box.hidden = true;
    root.appendChild(box);
    if (host.fo) host.fo.style.display = "none";
    // Keep presses, clicks and wheel inside the panel from reaching the diagram.
    ["pointerdown", "mousedown", "click", "dblclick", "wheel", "touchstart"].forEach((t) =>
      box.addEventListener(t, (ev) => ev.stopPropagation()));

    let tab = "summary";
    let view = null;       // {title, kind, iri, curie, summary(html), man, ttl}
    let wanted = true;     // false after "s" hides it: clicks then don't reopen it

    const cls = (iri) => src.classes[iri];
    const prp = (iri) => src.props[iri];
    const lbl = (iri) => (cls(iri) || prp(iri) || { label: iri }).label;

    function refs(list) {
      const chips = list.filter((r) => cls(r) || prp(r)).map((r) =>
        `<span class="o2u-ref${prp(r) ? " prop" : ""}" data-ref="${esc(r)}" title="${esc(r)}">${esc(lbl(r))}</span>`);
      return chips.length ? `<div class="o2u-refs">${chips.join("")}</div>` : "";
    }
    const axHtml = (a, extra) =>
      `<div class="o2u-ax${extra || ""}"><b>${esc(a.k)}</b>${esc(a.m)}${refs(a.refs)}</div>`;
    function annHtml(ent) {
      if (!ent.ann.length) return "";
      return "<dl>" + ent.ann.map(([n, v]) => `<dt>${esc(n)}</dt><dd>${esc(v)}</dd>`).join("") + "</dl>";
    }

    const findings = src.findings || [];
    const caseChips = (ids) => ids.length
      ? `<div class="o2u-refs">${ids.map((c) => `<button class="o2u-case" data-case="${esc(c)}">${esc(c)}</button>`).join("")}</div>` : "";
    const findHtml = (j) => {
      const f = findings[j];
      return `<div class="o2u-ax find"><b>${esc(f.rule)}</b>${esc(f.message)}` +
        `<div class="o2u-why">${esc(f.severity)} · focus node ${esc(f.focus)}</div>${f.case ? caseChips([f.case]) : ""}</div>`;
    };

    function caseView(id) {
      const c = src.cases && src.cases[id];
      if (!c) return null;
      const summary = `<p>${c.events.length} logged events, in order. Its path is highlighted on the diagram.</p>` +
        c.events.map(([st, lab], i) => `<div class="o2u-ev"><i>${i + 1}</i><span>${esc(lbl(st))}` +
          `<span class="o2u-note"> · ${esc(lab)}</span></span></div>`).join("") +
        `<h4>Findings</h4>` + (c.findings.length ? c.findings.map(findHtml).join("") : '<p class="o2u-note">None.</p>');
      return { title: id, kind: "case", summary, man: c.events.map(([st, lab], i) => `${i + 1}. ${lbl(st)}  # ${lab}`).join("\n"),
        ttl: "# events of " + id + "\n" + c.events.map(([st, lab]) => `#   ${lab} a ${cls(st) ? cls(st).name : st}`).join("\n") };
    }

    function flowEdgeView(e) {
      const s = esc(lbl(e.src)), d = esc(lbl(e.dst));
      let summary;
      if (e.kind === "sequence") {
        summary = `<p>In the designed process <i>${d}</i> comes directly after <i>${s}</i>. Drawn from:</p><pre>${esc(e.text)}</pre>` +
          (src.summary && src.summary.cases ? `<h4>Taken by ${e.cases.length} case${e.cases.length === 1 ? "" : "s"}</h4>${caseChips(e.cases)}` : "");
      } else if (e.kind === "requirement") {
        const hit = findings.map((f, j) => [f, j]).filter(([f]) => f.step === e.dst).map(([, j]) => j);
        summary = `<p>A rule: <i>${s}</i> must come before <i>${d}</i>${e.label ? ` <b>${esc(e.label)}</b>` : ""}. Drawn from:</p>` +
          `<pre>${esc(e.text)}</pre><p class="o2u-note">OWL reads this open-world: a missing predecessor is assumed to exist somewhere. ` +
          "SHACL shapes check the logged cases closed-world.</p>" +
          (hit.length ? "<h4>Findings at the step it constrains</h4>" + hit.map(findHtml).join("") : "");
      } else {
        const hit = findings.map((f, j) => [f, j]).filter(([f]) => e.cases.includes(f.case)).map(([, j]) => j);
        summary = `<p>Observed, not designed: no axiom puts <i>${d}</i> directly after <i>${s}</i>, but the log does.</p>` +
          `<pre>${esc(e.text)}</pre><h4>Cases</h4>${caseChips(e.cases)}<h4>Does it break a rule?</h4>` +
          (hit.length ? hit.map(findHtml).join("") : `<p class="o2u-note">${src.summary && src.summary.shapes
            ? "No shape reports a breach in these cases: a variation from the design, not a violation."
            : "No rules (SHACL shapes) were loaded, so this is not checked."}</p>`);
      }
      const kind = { sequence: "designed sequence", requirement: "rule: must come first", deviation: "observed, not designed" }[e.kind];
      return { title: `${lbl(e.src)} → ${lbl(e.dst)}`, kind, summary, man: e.text,
        ttl: [e.src, e.dst].map((i) => (cls(i) || { ttl: "" }).ttl).join("\n\n") };
    }

    function classView(iri) {
      const c = cls(iri);
      if (!c) return null;
      const fl = c.findings && c.findings.length
        ? "<h4>Findings at this step</h4>" + c.findings.map(findHtml).join("") : "";
      const summary = (c.lane ? `<p class="o2u-note">Lane: ${esc(c.lane)}</p>` : "") + fl + annHtml(c) +
        (c.ax.length ? "<h4>Axioms</h4>" + c.ax.map((a) => axHtml(a)).join("")
                     : '<p class="o2u-note">No logical axioms: the class is only declared here.</p>');
      return { title: c.label, kind: "class", iri: c.iri, curie: c.curie, summary, man: frame(c), ttl: c.ttl };
    }

    function propView(iri) {
      const p = prp(iri);
      if (!p) return null;
      const summary = annHtml(p) + (p.ax.length ? "<h4>Axioms</h4>" + p.ax.map((a) => axHtml(a)).join("") : "");
      return { title: p.label, kind: "property", iri: p.iri, curie: p.curie, summary, man: frame(p), ttl: p.ttl };
    }

    const WHAT = {
      generalization: (s, d) => `Every <i>${s}</i> is ${an(d).slice(0, -d.length)}<i>${d}</i>. The line is drawn from this axiom:`,
      definition: (s, d) => `<i>${s}</i> is defined as, among other things, a kind of <i>${d}</i>. ` +
        "The definition gives necessary and sufficient conditions, so anything that meets it is classified here:",
      restriction: (s, d, l) => `A rule on every <i>${s}</i>: <b>${l}</b> <i>${d}</i>. Stated by:`,
      equivalent: (s, d) => `<i>${s}</i> and <i>${d}</i> are the same class. Stated by:`,
      association: (s, d, l) => `The relation <b>${l}</b> links <i>${s}</i> (its domain) to <i>${d}</i> (its range). Declared in:`,
    };

    function edgeView(eid) {
      const e = src.edges[eid];
      if (!e) return null;
      if (["sequence", "requirement", "deviation"].includes(e.kind)) return flowEdgeView(e);
      const s = esc(lbl(e.src)), d = esc(lbl(e.dst)), l = esc((e.label || "").replace(/\n/g, "; "));
      const title = `${lbl(e.src)} → ${lbl(e.dst)}`;
      let summary, man, ttl;
      const classAx = (pairs, extra) => pairs.map(([iri, i]) => axHtml(cls(iri).ax[i], extra)).join("");
      const classFrames = (pairs) => {
        const by = new Map();
        pairs.forEach(([iri, i]) => { if (!by.has(iri)) by.set(iri, []); by.get(iri).push(i); });
        return [...by].map(([iri, is]) => frame(cls(iri), is)).join("\n\n");
      };
      const ttlOf = (iris) => [...new Set(iris)].map((i) => (cls(i) || prp(i)).ttl).join("\n\n");
      if (e.kind === "inferred") {
        const pr = e.premises || { classes: [], props: [] };
        summary = `<p>Inferred by the reasoner: every <i>${s}</i> is ${an(d).slice(0, -d.length)}<i>${d}</i>. ` +
          "No axiom in the file says so directly.</p>" +
          "<h4>It follows from</h4>" + classAx(pr.classes, " inf") +
          pr.props.map((p) => prp(p).ax.filter((a) => /SubProperty|Chain|Inverse/.test(a.k))
            .map((a) => axHtml({ k: `${prp(p).label}: ${a.k}`, m: a.m, refs: a.refs }, " inf")).join("")).join("") +
          '<p class="o2u-note">These are the axioms such an inference usually rests on: the ' +
          "subclass's own axioms, the superclass's definition, and the property hierarchy " +
          "between them. A reasoner's explanation service would give the exact minimal set.</p>";
        man = "# inferred, not asserted: " + `${lbl(e.src)} SubClassOf ${lbl(e.dst)}\n\n` +
          [classFrames(pr.classes)].concat(pr.props.map((p) => frame(prp(p)))).join("\n\n");
        ttl = "# no triple states this; the axioms it rests on:\n\n" +
          ttlOf(pr.classes.map((c) => c[0]).concat(pr.props));
      } else if (e.kind === "association") {
        const ps = e.props || [];
        summary = `<p>${WHAT.association(s, d, l)}</p>` +
          ps.map((p) => `<h4>${esc(prp(p).label)}</h4>` + prp(p).ax.map((a) => axHtml(a)).join("") + refs([p])).join("");
        man = ps.map((p) => frame(prp(p))).join("\n\n");
        ttl = ttlOf(ps);
      } else {
        const ax = e.axioms || [];
        summary = `<p>${(WHAT[e.kind] || WHAT.generalization)(s, d, l)}</p>` + classAx(ax) +
          `<p class="o2u-note">${refs([e.src, e.dst])}</p>`;
        man = classFrames(ax);
        ttl = ttlOf(ax.map((a) => a[0]));
      }
      const kind = { generalization: "subclass of", definition: "defined as a kind of",
        restriction: "restriction", equivalent: "equivalent class", association: "relation",
        inferred: "inferred subclass of" }[e.kind] || e.kind;
      return { title, kind, summary, man, ttl };
    }

    function render() {
      if (!view) return;
      const id = view.iri
        ? `<div class="o2u-src-id"><a href="${esc(view.iri)}" target="_blank" rel="noopener">${esc(view.curie)}</a>` +
          (view.curie !== view.iri ? ` · ${esc(view.iri)}` : "") + "</div>"
        : "";
      const body = tab === "summary" ? view.summary
        : `<pre>${esc(tab === "man" ? view.man : view.ttl)}</pre>`;
      box.innerHTML =
        `<div class="o2u-src-head"><div class="o2u-src-title"><div class="o2u-src-kind">${esc(view.kind)}</div>` +
        `${esc(view.title)}</div><button class="o2u-src-x" title="Hide (s)">×</button></div>` + id +
        '<div class="o2u-src-tabs">' +
        [["summary", "Summary"], ["man", "Manchester"], ["ttl", "Turtle"]].map(([k, t]) =>
          `<button data-tab="${k}"${k === tab ? ' class="on"' : ""}>${t}</button>`).join("") +
        '<button class="o2u-copy" title="Copy the Manchester or Turtle text">Copy</button></div>' +
        `<div class="o2u-src-body">${body}</div>`;
    }

    box.addEventListener("click", (ev) => {
      const t = ev.target;
      if (t.closest(".o2u-src-x")) { hide(); return; }
      const tb = t.closest("[data-tab]");
      if (tb) { tab = tb.getAttribute("data-tab"); render(); return; }
      if (t.closest(".o2u-copy")) {
        const text = tab === "ttl" ? view.ttl : view.man;
        const b = t.closest(".o2u-copy");
        const done = () => { b.textContent = "Copied"; setTimeout(() => { b.textContent = "Copy"; }, 1200); };
        try { navigator.clipboard.writeText(text).then(done, () => {}); } catch (_) { /* no clipboard */ }
        return;
      }
      const cs = t.closest("[data-case]");
      if (cs) {
        const id = cs.getAttribute("data-case");
        if (hooks.showCase) hooks.showCase(id);
        show(caseView(id));
        return;
      }
      const r = t.closest("[data-ref]");
      if (r) {
        const iri = r.getAttribute("data-ref");
        if (cls(iri) && hooks.goClass(iri)) return;   // pins the class, which shows it
        show(cls(iri) ? classView(iri) : propView(iri));
      }
    });

    function show(v) {
      if (!v) return;
      view = v;
      render();
      if (!wanted) return;
      box.hidden = false;
      if (host.fo) { host.fo.style.display = ""; host.place(); }
    }
    function hide() {
      box.hidden = true;
      if (host.fo) host.fo.style.display = "none";
    }

    return {
      showClass: (iri) => show(classView(iri)),
      showEdge: (eid) => show(edgeView(eid)),
      showCase: (id) => show(caseView(id)),
      hide,
      toggle() {
        if (box.hidden) { wanted = true; if (view) show(view); }
        else { wanted = false; hide(); }
      },
      get visible() { return !box.hidden; },
      destroy() { box.remove(); if (host.fo) host.fo.remove(); },
    };
  }

  global.OwlUmlInteract = { attach };
})(typeof window !== "undefined" ? window : this);
