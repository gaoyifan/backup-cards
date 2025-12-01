from __future__ import annotations

import asyncio
import datetime
import logging
import os
import subprocess
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import AsyncIterator, Awaitable, Callable

import pyudev

from backend.config import get_config
from backend.devices import get_device_by_path
from backend.models import BackupStatus, BackupTaskDTO, BackupType
from backend.rsync_parser import RsyncOutputParser
from backend.task_store import TaskStore
from backend.utils import auto_backup_supported, calculate_size, find_rsync, resolve_target_path

logger = logging.getLogger(__name__)

DEFAULT_MOUNT_ROOT = "/mnt"
MOUNT_PREFIX = "sd-backup"


class ProgressBus:
    def __init__(self):
        self._queues: dict[str, set[asyncio.Queue]] = {}
        self._lock = asyncio.Lock()

    async def publish(self, backup_id: str, size_completed: int, size_total: int) -> None:
        async with self._lock:
            queues = list(self._queues.get(backup_id, set()))
        for queue in queues:
            queue.put_nowait((size_completed, size_total))

    async def stream(self, backup_id: str) -> AsyncIterator[tuple[int, int]]:
        queue: asyncio.Queue = asyncio.Queue()
        async with self._lock:
            watchers = self._queues.setdefault(backup_id, set())
            watchers.add(queue)

        try:
            while True:
                yield await queue.get()
        finally:
            async with self._lock:
                watchers = self._queues.get(backup_id)
                if watchers and queue in watchers:
                    watchers.remove(queue)
                    if not watchers:
                        self._queues.pop(backup_id, None)


class TaskEventBus:
    """Pub/sub bus for task list updates."""

    def __init__(self):
        self._queues: set[asyncio.Queue] = set()
        self._lock = asyncio.Lock()

    async def publish(self, tasks: list[BackupTaskDTO]) -> None:
        async with self._lock:
            queues = list(self._queues)
        for queue in queues:
            queue.put_nowait(tasks)

    async def stream(self) -> AsyncIterator[list[BackupTaskDTO]]:
        queue: asyncio.Queue = asyncio.Queue()
        async with self._lock:
            self._queues.add(queue)

        try:
            while True:
                yield await queue.get()
        finally:
            async with self._lock:
                self._queues.discard(queue)


