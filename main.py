import asyncio
import logging
import socket
import sys
from contextlib import suppress
from functools import partial
from pathlib import Path
from typing import Optional

import typer
import uvicorn
from asyncer import syncify

from backend.config import init_config_store
from backend.server import app
from frontend.app import SDBackupApp

logger = logging.getLogger(__name__)
cli = typer.Typer()


def configure_logging(log_path=None):
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)

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


def create_uvicorn_server(host, port, log_config=None):
    config = uvicorn.Config(
        app,
        host=host,
        port=port,
        log_level="info",
        log_config=log_config,
        loop="asyncio",
    )
    return uvicorn.Server(config)


def get_free_port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("", 0))
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


@cli.command()
@partial(syncify, raise_sync_error=False)
async def main(
    headless: bool = typer.Option(False, "--headless", help="Run backend only"),
    listen_addr: str = typer.Option("127.0.0.1", "--listen-addr", help="GraphQL listen address"),
    listen_port: int = typer.Option(0, "--listen-port", help="GraphQL listen port (0 = auto)"),
    log_path: Optional[Path] = typer.Option(None, "--log-path", help="Path to log file"),
    db_path: Path = typer.Option(Path("sd-backup.db"), "--db-path", help="SQLite path for runtime config"),
):
    await init_config_store(str(db_path))

    configure_logging(str(log_path) if log_path else None)

    if listen_port == 0:
        listen_port = get_free_port()

    log_path_str = str(log_path) if log_path else None
    log_config = build_uvicorn_log_config(log_path_str)

    logger.info(
        "Starting SD Backup backend on %s:%s (headless=%s)",
        listen_addr,
        listen_port,
        headless,
    )

    if not log_path_str:
        typer.echo(f"Backend starting on http://{listen_addr}:{listen_port}")

    if headless:
        typer.echo("Running in headless mode. Press Ctrl+C to exit.")
        server = create_uvicorn_server(listen_addr, listen_port, log_config)
        try:
            await server.serve()
        except KeyboardInterrupt:
            typer.echo("Exiting...")
    else:
        server = create_uvicorn_server(listen_addr, listen_port, log_config)
        backend_task = asyncio.create_task(server.serve())
        try:
            ui_app = SDBackupApp(host=listen_addr, port=listen_port)
            await ui_app.run_async()
        finally:
            server.should_exit = True
            backend_task.cancel()
            with suppress(asyncio.CancelledError):
                await backend_task


if __name__ == "__main__":
    cli()
