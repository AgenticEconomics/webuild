#!/usr/bin/env python3
"""Rename product identity grok → webuild across the webuild fork.

Preserves:
  - API model IDs (grok-build, grok-3, grok-4*, …) — hyphenated model slugs
  - *.grok.com / api.x.ai hostnames
  - LICENSE / THIRD-PARTY-NOTICES legal text (skipped files)
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

ROOT = Path("/home/jerry.zhang/webuild")

SKIP_DIR_NAMES = {
    ".git",
    "target",
    "node_modules",
    "__pycache__",
}
SKIP_FILES = {
    "THIRD-PARTY-NOTICES",
    "LICENSE",
    "grok-build-main.zip",
    "rename_grok_to_webuild.py",
}
SKIP_SUFFIXES = {
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".webp",
    ".ico",
    ".woff",
    ".woff2",
    ".ttf",
    ".otf",
    ".zip",
    ".gz",
    ".tar",
    ".bin",
    ".exe",
    ".so",
    ".dylib",
    ".a",
    ".o",
    ".pdf",
}

# Placeholder tokens for strings we must not rewrite.
PROTECT = [
    # Versioned / hyphenated API model IDs (and close variants).
    (re.compile(r"grok-4\.20-multi-agent"), "__KEEP_MODEL_GROK_420_MA__"),
    (re.compile(r"grok-4\.20"), "__KEEP_MODEL_GROK_420__"),
    (re.compile(r"grok-4-0709"), "__KEEP_MODEL_GROK_4_0709__"),
    (re.compile(r"grok-3-mini"), "__KEEP_MODEL_GROK_3_MINI__"),
    (re.compile(r"grok-code-fast-1"), "__KEEP_MODEL_GROK_CODE_FAST_1__"),
    (re.compile(r"grok-code"), "__KEEP_MODEL_GROK_CODE__"),
    (re.compile(r"grok-2-vision"), "__KEEP_MODEL_GROK_2_VISION__"),
    (re.compile(r"grok-2-image"), "__KEEP_MODEL_GROK_2_IMAGE__"),
    (re.compile(r"grok-2"), "__KEEP_MODEL_GROK_2__"),
    (re.compile(r"grok-3"), "__KEEP_MODEL_GROK_3__"),
    (re.compile(r"grok-4"), "__KEEP_MODEL_GROK_4__"),
    # Default coding model slug (hyphen) — keep for API routing.
    (re.compile(r"grok-build"), "__KEEP_MODEL_GROK_BUILD__"),
    # Hostnames still pointing at upstream.
    (re.compile(r"cli-chat-proxy\.grok\.com"), "__KEEP_HOST_CLI_CHAT_PROXY__"),
    (re.compile(r"assets\.grok\.com"), "__KEEP_HOST_ASSETS__"),
    (re.compile(r"code\.grok\.com"), "__KEEP_HOST_CODE__"),
    (re.compile(r"(?<![A-Za-z0-9-])grok\.com"), "__KEEP_HOST_GROK_COM__"),
]

# Ordered content substitutions (after protection).
REPLACEMENTS: list[tuple[str, str]] = [
    # Cargo / rust crate identity
    ("xai-grok-", "xai-webuild-"),
    ("xai_grok_", "xai_webuild_"),
    ("XAI_GROK_", "XAI_WEBUILD_"),
    ("xai.grok.", "xai.webuild."),
    # Tool namespaces / modules (underscore form; hyphen model id is protected)
    ("GrokBuildHashline", "WeBuildHashline"),
    ("GrokBuildConcise", "WeBuildConcise"),
    ("GrokBuild", "WeBuild"),
    ("grok_build_hashline", "webuild_build_hashline"),
    ("grok_build_concise", "webuild_build_concise"),
    ("grok_build", "webuild_build"),
    ("GROK_BUILD_", "WEBUILD_BUILD_"),
    # Themes
    ("groknight", "webuildnight"),
    ("grokday", "webuildday"),
    ("GrokNight", "WeBuildNight"),
    ("GrokDay", "WeBuildDay"),
    # Env / path identity
    ("GROK_", "WEBUILD_"),
    # Product display
    ("Grok Build", "WeBuild"),
    ("GROK BUILD", "WEBUILD"),
    ("Grok build", "WeBuild"),
    # npm scope packages
    ("@xai-official/grok", "@webuild/webuild"),
    # Proto / service names
    ("GrokToolsService", "WeBuildToolsService"),
    ("GrokTools", "WeBuildTools"),
]

# Path-fragment renames applied to file *contents* (quoted path pieces).
PATHISH = [
    (re.compile(r"(?<![A-Za-z0-9_])\.grok(?![A-Za-z0-9_])"), ".webuild"),
    (re.compile(r"/etc/grok(?![A-Za-z0-9_])"), "/etc/webuild"),
    (re.compile(r"\$HOME/\.grok"), "$HOME/.webuild"),
    (re.compile(r"~/\\.grok"), "~/.webuild"),
    (re.compile(r"~/\.grok"), "~/.webuild"),
]

# Word-ish CLI / binary renames (after package renames).
CLI_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r'\bname\s*=\s*"grok"'), 'name = "webuild"'),
    (re.compile(r"\bname\s*=\s*'grok'"), "name = 'webuild'"),
    (re.compile(r"\bgrok\.exe\b"), "webuild.exe"),
    (re.compile(r"`grok`"), "`webuild`"),
    (re.compile(r"'grok'"), "'webuild'"),
    (re.compile(r'"grok"'), '"webuild"'),
    (re.compile(r"\bbin/grok\b"), "bin/webuild"),
    (re.compile(r"\b/grok\b"), "/webuild"),
    # Remaining identifier fragments commonly used in Rust
    (re.compile(r"\bgrok_home\b"), "webuild_home"),
    (re.compile(r"\bgrok_application\b"), "webuild_application"),
    (re.compile(r"\bresolve_grok_home\b"), "resolve_webuild_home"),
    (re.compile(r"\bdefault_grok_home\b"), "default_webuild_home"),
    (re.compile(r"\buser_grok_home\b"), "user_webuild_home"),
    (re.compile(r"\bgrok_managed\b"), "webuild_managed"),
    (re.compile(r"\bagent_product:\s*\"grok-shell\""), 'agent_product: "webuild-shell"'),
    (re.compile(r"\bgrok-shell\b"), "webuild-shell"),
    (re.compile(r"\bgrok-pager\b"), "webuild-pager"),
    (re.compile(r"\bnpm/grok\b"), "npm/webuild"),
]


def should_skip_dir(name: str) -> bool:
    return name in SKIP_DIR_NAMES


def iter_files() -> list[Path]:
    out: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(ROOT):
        dirnames[:] = [d for d in dirnames if not should_skip_dir(d)]
        for fn in filenames:
            if fn in SKIP_FILES:
                continue
            p = Path(dirpath) / fn
            if p.suffix.lower() in SKIP_SUFFIXES:
                continue
            # Skip the zip and binary-ish large files by name
            if fn.endswith(".zip"):
                continue
            out.append(p)
    return out


def protect(text: str) -> str:
    for pat, token in PROTECT:
        text = pat.sub(token, text)
    return text


def unprotect(text: str) -> str:
    rev = {
        "__KEEP_MODEL_GROK_420_MA__": "grok-4.20-multi-agent",
        "__KEEP_MODEL_GROK_420__": "grok-4.20",
        "__KEEP_MODEL_GROK_4_0709__": "grok-4-0709",
        "__KEEP_MODEL_GROK_3_MINI__": "grok-3-mini",
        "__KEEP_MODEL_GROK_CODE_FAST_1__": "grok-code-fast-1",
        "__KEEP_MODEL_GROK_CODE__": "grok-code",
        "__KEEP_MODEL_GROK_2_VISION__": "grok-2-vision",
        "__KEEP_MODEL_GROK_2_IMAGE__": "grok-2-image",
        "__KEEP_MODEL_GROK_2__": "grok-2",
        "__KEEP_MODEL_GROK_3__": "grok-3",
        "__KEEP_MODEL_GROK_4__": "grok-4",
        "__KEEP_MODEL_GROK_BUILD__": "grok-build",
        "__KEEP_HOST_CLI_CHAT_PROXY__": "cli-chat-proxy.grok.com",
        "__KEEP_HOST_ASSETS__": "assets.grok.com",
        "__KEEP_HOST_CODE__": "code.grok.com",
        "__KEEP_HOST_GROK_COM__": "grok.com",
    }
    for token, original in rev.items():
        text = text.replace(token, original)
    return text


def transform_text(text: str) -> str:
    text = protect(text)
    for old, new in REPLACEMENTS:
        text = text.replace(old, new)
    for pat, repl in PATHISH:
        text = pat.sub(repl, text)
    for pat, repl in CLI_PATTERNS:
        text = pat.sub(repl, text)
    # Soft leftover product wording
    text = re.sub(r"\bGrok\b", "WeBuild", text)
    text = unprotect(text)
    return text


def rename_directories() -> list[tuple[Path, Path]]:
    """Rename dirs containing grok, deepest-first. Returns (old, new) pairs."""
    dirs: list[Path] = []
    for dirpath, dirnames, _ in os.walk(ROOT):
        dirnames[:] = [d for d in dirnames if not should_skip_dir(d)]
        for d in dirnames:
            if "grok" in d.lower():
                dirs.append(Path(dirpath) / d)
    # deepest first
    dirs.sort(key=lambda p: len(p.parts), reverse=True)
    renamed: list[tuple[Path, Path]] = []
    for old in dirs:
        name = old.name
        new_name = name
        new_name = new_name.replace("xai-grok-", "xai-webuild-")
        new_name = new_name.replace("grok_build_hashline", "webuild_build_hashline")
        new_name = new_name.replace("grok_build_concise", "webuild_build_concise")
        new_name = new_name.replace("grok_build", "webuild_build")
        # npm packages: grok → webuild, grok-darwin-arm64 → webuild-darwin-arm64
        if new_name == "grok" or new_name.startswith("grok-"):
            new_name = "webuild" + new_name[len("grok") :]
        new_name = new_name.replace("Grok", "WeBuild").replace("grok", "webuild")
        if new_name == name:
            continue
        new = old.with_name(new_name)
        if new.exists():
            raise SystemExit(f"target exists: {new}")
        old.rename(new)
        renamed.append((old, new))
        print(f"DIR  {old.relative_to(ROOT)} -> {new.relative_to(ROOT)}")
    return renamed


def rename_files_with_grok() -> list[tuple[Path, Path]]:
    files: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(ROOT):
        dirnames[:] = [d for d in dirnames if not should_skip_dir(d)]
        for fn in filenames:
            if "grok" in fn.lower() and fn not in SKIP_FILES and not fn.endswith(".zip"):
                files.append(Path(dirpath) / fn)
    files.sort(key=lambda p: len(p.parts), reverse=True)
    renamed: list[tuple[Path, Path]] = []
    for old in files:
        name = old.name
        new_name = name
        new_name = new_name.replace("xai-grok-", "xai-webuild-")
        new_name = new_name.replace("grok_build", "webuild_build")
        new_name = new_name.replace("GROK_BUILD", "WEBUILD")
        new_name = new_name.replace("Grok", "WeBuild").replace("grok", "webuild")
        if new_name == name:
            continue
        new = old.with_name(new_name)
        if new.exists():
            raise SystemExit(f"target exists: {new}")
        old.rename(new)
        renamed.append((old, new))
        print(f"FILE {old.relative_to(ROOT)} -> {new.relative_to(ROOT)}")
    return renamed


def rewrite_contents() -> tuple[int, int]:
    changed = 0
    scanned = 0
    for path in iter_files():
        scanned += 1
        try:
            raw = path.read_bytes()
        except OSError as e:
            print(f"skip read {path}: {e}", file=sys.stderr)
            continue
        # Skip obvious binaries
        if b"\0" in raw[:4096]:
            continue
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            try:
                text = raw.decode("latin-1")
            except Exception:
                continue
        new = transform_text(text)
        if new != text:
            path.write_text(new, encoding="utf-8")
            changed += 1
    return scanned, changed


def main() -> None:
    print("=== Phase 1: rename directories ===")
    rename_directories()
    print("=== Phase 2: rename files ===")
    rename_files_with_grok()
    print("=== Phase 3: rewrite file contents ===")
    scanned, changed = rewrite_contents()
    print(f"scanned={scanned} changed={changed}")
    print("done")


if __name__ == "__main__":
    main()
