"""Tests for backend/utils.py utility functions."""

import datetime
import os
import platform
import tempfile
from pathlib import Path
from unittest.mock import MagicMock

import pytest

import backend.utils as utils
from backend.utils import auto_backup_supported, calculate_size, check_rsync_available, find_rsync, resolve_target_path


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

    def test_date_falls_back_to_now_when_only_pre_1980(self):
        """Ensure {date} ignores files before 1980."""
        with tempfile.TemporaryDirectory() as tmpdir:
            ancient = Path(tmpdir) / "ancient.txt"
            ancient.write_text("old")
            old_ts = datetime.datetime(1975, 1, 1, tzinfo=datetime.timezone.utc).timestamp()
            os.utime(ancient, (old_ts, old_ts))

            before = datetime.datetime.now().strftime("%Y%m%d")
            result = resolve_target_path(
                uuid_value="abcd",
                fs_label="SD",
                source_path=tmpdir,
                template="/backup/{date}",
            )
            after = datetime.datetime.now().strftime("%Y%m%d")
            assert result in (f"/backup/{before}", f"/backup/{after}")

    def test_model_template_substitution(self, monkeypatch):
        """Ensure {model} placeholder uses detected camera model."""
        with tempfile.TemporaryDirectory() as tmpdir:
            calls: list[frozenset[str]] = []

            def fake_find(source_path, extensions, tag_order):
                calls.append(extensions)
                assert source_path == tmpdir
                assert tag_order
                if extensions is utils.IMAGE_EXTENSIONS:
                    return "Alpha 7 C"
                pytest.fail("Video lookup should not run when image result found")

            monkeypatch.setattr(utils, "_find_exif_tag", fake_find)

            result = resolve_target_path(
                uuid_value="abcd",
                fs_label="SDCARD",
                source_path=tmpdir,
                template="/backup/{model}",
            )
            assert result == "/backup/Alpha-7-C"
            assert calls == [utils.IMAGE_EXTENSIONS]

    def test_model_template_falls_back_to_video(self, monkeypatch):
        """Ensure {model} falls back to video metadata when needed."""
        with tempfile.TemporaryDirectory() as tmpdir:
            calls: list[frozenset[str]] = []

            def fake_find(source_path, extensions, tag_order):
                calls.append(extensions)
                if extensions is utils.IMAGE_EXTENSIONS:
                    return None
                return "FX30"

            monkeypatch.setattr(utils, "_find_exif_tag", fake_find)

            result = resolve_target_path(
                uuid_value="abcd",
                fs_label="SDCARD",
                source_path=tmpdir,
                template="/backup/{model}",
            )
            assert result == "/backup/FX30"
            assert calls == [utils.IMAGE_EXTENSIONS, utils.VIDEO_EXTENSIONS]


class TestFindEarliestTimestamp:
    def _write_with_mtime(self, path: Path, dt: datetime.datetime) -> None:
        path.write_text("data")
        ts = dt.timestamp()
        os.utime(path, (ts, ts))

    def test_prefers_within_one_year(self, tmp_path):
        now = datetime.datetime(2030, 1, 1, tzinfo=datetime.timezone.utc)
        recent = now - datetime.timedelta(days=30)
        older = now - datetime.timedelta(days=400)
        self._write_with_mtime(tmp_path / "recent.dat", recent)
        self._write_with_mtime(tmp_path / "older.dat", older)

        result = utils._find_earliest_timestamp(tmp_path.as_posix(), now=now)
        assert result.strftime("%Y%m%d") == recent.strftime("%Y%m%d")

    def test_falls_back_to_five_year_window(self, tmp_path):
        now = datetime.datetime(2030, 1, 1, tzinfo=datetime.timezone.utc)
        three_years = now - datetime.timedelta(days=3 * 365)
        six_years = now - datetime.timedelta(days=6 * 365)
        self._write_with_mtime(tmp_path / "three.dat", three_years)
        self._write_with_mtime(tmp_path / "six.dat", six_years)

        result = utils._find_earliest_timestamp(tmp_path.as_posix(), now=now)
        assert result.strftime("%Y%m%d") == three_years.strftime("%Y%m%d")

    def test_falls_back_to_post_1980(self, tmp_path):
        now = datetime.datetime(2030, 1, 1, tzinfo=datetime.timezone.utc)
        old = datetime.datetime(1990, 5, 1, tzinfo=datetime.timezone.utc)
        older = datetime.datetime(1985, 7, 1, tzinfo=datetime.timezone.utc)
        very_old = datetime.datetime(1970, 1, 1, tzinfo=datetime.timezone.utc)
        self._write_with_mtime(tmp_path / "old.dat", old)
        self._write_with_mtime(tmp_path / "older.dat", older)
        self._write_with_mtime(tmp_path / "very_old.dat", very_old)

        result = utils._find_earliest_timestamp(tmp_path.as_posix(), now=now)
        assert result.strftime("%Y%m%d") == older.strftime("%Y%m%d")

    def test_returns_now_when_no_valid_files(self, tmp_path):
        now = datetime.datetime(2030, 1, 1, tzinfo=datetime.timezone.utc)
        very_old = datetime.datetime(1970, 1, 1, tzinfo=datetime.timezone.utc)
        self._write_with_mtime(tmp_path / "very_old.dat", very_old)

        result = utils._find_earliest_timestamp(tmp_path.as_posix(), now=now)
        assert result == now
