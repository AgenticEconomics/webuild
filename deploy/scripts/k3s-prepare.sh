#!/usr/bin/env bash
# Prepare a local k3s cluster for WeBuild sandbox pods.
# Writes deploy/secrets/k3s-kubeconfig.yaml, applies the sandbox namespace,
# and creates deploy/.env.k3s (secrets preserved on later runs).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
DEPLOY="$ROOT/deploy"
SECRETS="$DEPLOY/secrets"
ENV_FILE="$DEPLOY/.env.k3s"
HOST_KUBECONFIG="${HOST_KUBECONFIG:-/etc/rancher/k3s/k3s.yaml}"

as_root() {
  if [[ "${EUID}" -eq 0 ]]; then
    "$@"
  else
    sudo "$@"
  fi
}

if ! command -v k3s >/dev/null 2>&1 && [[ ! -x /usr/local/bin/k3s ]]; then
  echo "k3s is not installed. Install it with Traefik disabled so port 80 stays free:" >&2
  echo "  curl -sfL https://get.k3s.io | sh -s - --disable=traefik" >&2
  exit 1
fi

K3S_BIN="$(command -v k3s || true)"
K3S_BIN="${K3S_BIN:-/usr/local/bin/k3s}"

if ! as_root test -r "$HOST_KUBECONFIG"; then
  echo "Cannot read $HOST_KUBECONFIG" >&2
  exit 1
fi

if as_root "$K3S_BIN" kubectl -n kube-system get svc traefik >/dev/null 2>&1; then
  echo "warning: kube-system/traefik is present and may already bind port 80." >&2
  echo "         reinstall k3s with: --disable=traefik" >&2
fi

NODE_IP="$(as_root "$K3S_BIN" kubectl get nodes -o jsonpath='{.items[0].status.addresses[?(@.type=="InternalIP")].address}')"
NODE_IP="${NODE_IP%% *}"
if [[ -z "$NODE_IP" ]]; then
  echo "k3s node has no InternalIP" >&2
  exit 1
fi

mkdir -p "$SECRETS"
tmp="$(mktemp)"
as_root cat "$HOST_KUBECONFIG" >"$tmp"
python3 - "$tmp" "$SECRETS/k3s-kubeconfig.yaml" <<'PY'
import re, sys
src, dest = sys.argv[1], sys.argv[2]
text = open(src, encoding="utf-8").read()
text = re.sub(r"(?m)^[ \t]*certificate-authority-data:.*\n", "", text)
text, n = re.subn(
    r"server:\s*https://\S+",
    "server: https://host.docker.internal:6443",
    text,
    count=1,
)
if n != 1:
    raise SystemExit("kubeconfig has no cluster server URL")
if "insecure-skip-tls-verify" not in text:
    text = text.replace(
        "server: https://host.docker.internal:6443",
        "server: https://host.docker.internal:6443\n    insecure-skip-tls-verify: true",
        1,
    )
open(dest, "w", encoding="utf-8").write(text)
PY
rm -f "$tmp"
chmod 600 "$SECRETS/k3s-kubeconfig.yaml"

as_root "$K3S_BIN" kubectl apply -f "$DEPLOY/k3s/sandbox-namespace.yaml"

if [[ ! -f "$SECRETS/invite_whitelist.json" ]]; then
  cp "$DEPLOY/k3s/invite_whitelist.example.json" "$SECRETS/invite_whitelist.json"
  chmod 600 "$SECRETS/invite_whitelist.json"
  echo "wrote $SECRETS/invite_whitelist.json (user vitacardia / vitacardia)"
fi

python3 - "$ENV_FILE" "$NODE_IP" "$DEPLOY/.env.k3s.example" <<'PY'
import pathlib, re, secrets, sys
path, node_ip, example = sys.argv[1:]
dest = pathlib.Path(path)
if dest.exists():
    text = dest.read_text(encoding="utf-8")
    prev = ""
    m = re.search(r"^K3S_NODE_IP=(.*)$", text, re.M)
    if m:
        prev = m.group(1).strip()

    def set_key(key: str, value: str) -> None:
        global text
        line = f"{key}={value}"
        text2, n = re.subn(rf"^{re.escape(key)}=.*$", line, text, count=1, flags=re.M)
        text = text2 if n else text.rstrip() + "\n" + line + "\n"

    set_key("K3S_NODE_IP", node_ip)
    # Keep a hand-edited relay URL unless it still points at the previous node IP.
    relay = f"ws://{node_ip}/ws/relay"
    hub = f"ws://{node_ip}/ws/hub"
    if prev and prev != node_ip:
        text = text.replace(f"ws://{prev}/ws/relay", relay).replace(f"ws://{prev}/ws/hub", hub)
    if not re.search(r"^RELAY_URL=\S+", text, re.M):
        set_key("RELAY_URL", relay)
    if not re.search(r"^HUB_WS_URL=\S+", text, re.M):
        set_key("HUB_WS_URL", hub)
    dest.write_text(text if text.endswith("\n") else text + "\n", encoding="utf-8")
else:
    db = secrets.token_urlsafe(24)
    jwt = secrets.token_urlsafe(32)
    token = secrets.token_urlsafe(24)
    body = pathlib.Path(example).read_text(encoding="utf-8")
    body = body.replace("K3S_NODE_IP=127.0.0.1", f"K3S_NODE_IP={node_ip}")
    body = body.replace("DB_PASSWORD=change-me", f"DB_PASSWORD={db}")
    body = body.replace("JWT_SECRET=change-me", f"JWT_SECRET={jwt}")
    body = body.replace(
        "RELAY_INTERNAL_TOKEN=change-me-internal-agent-token",
        f"RELAY_INTERNAL_TOKEN={token}",
    )
    body = body.replace("ws://127.0.0.1/ws/relay", f"ws://{node_ip}/ws/relay")
    body = body.replace("ws://127.0.0.1/ws/hub", f"ws://{node_ip}/ws/hub")
    dest.write_text(body, encoding="utf-8")
    print(f"wrote {dest} (DB_PASSWORD and JWT_SECRET generated)")
dest.chmod(0o600)
print(f"k3s node IP: {node_ip}")
print(f"kubeconfig: {pathlib.Path(path).parent / 'secrets' / 'k3s-kubeconfig.yaml'}")
PY

echo "namespace vitacardia applied"
echo "next: deploy/scripts/k3s-import-sandbox.sh && deploy/scripts/k3s-up.sh"
