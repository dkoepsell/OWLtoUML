"use strict";

const $ = (id) => document.getElementById(id);

let panZoom = null;
let svgEl = null;
let interact = null;
let matches = [];
let matchIdx = -1;

// The exact, standalone SVG returned by the server for the current render.
// Kept verbatim so downloads are fully portable (intrinsic size, viewBox,
// no svg-pan-zoom runtime transforms or overlays).
let lastSvgText = null;
let lastName = "diagram";

// ---- status helpers --------------------------------------------------------
function setStatus(msg, isError = false) {
  const s = $("status");
  $("statusText").textContent = msg;
  s.classList.toggle("error", isError);
}
function showOverlay(msg) {
  $("overlayMsg").textContent = msg || "Working…";
  $("overlay").hidden = false;
}
function hideOverlay() { $("overlay").hidden = true; }

// ---- upload / render -------------------------------------------------------
async function renderFile(file) {
  if (!file) return;
  showOverlay("Parsing & laying out…");
  setStatus(`Uploading ${file.name} (${(file.size / 1024).toFixed(0)} KB)…`);

  const fd = new FormData();
  fd.append("file", file);
  fd.append("format", $("format").value);
  if ($("keepUnused").checked) fd.append("keep_unused", "1");

  let res, data;
  try {
    res = await fetch("/api/render", { method: "POST", body: fd });
    data = await res.json();
  } catch (e) {
    hideOverlay();
    setStatus(`Network error: ${e.message}`, true);
    return;
  }
  hideOverlay();

  if (!res.ok || data.error) {
    setStatus(data.error || `Server error (${res.status})`, true);
    return;
  }
  lastSvgText = data.svg;
  lastName = file.name.replace(/\.[^.]+$/, "") || "diagram";
  mountSvg(data.svg);
  const pruned = data.pruned ? ` · ${data.pruned} unused imported classes left out` : "";
  const groups = data.groups && data.groups.length > 1 ? ` · ${data.groups.length} groups` : "";
  setStatus(
    `${file.name} — ${data.classes} classes, ${data.edges} relations${groups}${pruned} · engine: ${data.engine}`
  );
}

function mountSvg(svgText) {
  const vp = $("viewport");
  vp.innerHTML = svgText;
  vp.hidden = false;
  $("dropzone").hidden = true;
  $("toolbar").hidden = false;
  $("hint").hidden = false;

  svgEl = vp.querySelector("svg");
  if (!svgEl) { setStatus("Server returned no SVG", true); return; }
  // Let it fill the viewport; svg-pan-zoom needs explicit sizing.
  svgEl.removeAttribute("width");
  svgEl.removeAttribute("height");
  svgEl.setAttribute("width", "100%");
  svgEl.setAttribute("height", "100%");

  if (interact) { interact.destroy(); interact = null; }
  if (panZoom) { try { panZoom.destroy(); } catch (_) {} }
  panZoom = svgPanZoom(svgEl, {
    zoomEnabled: true,
    controlIconsEnabled: false,
    fit: true,
    center: true,
    minZoom: 0.05,
    maxZoom: 40,
    zoomScaleSensitivity: 0.4,
    dblClickZoomEnabled: false,
  });
  // Hover/pin/drag/follow-the-line behaviour (static/interact.js).
  interact = OwlUmlInteract.attach(svgEl, { onNavigate: centerOn });

  matches = [];
  matchIdx = -1;
  $("search").value = "";
}

// ---- search ----------------------------------------------------------------
function clearHighlights() {
  document
    .querySelectorAll(".node--hit, .node--current")
    .forEach((n) => n.classList.remove("node--hit", "node--current"));
}

function runSearch(q) {
  clearHighlights();
  matches = [];
  matchIdx = -1;
  q = q.trim().toLowerCase();
  if (!svgEl || !q) return;

  svgEl.querySelectorAll("g.node:not(.uml-legend)").forEach((g) => {
    if ((g.textContent || "").toLowerCase().includes(q)) {
      g.classList.add("node--hit");
      matches.push(g);
    }
  });
  if (matches.length) {
    matchIdx = 0;
    focusMatch();
  }
  setStatus(matches.length ? `${matches.length} match(es)` : "No matches");
}

function focusMatch() {
  if (matchIdx < 0 || !matches.length) return;
  document
    .querySelectorAll(".node--current")
    .forEach((n) => n.classList.remove("node--current"));
  const el = matches[matchIdx];
  el.classList.add("node--current");
  if (interact) interact.pin(interact.idOf(el));
  centerOn(el);
}

// Transform-agnostic centering via screen coordinates.
function centerOn(el) {
  if (!panZoom) return;
  const r = el.getBoundingClientRect();
  const c = svgEl.getBoundingClientRect();
  const dx = (c.left + c.width / 2) - (r.left + r.width / 2);
  const dy = (c.top + c.height / 2) - (r.top + r.height / 2);
  panZoom.panBy({ x: dx, y: dy });
}

// Refit after classes moved: the drawing's bounds have changed.
function refit() {
  if (!panZoom) return;
  panZoom.updateBBox();
  panZoom.resize();
  panZoom.fit();
  panZoom.center();
}

