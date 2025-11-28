"""Test real-time GraphQL subscriptions for backup tasks and devices."""

import asyncio
import os
import subprocess
import sys
import tempfile
import time

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from gql import Client, gql
from gql.transport.aiohttp import AIOHTTPTransport
from gql.transport.websockets import WebsocketsTransport


async def wait_for_server(http_url: str, timeout: float = 5.0) -> bool:
    """Wait for the GraphQL server to be ready."""
    transport = AIOHTTPTransport(url=http_url)
    client = Client(transport=transport)
    start = time.time()
    while time.time() - start < timeout:
        try:
            async with client as session:
                query = gql("query { config { autoBackupEnabled } }")
                await session.execute(query)
                return True
        except Exception:
            await asyncio.sleep(0.1)
    return False


async def test_tasks_subscription(ws_url: str, http_url: str, source_dir: str, target_dir: str):
    """Test that backupTasksUpdated subscription receives updates."""
    print("Testing backupTasksUpdated subscription...")

    ws_transport = WebsocketsTransport(url=ws_url)
    ws_client = Client(transport=ws_transport)

    http_transport = AIOHTTPTransport(url=http_url)
    http_client = Client(transport=http_transport)

    subscription_query = gql("""
        subscription {
            backupTasksUpdated {
                backupId
                status
                type
                source
                target
            }
        }
    """)

    mutation_query = gql("""
        mutation StartBackup($source: String!, $target: String!) {
            startManualBackup(source: $source, target: $target)
        }
    """)

    received_updates = []
    backup_id = None

    async def collect_updates():
        nonlocal received_updates
        try:
            async with ws_client as session:
                async for result in session.subscribe(subscription_query):
                    tasks = result.get("backupTasksUpdated", [])
                    received_updates.append(tasks)
                    # Stop after receiving 2 updates (initial + at least one change)
                    if len(received_updates) >= 2:
                        break
        except asyncio.CancelledError:
            pass

    # Start subscription in background
    subscription_task = asyncio.create_task(collect_updates())

    # Give subscription time to connect
    await asyncio.sleep(0.3)

    # Start a backup to trigger updates
    async with http_client as session:
        result = await session.execute(
            mutation_query,
            variable_values={"source": source_dir, "target": target_dir}
        )
        backup_id = result.get("startManualBackup")
        print(f"  Started backup: {backup_id[:8]}...")

    # Wait for subscription to receive updates (short timeout)
    try:
        await asyncio.wait_for(subscription_task, timeout=5.0)
    except asyncio.TimeoutError:
        subscription_task.cancel()
        try:
            await subscription_task
        except asyncio.CancelledError:
            pass

    # Verify we received updates
    assert len(received_updates) >= 1, f"Expected at least 1 update, got {len(received_updates)}"
    print(f"  Received {len(received_updates)} subscription updates")

    # Check that we received the backup we started
    all_task_ids = set()
    for update in received_updates:
        for task in update:
            all_task_ids.add(task.get("backupId"))

    assert backup_id in all_task_ids, f"Expected backup {backup_id} in updates"
    print(f"  Verified backup in subscription updates")

    print("  backupTasksUpdated subscription test PASSED")
    return True


async def test_devices_subscription(ws_url: str):
    """Test that devicesUpdated subscription emits initial state."""
    print("Testing devicesUpdated subscription...")

    ws_transport = WebsocketsTransport(url=ws_url)
    ws_client = Client(transport=ws_transport)

    subscription_query = gql("""
        subscription {
            devicesUpdated {
                devicePath
                mountPoint
            }
        }
    """)

    received_updates = []

    async def collect_updates():
        nonlocal received_updates
        try:
            async with ws_client as session:
                async for result in session.subscribe(subscription_query):
                    devices = result.get("devicesUpdated", [])
                    received_updates.append(devices)
                    # Just need initial state
                    break
        except asyncio.CancelledError:
            pass

    subscription_task = asyncio.create_task(collect_updates())

    try:
        await asyncio.wait_for(subscription_task, timeout=3.0)
    except asyncio.TimeoutError:
        subscription_task.cancel()
        try:
            await subscription_task
        except asyncio.CancelledError:
            pass

    # Subscription should emit initial state immediately
    assert len(received_updates) >= 1, f"Expected initial state emission, got {len(received_updates)} updates"
    print(f"  Received initial device list with {len(received_updates[0])} devices")
    print("  devicesUpdated subscription test PASSED")
    return True


async def test_initial_task_state(ws_url: str):
    """Test that backupTasksUpdated emits initial state on connect."""
    print("Testing initial task state emission...")

    ws_transport = WebsocketsTransport(url=ws_url)
    ws_client = Client(transport=ws_transport)

    subscription_query = gql("""
        subscription {
            backupTasksUpdated {
                backupId
                status
            }
        }
    """)

    initial_state = None

    async def get_initial():
        nonlocal initial_state
        try:
            async with ws_client as session:
                async for result in session.subscribe(subscription_query):
                    initial_state = result.get("backupTasksUpdated", [])
                    break
        except asyncio.CancelledError:
            pass

    subscription_task = asyncio.create_task(get_initial())

    try:
        await asyncio.wait_for(subscription_task, timeout=3.0)
    except asyncio.TimeoutError:
        subscription_task.cancel()
        try:
            await subscription_task
        except asyncio.CancelledError:
            pass

    assert initial_state is not None, "Expected initial state emission"
    print(f"  Received initial task list with {len(initial_state)} tasks")
    print("  Initial task state test PASSED")
    return True


async def run_tests(port: int, source_dir: str, target_dir: str):
    """Run all subscription tests."""
    ws_url = f"ws://127.0.0.1:{port}/graphql"
    http_url = f"http://127.0.0.1:{port}/graphql"

    print(f"Running subscription tests against port {port}")

    # Wait for server
    if not await wait_for_server(http_url):
        raise RuntimeError("Server did not start in time")
    print("Server is ready")

    # Run tests
    await test_initial_task_state(ws_url)
    await test_devices_subscription(ws_url)
    await test_tasks_subscription(ws_url, http_url, source_dir, target_dir)

    print("\nAll subscription tests PASSED!")


def main():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "test.db")
        source_dir = os.path.join(tmpdir, "source")
        target_dir = os.path.join(tmpdir, "target")

        # Create test source directory with some files
        os.makedirs(source_dir)
        for i in range(3):
            with open(os.path.join(source_dir, f"file{i}.txt"), "w") as f:
                f.write(f"Test content {i}\n" * 10)

        # Start server
        process = subprocess.Popen(
            [
                "uv", "run", "python", "main.py",
                "--headless",
                "--listen-addr", "127.0.0.1",
                "--listen-port", "0",  # Dynamic port
                "--db-path", db_path,
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )

        port = None
        try:
            # Read output to find the port
            start_time = time.time()
            while time.time() - start_time < 5:
                line = process.stdout.readline()
                if not line:
                    if process.poll() is not None:
                        raise RuntimeError("Server process exited unexpectedly")
                    continue
                # Look for "Backend starting on http://127.0.0.1:XXXXX"
                if "http://" in line and ":" in line:
                    # Extract port from URL
                    import re
                    match = re.search(r':(\d+)', line.split("http://")[-1])
                    if match:
                        port = int(match.group(1))
                        print(f"Detected server on port {port}")
                        break

            if port is None:
                raise RuntimeError("Could not determine server port")

            # Run async tests
            asyncio.run(run_tests(port, source_dir, target_dir))

        finally:
            process.terminate()
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()


if __name__ == "__main__":
    main()

