import asyncio
import logging
import multiprocessing
import shlex
import socket
import sys
import time
from pathlib import Path

# Ensure local project sources are importable both when frozen and during analysis
REPO_ROOT = Path(__file__).resolve().parent.parent
SRC_ROOT = REPO_ROOT / "src"
for _p in (REPO_ROOT, SRC_ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import webview

from backend.backup import check_rsync_available
from backend.config import init_config_store
from frontend.app import SDBackupApp
from main import (
    _await_backend_port,
    _run_textual_web_server,
    _shutdown_backend_server,
    create_uvicorn_server,
    get_free_port,
)

logger = logging.getLogger(__name__)

LISTEN_ADDR = "127.0.0.1"
WEB_HOST = "127.0.0.1"


def _wait_for_port(host: str, port: int, timeout: float = 60.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.settimeout(0.5)
            try:
                sock.connect((host, port))
                return True
            except OSError:
                pass
        time.sleep(0.1)
    return False


async def _serve_backend_and_web(
    stop_event: multiprocessing.Event,
    ready_event: multiprocessing.Event,
    port_queue: multiprocessing.Queue,
    db_path: Path,
    web_host: str,
    web_port: int,
) -> None:
    backend_server = None
    backend_task = None
    web_process: multiprocessing.Process | None = None

    try:
        check_rsync_available()
        await init_config_store(str(db_path))

        backend_server = create_uvicorn_server(LISTEN_ADDR, 0)
        backend_task = asyncio.create_task(backend_server.serve())
        backend_port = await _await_backend_port(backend_server)

        logger.info("Backend running on http://%s:%s", LISTEN_ADDR, backend_port)

        if getattr(sys, "frozen", False):
            web_command_parts = [sys.executable, "_connect", LISTEN_ADDR, str(backend_port)]
        else:
            web_command_parts = [sys.executable, str(Path(__file__).resolve()), "_connect", LISTEN_ADDR, str(backend_port)]
        web_command = " ".join(shlex.quote(arg) for arg in web_command_parts)

        ctx = multiprocessing.get_context("spawn")
        web_process = ctx.Process(
            target=_run_textual_web_server, args=(web_command, web_host, web_port, "SD Backup", None), daemon=False
        )
        web_process.start()

        port_ready = await asyncio.to_thread(_wait_for_port, web_host, web_port, 60)
        if port_ready:
            port_queue.put(web_port)
            ready_event.set()
        else:
            logger.error("Timed out waiting for Textual web UI on %s:%s", web_host, web_port)
            port_queue.put(None)
            raise RuntimeError(f"Textual web UI failed to bind to {web_host}:{web_port}")

        await asyncio.to_thread(stop_event.wait)
    except Exception:
        logger.exception("Failed while running bundled backend/web servers")
        with suppress(Exception):
            port_queue.put(None)
        raise
    finally:
        ready_event.set()

        if web_process is not None and web_process.is_alive():
            web_process.terminate()
            await asyncio.to_thread(web_process.join, 5)

        await _shutdown_backend_server(backend_server, backend_task)


def _launch_servers(db_path: Path, web_host: str, web_port: int, stop_event, ready_event, port_queue) -> None:
    asyncio.run(_serve_backend_and_web(stop_event, ready_event, port_queue, db_path, web_host, web_port))


async def _connect_mode(backend_addr: str, backend_port: int) -> None:
    if backend_port <= 0:
        raise SystemExit("Backend port must be greater than 0")

    logger.info("Starting bundled Textual UI connecting to %s:%s", backend_addr, backend_port)
    ui_app = SDBackupApp(host=backend_addr, port=backend_port)
    await ui_app.run_async()


def main() -> None:
    db_path = Path.home() / ".local" / "share" / "sd-backup" / "sd-backup.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    web_port = get_free_port()

    stop_event = multiprocessing.Event()
    ready_event = multiprocessing.Event()
    port_queue: multiprocessing.Queue[int | None] = multiprocessing.Queue(maxsize=1)

    server_process = multiprocessing.Process(
        target=_launch_servers, args=(db_path, WEB_HOST, web_port, stop_event, ready_event, port_queue), daemon=False
    )
    server_process.start()

    try:
        if not ready_event.wait(timeout=20):
            raise RuntimeError("Backend/web processes failed to start")

        if not server_process.is_alive() and server_process.exitcode:
            raise RuntimeError(f"Bundled services exited early (code {server_process.exitcode})")

        try:
            bound_port = port_queue.get(timeout=5)
        except Exception:
            bound_port = None

        if not bound_port:
            raise RuntimeError("Web UI failed to start or report bound port")

        if not _wait_for_port(WEB_HOST, bound_port, timeout=15):
            raise RuntimeError(f"Web UI failed to open on {WEB_HOST}:{bound_port}")

        window = webview.create_window("SD Backup", f"http://{WEB_HOST}:{bound_port}", confirm_close=True, height=800)
        webview.start(gui="cocoa")
    finally:
        stop_event.set()
        if server_process.is_alive():
            server_process.join(timeout=5)
        if server_process.is_alive():
            server_process.kill()


if __name__ == "__main__":
    multiprocessing.freeze_support()
    if len(sys.argv) > 1 and sys.argv[1] == "_connect":
        if len(sys.argv) < 4:
            raise SystemExit("Usage: mac_app.py _connect BACKEND_ADDR BACKEND_PORT")
        asyncio.run(_connect_mode(sys.argv[2], int(sys.argv[3])))
    else:
        main()
