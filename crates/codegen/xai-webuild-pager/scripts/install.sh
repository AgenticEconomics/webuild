#!/usr/bin/env bash
# WeBuild installer — GitHub Releases (AgenticEconomics/webuild)
#
# Prefer the canonical script at repo root (also available via curl):
#   curl -fsSL https://raw.githubusercontent.com/AgenticEconomics/webuild/main/scripts/install.sh | bash
#
# This path is kept for compatibility with older docs that pointed at
# crates/codegen/xai-webuild-pager/scripts/install.sh.
set -euo pipefail
ROOT_INSTALL="https://raw.githubusercontent.com/AgenticEconomics/webuild/main/scripts/install.sh"
if command -v curl >/dev/null 2>&1; then
  exec bash -c "$(curl -fsSL "$ROOT_INSTALL")" bash "$@"
elif command -v wget >/dev/null 2>&1; then
  exec bash -c "$(wget -qO- "$ROOT_INSTALL")" bash "$@"
else
  echo "error: curl or wget required" >&2
  exit 1
fi
