#!/usr/bin/env bash
# Enterprise installer alias — same as the public GitHub Releases installer.
set -euo pipefail
ROOT_INSTALL="https://raw.githubusercontent.com/AgenticEconomics/webuild/main/scripts/install.sh"
echo "Note: enterprise channel is not separate on this fork; installing from GitHub Releases." >&2
if command -v curl >/dev/null 2>&1; then
  exec bash -c "$(curl -fsSL "$ROOT_INSTALL")" bash "$@"
else
  exec bash -c "$(wget -qO- "$ROOT_INSTALL")" bash "$@"
fi
