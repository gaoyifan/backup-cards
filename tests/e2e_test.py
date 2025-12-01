"""End-to-end integration tests for backup functionality."""

import subprocess
import tempfile
import time
from pathlib import Path

import pytest
import requests
from gql import Client, gql
from gql.transport.aiohttp import AIOHTTPTransport


def wait_for_server(host: str, port: int, timeout: int = 15) -> None:
    """Wait for the GraphQL server to be ready."""
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
    """Wait for backup to complete."""
    import asyncio

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
        result = await client.execute(query, variable_values={"id": backup_id})
        status = result["backupTask"]["status"]
        if status == "COMPLETED":
            return
        if status in {"FAILED", "CANCELLED"}:
            raise AssertionError(f"Backup ended unexpectedly with status {status}")
        await asyncio.sleep(1)
    raise TimeoutError("Backup did not complete in time")


@pytest.mark.asyncio
@pytest.mark.integration
async def test_manual_backup_e2e(free_port):
    """Test end-to-end manual backup flow via GraphQL API."""
    with tempfile.TemporaryDirectory() as tmpdir:
        test_dir = Path(tmpdir)
        source_dir = test_dir / "source"
        target_dir = test_dir / "target"

        # Setup test directories
        source_dir.mkdir()
        target_dir.mkdir()
        (source_dir / "file1.txt").write_text("content1")
        (source_dir / "file2.txt").write_text("content2")

        port = free_port

        process = subprocess.Popen(
            [
                "uv",
                "run",
                "python",
                "app.py",
                "daemon",
                "127.0.0.1",
                str(port),
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

        try:
            wait_for_server("127.0.0.1", port)
            transport = AIOHTTPTransport(url=f"http://127.0.0.1:{port}/graphql")
            async with Client(transport=transport, fetch_schema_from_transport=True) as client:
                mutation = gql(
                    """
                    mutation($source: String!, $target: String!) {
                        startManualBackup(source: $source, target: $target)
                    }
                    """
                )
                result = await client.execute(mutation, variable_values={"source": str(source_dir), "target": str(target_dir)})
                backup_id = result["startManualBackup"]
                assert backup_id, "Mutation must return a backup id"

                await wait_for_completion(client, backup_id)

            files = sorted(target_dir.iterdir())
            names = [file.name for file in files]
            assert "file1.txt" in names and "file2.txt" in names, f"Unexpected files in target: {names}"
        finally:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
