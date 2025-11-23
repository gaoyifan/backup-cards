import subprocess
import os
import time
import yaml

CONFIG_FILE = "config.yaml"
LOG_FILE = "test_sd_backup.log"

def test_logging():
    # Backup existing config
    if os.path.exists(CONFIG_FILE):
        os.rename(CONFIG_FILE, CONFIG_FILE + ".bak")
    
    try:
        # Create config with log_path
        config = {
            "graphql_host": "127.0.0.1",
            "graphql_port": 0,
            "log_path": LOG_FILE,
            "mount_point_template": "/tmp/mount",
            "target_path_template": "/tmp/target"
        }
        with open(CONFIG_FILE, "w") as f:
            yaml.dump(config, f)
            
        # Run main.py
        print("Starting backend...")
        process = subprocess.Popen(
            ["uv", "run", "python", "src/main.py", "--headless"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )
        
        time.sleep(5)
        
        process.terminate()
        try:
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            process.kill()
            
        stdout, stderr = process.communicate()
        
        print(f"STDOUT: '{stdout}'")
        print(f"STDERR: '{stderr}'")
        
        # Check log file
        if os.path.exists(LOG_FILE):
            print(f"Log file {LOG_FILE} exists.")
            with open(LOG_FILE, "r") as f:
                logs = f.read()
                print(f"Log content length: {len(logs)}")
                if "Backend started on" in logs or "Uvicorn running on" in logs:
                    print("SUCCESS: Logs found in file.")
                else:
                    print("FAILURE: Expected logs not found in file.")
                    print(logs)
        else:
            print(f"FAILURE: Log file {LOG_FILE} not created.")
            
        # Check stdout/stderr
        # We expect them to be empty or very minimal (maybe uv output?)
        # uv run might output some stuff, but the python script shouldn't.
        # If we run with `uv run -q` maybe?
        # But let's check if our application logs are there.
        if "Backend started on" in stdout or "INFO:" in stderr:
            print("FAILURE: Logs found in stdout/stderr.")
        else:
            print("SUCCESS: No app logs in stdout/stderr.")

    finally:
        # Restore config
        if os.path.exists(CONFIG_FILE + ".bak"):
            os.rename(CONFIG_FILE + ".bak", CONFIG_FILE)
        if os.path.exists(LOG_FILE):
            os.remove(LOG_FILE)

if __name__ == "__main__":
    test_logging()