# Global task event bus instance
task_event_bus = TaskEventBus()


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
        """Mark all PENDING/IN_PROGRESS tasks as FAILED on startup (stale from previous run)."""
        count = await TaskStore.fail_stale_tasks([BackupStatus.PENDING, BackupStatus.IN_PROGRESS])
        if count > 0:
            logger.info("Marked %d stale tasks as failed from previous run", count)
        return count

    async def _publish_task_update(self) -> None:
        """Fetch current task list and publish to subscribers."""
        tasks = await self.list_tasks(limit=50)
        await task_event_bus.publish(tasks)

    def subscribe_tasks(self) -> AsyncIterator[list[BackupTaskDTO]]:
        """Subscribe to task list updates."""
        return task_event_bus.stream()

    # ------------------------------------------------------------------ #
    # Public API used by GraphQL
    # ------------------------------------------------------------------ #
    async def start_manual_backup(self, source: str, target: str) -> str:
        source_path = Path(source)
        target_path = Path(target).expanduser().resolve()

        # Block device (e.g., /dev/sda1)
        if source_path.is_block_device():
            device = get_device_by_path(source)
            if device is None:
                raise ValueError(f"Device not found: {source}")
            mount = await self.mount_device(device)
            task = BackupTaskDTO.new(source=mount.path, target=str(target_path), backup_type=BackupType.MANUAL)
            return await self._enqueue_backup(task, cleanup=self._unmount_cleanup(mount) if mount.owned else None)

        # Regular directory/file backup
        source_path = source_path.expanduser().resolve()
        if not source_path.exists():
            raise FileNotFoundError(f"Source path {source_path} does not exist.")
        task = BackupTaskDTO.new(source=str(source_path), target=str(target_path), backup_type=BackupType.MANUAL)
        return await self._enqueue_backup(task)

    async def cancel_backup(self, backup_id: str) -> bool:
        running = self._active.get(backup_id)
        if not running:
            logger.info("No running task for backup_id=%s", backup_id)
            return False

        running.cancel_requested = True
        process = running.process
        if process and process.returncode is None:
            logger.info("Cancelling backup %s", backup_id)
            process.terminate()
            try:
                await asyncio.wait_for(process.wait(), timeout=10)
            except asyncio.TimeoutError:
                process.kill()
                await process.wait()
        return True

    def subscribe_progress(self, backup_id: str) -> AsyncIterator[tuple[int, int]]:
        async def iterator():
            task = await self.get_task(backup_id)
            if task:
                yield (task.size_completed, task.size_total)
            async for payload in self._progress.stream(backup_id):
                yield payload

        return iterator()

    async def list_tasks(self, limit: int = 20, offset: int = 0) -> list[BackupTaskDTO]:
        return await TaskStore.list(limit=limit, offset=offset)

    async def get_task(self, backup_id: str) -> BackupTaskDTO | None:
        return await TaskStore.get(backup_id)

    # ------------------------------------------------------------------ #
    # Auto backup entry point (used by DeviceMonitor)
    # ------------------------------------------------------------------ #
    async def handle_device(self, device: pyudev.Device) -> str | None:
        if not auto_backup_supported():
            logger.info("Auto backup unsupported on this platform. Ignoring %s", device.device_node)
            return None
        config = await get_config()
        if not config.auto_backup_enabled:
            logger.info("Auto backup disabled. Ignoring %s", device.device_node)
            return None
        mount = await self.mount_device(device)
        target_path = await self._resolve_target_path(device, mount.path, config.auto_backup_target_path)
        task = BackupTaskDTO.new(source=mount.path, target=target_path, backup_type=BackupType.AUTO)
        cleanup = self._unmount_cleanup(mount) if mount.owned else None
        try:
            return await self._enqueue_backup(task, cleanup=cleanup)
        except Exception:
            if cleanup:
                await cleanup(BackupStatus.FAILED)
            raise

    def _unmount_cleanup(self, mount: MountHandle) -> Callable[[BackupStatus], Awaitable[None]]:
        return lambda _: self._unmount_path(mount.path)

    async def mount_device(self, device: pyudev.Device) -> MountHandle:
        device_node = device.device_node
        uuid_value = device.get("ID_FS_UUID", "unknown")
        return await asyncio.to_thread(self._mount_device_sync, device_node, uuid_value)

    def _mount_device_sync(self, device_node: str, uuid_value: str) -> MountHandle:
        with open("/proc/mounts", "r", encoding="utf-8") as mounts:
            for line in mounts:
                parts = line.split()
                if parts and parts[0] == device_node:
                    mount_path = os.path.realpath(parts[1])
                    logger.info("Device %s already mounted at %s", device_node, mount_path)
                    return MountHandle(path=mount_path, owned=False)

        mount_point = os.path.join(DEFAULT_MOUNT_ROOT, f"{MOUNT_PREFIX}-{uuid_value}")
        os.makedirs(mount_point, exist_ok=True)
        logger.info("Mounting %s to %s", device_node, mount_point)
        subprocess.run(["mount", device_node, mount_point], check=True)
        normalized = os.path.realpath(mount_point)
        return MountHandle(path=normalized, owned=True)

    async def _unmount_path(self, mount_point: str) -> None:
        await asyncio.to_thread(self._unmount_path_sync, mount_point)

    def _unmount_path_sync(self, mount_point: str) -> None:
        try:
            subprocess.run(["umount", mount_point], check=True)
        except subprocess.CalledProcessError as exc:
            logger.warning("Failed to unmount %s: %s", mount_point, exc)
            return
        self._remove_temp_mount_dir(mount_point)

    def _remove_temp_mount_dir(self, mount_point: str) -> None:
        """Remove temporary mount dir created under DEFAULT_MOUNT_ROOT."""
        try:
            mount_path = Path(mount_point).resolve()
            root_path = Path(DEFAULT_MOUNT_ROOT).resolve()
        except OSError as exc:
            logger.debug("Skipped resolving mount path %s: %s", mount_point, exc)
            return

        prefix = f"{MOUNT_PREFIX}-"
        if mount_path.parent != root_path or not mount_path.name.startswith(prefix):
            return

        try:
            mount_path.rmdir()
            logger.debug("Removed temporary mount directory %s", mount_path)
        except FileNotFoundError:
            logger.debug("Mount directory %s already removed", mount_path)
        except OSError as exc:
            logger.warning("Failed to remove mount directory %s: %s", mount_path, exc)

    async def _resolve_target_path(self, device: pyudev.Device, source_path: str, template: str) -> str:
        uuid_value = device.get("ID_FS_UUID", "unknown")
        fs_label = device.get("ID_FS_LABEL_ENC", "")
        return await asyncio.to_thread(resolve_target_path, uuid_value, fs_label, source_path, template)

    # ------------------------------------------------------------------ #
    # Internal helpers
    # ------------------------------------------------------------------ #
    async def _enqueue_backup(
        self,
        task: BackupTaskDTO,
        cleanup: Callable[[BackupStatus], Awaitable[None]] | None = None,
    ) -> str:
        size_total = await asyncio.to_thread(calculate_size, Path(task.source))
        task = task.with_size_total(size_total)
        logger.debug("Creating task record for backup %s", task.backup_id)
        await TaskStore.create(task)
        await self._publish_task_update()

        logger.debug("Enqueuing backup %s", task.backup_id)
        running = RunningBackup(cleanup=cleanup, parser=RsyncOutputParser(), size_total=size_total)
        self._active[task.backup_id] = running
        job = asyncio.create_task(self._run_backup(task))
        self._track_background_task(task.backup_id, job)
        return task.backup_id

    def _track_background_task(self, backup_id: str, task: asyncio.Task) -> None:
        self._background_tasks.add(task)

        def _done_callback(done_task: asyncio.Task) -> None:
            exc = done_task.exception()
            if exc is not None:
                logger.exception("Background task for backup %s failed", backup_id, exc_info=exc)
            self._background_tasks.discard(done_task)

        task.add_done_callback(_done_callback)

    async def _run_backup(self, task: BackupTaskDTO) -> None:
        running = self._active[task.backup_id]
        if task.size_total > 0:
            running.size_total = task.size_total
        cleanup_cb = running.cleanup
        final_status: BackupStatus | None = None
        started_at = datetime.datetime.utcnow()
        await TaskStore.update_status(task.backup_id, status=BackupStatus.IN_PROGRESS, started_at=started_at)
        await self._publish_task_update()

        target = Path(task.target)
        await asyncio.to_thread(target.mkdir, parents=True, exist_ok=True)

        if not running.cancel_requested:
            process: asyncio.subprocess.Process | None = None
            consumer: asyncio.Task | None = None
            returncode: int | None = None
            try:
                process = await self._launch_rsync(Path(task.source), target)
                running.process = process
                consumer = asyncio.create_task(self._consume_rsync_output(task.backup_id, process.stdout, running))
                returncode = await process.wait()
                await consumer
                consumer = None
            except asyncio.CancelledError:
                running.cancel_requested = True
                final_status = BackupStatus.CANCELLED
            except Exception as exc:
                logger.exception("Backup %s failed: %s", task.backup_id, exc)
                final_status = BackupStatus.FAILED
            finally:
                if consumer:
                    consumer.cancel()
                    with suppress(asyncio.CancelledError):
                        await consumer

            if final_status is None:
                if running.cancel_requested:
                    final_status = BackupStatus.CANCELLED
                elif returncode == 0:
                    final_status = BackupStatus.COMPLETED
                else:
                    final_status = BackupStatus.FAILED
        else:
            final_status = BackupStatus.CANCELLED

        # Finalize task and publish progress
        progress_payload = await TaskStore.finalize(task.backup_id, status=final_status, started_at=started_at)
        if progress_payload:
            await self._progress.publish(task.backup_id, *progress_payload)
        await self._publish_task_update()

        # Cleanup
        if cleanup_cb:
            try:
                await cleanup_cb(final_status)
            except Exception as exc:
                logger.warning("Cleanup hook failed: %s", exc)
        self._active.pop(task.backup_id, None)

    async def _launch_rsync(self, source: Path, target: Path) -> asyncio.subprocess.Process:
        source_arg = f"{source}/" if source.is_dir() else str(source)
        target_arg = f"{target}/" if target.is_dir() else str(target)
        rsync_bin = find_rsync()
        if not rsync_bin:
            raise RuntimeError("rsync is required but not found. Please install rsync.")
        cmd = [
            rsync_bin,
            "-a",
            "--stats",
            "--bwlimit=3m",
            "--info=progress2",
            source_arg,
            target_arg,
        ]
        logger.info("Launching rsync: %s", " ".join(cmd))
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        return process

    async def _consume_rsync_output(
        self,
        backup_id: str,
        stream: asyncio.StreamReader | None,
        running: RunningBackup,
    ) -> None:
        if not stream:
            return
        buffer = ""
        while True:
            chunk = await stream.read(4096)
            if not chunk:
                break
            buffer += chunk.decode(errors="ignore").replace("\r", "\n")
            while True:
                newline = buffer.find("\n")
                if newline == -1:
                    break
                line, buffer = buffer[:newline], buffer[newline + 1 :]
                if line.strip():
                    await self._handle_rsync_output(backup_id, line.strip(), running)
        if buffer.strip():
            await self._handle_rsync_output(backup_id, buffer.strip(), running)

    async def _handle_rsync_output(self, backup_id: str, line: str, running: RunningBackup) -> None:
        """Parse `rsync --info=progress2 --stats` output and emit progress updates."""
        logger.debug("rsync[%s]: %s", backup_id[:8], line)
        parser = running.parser
        if parser is None:
            return

        progress, summary_updated = parser.parse_line(line)
        size_total_hint = parser.total_bytes or (running.size_total if running.size_total else None)

        if progress:
            if progress.total_bytes:
                size_total_hint = progress.total_bytes
            if size_total_hint:
                running.size_total = size_total_hint
            await self._update_progress(
                backup_id,
                size_completed=progress.transferred_bytes,
                size_total_hint=size_total_hint,
            )
            return

        if summary_updated:
            if size_total_hint:
                running.size_total = size_total_hint
            completed = parser.transferred_total
            await self._update_progress(
                backup_id,
                size_completed=completed,
                size_total_hint=size_total_hint,
            )

    async def _update_progress(
        self,
        backup_id: str,
        *,
        size_completed: int | None,
        size_total_hint: int | None = None,
        force_publish: bool = False,
    ) -> None:
        progress_payload = await TaskStore.update_progress(
            backup_id,
            size_completed=size_completed,
            size_total_hint=size_total_hint,
            force_publish=force_publish,
        )
        if progress_payload:
            size_completed_value, size_total_value = progress_payload
            await self._progress.publish(backup_id, size_completed_value, size_total_value)

