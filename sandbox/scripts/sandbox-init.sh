#!/bin/bash
set -euo pipefail

# ── Sandbox Initialization Script ──
# Runs as the sandbox user before starting the webuild agent.

WORKSPACE="/workspace"
REPO_URL="${SANDBOX_REPO_URL:-}"
REPO_BRANCH="${SANDBOX_REPO_BRANCH:-main}"
SETUP_SCRIPT="${SANDBOX_SETUP_SCRIPT:-}"

echo "[sandbox-init] Starting initialization..."

# Clone repository if specified
if [ -n "$REPO_URL" ]; then
    echo "[sandbox-init] Cloning $REPO_URL (branch: $REPO_BRANCH)..."
    git clone --depth 1 --branch "$REPO_BRANCH" "$REPO_URL" "$WORKSPACE" 2>/dev/null || \
        git clone --depth 1 "$REPO_URL" "$WORKSPACE"
    cd "$WORKSPACE"
fi

# Run custom setup script if provided
if [ -n "$SETUP_SCRIPT" ] && [ -f "$SETUP_SCRIPT" ]; then
    echo "[sandbox-init] Running setup script..."
    bash "$SETUP_SCRIPT"
fi

# Configure git safe directory
git config --global --add safe.directory "$WORKSPACE" 2>/dev/null || true

# Set up webuild config directory
mkdir -p "$HOME/.webuild"

# Pass through API key if provided
if [ -n "${DASHSCOPE_API_KEY:-}" ]; then
    echo "$DASHSCOPE_API_KEY" > "$HOME/.webuild/api_key"
fi

echo "[sandbox-init] Initialization complete. Starting webuild agent..."

# Start the webuild agent in headless mode
exec webuild agent stdio --headless "$@"
