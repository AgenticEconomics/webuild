#!/usr/bin/env bash
# Build (optional) and import the sandbox image into k3s containerd.
# Kubernetes will look up docker.io/library/webuild-sandbox:local.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
IMAGE="${SANDBOX_IMAGE:-webuild-sandbox:local}"
K3S_BIN="$(command -v k3s || true)"
K3S_BIN="${K3S_BIN:-/usr/local/bin/k3s}"

as_root() {
  if [[ "${EUID}" -eq 0 ]]; then
    "$@"
  else
    sudo "$@"
  fi
}

if [[ ! -x "$K3S_BIN" ]] && ! command -v k3s >/dev/null 2>&1; then
  echo "k3s is not installed" >&2
  exit 1
fi

if [[ "${1:-}" == "--build" ]]; then
  bin="$ROOT/sandbox/webuild-linux-x86_64"
  if [[ ! -f "$bin" ]]; then
    echo "missing $bin" >&2
    echo "build it with: cargo build -p xai-webuild-pager-bin --release" >&2
    echo "then: cp target/release/xai-webuild-pager sandbox/webuild-linux-x86_64" >&2
    exit 1
  fi
  if [[ ! -d "$ROOT/sandbox/agent-skills" ]]; then
    mkdir -p "$ROOT/sandbox/agent-skills"
    cp -a "$ROOT/third_party/agent-skills/." "$ROOT/sandbox/agent-skills/"
  fi
  docker build -t "$IMAGE" "$ROOT/sandbox"
fi

if ! docker image inspect "$IMAGE" >/dev/null 2>&1; then
  echo "docker image $IMAGE not found. Build it first:" >&2
  echo "  deploy/scripts/k3s-import-sandbox.sh --build" >&2
  exit 1
fi

echo "importing $IMAGE into k3s containerd..."
docker save "$IMAGE" | as_root "$K3S_BIN" ctr images import -
echo "imported. Gateway SANDBOX_IMAGE should be docker.io/library/${IMAGE}"
