#!/usr/bin/env bash
# Deploy a git ref of owl2uml to the production server and verify it.
#
#   scripts/deploy.sh [REF]        (default: HEAD)
#
# Needs ssh access to $DEPLOY_HOST with passwordless sudo. Backs up the
# running code, installs Python deps, the ROBOT jar and the compiled
# O2uConvert helper, restarts the service and checks the public site.
set -euo pipefail
REF="${1:-HEAD}"
HOST="${DEPLOY_HOST:-drkoepsell@178.105.7.249}"
APP=/opt/owl2uml
URL="${DEPLOY_URL:-https://owltouml.davidkoepsell.com}"
ROBOT_VERSION="1.9.8"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

echo "==> Packing $(git -C "$ROOT" rev-parse --short "$REF")"
TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT
git -C "$ROOT" archive "$REF" src requirements.txt scripts owl2uml serve examples \
  | gzip > "$TMP/release.tgz"
scp -q "$TMP/release.tgz" "$HOST:/tmp/owl2uml-release.tgz"

echo "==> Installing on $HOST"
ssh -o BatchMode=yes "$HOST" "ROBOT_VERSION=$ROBOT_VERSION APP=$APP bash -s" <<'REMOTE'
set -euo pipefail
sudo -n true
TS=$(date +%Y%m%d-%H%M%S)
sudo tar -czf "/opt/owl2uml-backup-$TS.tgz" -C /opt owl2uml/src owl2uml/requirements.txt
echo "    backup /opt/owl2uml-backup-$TS.tgz"
rm -rf /tmp/owl2uml-release && mkdir /tmp/owl2uml-release
tar -xzf /tmp/owl2uml-release.tgz -C /tmp/owl2uml-release
sudo rsync -a --delete --exclude __pycache__ /tmp/owl2uml-release/src/ "$APP/src/"
sudo rsync -a /tmp/owl2uml-release/requirements.txt /tmp/owl2uml-release/scripts \
  /tmp/owl2uml-release/owl2uml /tmp/owl2uml-release/serve /tmp/owl2uml-release/examples "$APP/"
sudo chown -R www-data:www-data "$APP"
sudo -u www-data -H "$APP/.venv/bin/pip" install -q -r "$APP/requirements.txt"
sudo -u www-data mkdir -p "$APP/.local/robot" "$APP/.local/o2u"
JAR="$APP/.local/robot/robot.jar"
[ -f "$JAR" ] || sudo -u www-data curl -fsSL -o "$JAR" \
  "https://github.com/ontodev/robot/releases/download/v$ROBOT_VERSION/robot.jar"
sudo -u www-data java -m jdk.compiler/com.sun.tools.javac.Main -nowarn -cp "$JAR" \
  -d "$APP/.local/o2u" "$APP/src/owl2uml/java/O2uConvert.java"
sudo systemctl restart owl2uml
sleep 2
systemctl is-active owl2uml
rm -rf /tmp/owl2uml-release /tmp/owl2uml-release.tgz
REMOTE

echo "==> Checking $URL"
code=$(curl -s -o /dev/null -w "%{http_code}" "$URL/")
[ "$code" = 200 ] || { echo "site returned $code" >&2; exit 1; }
out=$(curl -s -F "file=@$ROOT/examples/pizza.ttl" "$URL/api/render")
echo "$out" | python3 -c "import sys,json; d=json.load(sys.stdin); assert not d.get('error'), d['error']; print('    render ok:', d['classes'], 'classes,', d['edges'], 'relations')"
echo "==> Deployed"
