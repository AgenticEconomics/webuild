#!/usr/bin/env bash
# Provision a GitLab Runner for webuild CI.
#
# Prerequisites:
#   - gitlab-runner installed: curl -L https://packages.gitlab.com/install/repositories/runner/gitlab-runner/script.deb.sh | sudo bash && sudo apt install gitlab-runner
#   - Rust toolchain installed under /root/.cargo (via rustup)
#   - protoc >= 3.15 on PATH (apt install protobuf-compiler)
#   - ripgrep installed (apt install ripgrep)
#
# Usage:
#   1. Replace REPLACE_WITH_RUNNER_TOKEN in config.toml with the actual runner registration token
#   2. Copy config.toml to /etc/gitlab-runner/config.toml
#   3. Ensure /root/.cargo and /root/.rustup are readable by gitlab-runner user:
#        chmod o+rx /root
#        chmod -R o+rX /root/.cargo /root/.rustup
#   4. Restart: systemctl restart gitlab-runner
#
# CI Variables (configure in GitLab → Settings → CI/CD → Variables):
#   GITLAB_RELEASE_TOKEN  — PAT with `api` scope for publishing releases (masked, not protected)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

if [ "$(id -u)" -ne 0 ]; then
  echo "ERROR: run as root" >&2
  exit 1
fi

cp "$SCRIPT_DIR/config.toml" /etc/gitlab-runner/config.toml
systemctl enable --now gitlab-runner
systemctl restart gitlab-runner
echo "Runner configured. Verify at: https://git.jarvikheart.cn/admin/runners"
