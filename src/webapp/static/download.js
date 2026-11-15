"use strict";
// Downloading the diagram. Shares app.js's globals (classic scripts).

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
  out.querySelectorAll("style.oi-style, path.oi-hit, g.o2u-draft").forEach((n) => n.remove());
  out.classList.remove("o2u-editing");
  out.querySelectorAll(".o2u-deleted, .o2u-moved, .o2u-sel")
    .forEach((n) => n.classList.remove("o2u-deleted", "o2u-moved", "o2u-sel"));
  // Keep the inferred-view stylesheet even if svg-pan-zoom left it outside the
  // viewport group we copied from.
  if (!out.querySelector("style.o2u-style")) {
    const st = svgEl.querySelector("style.o2u-style");
    if (st) out.insertBefore(doc.importNode(st, true), out.firstChild);
  }
  // Keep the embedded OWL source, so the file's source panel works offline.
  if (!out.querySelector("[id='o2u-source']")) {
    const js = svgEl.querySelector("[id='o2u-source']");
    if (js) out.insertBefore(doc.importNode(js, true), out.firstChild);
  }
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
