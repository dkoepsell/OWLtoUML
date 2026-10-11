#!/usr/bin/env bash
# Reproducible environment setup for owl2uml:
#   - Python venv + dependencies (rdflib, flask)
#   - Graphviz `dot` installed into a project-local prefix (no root needed)
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

echo "==> Python venv + deps"
python3 -m venv .venv
. .venv/bin/activate
pip install --quiet --upgrade pip
pip install --quiet -r requirements.txt

PREFIX="$ROOT/.local"
DOT="$PREFIX/usr/bin/dot"

if [ -x "$DOT" ]; then
  echo "==> Graphviz already present at $DOT"
else
  echo "==> Installing Graphviz locally (no sudo)"
  TMP="$(mktemp -d)"
  trap 'rm -rf "$TMP"' EXIT
  # libgts provides libgts-0.7.so.5, required by the neato/sfdp/fdp layout
  # plugins (the scalable fallback used for large ontologies). The package was
  # renamed *t64 in the Ubuntu time64 transition, so try both names.
  ( cd "$TMP" && apt-get download \
      graphviz libgvc6 libcgraph6 libcdt5 libpathplan4 libgd3 libxpm4 \
      && { apt-get download libgts-0.7-5t64 || apt-get download libgts-0.7-5; } )
  mkdir -p "$PREFIX"
  for d in "$TMP"/*.deb; do dpkg-deb -x "$d" "$PREFIX"; done
fi

echo "==> Configuring Graphviz plugins"
LIBDIR="$PREFIX/usr/lib/x86_64-linux-gnu"
export LD_LIBRARY_PATH="$LIBDIR:$LIBDIR/graphviz:${LD_LIBRARY_PATH:-}"
export GVBINDIR="$LIBDIR/graphviz"
"$DOT" -c || true   # writes plugin config registry (config6a)
"$DOT" -V

echo "==> Done. Run the web UI with:  ./serve"
