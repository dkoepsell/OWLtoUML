/* OWL → UML diagram interaction for Graphviz SVG output.
 *
 *   hover a class   → highlight it, its relations and its neighbours
 *   click a class   → pin that focus (shift-click adds/removes classes)
 *   click it again  → quickly: widen the focus by one more hop; later: unpin
 *   click a line    → jump to the class at its far end
 *   drag a class    → move it; connected lines follow
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
    function fitCanvas() {
      if (!bg) return;
      const o = pairs(tokens(bgPoints));
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
      if (opts.onFocus) opts.onFocus([...pinned], hops);
    }

    function clear() { pinned = new Set(); hops = 1; restore(); }

    function navigate(g) {
      if (opts.onNavigate) return opts.onNavigate(g);
      // Standalone: shift the viewBox so the class is centred.
      const r = g.getBoundingClientRect(), c = svg.getBoundingClientRect();
      const k = svg.getScreenCTM().a;
      const vb = svg.viewBox.baseVal;
      vb.x -= ((c.left + c.width / 2) - (r.left + r.width / 2)) / k;
      vb.y -= ((c.top + c.height / 2) - (r.top + r.height / 2)) / k;
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
      // Jump to whichever end is farther from where the line was clicked.
      const dist = (id) => {
        const r = nodes.get(id).g.getBoundingClientRect();
        return Math.hypot(r.left + r.width / 2 - ev.clientX, r.top + r.height / 2 - ev.clientY);
      };
      const far = dist(e.s) > dist(e.t) ? e.s : e.t;
      navigate(nodes.get(far).g);
      if (!pinned.size) showEdge(e);
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
    }

    svg.addEventListener("pointerdown", onDown, true);
    svg.addEventListener("click", onClick);
    svg.addEventListener("mouseover", onOver);
    svg.addEventListener("mouseout", onOut);
    doc.addEventListener("keydown", onKey);

    if (opts.standalone) standalone(svg);

    return {
      pin: (id) => { pinned = new Set([id]); hops = 1; restore(); },
      idOf: (g) => titleOf(g),
      clear,
      reset,
      spread,
      bounds,
      destroy() {
        swallowed.forEach((t) => svg.removeEventListener(t, swallow, true));
        svg.removeEventListener("pointerdown", onDown, true);
        svg.removeEventListener("click", onClick);
        svg.removeEventListener("mouseover", onOver);
        svg.removeEventListener("mouseout", onOut);
        doc.removeEventListener("keydown", onKey);
        onUp();
      },
    };
  }

  // Wheel-zoom and drag-to-pan for an SVG opened on its own in a browser,
  // done by editing the viewBox (no svg-pan-zoom available there).
  function standalone(svg) {
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
    }, { passive: false });

    let pan = null;
    svg.addEventListener("mousedown", (ev) => {
      pan = { x: ev.clientX, y: ev.clientY, vx: vb.x, vy: vb.y, k: svg.getScreenCTM().a };
    });
    svg.ownerDocument.addEventListener("mousemove", (ev) => {
      if (!pan) return;
      vb.x = pan.vx - (ev.clientX - pan.x) / pan.k;
      vb.y = pan.vy - (ev.clientY - pan.y) / pan.k;
    });
    svg.ownerDocument.addEventListener("mouseup", () => { pan = null; });
  }

  global.OwlUmlInteract = { attach };
})(typeof window !== "undefined" ? window : this);
