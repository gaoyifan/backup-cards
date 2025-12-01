"""Tests for path hint context derivation."""

from pathlib import Path

from frontend.path_hints import derive_hint_context


def test_empty_value_defaults_to_home():
    """Test that empty input defaults to home directory."""
    ctx = derive_hint_context("")
    assert ctx is not None
    assert ctx.display_base == "~/"
    assert ctx.partial == ""
    assert ctx.query_path == str(Path.home())


def test_home_relative_path():
    """Test home-relative path parsing."""
    ctx = derive_hint_context("~/Backups/2024")
    assert ctx is not None
    assert ctx.display_base == "~/Backups/"
    assert ctx.partial == "2024"
    assert ctx.query_path.endswith("Backups")


def test_absolute_path():
    """Test absolute path parsing."""
    ctx = derive_hint_context("/var/log/sys")
    assert ctx is not None
    assert ctx.display_base == "/var/log/"
    assert ctx.partial == "sys"
    assert ctx.query_path == "/var/log"


def test_relative_paths_not_supported():
    """Test that relative paths are not supported."""
    ctx = derive_hint_context("relative/path")
    assert ctx is None
