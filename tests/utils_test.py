"""Tests for backend/utils.py utility functions."""

import os
import platform
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from backend.utils import (
    auto_backup_supported,
    calculate_size,
    check_rsync_available,
    find_rsync,
    resolve_target_path,
)


class TestFindRsync:
    """Tests for find_rsync function."""

    def test_returns_homebrew_rsync_if_exists(self, monkeypatch):
        """Test that Homebrew rsync is preferred when it exists."""
        monkeypatch.setattr(os.path, "exists", lambda p: p == "/opt/homebrew/bin/rsync")
        result = find_rsync()
        assert result == "/opt/homebrew/bin/rsync"

    def test_returns_usr_local_rsync_if_exists(self, monkeypatch):
        """Test that /usr/local/bin/rsync is found when it exists."""
        monkeypatch.setattr(os.path, "exists", lambda p: p == "/usr/local/bin/rsync")
        result = find_rsync()
        assert result == "/usr/local/bin/rsync"

    def test_returns_fallback_rsync_when_no_candidates(self, monkeypatch):
        """Test fallback to 'rsync' when no candidates exist."""
        monkeypatch.setattr(os.path, "exists", lambda p: False)
        monkeypatch.setattr("shutil.which", lambda x: None)
        result = find_rsync()
        assert result == "rsync"

    def test_uses_shutil_which_as_fallback(self, monkeypatch):
        """Test that shutil.which is used when standard paths don't exist."""
        monkeypatch.setattr(os.path, "exists", lambda p: p == "/custom/bin/rsync")
        monkeypatch.setattr("backend.utils.shutil.which", lambda x: "/custom/bin/rsync")
        result = find_rsync()
        assert result == "/custom/bin/rsync"


class TestCheckRsyncAvailable:
    """Tests for check_rsync_available function."""

    def test_raises_when_rsync_not_found(self, monkeypatch):
        """Test that RuntimeError is raised when rsync is not found."""
        monkeypatch.setattr("backend.utils.find_rsync", lambda: None)
        with pytest.raises(RuntimeError, match="rsync is required"):
            check_rsync_available()

    def test_raises_on_file_not_found(self, monkeypatch):
        """Test that RuntimeError is raised when subprocess fails."""
        import subprocess

        monkeypatch.setattr("backend.utils.find_rsync", lambda: "/nonexistent/rsync")
        monkeypatch.setattr(
            subprocess,
            "run",
            MagicMock(side_effect=FileNotFoundError("rsync not found")),
        )
        with pytest.raises(RuntimeError, match="rsync is required"):
            check_rsync_available()

    def test_success_when_rsync_available(self, monkeypatch):
        """Test success when rsync is available and runs."""
        import subprocess

        monkeypatch.setattr("backend.utils.find_rsync", lambda: "/usr/bin/rsync")
        mock_result = MagicMock()
        mock_result.stdout = "rsync  version 3.2.7  protocol version 31\n"
        monkeypatch.setattr(subprocess, "run", MagicMock(return_value=mock_result))

        # Should not raise
        check_rsync_available()


class TestAutoBackupSupported:
    """Tests for auto_backup_supported function."""

    def test_returns_true_on_linux(self, monkeypatch):
        """Test that auto_backup_supported returns True on Linux."""
        monkeypatch.setattr(platform, "system", lambda: "Linux")
        assert auto_backup_supported() is True

    def test_returns_false_on_macos(self, monkeypatch):
        """Test that auto_backup_supported returns False on macOS."""
        monkeypatch.setattr(platform, "system", lambda: "Darwin")
        assert auto_backup_supported() is False

    def test_returns_false_on_windows(self, monkeypatch):
        """Test that auto_backup_supported returns False on Windows."""
        monkeypatch.setattr(platform, "system", lambda: "Windows")
        assert auto_backup_supported() is False


class TestCalculateSize:
    """Tests for calculate_size function."""

    def test_calculates_single_file_size(self):
        """Test size calculation for a single file."""
        with tempfile.NamedTemporaryFile(delete=False) as f:
            f.write(b"x" * 100)
            f.flush()
            try:
                result = calculate_size(Path(f.name))
                assert result == 100
            finally:
                os.unlink(f.name)

    def test_calculates_directory_size(self):
        """Test size calculation for a directory with multiple files."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir)
            (path / "file1.txt").write_bytes(b"a" * 50)
            (path / "file2.txt").write_bytes(b"b" * 75)
            subdir = path / "subdir"
            subdir.mkdir()
            (subdir / "file3.txt").write_bytes(b"c" * 25)

            result = calculate_size(path)
            assert result == 150

    def test_handles_empty_directory(self):
        """Test that empty directories return 0."""
        with tempfile.TemporaryDirectory() as tmpdir:
            result = calculate_size(Path(tmpdir))
            assert result == 0

    def test_handles_nonexistent_file(self):
        """Test that nonexistent files return 0."""
        result = calculate_size(Path("/nonexistent/path/file.txt"))
        assert result == 0


class TestResolveTargetPath:
    """Tests for resolve_target_path function."""

    def test_basic_template_substitution(self):
        """Test basic template variable substitution."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create a file with known mtime
            test_file = Path(tmpdir) / "test.txt"
            test_file.write_text("content")

            result = resolve_target_path(
                uuid_value="1234-5678-abcd",
                fs_label="MYSD",
                source_path=tmpdir,
                template="/backups/{uuid_short}_{fs_label}",
            )
            assert result == "/backups/1234_MYSD"

    def test_date_template(self):
        """Test date formatting in template."""
        with tempfile.TemporaryDirectory() as tmpdir:
            result = resolve_target_path(
                uuid_value="abcd",
                fs_label="SD",
                source_path=tmpdir,
                template="/backup/{date}",
            )
            # Result should be a valid date in YYYYMMDD format
            import re

            assert re.match(r"/backup/\d{8}$", result)

    def test_expands_home_tilde(self):
        """Test that ~ is expanded to home directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            result = resolve_target_path(
                uuid_value="test",
                fs_label="SD",
                source_path=tmpdir,
                template="~/backups/{uuid}",
            )
            assert result.startswith(str(Path.home()))
            assert "test" in result

    def test_full_uuid_substitution(self):
        """Test full UUID substitution."""
        with tempfile.TemporaryDirectory() as tmpdir:
            result = resolve_target_path(
                uuid_value="1234-5678-abcd-efgh",
                fs_label="SD",
                source_path=tmpdir,
                template="/backup/{uuid}",
            )
            assert result == "/backup/1234-5678-abcd-efgh"

    def test_short_uuid_with_short_value(self):
        """Test uuid_short with a UUID shorter than 4 characters."""
        with tempfile.TemporaryDirectory() as tmpdir:
            result = resolve_target_path(
                uuid_value="AB",
                fs_label="SD",
                source_path=tmpdir,
                template="/backup/{uuid_short}",
            )
            assert result == "/backup/AB"

