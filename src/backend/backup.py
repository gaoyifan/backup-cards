from __future__ import annotations

import asyncio
import datetime
import logging
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import AsyncIterator, Awaitable, Callable, Generic, TypeVar

import pyudev

from backend.config import get_config
from backend.devices import get_device_by_path
from backend.models import BackupStatus, BackupTaskDTO, BackupType
from backend.rsync_parser import RsyncOutputParser
from backend.task_store import TaskStore
from backend.utils import auto_backup_supported, calculate_size, find_rsync, mount_device, resolve_target_path, unmount_device

logger = logging.getLogger(__name__)

T = TypeVar("T")


class EventBus(Generic[T]):
    """Generic pub/sub bus for async events."""

    def __init__(self):
        self._queues: set[asyncio.Queue[T]] = set()
        self._lock = asyncio.Lock()

    async def publish(self, event: T) -> None:
        async with self._lock:
            queues = list(self._queues)
        for q in queues:
            q.put_nowait(event)

    async def stream(self) -> AsyncIterator[T]:
        queue: asyncio.Queue[T] = asyncio.Queue()
        async with self._lock:
            self._queues.add(queue)
        try:
            while True:
                yield await queue.get()
        finally:
            async with self._lock:
                self._queues.discard(queue)


class ProgressBus:
    """Pub/sub bus for backup progress updates, keyed by backup_id."""

    def __init__(self):
        self._buses: dict[str, EventBus[tuple[int, int]]] = {}
        self._lock = asyncio.Lock()

    async def publish(self, backup_id: str, size_completed: int, size_total: int) -> None:
        async with self._lock:
            bus = self._buses.get(backup_id)
        if bus:
            await bus.publish((size_completed, size_total))

    async def stream(self, backup_id: str) -> AsyncIterator[tuple[int, int]]:
        async with self._lock:
            if backup_id not in self._buses:
                self._buses[backup_id] = EventBus()
            bus = self._buses[backup_id]
        try:
            async for event in bus.stream():
                yield event
        finally:
            async with self._lock:
                if backup_id in self._buses and not self._buses[backup_id]._queues:
                    del self._buses[backup_id]


task_event_bus: EventBus[list[BackupTaskDTO]] = EventBus()


@dataclass
class RunningBackup:
    process: asyncio.subprocess.Process | None = None
    cleanup: Callable[[BackupStatus], Awaitable[None]] | None = None
    cancel_requested: bool = False
    parser: RsyncOutputParser | None = None
    size_total: int = 0


@dataclass(frozen=True)
class MountHandle:
    path: str
    owned: bool


