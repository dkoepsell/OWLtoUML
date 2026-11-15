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

ROBOT_VERSION="1.9.8"
ROBOT_JAR="$PREFIX/robot/robot.jar"
if [ -f "$ROBOT_JAR" ]; then
  echo "==> ROBOT already present at $ROBOT_JAR"
elif command -v java >/dev/null; then
  echo "==> Downloading ROBOT $ROBOT_VERSION (OWL/XML, Manchester, Functional, OBO input; explanations)"
  mkdir -p "$(dirname "$ROBOT_JAR")"
  curl -fsSL -o "$ROBOT_JAR.part" \
    "https://github.com/ontodev/robot/releases/download/v$ROBOT_VERSION/robot.jar" \
    && mv "$ROBOT_JAR.part" "$ROBOT_JAR"
else
  echo "==> No Java runtime: skipping ROBOT (rdflib loader will be used)"
fi

if [ -f "$ROBOT_JAR" ]; then
  echo "==> Compiling the O2uConvert loader helper"
  mkdir -p "$PREFIX/o2u"
  java -m jdk.compiler/com.sun.tools.javac.Main -nowarn -cp "$ROBOT_JAR" \
    -d "$PREFIX/o2u" src/owl2uml/java/O2uConvert.java \
    || echo "    (no JDK compiler: the helper will run from source, a little slower)"
fi

echo "==> Done. Run the web UI with:  ./serve"
