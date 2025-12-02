"""Tests for real-time GraphQL subscriptions for backup tasks and devices."""

import asyncio
import re
import subprocess
import time

import pytest
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


def _extract_port_from_process(process: subprocess.Popen, timeout: float = 5.0) -> int:
    if process.stdout is None:
        raise RuntimeError("Process missing stdout pipe")

    lines: list[str] = []
    deadline = time.time() + timeout
    while time.time() < deadline:
        line = process.stdout.readline()
        if not line:
            if process.poll() is not None:
                break
            continue
        lines.append(line.strip())
        if "http://" in line and ":" in line:
            match = re.search(r":(\d+)", line.split("http://")[-1])
            if match:
                return int(match.group(1))

    joined = os.linesep.join(lines)
    raise RuntimeError(f"Could not determine server port from output:\n{joined}")


@pytest.fixture(scope="module")
def subscription_env(tmp_path_factory):
    """Fixture to set up a test server for subscription tests."""
    base_path = tmp_path_factory.mktemp("subscription")
    source_dir = base_path / "source"
    target_dir = base_path / "target"
    db_path = base_path / "test.db"

    source_dir.mkdir()
    target_dir.mkdir()

    for i in range(3):
        (source_dir / f"file{i}.txt").write_text(f"Test content {i}\n" * 10)

    process = subprocess.Popen(
        [
            "uv",
            "run",
            "python",
            "app.py",
            "daemon",
            "127.0.0.1",
            "0",
            "--db-path",
            str(db_path),
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )

    try:
        port = _extract_port_from_process(process)
        http_url = f"http://127.0.0.1:{port}/graphql"
        ws_url = f"ws://127.0.0.1:{port}/graphql"

        if not asyncio.run(wait_for_server(http_url)):
            raise RuntimeError("Server did not start in time")

        yield {
            "ws_url": ws_url,
            "http_url": http_url,
            "source_dir": str(source_dir),
            "target_dir": str(target_dir),
        }
    finally:
        process.terminate()
        try:
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
        if process.stdout:
            process.stdout.close()


async def _run_tasks_subscription(ws_url: str, http_url: str, source_dir: str, target_dir: str):
    """Test that backupTasksUpdated subscription receives updates."""
    print("Testing backupTasksUpdated subscription...")

    ws_transport = WebsocketsTransport(url=ws_url)
    ws_client = Client(transport=ws_transport)

    http_transport = AIOHTTPTransport(url=http_url)
    http_client = Client(transport=http_transport)

    subscription_query = gql(
        """
        subscription {
            backupTasksUpdated {
                backupId
                status
                type
                source
                target
            }
        }
    """
    )

    mutation_query = gql(
        """
        mutation StartBackup($source: String!, $target: String!) {
            startManualBackup(source: $source, target: $target)
        }
    """
    )

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
        result = await session.execute(mutation_query, variable_values={"source": source_dir, "target": target_dir})
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


async def _run_devices_subscription(ws_url: str):
    """Test that devicesUpdated subscription emits initial state."""
    print("Testing devicesUpdated subscription...")

    ws_transport = WebsocketsTransport(url=ws_url)
    ws_client = Client(transport=ws_transport)

    subscription_query = gql(
        """
        subscription {
            devicesUpdated {
                devicePath
                mountPoint
            }
        }
    """
    )

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


async def _run_initial_task_state(ws_url: str):
    """Test that backupTasksUpdated emits initial state on connect."""
    print("Testing initial task state emission...")

    ws_transport = WebsocketsTransport(url=ws_url)
    ws_client = Client(transport=ws_transport)

    subscription_query = gql(
        """
        subscription {
            backupTasksUpdated {
                backupId
                status
            }
        }
    """
    )

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


@pytest.mark.asyncio
@pytest.mark.integration
async def test_initial_task_state(subscription_env):
    """Test that backupTasksUpdated emits initial state on connect."""
    await _run_initial_task_state(subscription_env["ws_url"])


@pytest.mark.asyncio
@pytest.mark.integration
async def test_devices_subscription(subscription_env):
    """Test that devicesUpdated subscription emits initial state."""
    await _run_devices_subscription(subscription_env["ws_url"])


@pytest.mark.asyncio
@pytest.mark.integration
async def test_tasks_subscription(subscription_env):
    """Test that backupTasksUpdated subscription receives updates."""
    env = subscription_env
    await _run_tasks_subscription(env["ws_url"], env["http_url"], env["source_dir"], env["target_dir"])
