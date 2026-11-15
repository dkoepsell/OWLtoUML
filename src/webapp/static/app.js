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
let lastFile = null;
let lastFileSent = null;
let lastForm = null;      // the last render's request, reused by figure exports   // the sidecar upload applies to the first drawing only       // kept so the view can be switched without re-choosing it

// Edit mode (static/edit.js): a list of edits applied server-side on re-layout/export.
let editor = null;
let exportedAt = 0;        // edit count when last exported, for the unsaved-edits warning

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

  let restore = null;
  if (file !== lastFile && editor) {
    if (editor.count() > exportedAt && !confirm("Discard your unexported edits to the current ontology?")) {
      hideOverlay(); setStatus("Kept the current ontology"); return;
    }
    restore = editor.bindFile(file);
    exportedAt = 0;
  }
  // Saved positions: moved classes stay put when the same ontology is drawn
  // again (reasoner, module, options); a new ontology may bring a sidecar.
  const layout = file === lastFile && interact ? pinnedOnly(interact.layout()) : null;
  if (file !== lastFile) $("module").value = "";   // a new ontology starts whole
  lastFile = file;
  const flow = $("view").value === "flow";
  const fd = new FormData();
  fd.append("file", file);
  fd.append("format", $("format").value);
  fd.append("imports", $("imports").value);
  fd.append("aspect", stageAspect());
  if ($("module").value) fd.append("module", $("module").value);
  if (layout && Object.keys(layout).length) fd.append("layout_json", JSON.stringify(layout));
  else if (file !== lastFileSent && $("layoutFile").files[0]) fd.append("layout", $("layoutFile").files[0]);
  lastFileSent = file;
  if ($("keepUnused").checked) fd.append("keep_unused", "1");
  if ($("reason").checked) fd.append("reason", "auto");
  if ($("definitions").checked) fd.append("definitions", "1");
  fd.append("profile", $("profile").value);
  if ($("chains").checked) fd.append("chains", "1");
  if ($("view").value === "properties") fd.append("view", "properties");
  if (flow) {
    fd.append("view", "flow");
    for (const f of $("events").files) fd.append("events", f);
    if ($("shapes").files[0]) fd.append("shapes", $("shapes").files[0]);
  } else if (editor && editor.count()) {
    fd.append("edits", JSON.stringify(editor.ops()));
  }

  lastForm = fd;
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
  resetStretch();
  setupModules(data);
  setupFlow(data);
  if (data.view === "flow") {
    const f = data.flow;
    const ev = f.cases ? ` · ${f.cases} cases, ${f.deviations} undesigned path(s)` : "";
    const sh = f.shapes ? ` · ${f.findings} SHACL finding(s)` : "";
    setStatus(`${file.name} — flow: ${f.steps} steps in ${f.lanes} lanes${ev}${sh}`);
    return;
  }
  const pruned = (data.pruned ? ` · ${data.pruned} unused imported classes left out` : "") +
    (data.profile ? ` · notation: ${data.profile.profiles.join(", ")}, ${data.profile.labels} line labels` : "");
  setupInferred(data.reasoning);
  const groups = data.groups && data.groups.length > 1 ? ` · ${data.groups.length} groups` : "";
  setStatus(
    `${file.name} — ${data.classes} classes, ${data.edges} relations${groups}${pruned} · engine: ${data.engine}` +
    loaderNote(data.loader) + coverageNote(data.coverage) + reasoningNote(data.reasoning) +
    editsNote(data.edits),
    !!(data.loader && data.loader.warnings.length) ||
    !!(data.reasoning && (data.reasoning.error || data.reasoning.inconsistent)) ||
    !!(data.edits && data.edits.skipped.length)
  );
  rendered = true;
  if (restore && confirm(`You have ${restore.length} unexported edit(s) saved for ${file.name}. Restore them?`)) {
    editor.load(restore);
    setEditMode(true);
  }
}

// ---- edit mode -----------------------------------------------------------------
function editsNote(r) {
  if (!r) return "";
  const sk = r.skipped.length ? `, ${r.skipped.length} could not be applied (${editor.skipped(r.skipped).join("; ")})` : "";
  return ` · ${r.applied} edit(s) applied${sk}`;
}

function setEditMode(v) {
  if (!editor) return;
  if (v && !interact) return;
  if (v && !editorAttached) {
    setStatus("Edit mode needs the class view drawn with Graphviz", true);
    return;
  }
  editor.setOn(v);
  $("editToggle").classList.toggle("active", v);
  $("editToggle").textContent = v ? "Done editing" : "Edit";
  $("editTools").hidden = !v;
  $("editHelp").hidden = !v;
}

function updateEditCount(nSteps) {
  $("editCount").textContent = `${nSteps} edit${nSteps === 1 ? "" : "s"}`;
  $("undo").disabled = !nSteps;
  $("editToggle").classList.toggle("has-edits", nSteps > 0);
}