// Stretch the layout to the viewport's shape so it fills the empty bands.
function spreadToFit() {
  if (!interact || !svgEl) return;
  const r = svgEl.getBoundingClientRect();
  if (interact.spread(r.width / r.height)) refit();
  else setStatus("Diagram already fills the window");
}

function step(delta) {
  if (!matches.length) return;
  matchIdx = (matchIdx + delta + matches.length) % matches.length;
  focusMatch();
  setStatus(`Match ${matchIdx + 1} / ${matches.length}`);
}

// ---- download --------------------------------------------------------------
// Downloads are self-contained interactive SVGs: the current diagram (with any
// classes the user dragged) plus interact.js inlined. Browsers run the script
// when the file is opened directly; Inkscape/Word/etc. ignore it and show the
// static drawing. The root <svg> attributes come from the server's original
// text so the file keeps its intrinsic size and viewBox.
let interactSrc = null;

async function downloadSvg() {
  if (!lastSvgText || !svgEl) { setStatus("Nothing to download yet", true); return; }
  if (interactSrc === null) {
    try { interactSrc = await (await fetch("/static/interact.js")).text(); }
    catch (e) { setStatus(`Could not load interact.js: ${e.message}`, true); return; }
  }

  const doc = new DOMParser().parseFromString(lastSvgText, "image/svg+xml");
  const out = doc.documentElement;
  while (out.firstChild) out.removeChild(out.firstChild);

  // svg-pan-zoom wraps the drawing in a transformed viewport <g>; take its
  // children, not the wrapper. Drop our runtime additions and highlight state.
  const live = svgEl.querySelector(".svg-pan-zoom_viewport") || svgEl;
  for (const child of live.childNodes) {
    out.appendChild(doc.importNode(child, true));
  }
  // A spread or dragged layout can outgrow the original canvas.
  const b = interact && interact.bounds();
  if (b) {
    out.setAttribute("viewBox", `${b.x} ${b.y} ${b.width} ${b.height}`);
    out.setAttribute("width", `${b.width}pt`);
    out.setAttribute("height", `${b.height}pt`);
  }
  out.querySelectorAll("style.oi-style, path.oi-hit").forEach((n) => n.remove());
  out.querySelectorAll(".oi-hl, .oi-sel, .oi-drag, .node--hit, .node--current")
    .forEach((n) => n.classList.remove("oi-hl", "oi-sel", "oi-drag", "node--hit", "node--current"));

  const script = doc.createElementNS("http://www.w3.org/2000/svg", "script");
  script.appendChild(doc.createCDATASection(
    interactSrc.replace(/]]>/g, "]]]]><![CDATA[>") +
    "\nOwlUmlInteract.attach(document.documentElement, { standalone: true });\n"
  ));
  out.appendChild(script);

  const xml = '<?xml version="1.0" encoding="UTF-8" standalone="no"?>\n' +
    new XMLSerializer().serializeToString(out);
  const blob = new Blob([xml], { type: "image/svg+xml;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `${lastName}.svg`;
  a.click();
  URL.revokeObjectURL(url);
}

// ---- wiring ----------------------------------------------------------------
window.addEventListener("DOMContentLoaded", () => {
  $("file").addEventListener("change", (e) => {
    const f = e.target.files[0];
    e.target.value = "";          // allow re-selecting the same file later
    renderFile(f);
  });

  // Toolbar "Open…" lets you load another ontology without reloading the app.
  $("open").addEventListener("click", () => $("file").click());

  const dz = $("dropzone");
  const stage = $("stage");
  ["dragenter", "dragover"].forEach((ev) =>
    stage.addEventListener(ev, (e) => {
      e.preventDefault();
      dz.classList.add("dragover");
    })
  );
  ["dragleave", "drop"].forEach((ev) =>
    stage.addEventListener(ev, (e) => {
      e.preventDefault();
      if (ev === "dragleave" && e.target !== stage && dz.contains(e.target)) return;
      dz.classList.remove("dragover");
    })
  );
  stage.addEventListener("drop", (e) => {
    const f = e.dataTransfer.files && e.dataTransfer.files[0];
    if (f) renderFile(f);
  });

  let searchTimer = null;
  $("search").addEventListener("input", (e) => {
    clearTimeout(searchTimer);
    const v = e.target.value;
    searchTimer = setTimeout(() => runSearch(v), 180);
  });
  $("search").addEventListener("keydown", (e) => {
    if (e.key === "Enter") step(e.shiftKey ? -1 : 1);
  });

  $("next").addEventListener("click", () => step(1));
  $("prev").addEventListener("click", () => step(-1));
  $("zoomIn").addEventListener("click", () => panZoom && panZoom.zoomIn());
  $("zoomOut").addEventListener("click", () => panZoom && panZoom.zoomOut());
  $("fit").addEventListener("click", refit);
  $("download").addEventListener("click", downloadSvg);
  $("clearFocus").addEventListener("click", () => interact && interact.clear());
  $("spread").addEventListener("click", spreadToFit);
  $("resetLayout").addEventListener("click", () => {
    if (!interact) return;
    interact.reset();
    refit();
  });

  window.addEventListener("resize", () => {
    if (panZoom) panZoom.resize();
  });
});
