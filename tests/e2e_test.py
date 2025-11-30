import asyncio
import shutil
import socket
import subprocess
import time
from pathlib import Path

import requests
from gql import Client, gql
from gql.transport.aiohttp import AIOHTTPTransport

TEST_DIR = Path("/tmp/sd-backup-test")
SOURCE_DIR = TEST_DIR / "source"
TARGET_DIR = TEST_DIR / "target"


def setup_directories() -> None:
    if TEST_DIR.exists():
        shutil.rmtree(TEST_DIR)
    SOURCE_DIR.mkdir(parents=True)
    TARGET_DIR.mkdir(parents=True)
    (SOURCE_DIR / "file1.txt").write_text("content1")
    (SOURCE_DIR / "file2.txt").write_text("content2")


def find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("", 0))
        return sock.getsockname()[1]


def wait_for_server(host: str, port: int, timeout: int = 15) -> None:
    url = f"http://{host}:{port}/graphql"
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            response = requests.post(url, json={"query": "{ __typename }"}, timeout=1)
            if response.status_code in (200, 400):
                return
        except requests.RequestException:
            time.sleep(0.5)
    raise TimeoutError(f"Backend not reachable at {url} after {timeout} seconds")


async def wait_for_completion(client: Client, backup_id: str, timeout: int = 30) -> None:
    query = gql(
        """
        query($id: ID!) {
            backupTask(backupId: $id) {
                status
            }
        }
        """
    )
    deadline = time.time() + timeout
    while time.time() < deadline:
        result = await client.execute_async(query, variable_values={"id": backup_id})
        status = result["backupTask"]["status"]
        if status == "COMPLETED":
            return
        if status in {"FAILED", "CANCELLED"}:
            raise AssertionError(f"Backup ended unexpectedly with status {status}")
        await asyncio.sleep(1)
    raise TimeoutError("Backup did not complete in time")


async def run_test() -> None:
    setup_directories()
    port = find_free_port()

    process = subprocess.Popen(
        [
            "uv",
            "run",
            "python",
            "app.py",
            "--headless",
            "--listen-port",
            str(port),
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    try:
        wait_for_server("127.0.0.1", port)
        transport = AIOHTTPTransport(url=f"http://127.0.0.1:{port}/graphql")
        client = Client(transport=transport, fetch_schema_from_transport=True)

        mutation = gql(
            """
            mutation($source: String!, $target: String!) {
                startManualBackup(source: $source, target: $target)
            }
            """
        )
        result = await client.execute_async(mutation, variable_values={"source": str(SOURCE_DIR), "target": str(TARGET_DIR)})
        backup_id = result["startManualBackup"]
        assert backup_id, "Mutation must return a backup id"

        await wait_for_completion(client, backup_id)

        files = sorted(TARGET_DIR.iterdir())
        names = [file.name for file in files]
        assert "file1.txt" in names and "file2.txt" in names, f"Unexpected files in target: {names}"
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()


if __name__ == "__main__":
    asyncio.run(run_test())
