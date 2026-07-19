#!/usr/bin/env bash
#
# WeBuild installer (GitHub Releases)
#
# Install the latest (or a pinned) prebuilt binary for Linux / macOS:
#
#   curl -fsSL https://raw.githubusercontent.com/AgenticEconomics/webuild/main/scripts/install.sh | bash
#   curl -fsSL .../install.sh | bash -s -- v0.2.102
#   WEBUILD_REPO=you/webuild bash <(curl -fsSL .../install.sh)
#
# Env:
#   WEBUILD_REPO      owner/name (default: AgenticEconomics/webuild)
#   WEBUILD_BIN_DIR   install dir (default: ~/.webuild/bin)
#   WEBUILD_VERSION   pin a release tag (e.g. v0.2.102); same as first arg
#   GITHUB_TOKEN      optional; higher API rate limit / private releases
#
set -euo pipefail

REPO="${WEBUILD_REPO:-AgenticEconomics/webuild}"
BIN_DIR="${WEBUILD_BIN_DIR:-$HOME/.webuild/bin}"
VERSION="${WEBUILD_VERSION:-${1:-}}"

if ! command -v curl >/dev/null 2>&1; then
  echo "error: curl is required" >&2
  exit 1
fi

case "$(uname -s)" in
  Linux)  os="linux" ;;
  Darwin) os="macos" ;;
  *)
    echo "error: unsupported OS $(uname -s) (Linux and macOS only in this installer)" >&2
    exit 1
    ;;
esac

case "$(uname -m)" in
  x86_64|amd64)   arch="x86_64" ;;
  arm64|aarch64)  arch="aarch64" ;;
  *)
    echo "error: unsupported architecture $(uname -m)" >&2
    exit 1
    ;;
esac

# Asset names published by .github/workflows/release.yml
ASSET="webuild-${os}-${arch}"
API="https://api.github.com/repos/${REPO}"
auth_hdr=()
if [ -n "${GITHUB_TOKEN:-}" ]; then
  auth_hdr=(-H "Authorization: Bearer ${GITHUB_TOKEN}")
fi

echo "WeBuild installer" >&2
echo "  repo:     ${REPO}" >&2
echo "  platform: ${os}-${arch}" >&2

if [ -z "$VERSION" ]; then
  echo "  resolving latest release..." >&2
  meta=$(curl -fsSL "${auth_hdr[@]}" \
    -H "Accept: application/vnd.github+json" \
    "${API}/releases/latest")
  VERSION=$(printf '%s' "$meta" | sed -n 's/.*"tag_name"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' | head -1)
  if [ -z "$VERSION" ]; then
    echo "error: could not resolve latest release for ${REPO}" >&2
    echo "       create a GitHub Release first (see docs in README)." >&2
    exit 1
  fi
else
  # Accept 0.2.102 or v0.2.102
  case "$VERSION" in
    v*) ;;
    *) VERSION="v${VERSION}" ;;
  esac
  echo "  version:  ${VERSION}" >&2
  meta=$(curl -fsSL "${auth_hdr[@]}" \
    -H "Accept: application/vnd.github+json" \
    "${API}/releases/tags/${VERSION}")
fi

echo "  release:  ${VERSION}" >&2

# Prefer browser_download_url for the matching asset name (exact or .tar.gz)
download_url=$(printf '%s' "$meta" | tr ',' '\n' | sed -n "s/.*\"browser_download_url\"[[:space:]]*:[[:space:]]*\"\\([^\"]*${ASSET}[^\"]*\\)\".*/\\1/p" | head -1)
if [ -z "$download_url" ]; then
  # Fallback: construct conventional release asset URL
  download_url="https://github.com/${REPO}/releases/download/${VERSION}/${ASSET}"
fi

tmpdir=$(mktemp -d)
trap 'rm -rf "$tmpdir"' EXIT
archive="$tmpdir/asset"
binary="$tmpdir/webuild"

