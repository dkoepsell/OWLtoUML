"use strict";
// Status-line notes about how the ontology was read (loader, imports,
// axiom coverage) and loading an ontology by IRI. Used by app.js, which
// defines $, setStatus, showOverlay, hideOverlay and renderFile.

// Which loader read the file, and how many of its imports could be loaded.
function loaderNote(l) {
  if (!l) return "";
  const by = l.loader === "robot" ? "OWL API (ROBOT)" : "rdflib";
  let note = ` · read as ${l.syntax} by ${by}`;
  if (l.imports.length) {
    const ok = l.imports.filter((i) => !i.error).length;
    note += ` · ${ok} of ${l.imports.length} import(s) loaded`;
    const failed = l.imports.filter((i) => i.error).map((i) => i.iri);
    if (failed.length) note += ` (missing: ${failed.slice(0, 3).join(", ")}${failed.length > 3 ? "…" : ""})`;
  }
  return note;
}

// What happened to the ontology's axioms (drawn / source panel / left out).
function coverageNote(c) {
  if (!c || !c.totals.axioms) return "";
  const t = c.totals;
  return ` · axioms: ${t.drawn} drawn, ${t.panel} in source panel, ${t.dropped} left out`;
}

// Load an ontology by IRI: the server fetches it (public hosts only) and the
// page then treats it exactly like an uploaded file.
async function loadIri(iri) {
  if (!iri) return;
  showOverlay("Fetching…");
  setStatus(`Fetching ${iri}…`);
  const fd = new FormData();
  fd.append("iri", iri);
  let res;
  try {
    res = await fetch("/api/fetch", { method: "POST", body: fd });
  } catch (e) {
    hideOverlay();
    setStatus(`Network error: ${e.message}`, true);
    return;
  }
  if (!res.ok) {
    hideOverlay();
    let msg = `Could not fetch ${iri} (${res.status})`;
    try { msg = (await res.json()).error || msg; } catch (e) { /* not JSON */ }
    setStatus(msg, true);
    return;
  }
  const blob = await res.blob();
  const name = res.headers.get("X-Filename") || "ontology.owl";
  hideOverlay();
  renderFile(new File([blob], name));
}

// Module picker: shown when the ontology has two or more modules of its own.
function setupModules(data) {
  const sel = $("module");
  const own = (data.modules || []).filter((m) => !m.upper);
  sel.hidden = own.length < 2 || data.view === "flow";
  if (sel.hidden) return;
  const keep = data.module || "";
  sel.innerHTML = "";
  const add = (value, text) => {
    const o = document.createElement("option");
    o.value = value; o.textContent = text; sel.appendChild(o);
  };
  add("", "All modules");
  add("overview", "Overview of modules");
  for (const m of own) add(m.id, `${m.id} (${m.count})`);
  sel.value = keep;
}

// The pinned entries of a layout (only those are worth sending back).
function pinnedOnly(layout) {
  const out = {};
  for (const [iri, v] of Object.entries(layout || {})) if (v.pinned) out[iri] = v;
  return out;
}
