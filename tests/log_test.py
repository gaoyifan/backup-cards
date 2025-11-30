import os
import subprocess
import tempfile
import time

LOG_FILE = "test_sd_backup.log"


def test_logging():
    with tempfile.TemporaryDirectory() as tmpdir:
        log_path = os.path.join(tmpdir, LOG_FILE)
        db_path = os.path.join(tmpdir, "config.db")

        process = subprocess.Popen(
            [
                "uv",
                "run",
                "python",
                "app.py",
                "--log-path",
                log_path,
                "daemon",
                "127.0.0.1",
                "0",
                "--db-path",
                db_path,
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

        if not os.path.exists(log_path):
            raise AssertionError("Log file not created.")

        with open(log_path, "r") as f:
            logs = f.read()
            if "Starting SD Backup backend (daemon mode)" not in logs:
                raise AssertionError("Expected backend logs in log file.")

        if "Starting SD Backup backend (daemon mode)" in stdout:
            raise AssertionError("Backend log message leaked to stdout.")

        if "Starting SD Backup backend (daemon mode)" in stderr or "INFO:" in stderr:
            raise AssertionError("Unexpected logs in stderr.")


if __name__ == "__main__":
    test_logging()
