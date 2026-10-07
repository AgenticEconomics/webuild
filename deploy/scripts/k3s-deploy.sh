#!/usr/bin/env bash
# Deploy the WeBuild platform into the local k3s namespace "vitacardia".
# Host ports 80/443 stay with the VitaCardia site. The edge is NodePort 30080.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
NS=vitacardia
KUBECTL=(k3s kubectl)

as_root() {
  if [[ "${EUID}" -eq 0 ]]; then
    "$@"
  else
    sudo "$@"
  fi
}

if ! command -v k3s >/dev/null 2>&1 && [[ ! -x /usr/local/bin/k3s ]]; then
  echo "k3s is not installed" >&2
  exit 1
fi

need_image() {
  local ref="$1"
  if ! as_root k3s ctr images ls | awk '{print $1}' | grep -qx "$ref"; then
    echo "missing k3s image: $ref" >&2
    if [[ "$ref" == *"sandbox"* ]]; then
      echo "build and import with: deploy/scripts/k3s-import-sandbox.sh --build" >&2
    else
      echo "build and import with: deploy/scripts/k3s-build-images.sh" >&2
    fi
    exit 1
  fi
}

need_image "docker.io/library/webuild-auth:local"
need_image "docker.io/library/webuild-relay:local"
need_image "docker.io/library/webuild-hub:local"
need_image "docker.io/library/webuild-gateway:local"
need_image "docker.io/library/webuild-web-ide:local"
need_image "docker.io/library/webuild-sandbox:local"
need_image "docker.io/library/postgres:16-alpine"
need_image "docker.io/library/nginx:alpine"

as_root "${KUBECTL[@]}" apply -f "$ROOT/deploy/k3s/sandbox-namespace.yaml"

if ! as_root "${KUBECTL[@]}" -n "$NS" get secret webuild-env >/dev/null 2>&1; then
  db="$(python3 -c 'import secrets; print(secrets.token_urlsafe(24))')"
  jwt="$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')"
  token="$(python3 -c 'import secrets; print(secrets.token_urlsafe(24))')"
  dash="${DASHSCOPE_API_KEY:-}"
  as_root "${KUBECTL[@]}" -n "$NS" create secret generic webuild-env \
    --from-literal=DB_PASSWORD="$db" \
    --from-literal=DATABASE_URL="postgresql://webuild:${db}@postgres:5432/webuild" \
    --from-literal=JWT_SECRET="$jwt" \
    --from-literal=RELAY_INTERNAL_TOKEN="$token" \
    --from-literal=DASHSCOPE_API_KEY="$dash"
  echo "created secret webuild-env"
fi

as_root "${KUBECTL[@]}" -n "$NS" create secret generic invite-whitelist \
  --from-file=invite_whitelist.json="$ROOT/deploy/k3s/invite_whitelist.example.json" \
  --dry-run=client -o yaml | as_root "${KUBECTL[@]}" apply -f -

as_root "${KUBECTL[@]}" -n "$NS" create configmap webuild-nginx \
  --from-file=nginx.conf="$ROOT/deploy/nginx/nginx.conf" \
  --from-file=webuild.conf="$ROOT/deploy/k3s/webuild.http.conf" \
  --dry-run=client -o yaml | as_root "${KUBECTL[@]}" apply -f -

as_root "${KUBECTL[@]}" apply -f "$ROOT/deploy/k3s/platform.yaml"

for dep in postgres auth relay hub gateway web-ide nginx; do
  as_root "${KUBECTL[@]}" -n "$NS" rollout status "deploy/${dep}" --timeout=180s
done

node_ip="$(as_root "${KUBECTL[@]}" get nodes -o jsonpath='{.items[0].status.addresses[?(@.type=="InternalIP")].address}')"
node_ip="${node_ip%% *}"
echo "namespace: ${NS}"
echo "Web IDE: http://${node_ip}:30080/"
echo "login: vitacardia / vitacardia"
