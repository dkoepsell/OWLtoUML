// Claims panel: the ontology's claims as English sentences (POST /api/claims,
// `owl2uml claims`). Opened from the View menu ("Claims") or the toolbar's
// Claims button; it covers the diagram until closed.
const O2uClaims = (() => {
  const el = (id) => document.getElementById(id);
  const wanted = () => el("view").value === "claims";
  const STATUS = {
    ASSERTED: "Stated in the ontology",
    ENTAILED: "Follows from what is stated",
    REFUTED: "Ruled out by what is stated",
    POSSIBLE: "Allowed, but not required",
    UNDETERMINED: "Left open: the ontology does not say",
  };
  const ORDER = ["ENTAILED", "REFUTED", "POSSIBLE", "UNDETERMINED", "ASSERTED"];
  let cache = { file: null, data: null };

  function esc(s) {
    return String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  }

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
    const iris = (r.iris || []).map((i) => `<code>${esc(i)}</code>`).join(" ");
    return `<li class="claim claim--${r.status.toLowerCase()}"><details>
      <summary>${esc(r.text)}${r.defn_linked ? ' <span class="claim-tag" title="Kept because it follows from a definition">definition</span>' : ""}</summary>
      <div class="claim-more">
        <div><b>Manchester:</b> <code>${esc(r.manchester)}</code></div>
        ${just ? `<div><b>Because:</b><ul>${just}</ul></div>` : ""}
        ${r.justification_skipped ? "<div class=\"hint\">Justification not computed (limit reached).</div>" : ""}
        <div class="claim-iris">${iris}</div>
      </div></details></li>`;
  }

  function show(data, file) {
    const pane = el("claimsPane");
    const recs = data.claims || [];
    const rep = data.report || {};
    const sig = rep.signature || {};
    const groups = ORDER.map((s) => [s, recs.filter((r) => r.status === s)]).filter(([, g]) => g.length);
    const secs = rep.seconds_total != null ? ` in ${rep.seconds_total}s` : "";
    pane.innerHTML = `
      <div class="claims-head">
        <div>
          <h2>Claims in ${esc(file.name)}</h2>
          <p class="hint">${recs.length} claims about ${sig.native ?? "?"} of the ontology's own classes,
          checked by ${Object.keys(rep.reasoners || {}).join(" and ") || "the reasoners"}${secs}.
          Click a claim for its Manchester form and the axioms that justify it.</p>
        </div>
        <div class="claims-actions">
          <button data-dl="txt">Download .txt</button>
          <button data-dl="tsv">.tsv</button>
          <button data-dl="jsonl">.jsonl</button>
          <button id="claimsClose" class="primary">Show diagram</button>
        </div>
      </div>
      ${(data.warnings || []).map((w) => `<p class="claims-warn">${esc(w)}</p>`).join("")}
      ${groups.length ? "" : "<p>No claims found.</p>"}
      ${groups.map(([s, g]) => `<section class="claims-group">
        <h3 class="claim--${s.toLowerCase()}">${STATUS[s]} <span class="claims-n">${s.toLowerCase()} · ${g.length}</span></h3>
        <ul>${g.map(item).join("")}</ul></section>`).join("")}`;
    const stem = file.name.replace(/\.[^.]+$/, "");
    pane.querySelectorAll("[data-dl]").forEach((b) => b.addEventListener("click", () => {
      const k = b.dataset.dl;
      if (k === "txt") save(data.txt, `${stem}-claims.txt`, "text/plain");
      if (k === "tsv") save(tsv(recs), `${stem}-claims.tsv`, "text/tab-separated-values");
      if (k === "jsonl") save(data.jsonl, `${stem}-claims.jsonl`, "application/x-ndjson");
    }));
    el("claimsClose").addEventListener("click", close);
    pane.hidden = false;
    pane.scrollTop = 0;
    el("dropzone").hidden = true;
    el("toolbar").hidden = false;
    el("claimsBtn").classList.add("active");
    const c = Object.entries(rep.records || {}).map(([k, n]) => `${n} ${k.toLowerCase()}`).join(", ");
    setStatus(`${file.name}: ${recs.length} claims (${c})`);
  }

  async function run(file) {
    if (!file) return;
    lastFile = file;
    if (cache.file === file && cache.data) return show(cache.data, file);
    showOverlay("Running HermiT and Pellet over the ontology… (can take a minute)");
    setStatus(`Working out the claims in ${file.name}…`);
    const fd = new FormData();
    fd.append("file", file);
    fd.append("format", el("format").value);
    fd.append("imports", el("imports").value);
    let res, data;
    try {
      res = await fetch("/api/claims", { method: "POST", body: fd });
      data = await res.json();
    } catch (e) {
      hideOverlay();
      setStatus(`Network error: ${e.message}`, true);
      return;
    }
    hideOverlay();
    if (!res.ok || data.error) {
      setStatus(data.error || `Server error (${res.status})`, true);
      if (data.detail) alert(data.detail);
      return;
    }
    cache = { file, data };
    show(data, file);
  }

  function close() {
    el("claimsPane").hidden = true;
    el("claimsBtn").classList.remove("active");
    if (wanted()) el("view").value = "classes";
    if (!svgEl && lastFile) renderFile(lastFile);   // claims came first: draw the diagram now
    else if (!svgEl) el("dropzone").hidden = false;
  }

  function toggle() {
    if (!el("claimsPane").hidden) return close();
    if (lastFile) run(lastFile);
  }

  return { wanted, run, toggle, close };
})();
