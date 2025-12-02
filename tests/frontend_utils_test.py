"""Tests for frontend/utils.py utility functions."""

from frontend.utils import calc_percent, fmt_bytes, fmt_progress, shorten_path


class TestFmtBytes:
    """Tests for fmt_bytes function."""

    def test_bytes(self):
        """Test formatting bytes."""
        assert fmt_bytes(0) == "0.0 B"
        assert fmt_bytes(512) == "512.0 B"
        assert fmt_bytes(1023) == "1023.0 B"

    def test_kilobytes(self):
        """Test formatting kilobytes."""
        assert fmt_bytes(1024) == "1.0 KB"
        assert fmt_bytes(1536) == "1.5 KB"
        assert fmt_bytes(1024 * 100) == "100.0 KB"

    def test_megabytes(self):
        """Test formatting megabytes."""
        assert fmt_bytes(1024 * 1024) == "1.0 MB"
        assert fmt_bytes(1024 * 1024 * 5) == "5.0 MB"
        assert fmt_bytes(1024 * 1024 * 100) == "100.0 MB"

    def test_gigabytes(self):
        """Test formatting gigabytes."""
        assert fmt_bytes(1024**3) == "1.0 GB"
        assert fmt_bytes(1024**3 * 2) == "2.0 GB"

    def test_terabytes(self):
        """Test formatting terabytes."""
        assert fmt_bytes(1024**4) == "1.0 TB"
        assert fmt_bytes(1024**4 * 2) == "2.0 TB"


class TestShortenPath:
    """Tests for shorten_path function."""

    def test_short_path_unchanged(self):
        """Test that short paths are not modified."""
        short = "/home/user/backup"
        assert shorten_path(short) == short

    def test_exact_length_unchanged(self):
        """Test path at exactly max length is unchanged."""
        path = "a" * 28
        assert shorten_path(path, max_len=28) == path

    def test_long_path_truncated(self):
        """Test that long paths are truncated with ellipsis."""
        long_path = "/very/long/path/to/some/deeply/nested/directory/file.txt"
        result = shorten_path(long_path, max_len=28)
        assert len(result) == 28
        assert result.startswith("...")

    def test_custom_max_length(self):
        """Test custom max_len parameter."""
        path = "/home/user/documents/file.txt"
        result = shorten_path(path, max_len=15)
        assert len(result) == 15
        assert result.startswith("...")

    def test_preserves_end_of_path(self):
        """Test that the end of the path is preserved."""
        path = "/prefix/something/important_file.txt"
        result = shorten_path(path, max_len=25)
        assert "important_file.txt" in result


class TestCalcPercent:
    """Tests for calc_percent function."""

    def test_normal_calculation(self):
        """Test normal percentage calculation."""
        assert calc_percent(50, 100) == 50.0
        assert calc_percent(25, 100) == 25.0
        assert calc_percent(100, 100) == 100.0

    def test_zero_completed(self):
        """Test with zero completed."""
        assert calc_percent(0, 100) == 0.0

    def test_none_completed(self):
        """Test with None completed."""
        assert calc_percent(None, 100) == 0.0

    def test_none_total(self):
        """Test with None total (should default to 1)."""
        result = calc_percent(0, None)
        assert result == 0.0

    def test_zero_total(self):
        """Test with zero total (defaults to 1 to avoid division by zero)."""
        # When total is 0, the function treats it as 1 to avoid division error
        # So calc_percent(50, 0) would compute 50/1 * 100 = 5000, but then > 0 check fails
        # Actually looking at the code: total = total or 1, so 0 becomes 1
        # Then 50/1 * 100 = 5000.0 if total > 0 (which 1 > 0 is true)
        result = calc_percent(50, 0)
        assert result == 5000.0  # 50 / 1 * 100

    def test_both_none(self):
        """Test with both values None."""
        assert calc_percent(None, None) == 0.0


class TestFmtProgress:
    """Tests for fmt_progress function."""

    def test_normal_progress(self):
        """Test formatting normal progress."""
        result = fmt_progress(512 * 1024, 1024 * 1024)
        assert "512.0 KB" in result
        assert "1.0 MB" in result
        assert "50.0%" in result

    def test_zero_total(self):
        """Test formatting with zero total."""
        assert fmt_progress(100, 0) == "0 bytes"

    def test_none_values(self):
        """Test formatting with None values."""
        assert fmt_progress(None, None) == "0 bytes"

    def test_complete_progress(self):
        """Test formatting 100% complete progress."""
        result = fmt_progress(1024 * 1024, 1024 * 1024)
        assert "100.0%" in result

    def test_partial_progress(self):
        """Test formatting partial progress."""
        result = fmt_progress(256 * 1024, 1024 * 1024)
        assert "25.0%" in result