class BackupManager:
    def __init__(self):
        self._active: dict[str, RunningBackup] = {}
        self._background_tasks: set[asyncio.Task] = set()
        self._progress = ProgressBus()

    async def fail_stale_tasks(self) -> int:
        """Mark all PENDING/IN_PROGRESS tasks as FAILED on startup."""
        count = await TaskStore.fail_stale_tasks([BackupStatus.PENDING, BackupStatus.IN_PROGRESS])
        if count > 0:
            logger.info("Marked %d stale tasks as failed from previous run", count)
        return count

    async def _publish_task_update(self) -> None:
        await task_event_bus.publish(await TaskStore.list(limit=50))

    def subscribe_tasks(self) -> AsyncIterator[list[BackupTaskDTO]]:
        return task_event_bus.stream()

    # --- Public API ---

    async def start_manual_backup(self, source: str, target: str) -> str:
        source_path = Path(source)
        target_path = Path(target).expanduser().resolve()

        if source_path.is_block_device():
            device = get_device_by_path(source)
            if device is None:
                raise ValueError(f"Device not found: {source}")
            mount = await self._mount_device(device)
            task = BackupTaskDTO.new(source=mount.path, target=str(target_path), backup_type=BackupType.MANUAL)
            cleanup = (lambda _: asyncio.to_thread(unmount_device, mount.path)) if mount.owned else None
            return await self._enqueue_backup(task, cleanup=cleanup)

        source_path = source_path.expanduser().resolve()
        if not source_path.exists():
            raise FileNotFoundError(f"Source path {source_path} does not exist.")
        task = BackupTaskDTO.new(source=str(source_path), target=str(target_path), backup_type=BackupType.MANUAL)
        return await self._enqueue_backup(task)

    async def cancel_backup(self, backup_id: str) -> bool:
        running = self._active.get(backup_id)
        if not running:
            return False
        running.cancel_requested = True
        if running.process and running.process.returncode is None:
            logger.info("Cancelling backup %s", backup_id)
            running.process.terminate()
            try:
                await asyncio.wait_for(running.process.wait(), timeout=10)
            except asyncio.TimeoutError:
                running.process.kill()
                await running.process.wait()
        return True

    def subscribe_progress(self, backup_id: str) -> AsyncIterator[tuple[int, int]]:
        async def iterator():
            if task := await TaskStore.get(backup_id):
                yield (task.size_completed, task.size_total)
            async for payload in self._progress.stream(backup_id):
                yield payload

        return iterator()

    async def list_tasks(self, limit: int = 20, offset: int = 0) -> list[BackupTaskDTO]:
        return await TaskStore.list(limit=limit, offset=offset)

    async def get_task(self, backup_id: str) -> BackupTaskDTO | None:
        return await TaskStore.get(backup_id)

    # --- Auto backup ---

    async def handle_device(self, device: pyudev.Device) -> str | None:
        if not auto_backup_supported():
            logger.info("Auto backup unsupported on this platform. Ignoring %s", device.device_node)
            return None
        config = await get_config()
        if not config.auto_backup_enabled:
            logger.info("Auto backup disabled. Ignoring %s", device.device_node)
            return None

        mount = await self._mount_device(device)
        target = await asyncio.to_thread(
            resolve_target_path,
            device.get("ID_FS_UUID", "unknown"),
            device.get("ID_FS_LABEL_ENC", ""),
            mount.path,
            config.auto_backup_target_path,
        )
        task = BackupTaskDTO.new(source=mount.path, target=target, backup_type=BackupType.AUTO)
        cleanup = (lambda _: asyncio.to_thread(unmount_device, mount.path)) if mount.owned else None
        try:
            return await self._enqueue_backup(task, cleanup=cleanup)
        except Exception:
            if cleanup:
                await cleanup(BackupStatus.FAILED)
            raise

    async def _mount_device(self, device: pyudev.Device) -> MountHandle:
        path, owned = await asyncio.to_thread(mount_device, device.device_node, device.get("ID_FS_UUID", "unknown"))
        return MountHandle(path=path, owned=owned)

    # --- Internal ---

    async def _enqueue_backup(
        self,
        task: BackupTaskDTO,
        cleanup: Callable[[BackupStatus], Awaitable[None]] | None = None,
    ) -> str:
        size_total = await asyncio.to_thread(calculate_size, Path(task.source))
        task = task.with_size_total(size_total)
        await TaskStore.create(task)
        await self._publish_task_update()

        running = RunningBackup(cleanup=cleanup, parser=RsyncOutputParser(), size_total=size_total)
        self._active[task.backup_id] = running
        job = asyncio.create_task(self._run_backup(task))
        self._background_tasks.add(job)
        job.add_done_callback(lambda t: self._on_task_done(task.backup_id, t))
        return task.backup_id

    def _on_task_done(self, backup_id: str, task: asyncio.Task) -> None:
        self._background_tasks.discard(task)
        if exc := task.exception():
            logger.exception("Background task for backup %s failed", backup_id, exc_info=exc)

    async def _run_backup(self, task: BackupTaskDTO) -> None:
        running = self._active[task.backup_id]
        if task.size_total > 0:
            running.size_total = task.size_total
        started_at = datetime.datetime.utcnow()
        await TaskStore.update_status(task.backup_id, status=BackupStatus.IN_PROGRESS, started_at=started_at)
        await self._publish_task_update()

        target = Path(task.target)
        await asyncio.to_thread(target.mkdir, parents=True, exist_ok=True)

        final_status = await self._execute_rsync(task, running) if not running.cancel_requested else BackupStatus.CANCELLED

        # Finalize
        if progress := await TaskStore.finalize(task.backup_id, status=final_status, started_at=started_at):
            await self._progress.publish(task.backup_id, *progress)
        await self._publish_task_update()

        # Cleanup
        if running.cleanup:
            try:
                await running.cleanup(final_status)
            except Exception as exc:
                logger.warning("Cleanup hook failed: %s", exc)
        self._active.pop(task.backup_id, None)

    async def _execute_rsync(self, task: BackupTaskDTO, running: RunningBackup) -> BackupStatus:
        """Execute rsync and return final status."""
        source, target = Path(task.source), Path(task.target)
        consumer: asyncio.Task | None = None
        try:
            rsync_bin = find_rsync()
            if not rsync_bin:
                raise RuntimeError("rsync not found")

            # Load exclude/include patterns from config
            config = await get_config()

            cmd = [
                rsync_bin,
                "-a",
                "--stats",
                "--bwlimit=3m",
                "--info=progress2",
            ]
            # Add include patterns first (rsync processes rules in order)
            for pattern in config.include_patterns:
                cmd.extend(["--include", pattern])
            # Add exclude patterns
            for pattern in config.exclude_patterns:
                cmd.extend(["--exclude", pattern])
            cmd.extend(
                [
                    f"{source}/" if source.is_dir() else str(source),
                    f"{target}/" if target.is_dir() else str(target),
                ]
            )
            logger.info("Launching rsync: %s", " ".join(cmd))
            process = await asyncio.create_subprocess_exec(*cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT)
            running.process = process
            consumer = asyncio.create_task(self._consume_rsync_output(task.backup_id, process.stdout, running))
            returncode = await process.wait()
            await consumer
            consumer = None

            if running.cancel_requested:
                return BackupStatus.CANCELLED
            return BackupStatus.COMPLETED if returncode == 0 else BackupStatus.FAILED

        except asyncio.CancelledError:
            return BackupStatus.CANCELLED
        except Exception as exc:
            logger.exception("Backup %s failed: %s", task.backup_id, exc)
            return BackupStatus.FAILED
        finally:
            if consumer:
                consumer.cancel()
                with suppress(asyncio.CancelledError):
                    await consumer

    async def _consume_rsync_output(self, backup_id: str, stream: asyncio.StreamReader | None, running: RunningBackup) -> None:
        if not stream:
            return
        buffer = ""
        while chunk := await stream.read(4096):
            buffer += chunk.decode(errors="ignore").replace("\r", "\n")
            while "\n" in buffer:
                line, buffer = buffer.split("\n", 1)
                if line.strip():
                    await self._handle_rsync_line(backup_id, line.strip(), running)
        if buffer.strip():
            await self._handle_rsync_line(backup_id, buffer.strip(), running)

    async def _handle_rsync_line(self, backup_id: str, line: str, running: RunningBackup) -> None:
        logger.debug("rsync[%s]: %s", backup_id[:8], line)
        if not running.parser:
            return

        progress, summary_updated = running.parser.parse_line(line)
        size_total = running.parser.total_bytes or running.size_total or None

        if progress:
            size_total = progress.total_bytes or size_total
            if size_total:
                running.size_total = size_total
            await self._update_progress(backup_id, progress.transferred_bytes, size_total)
        elif summary_updated and size_total:
            running.size_total = size_total
            await self._update_progress(backup_id, running.parser.transferred_total, size_total)

    async def _update_progress(self, backup_id: str, size_completed: int | None, size_total: int | None) -> None:
        if progress := await TaskStore.update_progress(backup_id, size_completed=size_completed, size_total_hint=size_total):
            await self._progress.publish(backup_id, *progress)
