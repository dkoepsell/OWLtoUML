"use strict";
// Scratchpad: draft or paste OWL in a side panel and see it drawn.
//
// The text is sent through the same path as an uploaded file: it is wrapped
// in a File object (marked o2uScratch) and handed to app.js's renderFile, so
// notation profiles, modules, flow view, edit mode, claims and exports all
// work unchanged. Every scratchpad render counts as the same document, so
// classes you dragged keep their places while you type.
//
// Ctrl/Cmd+Enter (or Render) draws with every option on the start screen.
// Live preview redraws after a pause in typing, without the reasoner or the
// claims, which are too slow to run on every pause.
const O2uScratch = (() => {
  const el = (id) => document.getElementById(id);
  const STORE = "o2u-scratch";
  const LIVE_PAUSE_MS = 900;

  // File extension per syntax, so downloads and exports get sensible names.
  const EXT = { auto: "ttl", turtle: "ttl", omn: "omn", ofn: "ofn", xml: "owl", owx: "owx", "json-ld": "jsonld" };

  // Prefixes added to Turtle when the text uses them without declaring them.
  const KNOWN = {
    rdf: "http://www.w3.org/1999/02/22-rdf-syntax-ns#",
    rdfs: "http://www.w3.org/2000/01/rdf-schema#",
    owl: "http://www.w3.org/2002/07/owl#",
    xsd: "http://www.w3.org/2001/XMLSchema#",
    skos: "http://www.w3.org/2004/02/skos/core#",
    obo: "http://purl.obolibrary.org/obo/",
    "": "http://example.org/scratch#",
  };

  const TEMPLATES = {
    turtle: `# A BFO-based starter in Turtle. Undeclared owl:, rdfs:, obo: and : prefixes
# are filled in for you. Ctrl+Enter draws it.
<http://example.org/scratch> a owl:Ontology .

obo:BFO_0000040 a owl:Class ; rdfs:label "material entity" .
obo:BFO_0000023 a owl:Class ; rdfs:label "role" .
obo:BFO_0000197 a owl:ObjectProperty ; rdfs:label "inheres in" .

:Person a owl:Class ;
  rdfs:label "person" ;
  rdfs:subClassOf obo:BFO_0000040 .

:JudgeRole a owl:Class ;
  rdfs:label "judge role" ;
  rdfs:subClassOf obo:BFO_0000023 ,
    [ a owl:Restriction ; owl:onProperty obo:BFO_0000197 ; owl:someValuesFrom :Person ] .
`,
    omn: `Prefix: : <http://example.org/scratch#>
Prefix: obo: <http://purl.obolibrary.org/obo/>
Prefix: rdfs: <http://www.w3.org/2000/01/rdf-schema#>

Ontology: <http://example.org/scratch>

ObjectProperty: obo:BFO_0000197
    Annotations: rdfs:label "inheres in"

Class: obo:BFO_0000040
    Annotations: rdfs:label "material entity"

Class: obo:BFO_0000023
    Annotations: rdfs:label "role"

Class: Person
    Annotations: rdfs:label "person"
    SubClassOf: obo:BFO_0000040

Class: JudgeRole
    Annotations: rdfs:label "judge role"
    SubClassOf: obo:BFO_0000023, obo:BFO_0000197 some Person
`,
  };

  let st = {
    open: false, live: false, timer: null, ctrl: null, sentText: null,
    offset: 0, errLine: 0, busyUntil: 0, pending: false,
  };

  // ---- persistence ---------------------------------------------------------------
  function save() {
    try {
      localStorage.setItem(STORE, JSON.stringify({
        text: el("scratchText").value, syntax: el("scratchSyntax").value, live: st.live,
        width: el("stage").style.getPropertyValue("--scratch-w") || "",
      }));
    } catch (_) { /* storage full or blocked: drafts just aren't kept */ }
  }
  function restore() {
    let s = null;
    try { s = JSON.parse(localStorage.getItem(STORE) || "null"); } catch (_) {}
    if (!s) return;
    el("scratchText").value = s.text || "";
    if (s.syntax) el("scratchSyntax").value = s.syntax;
    st.live = !!s.live;
    el("scratchLive").checked = st.live;
    if (s.width) el("stage").style.setProperty("--scratch-w", s.width);
  }

  // ---- syntax helpers ---------------------------------------------------------------
  // Same first-line tests as owl2uml/load.py's sniff(), reduced to "is this Turtle?".
  function looksTurtle(text) {
    const s = text.split("\n").filter((l) => l.trim() && !/^\s*(#|\/\/)/.test(l)).join("\n").trimStart();
    if (!s) return false;
    return !/^(<|\{|\[|Prefix\s*\(|Ontology\s*\(|Prefix:|Ontology:|Class:|ObjectProperty:|DataProperty:|format-version:|\[Term\])/.test(s);
  }

  // Declarations for prefixes the Turtle uses but never declares.
  function missingPrefixes(text) {
    const add = [];
    for (const [p, iri] of Object.entries(KNOWN)) {
      const pe = p.replace(/[-]/g, "\\-");
      const declared = new RegExp(`(@prefix|PREFIX)\\s+${pe}:`, "i").test(text);
      if (declared) continue;
      const used = p
        ? new RegExp(`(^|[\\s;,(\\[\\^])${pe}:[A-Za-z_0-9]`, "m").test(text)
        : /(^|[\s;,(\[\^]):[A-Za-z_]/m.test(text);
      if (used) add.push(`@prefix ${p}: <${iri}> .`);
    }
    return add;
  }

  // The text to send, and how many lines were added in front of it.
  function prepared() {
    const text = el("scratchText").value;
    const syntax = el("scratchSyntax").value;
    if (syntax === "turtle" || (syntax === "auto" && looksTurtle(text))) {
      const add = missingPrefixes(text);
      if (add.length) return { body: add.join("\n") + "\n" + text, offset: add.length };
    }
    return { body: text, offset: 0 };
  }

  function makeFile() {
    const syntax = el("scratchSyntax").value;
    const { body, offset } = prepared();
    const f = new File([body], `scratchpad.${EXT[syntax] || "ttl"}`, { type: "text/plain" });
    f.o2uScratch = true;
    f.o2uFormat = syntax;
    return { file: f, offset };
  }

  // ---- messages and the error line -----------------------------------------------
  // Parser messages count lines of what was sent; shift them back to the user's text.
  function shiftLines(msg, offset) {
    if (!offset) return msg;
    return msg.replace(/\b(line)\s+(\d+)/gi, (m, w, n) => `${w} ${Math.max(1, +n - offset)}`);
  }
  function firstLine(msg) {
    const m = /\bline\s+(\d+)/i.exec(msg);
    return m ? +m[1] : 0;
  }

  function say(msg, kind) {
    const m = el("scratchMsg");
    m.textContent = msg;
    m.className = "scratch-msg" + (kind ? ` scratch-msg--${kind}` : "");
    m.classList.toggle("scratch-msg--link", kind === "error" && !!st.errLine);
    m.title = kind === "error" && st.errLine ? `Go to line ${st.errLine}` : "";
  }

  function gutter() {
    const n = el("scratchText").value.split("\n").length;
    const g = el("scratchGutter");
    let out = "";
    for (let i = 1; i <= n; i++) out += i === st.errLine ? `<b>${i}</b>\n` : `${i}\n`;
    g.innerHTML = out;
    g.scrollTop = el("scratchText").scrollTop;
  }

  function goToLine(n) {
    const ta = el("scratchText");
    const lines = ta.value.split("\n");
    if (n < 1 || n > lines.length) return;
    const start = lines.slice(0, n - 1).reduce((a, l) => a + l.length + 1, 0);
    ta.focus();
    ta.setSelectionRange(start, start + lines[n - 1].length);
    const lh = parseFloat(getComputedStyle(ta).lineHeight) || 18;
    ta.scrollTop = Math.max(0, (n - 4) * lh);
    gutter();
  }

  // ---- rendering ------------------------------------------------------------------------
  async function render(quick) {
    const text = el("scratchText").value;
    if (!text.trim()) { say("Nothing to draw yet. Type or paste OWL, or pick a template.", ""); return; }
    if (quick && Date.now() < st.busyUntil) { schedule(); return; }
    clearTimeout(st.timer);
    if (st.ctrl) st.ctrl.abort();          // a newer draft replaces the one still drawing
    const ctrl = new AbortController();
    st.ctrl = ctrl;
    const { file, offset } = makeFile();
    st.sentText = text;
    st.offset = offset;
    say(quick ? "Drawing…" : "Drawing with every option on…", "busy");
    const res = await renderFile(file, { quick, signal: ctrl.signal });
    if (ctrl !== st.ctrl) return;          // superseded
    st.ctrl = null;
    if (!res) { say("Drawn as a comparison with the older version chosen on the start screen.", "ok"); return; }
    if (res.aborted) return;
    if (res.ok) {
      st.errLine = 0;
      gutter();
      say(quick ? "Drawn (live: no reasoner, no claims). Ctrl+Enter for everything." : "Drawn.", "ok");
      return;
    }
    if (res.status === 429) {
      st.busyUntil = Date.now() + 5000;
      say("The server is busy: live preview paused for a few seconds.", "error");
      if (quick) schedule();
      return;
    }
    const msg = shiftLines(res.error || "Could not draw this.", offset);
    setStatus(`Scratchpad: ${msg}`, true);     // the footer gets the user's line numbers too
    st.errLine = firstLine(msg);
    gutter();
    say(`${msg}${res.kept ? " (the last good drawing is still shown)" : ""}`, "error");
  }

  function schedule() {
    clearTimeout(st.timer);
    if (!st.live || !st.open) return;
    st.timer = setTimeout(() => {
      if (el("scratchText").value !== st.sentText) render(true);
    }, Math.max(LIVE_PAUSE_MS, st.busyUntil - Date.now()));
  }

  // ---- templates and copying in ---------------------------------------------------
  async function useTemplate(which) {
    const ta = el("scratchText");
    let text = null, syntax = null;
    if (which === "blank") { text = ""; syntax = "auto"; }
    else if (TEMPLATES[which]) { text = TEMPLATES[which]; syntax = which; }
    else if (which === "current") {
      const f = typeof lastFile !== "undefined" ? lastFile : null;
      if (!f) { say("Open an ontology first, then copy it in.", "error"); return; }
      if (f.size > 2 * 1024 * 1024 &&
          !confirm(`${f.name} is ${(f.size / 1048576).toFixed(1)} MB. Large texts make the scratchpad slow. Copy it anyway?`)) return;
      text = await f.text();
      syntax = f.o2uFormat || "auto";
    }
    if (text === null) return;
    if (ta.value.trim() && ta.value !== text && !confirm("Replace the text in the scratchpad?")) return;
    ta.value = text;
    el("scratchSyntax").value = syntax;
    st.errLine = 0;
    gutter();
    save();
    say("", "");
    if (text) render(true);      // a quick draw; Ctrl+Enter adds the reasoner and claims
  }

  // Edit mode on a scratchpad drawing: write the edits into the text itself.
  async function pullEdits() {
    if (!editor || !editor.count() || !lastFile || !lastFile.o2uScratch) return;
    const syntax = el("scratchSyntax").value;
    const out = syntax === "xml" ? "xml" : "turtle";
    if (!["auto", "turtle", "xml"].includes(syntax) &&
        !confirm("The text will be rewritten as Turtle, with your diagram edits applied. Continue?")) return;
    const fd = new FormData();
    fd.append("file", lastFile);
    fd.append("format", lastFile.o2uFormat || "auto");
    fd.append("fmt", out);
    fd.append("edits", JSON.stringify(editor.ops()));
    say("Writing the edits into the text…", "busy");
    let res;
    try { res = await fetch("/api/export", { method: "POST", body: fd }); }
    catch (e) { say(`Network error: ${e.message}`, "error"); return; }
    if (!res.ok) {
      let msg = `Could not apply the edits (${res.status})`;
      try { msg = (await res.json()).error || msg; } catch (_) {}
      say(msg, "error");
      return;
    }
    const skipped = +(res.headers.get("X-Edits-Skipped") || 0);
    el("scratchText").value = await res.text();
    el("scratchSyntax").value = out === "xml" ? "xml" : "turtle";
    editor.bindFile(null);       // the edits now live in the text
    exportedAt = 0;
    setEditMode(false);
    save();
    await render(false);
    if (skipped) say(`${skipped} edit(s) could not be applied and were dropped.`, "error");
  }

  function onEdits(n) {
    const b = el("scratchPull");
    if (b) b.hidden = !(n && st.open && typeof lastFile !== "undefined" && lastFile && lastFile.o2uScratch);
  }

  // ---- panel ----------------------------------------------------------------------------
  function refit() {
    if (typeof panZoom !== "undefined" && panZoom) {
      try { panZoom.resize(); panZoom.fit(); panZoom.center(); } catch (_) { /* no diagram yet */ }
    }
  }
  function open() {
    st.open = true;
    el("scratchPane").hidden = false;
    el("stage").classList.add("with-scratch");
    el("scratchBtn").classList.add("active");
    gutter();
    el("scratchText").focus();
    onEdits(editor ? editor.count() : 0);
    refit();
  }
  function close() {
    st.open = false;
    clearTimeout(st.timer);
    el("scratchPane").hidden = true;
    el("stage").classList.remove("with-scratch");
    el("scratchBtn").classList.remove("active");
    refit();
  }
  const toggle = () => (st.open ? close() : open());

  // Drag the panel's right edge to resize it.
  function resizer() {
    const h = el("scratchResize");
    h.addEventListener("pointerdown", (ev) => {
      ev.preventDefault();
      h.setPointerCapture(ev.pointerId);
      const stage = el("stage").getBoundingClientRect();
      const move = (e) => {
        const w = Math.max(260, Math.min(e.clientX - stage.left, stage.width - 240));
        el("stage").style.setProperty("--scratch-w", `${Math.round(w)}px`);
        if (typeof panZoom !== "undefined" && panZoom) try { panZoom.resize(); } catch (_) {}
      };
      const up = () => {
        h.removeEventListener("pointermove", move);
        h.removeEventListener("pointerup", up);
        save();
        refit();
      };
      h.addEventListener("pointermove", move);
      h.addEventListener("pointerup", up);
    });
  }

  function init() {
    if (!el("scratchPane")) return;
    restore();
    const ta = el("scratchText");
    ta.addEventListener("input", () => { gutter(); save(); schedule(); });
    ta.addEventListener("scroll", () => { el("scratchGutter").scrollTop = ta.scrollTop; });
    ta.addEventListener("keydown", (e) => {
      if ((e.ctrlKey || e.metaKey) && e.key === "Enter") { e.preventDefault(); render(false); return; }
      if (e.key === "Tab" && !e.shiftKey && !e.ctrlKey && !e.metaKey && !e.altKey) {
        e.preventDefault();      // indent instead of leaving the editor (Esc then Tab leaves it)
        const s = ta.selectionStart, end = ta.selectionEnd;
        ta.setRangeText("    ", s, end, "end");
        gutter(); save(); schedule();
      }
      if (e.key === "Escape") ta.blur();
    });
    el("scratchRender").addEventListener("click", () => render(false));
    el("scratchLive").addEventListener("change", (e) => {
      st.live = e.target.checked;
      save();
      if (st.live && ta.value !== st.sentText) render(true);
    });
    el("scratchSyntax").addEventListener("change", () => { save(); if (st.live) render(true); });
    el("scratchTemplate").addEventListener("change", (e) => {
      const v = e.target.value;
      e.target.value = "";
      if (v) useTemplate(v);
    });
    el("scratchMsg").addEventListener("click", () => { if (st.errLine) goToLine(st.errLine); });
    el("scratchClose").addEventListener("click", close);
    el("scratchBtn").addEventListener("click", toggle);
    el("scratchStart").addEventListener("click", open);
    el("scratchPull").addEventListener("click", pullEdits);
    resizer();
    gutter();
  }

  window.addEventListener("DOMContentLoaded", init);
  return { open, close, toggle, onEdits, render };
})();