let editorAttached = false;
let rendered = false;      // set by renderFile when a class view came back

async function relayout() {
  if (!lastFile) return;
  rendered = false;
  await renderFile(lastFile);
  if (rendered && editor) { editor.markBaked(); editor.setOn(editor.isOn()); }
}

async function exportOwl() {
  if (!lastFile || !editor) return;
  const fd = new FormData();
  fd.append("file", lastFile);
  fd.append("format", $("format").value);
  fd.append("fmt", $("exportFmt").value);
  fd.append("edits", JSON.stringify(editor.ops()));
  setStatus("Exporting…");
  let res;
  try {
    res = await fetch("/api/export", { method: "POST", body: fd });
  } catch (e) { setStatus(`Network error: ${e.message}`, true); return; }
  if (!res.ok) {
    let msg = `Export failed (${res.status})`;
    try { msg = (await res.json()).error || msg; } catch (_) {}
    setStatus(msg, true);
    return;
  }
  const blob = await res.blob();
  const cd = res.headers.get("Content-Disposition") || "";
  const m = cd.match(/filename="([^"]+)"/);
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = m ? m[1] : `${lastName}-edited.ttl`;
  a.click();
  URL.revokeObjectURL(a.href);
  exportedAt = editor.count();
  const skipped = +(res.headers.get("X-Edits-Skipped") || 0);
  setStatus(`Exported ${a.download} — ${res.headers.get("X-Edits-Applied") || 0} edit(s) applied` +
    (skipped ? `, ${skipped} could not be applied (Re-layout to see which)` : ""), !!skipped);
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
  // Clicking a class or line shows its OWL source in the side panel.
  $("sourcePanel").innerHTML = "";
  interact = OwlUmlInteract.attach(svgEl, {
    onNavigate: centerOn, sourceHost: $("sourcePanel"), edit: editor ? editor.hooks : null,
    app: true,
  });
  $("source").hidden = !interact.panel();
  editorAttached = !!(editor && editor.attach(svgEl, interact));
  $("editToggle").hidden = !editorAttached;
  if (!editorAttached && editor && editor.isOn()) setEditMode(false);

  matches = [];
  matchIdx = -1;
  $("search").value = "";
}

// ---- reasoning ---------------------------------------------------------------
// The server draws inferred subclass edges (class "rel-inferred") into the same
// layout; the toolbar button (or "i") hides them and their orange outlines by
// toggling the "hide-inferred" class on the <svg>.
let inferredCount = 0;

function reasoningNote(r) {
  if (!r || r.engine === "none") return "";
  if (r.error) return ` · reasoner (${r.engine}) failed: ${r.error}`;
  if (r.inconsistent) return ` · reasoner (${r.engine}): ontology is INCONSISTENT`;
  const unsat = r.unsatisfiable ? `, ${r.unsatisfiable} unsatisfiable` : "";
  return ` · reasoner ${r.engine}: ${r.inferred} inferred subclass relation(s)${unsat} (${r.seconds}s)`;
}

function setupInferred(r) {
  inferredCount = (r && !r.error && !r.inconsistent) ? r.inferred : 0;
  const b = $("inferred");
  b.hidden = !inferredCount;
  if (svgEl) svgEl.classList.add("hide-inferred");
  b.textContent = `Show inferred (${inferredCount})`;
}

function toggleInferred() {
  if (!svgEl || !inferredCount) return;
  const hidden = svgEl.classList.toggle("hide-inferred");
  $("inferred").textContent = `${hidden ? "Show" : "Hide"} inferred (${inferredCount})`;
}

