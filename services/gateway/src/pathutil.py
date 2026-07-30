"""Path safety helpers for sandbox file upload/download."""

from __future__ import annotations

import os
import re

# Relative roots allowed under /workspace
UPLOAD_DESTS = frozenset({"inbox"})
LIST_PREFIXES = frozenset({"outputs", "inbox"})
DOWNLOAD_ROOTS = frozenset({"outputs", "inbox"})

WORKSPACE_ROOT = "/workspace"

_SAFE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._ \u4e00-\u9fff()-]{0,200}$")


class PathValidationError(ValueError):
    """Raised when a user-supplied path fails safety checks."""


def sanitize_filename(name: str) -> str:
    """Return a basename-only safe filename or raise PathValidationError."""
    if not name or not name.strip():
        raise PathValidationError("Empty filename")
    base = os.path.basename(name.replace("\\", "/").strip())
    if not base or base in (".", ".."):
        raise PathValidationError(f"Invalid filename: {name!r}")
    if "\x00" in base:
        raise PathValidationError("NUL in filename")
    # Soft allowlist — still basename-only; reject path separators
    if "/" in base or "\\" in base:
        raise PathValidationError(f"Invalid filename: {name!r}")
    if not _SAFE_NAME.match(base):
        # Fall back: strip unsafe chars rather than reject all unicode docs
        cleaned = re.sub(r"[^\w.\u4e00-\u9fff() +\-]+", "_", base, flags=re.UNICODE)
        cleaned = cleaned.strip("._") or "upload.bin"
        if len(cleaned) > 200:
            cleaned = cleaned[:200]
        return cleaned
    return base


def resolve_under_workspace(*parts: str) -> str:
    """Join parts under /workspace and ensure the result stays inside it."""
    joined = os.path.normpath(os.path.join(WORKSPACE_ROOT, *[p for p in parts if p]))
    root = os.path.normpath(WORKSPACE_ROOT)
    if joined != root and not joined.startswith(root + os.sep):
        raise PathValidationError(f"Path escapes workspace: {joined}")
    return joined


def validate_upload_dest(dest: str) -> str:
    d = (dest or "inbox").strip().strip("/")
    if d not in UPLOAD_DESTS:
        raise PathValidationError(f"Upload dest not allowed: {dest!r}")
    return d


def validate_list_prefix(prefix: str) -> str:
    p = (prefix or "outputs").strip().strip("/")
    top = p.split("/", 1)[0]
    if top not in LIST_PREFIXES:
        raise PathValidationError(f"List prefix not allowed: {prefix!r}")
    # Ensure full prefix stays under workspace
    resolve_under_workspace(p)
    return p


def validate_download_path(rel_path: str) -> str:
    """Validate a workspace-relative download path; return normalized relative path."""
    if not rel_path or not rel_path.strip():
        raise PathValidationError("Empty path")
    raw = rel_path.strip().lstrip("/")
    if raw.startswith("..") or "/../" in f"/{raw}/" or "\\" in raw or "\x00" in raw:
        raise PathValidationError(f"Invalid path: {rel_path!r}")
    top = raw.split("/", 1)[0]
    if top not in DOWNLOAD_ROOTS:
        raise PathValidationError(f"Download root not allowed: {top!r}")
    abs_path = resolve_under_workspace(raw)
    rel = os.path.relpath(abs_path, WORKSPACE_ROOT)
    if rel.startswith(".."):
        raise PathValidationError(f"Path escapes workspace: {rel_path!r}")
    return rel.replace("\\", "/")


WORKSPACE_SUBDIRS = (
    "inbox",
    "sources",
    "work",
    "context",
    "memory",
    "ground-truth",
    "audits",
    "skills",
    "outputs",
    ".webuild",
)
