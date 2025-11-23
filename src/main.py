import argparse
import threading
import time
import uvicorn
import sys
import socket
import os
from backend.server import app
from config import load_config

import logging

def configure_logging(log_path=None):
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)
    
    # Remove existing handlers
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)
        
    formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    
    if log_path:
        handler = logging.FileHandler(log_path)
        handler.setFormatter(formatter)
        root_logger.addHandler(handler)
    else:
        handler = logging.StreamHandler(sys.stderr)
        handler.setFormatter(formatter)
        root_logger.addHandler(handler)

def run_backend(host, port, log_config=None):
    uvicorn.run(app, host=host, port=port, log_level="info", log_config=log_config)

def get_free_port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(('', 0))
        return s.getsockname()[1]

def main():
    parser = argparse.ArgumentParser(description="SD Card Backup Tool")
    parser.add_argument("--headless", action="store_true", help="Run in headless mode (backend only)")
    args = parser.parse_args()

    config = load_config()
    host = config.get("graphql_host", "127.0.0.1")
    port = config.get("graphql_port", 0)
    log_path = config.get("log_path")

    configure_logging(log_path)

    if port == 0:
        port = get_free_port()
        
    # Write port to file for external tools (e.g. E2E tests)
    with open(".port", "w") as f:
        f.write(str(port))

    # Prepare uvicorn log config if logging to file
    uvicorn_log_config = uvicorn.config.LOGGING_CONFIG.copy()
    if log_path:
        # If logging to file, we want uvicorn to also log to that file or be silent on stdout
        # Simplest way is to let uvicorn use the root logger which we configured?
        # Or explicitly configure uvicorn loggers.
        # Uvicorn by default configures its own loggers.
        # We can pass log_config=None to let it use root logger, but uvicorn might reconfigure.
        # Let's try passing a modified config or just None if we want it to inherit?
        # Actually, if we pass log_config=None, uvicorn uses basicConfig if not set?
        # Let's try to just redirect uvicorn logs to our file if log_path is set.
        # For now, let's pass None to run_backend and handle it there.
        pass

    # Start backend in a separate thread
    # We need to pass log configuration to uvicorn to prevent it from printing to stdout if log_path is set
    # If log_path is set, we want uvicorn to log to file or nothing to stdout.
    # We can create a log config dict.
    log_config = None
    if log_path:
        log_config = uvicorn.config.LOGGING_CONFIG.copy()
        log_config["handlers"]["default"] = {"class": "logging.FileHandler", "filename": log_path, "formatter": "default"}
        log_config["handlers"]["access"] = {"class": "logging.FileHandler", "filename": log_path, "formatter": "access"}
        # We might need to ensure formatters are defined or reuse them.
        # Uvicorn config is complex.
        # Simpler approach: If log_path is set, tell uvicorn to use our handlers?
        # Or just suppress uvicorn stdout?
        # Let's try modifying the handlers in the default config.
        pass

    backend_thread = threading.Thread(target=run_backend, args=(host, port, log_config), daemon=True)
    backend_thread.start()
    if not log_path:
        print(f"Backend started on http://{host}:{port}")

    if args.headless:
        print("Running in headless mode. Press Ctrl+C to exit.")
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            print("Exiting...")
    else:
        # Import frontend here to avoid dependency if headless (though we have them installed)
        # and to ensure backend is up or at least starting.
        # For Textual, we usually run it in the main thread.
        try:
            from frontend.app import SDBackupApp
            app = SDBackupApp(host=host, port=port)
            app.run()
        except ImportError as e:
            print(f"Failed to load frontend: {e}")
            sys.exit(1)

if __name__ == "__main__":
    main()
