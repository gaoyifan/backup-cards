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


def configure_logging(log_path=None, log_level=logging.INFO):
    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)

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


@cli.command()
@partial(syncify, raise_sync_error=False)
async def main(
    headless: bool = typer.Option(False, "--headless", help="Run backend only"),
    frontend_only: bool = typer.Option(False, "--frontend-only", help="Run frontend only"),
    listen_addr: str = typer.Option("127.0.0.1", "--listen-addr", help="GraphQL listen address"),
    listen_port: int = typer.Option(0, "--listen-port", help="GraphQL listen port (0 = auto)"),
    log_path: Optional[Path] = typer.Option(None, "--log-path", help="Path to log file"),
    db_path: Path = typer.Option(Path("sd-backup.db"), "--db-path", help="SQLite path for runtime config"),
    log_level: str = typer.Option("INFO", "--log-level", help="Log level"),
):
    if headless and frontend_only:
        raise typer.BadParameter("Cannot combine --frontend-only with --headless", param_name="frontend_only")

    if not frontend_only:
        await init_config_store(str(db_path))

    configure_logging(str(log_path) if log_path else None, log_level)

    if frontend_only and listen_port == 0:
        raise typer.BadParameter("--listen-port must be set when --frontend-only is used", param_name="listen_port")

    if listen_port == 0:
        listen_port = get_free_port()

    log_path_str = str(log_path) if log_path else None

    mode = "frontend-only" if frontend_only else ("headless" if headless else "full")
    logger.info("Starting SD Backup (%s mode) targeting %s:%s", mode, listen_addr, listen_port)

    if not log_path_str:
        if frontend_only:
            typer.echo(f"Frontend connecting to http://{listen_addr}:{listen_port}")
        else:
            typer.echo(f"Backend starting on http://{listen_addr}:{listen_port}")

    if headless:
        typer.echo("Running in headless mode. Press Ctrl+C to exit.")
        server = create_uvicorn_server(listen_addr, listen_port)
        try:
            await server.serve()
        except KeyboardInterrupt:
            typer.echo("Exiting...")
    elif frontend_only:
        typer.echo("Running frontend only. Press Ctrl+C to exit.")
        ui_app = SDBackupApp(host=listen_addr, port=listen_port)
        await ui_app.run_async()
    else:
        server = create_uvicorn_server(listen_addr, listen_port)
        backend_task = asyncio.create_task(server.serve())
        try:
            ui_app = SDBackupApp(host=listen_addr, port=listen_port)
            await ui_app.run_async()
        finally:
            server.should_exit = True
            try:
                await asyncio.wait_for(backend_task, timeout=5)
            except asyncio.TimeoutError:
                logger.warning("Timed out waiting for backend shutdown; cancelling task")
                backend_task.cancel()
                with suppress(asyncio.CancelledError):
                    await backend_task


if __name__ == "__main__":
    cli()
