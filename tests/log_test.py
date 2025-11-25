import subprocess
import os
import time
import tempfile
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
                "main.py",
                "--headless",
                "--listen-addr",
                "127.0.0.1",
                "--listen-port",
                "0",
                "--log-path",
                log_path,
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

        if os.path.exists(log_path):
            with open(log_path, "r") as f:
                logs = f.read()
                if "Starting SD Backup backend on" not in logs:
                    raise AssertionError("Expected backend logs in log file.")
        else:
            raise AssertionError("Log file not created.")

        if "Starting SD Backup backend on" in stdout or "INFO:" in stderr:
            raise AssertionError("Unexpected logs in stdout/stderr.")

if __name__ == "__main__":
    test_logging()
