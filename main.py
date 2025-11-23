import argparse
import logging
import socket
import sys
import threading
import time

import uvicorn

from backend.server import app
from config import load_config

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

def build_uvicorn_log_config(log_path):
    if not log_path:
        return None

    log_config = uvicorn.config.LOGGING_CONFIG.copy()
    log_config["handlers"]["default"] = {
        "class": "logging.FileHandler",
        "filename": log_path,
        "formatter": "default",
    }
    log_config["handlers"]["access"] = {
        "class": "logging.FileHandler",
        "filename": log_path,
        "formatter": "access",
    }
    log_config["loggers"]["uvicorn"]["handlers"] = ["default"]
    log_config["loggers"]["uvicorn.error"]["handlers"] = ["default"]
    log_config["loggers"]["uvicorn.access"]["handlers"] = ["access"]
    return log_config

def main():
    parser = argparse.ArgumentParser(description="SD Card Backup Tool")
    parser.add_argument("--headless", action="store_true", help="Run in headless mode (backend only)")
    parser.add_argument("--host", help="Override GraphQL host from config")
    parser.add_argument(
        "--port",
        type=int,
        help="Override GraphQL port from config (use 0 for dynamic allocation)",
    )
    args = parser.parse_args()

    config = load_config()
    host = args.host or config.get("graphql_host", "127.0.0.1")
    port = config.get("graphql_port", 0) if args.port is None else args.port
    log_path = config.get("log_path")

    configure_logging(log_path)

    if port == 0:
        port = get_free_port()

    log_config = build_uvicorn_log_config(log_path)

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
