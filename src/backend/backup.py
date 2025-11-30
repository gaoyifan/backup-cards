from __future__ import annotations

import asyncio
import datetime
import logging
import os
import platform
import shutil
import subprocess
import uuid
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

logger = logging.getLogger(__name__)

DEFAULT_MOUNT_ROOT = "/mnt"
MOUNT_PREFIX = "sd-backup"


def find_rsync() -> str:
    """Return the preferred rsync binary path or empty string if not found."""
    candidates = [
        "/usr/local/bin/rsync",  # Homebrew (Intel)
        "/opt/homebrew/bin/rsync",  # Homebrew (Apple Silicon)
        "/usr/bin/rsync",  # macOS built-in (older)
        shutil.which("rsync"),
    ]
    for candidate in candidates:
        if candidate and os.path.exists(candidate):
            return candidate
    return "rsync"


def check_rsync_available() -> None:
    """Check if rsync is available. Raises RuntimeError if not found."""
    rsync_bin = find_rsync()
    if not rsync_bin:
        raise RuntimeError("rsync is required but not found. Please install rsync.")
    try:
        result = subprocess.run([rsync_bin, "--version"], capture_output=True, check=True, text=True)
        version_line = result.stdout.split("\n", 1)[0]
        logger.info("Using %s via %s", version_line, rsync_bin)
    except FileNotFoundError as exc:
        raise RuntimeError("rsync is required but not found. Please install rsync.") from exc


