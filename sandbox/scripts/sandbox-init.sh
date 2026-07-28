#!/bin/bash
set -euo pipefail

# ── Sandbox Initialization Script (Phase V) ──
# Prepares /workspace and starts the full WeBuild headless agent (default),
# or the legacy Python chat-only agent when SANDBOX_AGENT=python.

WORKSPACE="${WEBUILD_WORKSPACE:-/workspace}"
REPO_URL="${SANDBOX_REPO_URL:-}"
REPO_BRANCH="${SANDBOX_REPO_BRANCH:-main}"
SETUP_SCRIPT="${SANDBOX_SETUP_SCRIPT:-}"
SANDBOX_AGENT="${SANDBOX_AGENT:-webuild}"
SESSION_ID="${SESSION_ID:-${SANDBOX_ID:-}}"
RELAY_URL="${RELAY_URL:-wss://webuild.datoms.cn/ws/relay}"
RELAY_TOKEN="${RELAY_TOKEN:-${RELAY_INTERNAL_TOKEN:-}}"
MODEL="${MODEL:-qwen-max}"

echo "[sandbox-init] Starting initialization (agent=${SANDBOX_AGENT})..."

mkdir -p "$WORKSPACE" "$HOME/.webuild"
cd "$WORKSPACE"

# Clone repository if specified and workspace is empty
if [ -n "$REPO_URL" ] && [ -z "$(ls -A "$WORKSPACE" 2>/dev/null || true)" ]; then
    echo "[sandbox-init] Cloning $REPO_URL (branch: $REPO_BRANCH)..."
    git clone --depth 1 --branch "$REPO_BRANCH" "$REPO_URL" "$WORKSPACE" 2>/dev/null || \
        git clone --depth 1 "$REPO_URL" "$WORKSPACE"
fi

if [ -n "$SETUP_SCRIPT" ] && [ -f "$SETUP_SCRIPT" ]; then
    echo "[sandbox-init] Running setup script..."
    bash "$SETUP_SCRIPT"
fi

git config --global --add safe.directory "$WORKSPACE" 2>/dev/null || true

# Persist API key for webuild BYOK paths
if [ -n "${DASHSCOPE_API_KEY:-}" ]; then
    printf '%s\n' "$DASHSCOPE_API_KEY" > "$HOME/.webuild/api_key"
    chmod 600 "$HOME/.webuild/api_key"
fi

# Minimal CLI config: YOLO in unattended sandbox; mark installer source
if [ ! -f "$HOME/.webuild/config.toml" ]; then
    cat > "$HOME/.webuild/config.toml" <<'EOF'
[cli]
auto_update = false

[sandbox]
profile = "off"
auto_allow_bash = true
EOF
fi

export WEBUILD_SANDBOX_MODE="${WEBUILD_SANDBOX_MODE:-1}"
export WEBUILD_YOLO="${WEBUILD_YOLO:-1}"
export WEBUILD_WORKSPACE="$WORKSPACE"
export MODEL

if [ "$SANDBOX_AGENT" = "python" ] || [ "$SANDBOX_AGENT" = "legacy-python" ]; then
    echo "[sandbox-init] Starting legacy Python sandbox agent..."
    exec python3 /opt/sandbox/sandbox_agent.py
fi

if ! command -v webuild >/dev/null 2>&1; then
    echo "[sandbox-init] error: webuild binary not found; falling back to Python agent" >&2
    exec python3 /opt/sandbox/sandbox_agent.py
fi

if [ -z "$SESSION_ID" ]; then
    echo "[sandbox-init] error: SESSION_ID or SANDBOX_ID is required" >&2
    exit 1
fi

if [ -z "$RELAY_TOKEN" ]; then
    echo "[sandbox-init] warning: RELAY_TOKEN empty; relay auth will fail" >&2
fi

# Build WeBuild Relay URL: session_id + role=agent + internal token
# (matches services/relay and legacy Python agent)
sep='?'
case "$RELAY_URL" in
    *\?*) sep='&' ;;
esac
WS_URL="${RELAY_URL}${sep}session_id=${SESSION_ID}&role=agent&token=${RELAY_TOKEN}&agent_kind=sandbox"
if [ -n "${WEBUILD_USER_ID:-}" ]; then
    WS_URL="${WS_URL}&user_id=${WEBUILD_USER_ID}"
fi

echo "[sandbox-init] Starting webuild agent headless..."
echo "[sandbox-init]   session=${SESSION_ID}"
echo "[sandbox-init]   model=${MODEL}"
echo "[sandbox-init]   relay=${RELAY_URL}"
echo "[sandbox-init]   version=$(webuild --version 2>/dev/null | head -1 || echo unknown)"

cd "$WORKSPACE"
# IMPORTANT: --webuild-ws-url must follow `headless` so HeadlessArgs pick it up.
# (`webuild agent --webuild-ws-url … headless` binds the flag on AgentArgs and
#  the Headless subcommand receives an empty URL — Relay then gets no session_id.)
exec webuild agent --yolo -m "$MODEL" headless --webuild-ws-url "$WS_URL" "$@"
