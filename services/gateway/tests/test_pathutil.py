"""Unit tests for Phase VII path safety helpers."""

from __future__ import annotations

import pytest

from src.pathutil import (
    PathValidationError,
    sanitize_filename,
    validate_download_path,
    validate_list_prefix,
    validate_upload_dest,
)


def test_sanitize_filename_basename():
    assert sanitize_filename("a/b/report.md") == "report.md"
    assert sanitize_filename("尽调报告.md").endswith(".md")


def test_sanitize_rejects_traversal_names():
    with pytest.raises(PathValidationError):
        sanitize_filename("..")
    with pytest.raises(PathValidationError):
        sanitize_filename("")


def test_upload_dest_allowlist():
    assert validate_upload_dest("inbox") == "inbox"
    with pytest.raises(PathValidationError):
        validate_upload_dest("outputs")
    with pytest.raises(PathValidationError):
        validate_upload_dest("../etc")


def test_list_prefix_allowlist():
    assert validate_list_prefix("outputs") == "outputs"
    assert validate_list_prefix("inbox") == "inbox"
    with pytest.raises(PathValidationError):
        validate_list_prefix("memory")


def test_download_path_allowlist():
    assert validate_download_path("outputs/report.md") == "outputs/report.md"
    assert validate_download_path("/outputs/a.pdf") == "outputs/a.pdf"
    with pytest.raises(PathValidationError):
        validate_download_path("memory/notes.md")
    with pytest.raises(PathValidationError):
        validate_download_path("outputs/../../etc/passwd")
    with pytest.raises(PathValidationError):
        validate_download_path("work/draft.md")
