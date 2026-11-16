// Version diff in the web app: with an older version chosen, the ontology
// that is opened is compared with it (POST /api/diff) instead of drawn alone.
const O2uDiff = (() => {
  const el = (id) => document.getElementById(id);
  const wanted = () => !!(el("oldFile") && el("oldFile").files[0]);

  async function run(file) {
    const old = el("oldFile").files[0];
    showOverlay("Comparing versions…");
    setStatus(`Comparing ${old.name} → ${file.name}…`);
    const fd = new FormData();
    fd.append("old", old);
    fd.append("new", file);
    fd.append("scope", el("diffScope").value);
    fd.append("imports", el("imports").value);
    fd.append("profile", el("profile").value);
    if (el("reason").checked) fd.append("reason", "auto");
    let res, data;
    try {
      res = await fetch("/api/diff", { method: "POST", body: fd });
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
    lastName = file.name.replace(/\.[^.]+$/, "") + "-diff";
    mountSvg(data.svg);
    resetStretch();
    const s = data.summary;
    const inf = s.inferred_added || s.inferred_removed || s.moved
      ? ` · inferred +${s.inferred_added} −${s.inferred_removed}, ${s.moved} moved` : "";
    setStatus(`${old.name} → ${file.name}: ${s.added} added, ${s.removed} removed, ` +
      `${s.renamed} renamed, ${s.deprecated} deprecated · axioms +${s.axioms_added} ` +
      `−${s.axioms_removed}${inf}${s.unsatisfiable ? ` · ${s.unsatisfiable} unsatisfiable` : ""}` +
      " · click a coloured class or line for old and new side by side",
    !!(s.unsatisfiable || s.inconsistent));
    rendered = true;
  }
  return { wanted, run };
})();