echo "  download: ${download_url}" >&2
if ! curl -fsSL -L "${auth_hdr[@]}" -o "$archive" "$download_url"; then
  echo "error: download failed" >&2
  echo "       expected asset name like: ${ASSET} or ${ASSET}.tar.gz" >&2
  exit 1
fi

# Unpack if compressed; otherwise treat as raw binary
case "$download_url" in
  *.tar.gz|*.tgz)
    tar -xzf "$archive" -C "$tmpdir"
    # Find first executable named webuild or xai-webuild-pager
    if [ -f "$tmpdir/webuild" ]; then
      :
    elif [ -f "$tmpdir/xai-webuild-pager" ]; then
      mv "$tmpdir/xai-webuild-pager" "$tmpdir/webuild"
    else
      found=$(find "$tmpdir" -type f \( -name webuild -o -name xai-webuild-pager \) | head -1)
      if [ -n "$found" ]; then
        mv "$found" "$tmpdir/webuild"
      else
        echo "error: archive did not contain webuild binary" >&2
        exit 1
      fi
    fi
    ;;
  *.zip)
    if command -v unzip >/dev/null 2>&1; then
      unzip -q "$archive" -d "$tmpdir"
    else
      echo "error: unzip required for .zip assets" >&2
      exit 1
    fi
    found=$(find "$tmpdir" -type f \( -name webuild -o -name xai-webuild-pager -o -name 'webuild.exe' \) | head -1)
    [ -n "$found" ] || { echo "error: zip missing webuild binary" >&2; exit 1; }
    mv "$found" "$tmpdir/webuild"
    ;;
  *)
    mv "$archive" "$binary"
    ;;
esac

if [ ! -f "$binary" ]; then
  # raw asset path already moved above for non-archive; ensure name
  if [ -f "$tmpdir/webuild" ]; then
    binary="$tmpdir/webuild"
  else
    echo "error: binary missing after download" >&2
    exit 1
  fi
fi

chmod +x "$binary"
if ! "$binary" --version </dev/null >/dev/null 2>&1; then
  # Some builds print to stderr only; still accept if exit 0
  if ! "$binary" --version </dev/null >/dev/null; then
    echo "error: downloaded binary failed --version; refusing to install" >&2
    exit 1
  fi
fi

mkdir -p "$BIN_DIR"
install -m 755 "$binary" "$BIN_DIR/webuild"
# Convenience alias used by some docs/scripts
ln -sfn webuild "$BIN_DIR/agent" 2>/dev/null || true

ver=$("$BIN_DIR/webuild" --version 2>/dev/null | head -1 || true)
echo >&2
echo "Installed ${ver:-webuild} → $BIN_DIR/webuild" >&2
echo >&2

# PATH hint
case ":$PATH:" in
  *":$BIN_DIR:"*) ;;
  *)
    echo "Add to your shell profile (once):" >&2
    echo "  export PATH=\"$BIN_DIR:\$PATH\"" >&2
    # shellcheck disable=SC2016
    if [ -n "${SHELL:-}" ] && [ "$(basename "$SHELL")" = "zsh" ]; then
      echo "  # e.g. echo 'export PATH=\"$BIN_DIR:\$PATH\"' >> ~/.zshrc" >&2
    else
      echo "  # e.g. echo 'export PATH=\"$BIN_DIR:\$PATH\"' >> ~/.bashrc" >&2
    fi
    echo >&2
    echo "Or run now:" >&2
    echo "  export PATH=\"$BIN_DIR:\$PATH\"" >&2
    echo "  webuild --version" >&2
    ;;
esac

echo >&2
echo "Quick start:" >&2
echo "  export DASHSCOPE_API_KEY=...   # default model qwen3.7-max" >&2
echo "  webuild                        # interactive TUI" >&2
echo "  webuild -p \"hello\" --always-approve" >&2
echo >&2
