from __future__ import annotations

import asyncio
import datetime
import logging
import os
import shutil
import subprocess
import uuid
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import AsyncIterator, Awaitable, Callable, Dict, Optional

import pyudev
from sqlalchemy import select

from backend.config import get_config
from backend.db import BackupTaskRecord, session_scope
from backend.models import BackupStatus, BackupTaskDTO, BackupType

logger = logging.getLogger(__name__)

DEFAULT_MOUNT_ROOT = "/mnt"
MOUNT_PREFIX = "sd-backup"


class ProgressBus:
    def __init__(self):
        self._queues: Dict[str, set[asyncio.Queue]] = {}
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


@dataclass
class RunningBackup:
    task: asyncio.Task
    process: Optional[asyncio.subprocess.Process] = None
    output_consumer: Optional[asyncio.Task] = None
    cleanup: Optional[Callable[[BackupStatus], Awaitable[None]]] = None
    cancel_requested: bool = False


class BackupManager:
    def __init__(self):
        self._active: Dict[str, RunningBackup] = {}
        self._background_tasks: set[asyncio.Task] = set()
        self._progress = ProgressBus()

    # ------------------------------------------------------------------ #
    # Public API used by GraphQL
    # ------------------------------------------------------------------ #
    async def start_manual_backup(self, source: str, target: str) -> str:
        source_path = Path(source).expanduser().resolve()
        target_path = Path(target).expanduser().resolve()

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
        async with session_scope() as session:
            stmt = (
                select(BackupTaskRecord)
                .order_by(BackupTaskRecord.id.desc())
                .offset(offset)
                .limit(limit)
            )
            result = await session.execute(stmt)
            records = result.scalars().all()
            return [self._record_to_dto(record) for record in records]

    async def get_task(self, backup_id: str) -> Optional[BackupTaskDTO]:
        async with session_scope() as session:
            stmt = select(BackupTaskRecord).where(BackupTaskRecord.backup_id == backup_id)
            result = await session.execute(stmt)
            record = result.scalars().one_or_none()
            if record is None:
                return None
            return self._record_to_dto(record)

    # ------------------------------------------------------------------ #
    # Auto backup entry point (used by DeviceMonitor)
    # ------------------------------------------------------------------ #
    async def handle_device(self, device: pyudev.Device) -> Optional[str]:
        config = await get_config()
        if not config.auto_backup_enabled:
            logger.info("Auto backup disabled. Ignoring %s", device.device_node)
            return None

        mount_point = await self.mount_device(device)
        target_path = await self.resolve_target_path(device, mount_point, config.auto_backup_target_path)

        async def cleanup(_: BackupStatus) -> None:
            await self._unmount_path(mount_point)

        try:
            return await self._enqueue_backup(
                source=Path(mount_point),
                target=Path(target_path),
                backup_type=BackupType.AUTO,
                cleanup=cleanup,
            )
        except Exception:
            await cleanup(BackupStatus.FAILED)
            raise

    async def mount_device(self, device: pyudev.Device) -> str:
        device_node = device.device_node
        uuid_value = device.get("ID_FS_UUID", "unknown")
        return await asyncio.to_thread(self._mount_device_sync, device_node, uuid_value)

    def _mount_device_sync(self, device_node: str, uuid_value: str) -> str:
        with open("/proc/mounts", "r", encoding="utf-8") as mounts:
            for line in mounts:
                parts = line.split()
                if parts and parts[0] == device_node:
                    logger.info("Device %s already mounted at %s", device_node, parts[1])
                    return parts[1]

        mount_point = os.path.join(DEFAULT_MOUNT_ROOT, f"{MOUNT_PREFIX}-{uuid_value}")
        os.makedirs(mount_point, exist_ok=True)
        logger.info("Mounting %s to %s", device_node, mount_point)
        subprocess.run(["mount", device_node, mount_point], check=True)
        return mount_point

    async def _unmount_path(self, mount_point: str) -> None:
        await asyncio.to_thread(self._unmount_path_sync, mount_point)

    def _unmount_path_sync(self, mount_point: str) -> None:
        try:
            subprocess.run(["umount", mount_point], check=True)
        except subprocess.CalledProcessError as exc:
            logger.warning("Failed to unmount %s: %s", mount_point, exc)

    async def resolve_target_path(self, device: pyudev.Device, source_path: str, template: str) -> str:
        uuid_value = device.get("ID_FS_UUID", "unknown")
        return await asyncio.to_thread(self._resolve_target_path_sync, uuid_value, source_path, template)

    def _resolve_target_path_sync(self, uuid_value: str, source_path: str, template: str) -> str:
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
        cleanup: Optional[Callable[[BackupStatus], Awaitable[None]]] = None,
    ) -> str:
        size_total = 0
        backup_id = uuid.uuid4().hex
        await self._create_task_record(
            backup_id=backup_id,
            source=str(source),
            target=str(target),
            status=BackupStatus.PENDING,
            backup_type=backup_type,
            size_total=size_total,
        )

        job = asyncio.create_task(
            self._run_backup(
                backup_id=backup_id,
                source=source,
                target=target,
                size_total=size_total,
            )
        )
        running = RunningBackup(task=job, cleanup=cleanup)
        self._active[backup_id] = running
        self._track_background_task(job)
        return backup_id

    def _track_background_task(self, task: asyncio.Task) -> None:
        self._background_tasks.add(task)

        def _done_callback(done_task: asyncio.Task) -> None:
            self._background_tasks.discard(done_task)

        task.add_done_callback(_done_callback)

    async def _run_backup(self, *, backup_id: str, source: Path, target: Path, size_total: int) -> None:
        running = self._active[backup_id]
        cleanup_cb = running.cleanup
        final_status: Optional[BackupStatus] = None
        started_at = datetime.datetime.utcnow()
        await self._update_task(
            backup_id,
            status=BackupStatus.IN_PROGRESS,
            started_at=started_at,
        )

        await asyncio.to_thread(target.mkdir, parents=True, exist_ok=True)

        if running.cancel_requested:
            final_status = BackupStatus.CANCELLED
            await self._finalize_task(backup_id, final_status, started_at)
            await self._complete_cleanup(backup_id, cleanup_cb, final_status)
            return

        process: Optional[asyncio.subprocess.Process] = None
        consumer: Optional[asyncio.Task] = None
        returncode: Optional[int] = None
        try:
            try:
                process = await self._launch_rsync(source, target)
            except FileNotFoundError:
                logger.warning("rsync not found. Falling back to Python copy for %s", backup_id)
                await asyncio.to_thread(self._python_copy, source, target)
                process = None

            running.process = process
            if process:
                consumer = asyncio.create_task(
                    self._consume_rsync_output(backup_id, process.stdout)
                )
                running.output_consumer = consumer
                returncode = await process.wait()
                await consumer
                consumer = None
                running.output_consumer = None
            else:
                await self._emit_progress_placeholder(backup_id)
                returncode = 0
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

        await self._finalize_task(backup_id, final_status, started_at)
        await self._complete_cleanup(backup_id, cleanup_cb, final_status)

    async def _launch_rsync(self, source: Path, target: Path) -> asyncio.subprocess.Process:
        source_arg = f"{source}/" if source.is_dir() else str(source)
        target_arg = f"{target}/" if target.is_dir() else str(target)
        cmd = [
            "rsync",
            "-a",
            "--delete",
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
        stream: Optional[asyncio.StreamReader],
    ) -> None:
        if not stream:
            return
        while True:
            line = await stream.readline()
            if not line:
                break
            text = line.decode(errors="ignore").strip()
            if not text:
                continue
            await self._handle_rsync_output(backup_id, text)

    async def _handle_rsync_output(self, backup_id: str, line: str) -> None:
        """Placeholder for parsing `rsync --info=progress2` lines."""
        # TODO: Parse real progress metrics from rsync --info=progress2 output.
        logger.debug("rsync[%s]: %s", backup_id[:8], line)
        await self._emit_progress_placeholder(backup_id)

    def _python_copy(self, source: Path, target: Path) -> None:
        if source.is_file():
            shutil.copy2(source, target / source.name)
            return
        for root, dirs, files in os.walk(source):
            rel_root = Path(root).relative_to(source)
            dest_dir = target / rel_root
            dest_dir.mkdir(parents=True, exist_ok=True)
            for file_name in files:
                src_file = Path(root) / file_name
                dest_file = dest_dir / file_name
                shutil.copy2(src_file, dest_file)

    async def _update_task(
        self,
        backup_id: str,
        *,
        status: BackupStatus,
        started_at: Optional[datetime.datetime] = None,
    ) -> None:
        async with session_scope() as session:
            stmt = select(BackupTaskRecord).where(BackupTaskRecord.backup_id == backup_id)
            result = await session.execute(stmt)
            record = result.scalars().one_or_none()
            if record is None:
                return
            record.status = status.value
            if started_at is not None:
                record.started_at = started_at
            session.add(record)

    async def _finalize_task(
        self,
        backup_id: str,
        status: BackupStatus,
        started_at: datetime.datetime,
    ) -> None:
        finished_at = datetime.datetime.utcnow()
        async with session_scope() as session:
            stmt = select(BackupTaskRecord).where(BackupTaskRecord.backup_id == backup_id)
            result = await session.execute(stmt)
            record = result.scalars().one_or_none()
            if record is None:
                return
            record.status = status.value
            record.started_at = record.started_at or started_at
            record.finished_at = finished_at
            session.add(record)
            size_total = record.size_total
            size_completed = record.size_completed
        await self._progress.publish(backup_id, size_completed, size_total)

    async def _create_task_record(
        self,
        *,
        backup_id: str,
        source: str,
        target: str,
        status: BackupStatus,
        backup_type: BackupType,
        size_total: int,
    ) -> None:
        created_at = datetime.datetime.utcnow()
        async with session_scope() as session:
            record = BackupTaskRecord(
                backup_id=backup_id,
                source=source,
                target=target,
                status=status.value,
                type=backup_type.value,
                started_at=created_at,
                finished_at=None,
                size_total=size_total,
                size_completed=0,
            )
            session.add(record)

    async def _emit_progress_placeholder(self, backup_id: str) -> None:
        await self._progress.publish(backup_id, 0, 0)

    async def _complete_cleanup(
        self,
        backup_id: str,
        cleanup_cb: Optional[Callable[[BackupStatus], Awaitable[None]]],
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

    def _record_to_dto(self, record: BackupTaskRecord) -> BackupTaskDTO:
        return BackupTaskDTO(
            backup_id=record.backup_id,
            source=record.source,
            target=record.target,
            status=BackupStatus(record.status),
            type=BackupType(record.type),
            started_at=record.started_at,
            finished_at=record.finished_at,
            size_total=record.size_total,
            size_completed=record.size_completed,
        )
