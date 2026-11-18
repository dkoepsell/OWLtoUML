// Claims side panel: what the ontology asserts and what a reasoner infers from
// it, as plain-English sentences (POST /api/claims, `owl2uml claims`).
// Turned on by the "Show claims" checkbox (generated alongside the diagram)
// or the toolbar's Claims button. While HermiT and Pellet run, the panel and
// the button show that the claims are being generated.
const O2uClaims = (() => {
  const el = (id) => document.getElementById(id);
  const STATUS = {
    ENTAILED: ["Inferred: follows from what is stated", "inferred"],
    REFUTED: ["Inferred: ruled out by what is stated", "inferred"],
    POSSIBLE: ["Possible: allowed, but not required", "inferred"],
    UNDETERMINED: ["Open: the ontology does not say", "inferred"],
    ASSERTED: ["Asserted: stated in the ontology", "asserted"],
  };
  const ORDER = Object.keys(STATUS);
  const show = { inferred: true, asserted: true };
  let st = { file: null, data: null, error: null, loading: false, t0: 0, timer: null, token: 0 };

  const esc = (s) => String(s ?? "").replace(/[&<>"]/g,
    (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  const wanted = () => el("showClaims").checked;

  function save(text, name, type) {
    const a = document.createElement("a");
    a.href = URL.createObjectURL(new Blob([text], { type }));
    a.download = name;
    a.click();
    setTimeout(() => URL.revokeObjectURL(a.href), 1000);
  }

  function tsv(recs) {
    const cell = (v) => String(v ?? "").replace(/[\t\n]/g, " ");
    const rows = [["id", "status", "tier", "grammar", "text", "manchester", "justification"]];
    for (const r of recs) {
      rows.push([r.id, r.status, r.tier, r.grammar, r.text, r.manchester,
        (r.justification || []).map((a) => a.axiom_id).join(";")]);
    }
    return rows.map((r) => r.map(cell).join("\t")).join("\n") + "\n";
  }

  function item(r) {
    const just = (r.justification || []).map((a) =>
      `<li><code>${esc(a.manchester || a.axiom_id)}</code></li>`).join("");
    return `<li class="claim claim--${r.status.toLowerCase()}"><details>
      <summary>${esc(r.text)}${r.defn_linked ? ' <span class="claim-tag" title="Follows from a class definition">definition</span>' : ""}</summary>
      <div class="claim-more">
        <div><b>Manchester:</b> <code>${esc(r.manchester)}</code></div>
        ${just ? `<div><b>Because:</b><ul>${just}</ul></div>` : ""}
        ${r.justification_skipped ? '<div class="claims-hint">Justification not computed (limit reached).</div>' : ""}
      </div></details></li>`;
  }

  // ---- panel ----------------------------------------------------------------
  function open() {
    el("claimsPane").hidden = false;
    el("stage").classList.add("with-claims");
    el("claimsBtn").classList.add("active");
    refit();
  }
  function close() {
    el("claimsPane").hidden = true;
    el("stage").classList.remove("with-claims");
    el("claimsBtn").classList.remove("active");
    refit();
  }
  function refit() {
    if (typeof panZoom !== "undefined" && panZoom) {
      try { panZoom.resize(); panZoom.fit(); panZoom.center(); } catch (_) { /* no diagram yet */ }
    }
  }

  function button() {
    const b = el("claimsBtn");
    b.classList.toggle("busy", st.loading);
    const n = st.data ? (st.data.claims || []).length : null;
    b.textContent = st.loading ? "Claims…" : n != null ? `Claims (${n})` : "Claims";
    b.title = st.loading ? "Generating the claims (HermiT and Pellet are running)"
      : "Show or hide the claims: what the ontology asserts and what follows from it, in plain English";
  }

  function head(sub) {
    return `<div class="claims-top">
        <h2>Claims${st.file ? ` <span>in ${esc(st.file.name)}</span>` : ""}</h2>
        <button class="claims-x" id="claimsX" title="Hide the claims panel">×</button>
      </div>${sub || ""}`;
  }

  function render() {
    button();
    const pane = el("claimsPane");
    if (st.loading) {
      const s = Math.round((Date.now() - st.t0) / 1000);
      pane.innerHTML = head(`<div class="claims-busy"><span class="spinner"></span>
        <div><b>Generating claims… ${s}s</b><br>
        HermiT and Pellet are checking which statements follow from the ontology,
        which it rules out and which it leaves open. This usually takes 10–60 seconds.
        You can keep using the diagram meanwhile.</div></div>`);
    } else if (st.error) {
      pane.innerHTML = head(`<div class="claims-error"><b>No claims.</b> ${esc(st.error)}</div>
        <button id="claimsRetry">Try again</button>`);
      el("claimsRetry").addEventListener("click", () => load(st.file, true));
    } else if (st.data) {
      const recs = st.data.claims || [];
      const rep = st.data.report || {};
      const inf = recs.filter((r) => STATUS[r.status][1] === "inferred").length;
      const vis = recs.filter((r) => show[STATUS[r.status][1]]);
      const groups = ORDER.map((s) => [s, vis.filter((r) => r.status === s)]).filter(([, g]) => g.length);
      pane.innerHTML = head(`
        <p class="claims-hint">${inf} inferred and ${recs.length - inf} asserted, checked by
          ${Object.keys(rep.reasoners || {}).join(" and ") || "the reasoners"}${rep.seconds_total != null ? ` in ${rep.seconds_total}s` : ""}.
          Click a claim for its Manchester form and the axioms behind it.</p>
        <div class="claims-filter">Show
          <label><input type="checkbox" data-f="inferred" ${show.inferred ? "checked" : ""}/> inferences (${inf})</label>
          <label><input type="checkbox" data-f="asserted" ${show.asserted ? "checked" : ""}/> assertions (${recs.length - inf})</label>
        </div>
        <div class="claims-dl">Download <button data-dl="txt">.txt</button><button data-dl="tsv">.tsv</button><button data-dl="jsonl">.jsonl</button></div>
        ${(st.data.warnings || []).map((w) => `<p class="claims-warn">${esc(w)}</p>`).join("")}
        <div class="claims-list">
        ${groups.length ? "" : '<p class="claims-hint">Nothing to show with these filters.</p>'}
        ${groups.map(([s, g]) => `<section class="claims-group">
          <h3 class="claim--${s.toLowerCase()}">${STATUS[s][0]} <span class="claims-n">${g.length}</span></h3>
          <ul>${g.map(item).join("")}</ul></section>`).join("")}
        </div>`);
      pane.querySelectorAll("[data-f]").forEach((c) => c.addEventListener("change", () => {
        show[c.dataset.f] = c.checked;
        render();
      }));
      const stem = st.file.name.replace(/\.[^.]+$/, "");
      pane.querySelectorAll("[data-dl]").forEach((b) => b.addEventListener("click", () => {
        const k = b.dataset.dl;
        if (k === "txt") save(st.data.txt, `${stem}-claims.txt`, "text/plain");
        if (k === "tsv") save(tsv(recs), `${stem}-claims.tsv`, "text/tab-separated-values");
        if (k === "jsonl") save(st.data.jsonl, `${stem}-claims.jsonl`, "application/x-ndjson");
      }));
    } else {
      pane.innerHTML = head('<p class="claims-hint">Open an ontology to see its claims.</p>');
    }
    el("claimsX").addEventListener("click", close);
  }

  // ---- generation -------------------------------------------------------------
  async function load(file, force = false) {
    if (!file) return render();
    if (!force && st.file === file && (st.data || st.loading)) return render();
    const token = ++st.token;
    clearInterval(st.timer);
    st = { ...st, file, data: null, error: null, loading: true, t0: Date.now(), token };
    st.timer = setInterval(() => { if (st.token === token && st.loading) render(); }, 1000);
    render();
    const fd = new FormData();
    fd.append("file", file);
    fd.append("format", el("format").value);
    fd.append("imports", el("imports").value);
    let data = null, error = null;
    try {
      const res = await fetch("/api/claims", { method: "POST", body: fd });
      data = await res.json().catch(() => null);
      if (!res.ok || !data || data.error) {
        error = (data && (data.error + (data.detail ? `\n${data.detail}` : ""))) ||
          `Server error (${res.status})${res.status === 502 || res.status === 504 ? ": the check took too long" : ""}`;
        data = null;
      }
    } catch (e) {
      error = `Network error: ${e.message}`;
    }
    if (token !== st.token) return;          // another ontology was opened meanwhile
    clearInterval(st.timer);
    st = { ...st, data, error, loading: false };
    render();
  }

  // Called by app.js whenever an ontology is drawn.
  function onRender(file) {
    if (st.file && st.file !== file) {       // new ontology: old claims no longer apply
      st = { ...st, file: null, data: null, error: null, loading: false, token: st.token + 1 };
      clearInterval(st.timer);
      button();
    }
    if (wanted() || !el("claimsPane").hidden) {
      open();
      load(file);
    }
  }

  function toggle() {
    if (!el("claimsPane").hidden) return close();
    open();
    load(typeof lastFile !== "undefined" ? lastFile : null);
  }

  return { onRender, toggle, close };
})();
