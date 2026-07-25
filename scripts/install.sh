#!/usr/bin/env bash
#
# WeBuild installer (GitLab Releases)
#
# Install the latest (or a pinned) prebuilt binary for Linux / macOS:
#
#   curl -fsSL https://git.jarvikheart.cn/jerryzhang/webuild/-/raw/main/scripts/install.sh | bash
#   curl -fsSL .../install.sh | bash -s -- v0.2.102
#   WEBUILD_REPO=group/project bash <(curl -fsSL .../install.sh)
#
# Env:
#   GITLAB_HOST     GitLab instance URL (default: https://git.jarvikheart.cn)
#   WEBUILD_REPO    namespace/project (default: jerryzhang/webuild)
#   WEBUILD_BIN_DIR install dir (default: ~/.webuild/bin)
#   WEBUILD_VERSION pin a release tag (e.g. v0.2.102); same as first arg
#   GITLAB_TOKEN    optional; for private projects
#
set -euo pipefail

GITLAB_HOST="${GITLAB_HOST:-https://git.jarvikheart.cn}"
REPO="${WEBUILD_REPO:-jerryzhang/webuild}"
BIN_DIR="${WEBUILD_BIN_DIR:-$HOME/.webuild/bin}"
VERSION="${WEBUILD_VERSION:-${1:-}}"

# URL-encode the project path for GitLab API (e.g. jerryzhang/webuild → jerryzhang%2Fwebuild)
PROJECT_ID="${REPO//\//%2F}"

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

# Prebuilt releases do not include macOS Intel binaries (CI matrix ships
# Apple Silicon only). Fail early with a clear next step.
if [ "$os" = "macos" ] && [ "$arch" = "x86_64" ]; then
  echo "error: no prebuilt binary for macOS Intel (x86_64)." >&2
  echo "       Releases ship webuild-macos-aarch64 (Apple Silicon) only." >&2
  echo "       On Intel Macs, build from source:" >&2
  echo "         git clone ${GITLAB_HOST}/${REPO}.git && cd webuild" >&2
  echo "         cargo build -p xai-webuild-pager-bin --release" >&2
  exit 1
fi

# Asset names published by .gitlab-ci.yml
ASSET="webuild-${os}-${arch}"
API="${GITLAB_HOST}/api/v4/projects/${PROJECT_ID}"
auth_hdr=()
if [ -n "${GITLAB_TOKEN:-}" ]; then
  auth_hdr=(-H "PRIVATE-TOKEN: ${GITLAB_TOKEN}")
fi

echo "WeBuild installer" >&2
echo "  gitlab:   ${GITLAB_HOST}" >&2
echo "  repo:     ${REPO}" >&2
echo "  platform: ${os}-${arch}" >&2

if [ -z "$VERSION" ]; then
  echo "  resolving latest release..." >&2
  meta=$(curl -fsSL "${auth_hdr[@]}" "${API}/releases/permalink/latest")
  VERSION=$(printf '%s' "$meta" | sed -n 's/.*"tag_name"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' | head -1)
  if [ -z "$VERSION" ]; then
    echo "error: could not resolve latest release for ${REPO}" >&2
    echo "       create a GitLab Release first (see docs in README)." >&2
    exit 1
  fi
else
  # Accept 0.2.102 or v0.2.102
  case "$VERSION" in
    v*) ;;
    *) VERSION="v${VERSION}" ;;
  esac
  echo "  version:  ${VERSION}" >&2
  meta=$(curl -fsSL "${auth_hdr[@]}" "${API}/releases/${VERSION}")
fi

echo "  release:  ${VERSION}" >&2

# Find download URL by matching asset link name in release metadata.
# GitLab release assets are stored as links with name + url.
download_url=$(printf '%s' "$meta" | tr ',' '\n' | \
  sed -n "s/.*\"name\"[[:space:]]*:[[:space:]]*\"\([^\"]*${ASSET}[^\"]*\)\".*/\1/p" | head -1)

if [ -n "$download_url" ]; then
  # We matched by name; now extract the corresponding url
  # Parse assets.links array to find the matching entry
  download_url=""
  # Use a more robust parse: extract each link object
  link_block=$(printf '%s' "$meta" | tr -d '\n' | \
    sed 's/.*"links"[[:space:]]*:[[:space:]]*\[//;s/\].*//' | \
    sed 's/},{/}\n{/g')
  while IFS= read -r link; do
    link_name=$(printf '%s' "$link" | sed -n 's/.*"name"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p')
    link_url=$(printf '%s' "$link" | sed -n 's/.*"url"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p')
    case "$link_name" in
      *"$ASSET"*)
        download_url="$link_url"
        break
        ;;
    esac
  done <<< "$link_block"
fi

if [ -z "$download_url" ]; then
  # Fallback: construct conventional release asset URL
  download_url="${GITLAB_HOST}/${REPO}/-/releases/${VERSION}/downloads/${ASSET}"
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

# Persist installer source so `webuild update` hints at GitLab reinstall.
CONFIG_FILE="$HOME/.webuild/config.toml"
mkdir -p "$HOME/.webuild"
if [ ! -f "$CONFIG_FILE" ]; then
  printf '[cli]\ninstaller = "gitlab-release"\nauto_update = false\n' > "$CONFIG_FILE"
elif ! grep -q '^\[cli\]' "$CONFIG_FILE" 2>/dev/null; then
  printf '\n[cli]\ninstaller = "gitlab-release"\nauto_update = false\n' >> "$CONFIG_FILE"
elif ! grep -q 'installer\s*=' "$CONFIG_FILE" 2>/dev/null; then
  # Insert installer under existing [cli] without clobbering user settings.
  tmp="$CONFIG_FILE.tmp.$$"
  awk '
    /^\[cli\][[:space:]]*(#.*)?$/ { print; print "installer = \"gitlab-release\""; print "auto_update = false"; next }
    { print }
  ' "$CONFIG_FILE" > "$tmp" && mv "$tmp" "$CONFIG_FILE"
fi

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