// ---- flow view ---------------------------------------------------------------
// The flow SVG carries both the practiced flow (from events) and the designed
// one; the "o2u-designed" class on the <svg> hides what came from the events.
function setupFlow(data) {
  const flow = data.view === "flow";
  $("viewToggle").textContent = flow ? "Classes" : "Flow";
  $("viewToggle").title = flow ? "Show the class diagram" : "Show the processes as a flow in swimlanes";
  // Spreading would pull steps out of their lanes, which are drawn in place.
  $("spread").hidden = flow;
  const sel = $("caseSel");
  sel.innerHTML = '<option value="">All cases</option>' +
    (flow ? (data.cases || []).map((c) => `<option value="${c.replace(/"/g, "&quot;")}">${c.replace(/</g, "&lt;")}</option>`).join("") : "");
  sel.hidden = !(flow && data.cases && data.cases.length);
  $("practiced").hidden = !(flow && data.flow && data.flow.cases);
  $("practiced").textContent = "Show designed";
}
function togglePracticed() {
  if (!svgEl) return;
  const designed = svgEl.classList.toggle("o2u-designed");
  $("practiced").textContent = designed ? "Show practiced" : "Show designed";
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

// Width / height sliders: each move stretches the gaps between classes by the
// change since the slider's last value (100 = as laid out).
const stretchAt = { x: 100, y: 100 };
function onStretch(axis) {
  const el = $(axis === "x" ? "stretchX" : "stretchY");
  const v = Number(el.value);
  if (!interact || !svgEl) { el.value = 100; return; }
  const k = v / stretchAt[axis];
  stretchAt[axis] = v;
  if (interact.stretch(axis === "x" ? k : 1, axis === "y" ? k : 1)) refit();
}
function resetStretch() {
  stretchAt.x = stretchAt.y = 100;
  $("stretchX").value = $("stretchY").value = 100;
}

// Width/height of the drawing area, so the server lays the diagram out for it.
function stageAspect() {
  const st = $("stage").getBoundingClientRect();
  return st.width > 0 && st.height > 0 ? (st.width / st.height).toFixed(3) : "auto";
}

function step(delta) {
  if (!matches.length) return;
  matchIdx = (matchIdx + delta + matches.length) % matches.length;
  focusMatch();
  setStatus(`Match ${matchIdx + 1} / ${matches.length}`);
}

// ---- wiring ----------------------------------------------------------------
window.addEventListener("DOMContentLoaded", () => {
  if (window.OwlUmlEdit) {
    editor = OwlUmlEdit.create({
      onChange: (n) => updateEditCount(n),
      onStale: () => setStatus("Undid an edit that is already drawn — Re-layout to redraw without it"),
    });
  }
  $("editToggle").addEventListener("click", () => setEditMode(!(editor && editor.isOn())));
  $("addClass").addEventListener("click", () => editor && editor.addClass());
  $("undo").addEventListener("click", () => editor && editor.undo());
  $("redo").addEventListener("click", () => editor && editor.redo());
  $("relayout").addEventListener("click", relayout);
  $("exportOwl").addEventListener("click", exportOwl);
  window.addEventListener("beforeunload", (e) => {
    if (editor && editor.count() > exportedAt) { e.preventDefault(); e.returnValue = ""; }
  });
  $("file").addEventListener("change", (e) => {
    const f = e.target.files[0];
    e.target.value = "";          // allow re-selecting the same file later
    renderFile(f);
  });

  $("iriForm").addEventListener("submit", (e) => {
    e.preventDefault();
    loadIri($("iri").value.trim());
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
  $("stretchX").addEventListener("input", () => onStretch("x"));
  $("module").addEventListener("change", () => { if (lastFile) renderFile(lastFile); });
  $("saveLayout").addEventListener("click", () => {
    if (interact) interact.saveLayout(`${lastName}.layout.json`);
  });
  $("stretchY").addEventListener("input", () => onStretch("y"));
  $("download").addEventListener("click", () => {
    const fmt = $("figureFmt").value;
    if (fmt === "svg") downloadSvg(); else downloadFigure(fmt);
  });
  $("clearFocus").addEventListener("click", () => interact && interact.clear());
  $("inferred").addEventListener("click", toggleInferred);
  $("view").addEventListener("change", () => { $("flowfiles").hidden = $("view").value !== "flow"; });
  $("viewToggle").addEventListener("click", () => {
    if (!lastFile) return;
    $("view").value = $("view").value === "flow" ? "classes" : "flow";
    $("flowfiles").hidden = $("view").value !== "flow";
    renderFile(lastFile);
  });
  $("caseSel").addEventListener("change", (e) => { if (interact) interact.showCase(e.target.value); });
  $("practiced").addEventListener("click", togglePracticed);
  $("source").addEventListener("click", () => {
    const p = interact && interact.panel();
    if (p) p.toggle();
  });
  // svg-pan-zoom swallows the mouse's default action, so clicking the diagram
  // would otherwise leave keyboard focus in the search box (and "i" or Esc
  // would type into it). Release focus when the diagram is pressed.
  $("viewport").addEventListener("pointerdown", () => {
    const a = document.activeElement;
    if (a && a.tagName === "INPUT") a.blur();
  }, true);
  document.addEventListener("keydown", (e) => {
    if (e.key === "e" && !/^(INPUT|SELECT|TEXTAREA)$/.test(e.target.tagName) && !e.ctrlKey && !e.metaKey &&
        !$("editToggle").hidden) setEditMode(!editor.isOn());
    if (e.key === "i" && e.target.tagName !== "INPUT") toggleInferred();
    if (e.key === "p" && !/^(INPUT|SELECT)$/.test(e.target.tagName) && !$("practiced").hidden) {
      // interact.js toggles the class; update the button once it has
      setTimeout(() => {
        $("practiced").textContent = svgEl && svgEl.classList.contains("o2u-designed") ? "Show practiced" : "Show designed";
      }, 0);
    }
  });
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