def auto_backup_supported() -> bool:
    """Return True if auto-backup is supported on this platform."""
    return platform.system() == "Linux"


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
        self._tasks = TaskStore()

    async def fail_stale_tasks(self) -> int:
        """Mark all PENDING/IN_PROGRESS tasks as FAILED on startup (stale from previous run)."""
        count = await self._tasks.fail_stale_tasks([BackupStatus.PENDING, BackupStatus.IN_PROGRESS])
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
            return await self._backup_from_mount(mount, target_path, BackupType.MANUAL)

        # Regular directory/file backup
        source_path = source_path.expanduser().resolve()
        if not source_path.exists():
            raise FileNotFoundError(f"Source path {source_path} does not exist.")
        return await self._enqueue_backup(
            source=source_path,
            target=target_path,
            backup_type=BackupType.MANUAL,
        )

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
        return await self._tasks.list(limit=limit, offset=offset)

    async def get_task(self, backup_id: str) -> BackupTaskDTO | None:
        return await self._tasks.get(backup_id)

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
        target_path = await self.resolve_target_path(device, mount.path, config.auto_backup_target_path)
        return await self._backup_from_mount(mount, Path(target_path), BackupType.AUTO)

    async def _backup_from_mount(
        self,
        mount: MountHandle,
        target: Path,
        backup_type: BackupType,
    ) -> str:
        """Shared device backup logic: backup from mount point with unmount cleanup."""
        cleanup: Callable[[BackupStatus], Awaitable[None]] | None = None
        if mount.owned:
            cleanup = lambda _: self._unmount_path(mount.path)
        try:
            return await self._enqueue_backup(
                source=Path(mount.path),
                target=target,
                backup_type=backup_type,
                cleanup=cleanup,
            )
        except Exception:
            if cleanup:
                await cleanup(BackupStatus.FAILED)
            raise

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

    async def resolve_target_path(self, device: pyudev.Device, source_path: str, template: str) -> str:
        uuid_value = device.get("ID_FS_UUID", "unknown")
        fs_label = device.get("ID_FS_LABEL_ENC", "")
        return await asyncio.to_thread(self._resolve_target_path_sync, uuid_value, fs_label, source_path, template)

    def _resolve_target_path_sync(self, uuid_value: str, fs_label: str, source_path: str, template: str) -> str:
        uuid_short = uuid_value[:4] if len(uuid_value) >= 4 else uuid_value
        earliest_mtime = None
        try:
            for root, _, files in os.walk(source_path):
                for name in files:
                    filepath = os.path.join(root, name)
                    try:
                        mtime = os.path.getmtime(filepath)
                    except OSError:
                        continue
                    if earliest_mtime is None or mtime < earliest_mtime:
                        earliest_mtime = mtime
        except Exception as exc:
            logger.warning("Error scanning %s for timestamps: %s", source_path, exc)

        if earliest_mtime:
            dt = datetime.datetime.fromtimestamp(earliest_mtime)
        else:
            dt = datetime.datetime.now()

        date_str = dt.strftime("%Y%m%d")
        hour_str = dt.strftime("%H")
        minute_str = dt.strftime("%M")
        target_path = template.format(
            date=date_str,
            hour=hour_str,
            minute=minute_str,
            uuid=uuid_value,
            uuid_short=uuid_short,
            fs_label=fs_label,
        )
        return os.path.expanduser(target_path)

    # ------------------------------------------------------------------ #
    # Internal helpers
    # ------------------------------------------------------------------ #
    async def _enqueue_backup(
        self,
        *,
        source: Path,
        target: Path,
        backup_type: BackupType,
        cleanup: Callable[[BackupStatus], Awaitable[None]] | None = None,
    ) -> str:
        size_total = await asyncio.to_thread(self._calculate_size_total, source)
        backup_id = uuid.uuid4().hex
        logger.debug("Creating task record for backup %s", backup_id)
        await self._tasks.create(
            backup_id=backup_id,
            source=str(source),
            target=str(target),
            status=BackupStatus.PENDING,
            backup_type=backup_type,
            size_total=size_total,
        )
        await self._publish_task_update()

        logger.debug("Enqueuing backup %s", backup_id)
        running = RunningBackup(cleanup=cleanup, parser=RsyncOutputParser(), size_total=size_total)
        self._active[backup_id] = running
        job = asyncio.create_task(
            self._run_backup(
                backup_id=backup_id,
                source=source,
                target=target,
                size_total=size_total,
            )
        )
        self._track_background_task(backup_id, job)
        return backup_id

    def _track_background_task(self, backup_id: str, task: asyncio.Task) -> None:
        self._background_tasks.add(task)

        def _done_callback(done_task: asyncio.Task) -> None:
            exc = done_task.exception()
            if exc is not None:
                logger.exception("Background task for backup %s failed", backup_id, exc_info=exc)
            self._background_tasks.discard(done_task)

        task.add_done_callback(_done_callback)

    async def _run_backup(self, *, backup_id: str, source: Path, target: Path, size_total: int) -> None:
        logger.debug("Background coroutine started for backup %s", backup_id)
        running = self._active[backup_id]
        if size_total and size_total > 0:
            running.size_total = size_total
        cleanup_cb = running.cleanup
        final_status: BackupStatus | None = None
        started_at = datetime.datetime.utcnow()
        logger.debug("Backup %s transitioning to IN_PROGRESS", backup_id)
        await self._tasks.update_status(
            backup_id,
            status=BackupStatus.IN_PROGRESS,
            started_at=started_at,
        )
        await self._publish_task_update()
        logger.debug("Backup %s marked IN_PROGRESS", backup_id)

        await asyncio.to_thread(target.mkdir, parents=True, exist_ok=True)

        if running.cancel_requested:
            await self._finish_backup(backup_id, BackupStatus.CANCELLED, started_at, cleanup_cb)
            return

        process: asyncio.subprocess.Process | None = None
        consumer: asyncio.Task | None = None
        returncode: int | None = None
        try:
            process = await self._launch_rsync(source, target)
            running.process = process
            consumer = asyncio.create_task(self._consume_rsync_output(backup_id, process.stdout, running))
            returncode = await process.wait()
            await consumer
            consumer = None
        except asyncio.CancelledError:
            running.cancel_requested = True
            final_status = BackupStatus.CANCELLED
        except Exception as exc:
            logger.exception("Backup %s failed: %s", backup_id, exc)
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
        await self._finish_backup(backup_id, final_status, started_at, cleanup_cb)

    async def _finish_backup(
        self,
        backup_id: str,
        final_status: BackupStatus,
        started_at: datetime.datetime,
        cleanup_cb: Callable[[BackupStatus], Awaitable[None]] | None,
    ) -> None:
        await self._finalize_task(backup_id, final_status, started_at)
        await self._publish_task_update()
        await self._complete_cleanup(backup_id, cleanup_cb, final_status)

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

    async def _finalize_task(
        self,
        backup_id: str,
        status: BackupStatus,
        started_at: datetime.datetime,
    ) -> None:
        progress_payload = await self._tasks.finalize(
            backup_id,
            status=status,
            started_at=started_at,
        )
        if progress_payload:
            size_completed, size_total = progress_payload
            await self._progress.publish(backup_id, size_completed, size_total)

    async def _update_progress(
        self,
        backup_id: str,
        *,
        size_completed: int | None,
        size_total_hint: int | None = None,
        force_publish: bool = False,
    ) -> None:
        progress_payload = await self._tasks.update_progress(
            backup_id,
            size_completed=size_completed,
            size_total_hint=size_total_hint,
            force_publish=force_publish,
        )
        if progress_payload:
            size_completed_value, size_total_value = progress_payload
            await self._progress.publish(backup_id, size_completed_value, size_total_value)

    async def _complete_cleanup(
        self,
        backup_id: str,
        cleanup_cb: Callable[[BackupStatus], Awaitable[None]] | None,
        final_status: BackupStatus,
    ) -> None:
        if cleanup_cb:
            await self._invoke_cleanup(cleanup_cb, final_status)
        self._active.pop(backup_id, None)

    async def _invoke_cleanup(
        self,
        cleanup_cb: Callable[[BackupStatus], Awaitable[None]],
        final_status: BackupStatus,
    ) -> None:
        try:
            await cleanup_cb(final_status)
        except Exception as exc:
            logger.warning("Cleanup hook for %s failed: %s", final_status.value, exc)

    def _calculate_size_total(self, path: Path) -> int:
        if path.is_file():
            try:
                return path.stat().st_size
            except OSError:
                return 0

        total_size = 0
        for root, _, files in os.walk(path):
            for file_name in files:
                file_path = Path(root) / file_name
                try:
                    total_size += file_path.stat().st_size
                except OSError:
                    continue
        return total_size
