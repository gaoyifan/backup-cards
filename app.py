import asyncio
import logging
import multiprocessing
import shlex
import socket
import sys
import signal
from contextlib import suppress
from functools import partial
from pathlib import Path
from typing import Optional

from aiohttp import web
import typer
import uvicorn
from asyncer import syncify
from textual_serve.server import Server
import webview

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


def run_webview(web_public_url: str):
    delimiter = '?' if '?' not in web_public_url else '&'
    web_public_url = f"{web_public_url}{delimiter}fontsize=11" # default font size is 16
    webview.create_window("SD Backup", web_public_url, height=800)
    webview.start()


@cli.command("web")
@partial(syncify, raise_sync_error=False)
async def web_cmd(
    db_path: Path = typer.Option(Path("sd-backup.db"), "--db-path", help="SQLite path for runtime config"),
    web_host: str = typer.Option("127.0.0.1", "--web-host", help="Host to bind the Textual web server"),
    web_port: int = typer.Option(0, "--web-port", help="Port for the Textual web server"),
    web_public_url: Optional[str] = typer.Option(
        None, "--web-public-url", help="External URL to advertise (for tunnels / proxies)"
    ),
    with_webview: bool = typer.Option(False, "--with-webview", help="Start a WebView for the Textual web server"),
):
    """Serve the Textual UI over HTTP alongside the backend."""

    listen_addr = "127.0.0.1"

    if web_port == 0:
        web_port = get_free_port()
    
    if web_public_url is None:
        web_public_url = f"http://{web_host}:{web_port}"

    shutdown_event = asyncio.Event()

    loop = asyncio.get_running_loop()
    loop.add_signal_handler(signal.SIGINT, shutdown_event.set)
    loop.add_signal_handler(signal.SIGTERM, shutdown_event.set)

    check_rsync_available()
    await init_config_store(str(db_path))

    backend_server = create_uvicorn_server(listen_addr, 0)
    backend_task = asyncio.create_task(backend_server.serve())
    backend_port = await _await_backend_port(backend_server)

    logger.info("Serving SD Backup web UI targeting %s:%s", listen_addr, backend_port)
    typer.echo(f"Backend starting on http://{listen_addr}:{backend_port}")

    if getattr(sys, "frozen", False):
        web_command_parts = [sys.executable, "connect", listen_addr, str(backend_port)]
    else:
        web_command_parts = [sys.executable, str(Path(__file__).resolve()), "connect", listen_addr, str(backend_port)]
    web_command = " ".join(shlex.quote(arg) for arg in web_command_parts)

    textual_server = Server(web_command, web_host, web_port, "SD Backup", web_public_url)
    textual_server.initialize_logging()
    textual_app = await textual_server._make_app()
    textual_runner = web.AppRunner(textual_app, handle_signals=False)
    await textual_runner.setup()
    textual_site = web.TCPSite(textual_runner, web_host, web_port)
    await textual_site.start()

    typer.echo("Serving Textual web UI with backend. Press Ctrl+C to exit.")
    typer.echo(f"Backend available at http://{listen_addr}:{backend_port}")
    typer.echo(f"Web UI available at {web_public_url}")

    if with_webview:
        process = multiprocessing.Process(target=run_webview, args=(web_public_url,))
        process.start()

        async def _wait_for_process_exit():
            await loop.run_in_executor(None, process.join)
            logger.info("WebView process exited, shutting down main loop")
            shutdown_event.set()        
        loop.create_task(_wait_for_process_exit())
    await shutdown_event.wait()
    await textual_site.stop()
    await textual_runner.cleanup()
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
