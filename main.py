import asyncio
import logging
import multiprocessing
import shlex
import socket
import sys
from contextlib import suppress
from functools import partial
from pathlib import Path
from typing import Optional

import typer
import uvicorn
from asyncer import syncify
from textual_serve.server import Server

from backend.backup import check_rsync_available
from backend.config import init_config_store
from backend.server import app
from frontend.app import SDBackupApp

logger = logging.getLogger(__name__)
cli = typer.Typer(no_args_is_help=True)


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


async def _await_backend_port(server: uvicorn.Server, timeout: float = 5.0) -> int:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while True:
        servers = getattr(server, "servers", None)
        if servers:
            sockets = servers[0].sockets
            if sockets:
                return sockets[0].getsockname()[1]
        if server.should_exit or loop.time() >= deadline:
            break
        await asyncio.sleep(0.05)
    raise RuntimeError("Backend server failed to bind to a port")


async def _shutdown_backend_server(
    backend_server: uvicorn.Server | None, backend_task: asyncio.Task | None
) -> None:
    if backend_server is None or backend_task is None:
        return

    backend_server.should_exit = True
    try:
        await asyncio.wait_for(backend_task, timeout=5)
    except asyncio.TimeoutError:
        logger.warning("Timed out waiting for backend shutdown; cancelling task")
        backend_task.cancel()
        with suppress(asyncio.CancelledError):
            await backend_task


def _run_textual_web_server(
    command: str, host: str, port: int, title: str, public_url: str | None
) -> None:
    server = Server(command, host, port, title, public_url)
    server.serve()


@cli.callback()
def main_callback(
    log_path: Optional[Path] = typer.Option(None, "--log-path", help="Path to log file"),
    log_level: str = typer.Option("INFO", "--log-level", help="Log level"),
) -> None:
    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)

    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)

    formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")

    if log_path:
        handler = logging.FileHandler(str(log_path))
    else:
        handler = logging.StreamHandler(sys.stderr)

    handler.setFormatter(formatter)
    root_logger.addHandler(handler)


@cli.command()
@partial(syncify, raise_sync_error=False)
async def tui(
    db_path: Path = typer.Option(Path("sd-backup.db"), "--db-path", help="SQLite path for runtime config"),
):
    """Run the backend and Textual UI inside the terminal."""

    listen_addr = "127.0.0.1"
    requested_port = 0

    backend_server: uvicorn.Server | None = None
    backend_task: asyncio.Task | None = None

    try:
        check_rsync_available()
        await init_config_store(str(db_path))

        backend_server = create_uvicorn_server(listen_addr, requested_port)
        backend_task = asyncio.create_task(backend_server.serve())

        backend_port = await _await_backend_port(backend_server)

        logger.info("Starting SD Backup TUI with backend targeting %s:%s", listen_addr, backend_port)
        typer.echo(f"Backend starting on http://{listen_addr}:{backend_port}")

        typer.echo("Launching terminal UI. Press Ctrl+C to exit.")
        ui_app = SDBackupApp(host=listen_addr, port=backend_port)
        await ui_app.run_async()
    except KeyboardInterrupt:
        typer.echo("Exiting...")
    finally:
        await _shutdown_backend_server(backend_server, backend_task)


@cli.command("connect")
@partial(syncify, raise_sync_error=False)
async def connect(
    backend_addr: str = typer.Argument("127.0.0.1", metavar="ADDR", help="Backend address"),
    backend_port: int = typer.Argument(8000, metavar="PORT", help="Backend port"),
):
    """Run only the Textual UI, connecting to an existing backend."""

    if backend_port <= 0:
        raise typer.BadParameter("PORT must be greater than 0", param_name="PORT")

    try:
        logger.info("Starting SD Backup connect mode targeting %s:%s", backend_addr, backend_port)
        typer.echo(f"Frontend connecting to http://{backend_addr}:{backend_port}")
        typer.echo("Running TUI only. Press Ctrl+C to exit.")
        ui_app = SDBackupApp(host=backend_addr, port=backend_port)
        await ui_app.run_async()
    except KeyboardInterrupt:
        typer.echo("Exiting...")


@cli.command()
@partial(syncify, raise_sync_error=False)
async def web(
    db_path: Path = typer.Option(Path("sd-backup.db"), "--db-path", help="SQLite path for runtime config"),
    web_host: str = typer.Option("127.0.0.1", "--web-host", help="Host to bind the Textual web server"),
    web_port: int = typer.Option(9000, "--web-port", help="Port for the Textual web server"),
    web_public_url: Optional[str] = typer.Option(
        None, "--web-public-url", help="External URL to advertise (for tunnels / proxies)"
    ),
):
    """Serve the Textual UI over HTTP alongside the backend."""

    listen_addr = "127.0.0.1"
    requested_port = 0

    backend_server: uvicorn.Server | None = None
    backend_task: asyncio.Task | None = None
    web_process: multiprocessing.Process | None = None

    try:
        check_rsync_available()
        await init_config_store(str(db_path))

        backend_server = create_uvicorn_server(listen_addr, requested_port)
        backend_task = asyncio.create_task(backend_server.serve())
        backend_port = await _await_backend_port(backend_server)

        logger.info("Serving SD Backup web UI targeting %s:%s", listen_addr, backend_port)
        typer.echo(f"Backend starting on http://{listen_addr}:{backend_port}")

        web_command_parts = [
            sys.executable,
            str(Path(__file__).resolve()),
            "connect",
            listen_addr,
            str(backend_port),
        ]
        web_command = " ".join(shlex.quote(arg) for arg in web_command_parts)

        ctx = multiprocessing.get_context("spawn")
        web_process = ctx.Process(
            target=_run_textual_web_server,
            args=(web_command, web_host, web_port, "SD Backup", web_public_url),
            daemon=False,
        )

        typer.echo("Serving Textual web UI with backend. Press Ctrl+C to exit.")
        typer.echo(f"Backend available at http://{listen_addr}:{backend_port}")
        typer.echo(f"Web UI available at http://{web_host}:{web_port}")
        web_process.start()

        await asyncio.to_thread(web_process.join)
    except KeyboardInterrupt:
        typer.echo("Exiting...")
    finally:
        if web_process is not None and web_process.is_alive():
            web_process.terminate()
            await asyncio.to_thread(web_process.join, 5)

        await _shutdown_backend_server(backend_server, backend_task)


@cli.command("daemon")
@partial(syncify, raise_sync_error=False)
async def daemon(
    listen_addr: str = typer.Argument("127.0.0.1", metavar="ADDR", help="GraphQL listen address"),
    listen_port: int = typer.Argument(0, metavar="PORT", help="GraphQL listen port (0 = auto)"),
    db_path: Path = typer.Option(Path("sd-backup.db"), "--db-path", help="SQLite path for runtime config"),
):
    """Run only the backend API."""

    if listen_port == 0:
        listen_port = get_free_port()

    try:
        check_rsync_available()
        await init_config_store(str(db_path))

        logger.info("Starting SD Backup backend (daemon mode) targeting %s:%s", listen_addr, listen_port)
        typer.echo(f"Backend starting on http://{listen_addr}:{listen_port}")

        typer.echo("Running in daemon mode. Press Ctrl+C to exit.")
        server = create_uvicorn_server(listen_addr, listen_port)
        await server.serve()
    except KeyboardInterrupt:
        typer.echo("Exiting...")


if __name__ == "__main__":
    cli()
