#!/usr/bin/env bash
# Start the local platform stack against the host k3s cluster.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
DEPLOY="$ROOT/deploy"

"$ROOT/deploy/scripts/k3s-prepare.sh"

if ! docker compose version >/dev/null 2>&1; then
  echo "docker compose is required" >&2
  exit 1
fi

docker compose \
  --env-file "$DEPLOY/.env.k3s" \
  -f "$DEPLOY/docker-compose.yml" \
  -f "$DEPLOY/docker-compose.k3s.yml" \
  --profile sandbox \
  up -d --build "$@"

node_ip="$(python3 -c 'import pathlib,re; t=pathlib.Path("'"$DEPLOY"'/.env.k3s").read_text(); print(re.search(r"^K3S_NODE_IP=(.*)$", t, re.M).group(1).strip())')"
echo "Web IDE: http://${node_ip}/"
echo "Sandbox image: deploy/scripts/k3s-import-sandbox.sh --build"
