"""Tests for logging functionality."""

import subprocess
import tempfile
import time
from pathlib import Path

import pytest

LOG_FILE = "test_sd_backup.log"


@pytest.mark.integration
def test_logging():
    """Test that logging to file works correctly and doesn't leak to stdout/stderr."""
    with tempfile.TemporaryDirectory() as tmpdir:
        log_path = Path(tmpdir) / LOG_FILE
        db_path = Path(tmpdir) / "config.db"

        process = subprocess.Popen(
            [
                "uv",
                "run",
                "python",
                "app.py",
                "--log-path",
                str(log_path),
                "daemon",
                "127.0.0.1",
                "0",
                "--db-path",
                str(db_path),
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

        time.sleep(5)

        process.terminate()
        try:
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            process.kill()

        stdout, stderr = process.communicate()

        assert log_path.exists(), "Log file not created"

        logs = log_path.read_text()
        assert "Starting SD Backup backend (daemon mode)" in logs, "Expected backend logs in log file"

        assert "Starting SD Backup backend (daemon mode)" not in stdout, "Backend log message leaked to stdout"
        assert "Starting SD Backup backend (daemon mode)" not in stderr, "Backend log message leaked to stderr"
        assert "INFO:" not in stderr, "Unexpected logs in stderr"
