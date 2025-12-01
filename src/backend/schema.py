from __future__ import annotations

import logging
import os
from datetime import datetime
from pathlib import Path
from typing import AsyncGenerator, List, Optional

import strawberry

from backend.backup import BackupManager, task_event_bus
from backend.utils import auto_backup_supported
from backend.config import Config, get_config, update_config
from backend.devices import device_event_bus, list_available_devices
from backend.models import BackupStatus, BackupTaskDTO, BackupType, DeviceInfo

logger = logging.getLogger(__name__)

backup_manager = BackupManager()

BackupStatusEnum = strawberry.enum(BackupStatus, name="BackupStatus")
BackupTypeEnum = strawberry.enum(BackupType, name="BackupType")


@strawberry.type
class ConfigType:
    auto_backup_enabled: bool = strawberry.field(name="autoBackupEnabled")
    auto_backup_target_path: str = strawberry.field(name="autoBackupTargetPath")
    auto_backup_supported: bool = strawberry.field(name="autoBackupSupported")


@strawberry.input
class ConfigInput:
    auto_backup_enabled: Optional[bool] = strawberry.field(name="autoBackupEnabled", default=None)
    auto_backup_target_path: Optional[str] = strawberry.field(name="autoBackupTargetPath", default=None)


@strawberry.type
class BackupTaskType:
    backup_id: strawberry.ID = strawberry.field(name="backupId")
    source: str
    target: str
    status: BackupStatusEnum
    type: BackupTypeEnum
    started_at: datetime = strawberry.field(name="startedAt")
    finished_at: Optional[datetime] = strawberry.field(name="finishedAt")
    size_total: int = strawberry.field(name="sizeTotal")
    size_completed: int = strawberry.field(name="sizeCompleted")


@strawberry.type
class BackupProgressType:
    size_completed: int = strawberry.field(name="sizeCompleted")
    size_total: int = strawberry.field(name="sizeTotal")


@strawberry.type
class DeviceType:
    device_path: str = strawberry.field(name="devicePath")
    mount_point: Optional[str] = strawberry.field(name="mountPoint")


def _config_to_type(config: Config) -> ConfigType:
    return ConfigType(
        auto_backup_enabled=config.auto_backup_enabled,
        auto_backup_target_path=config.auto_backup_target_path,
        auto_backup_supported=auto_backup_supported(),
    )


def _task_to_type(task: BackupTaskDTO) -> BackupTaskType:
    started_at = task.started_at or datetime.utcnow()
    return BackupTaskType(
        backup_id=task.backup_id,
        source=task.source,
        target=task.target,
        status=task.status,
        type=task.type,
        started_at=started_at,
        finished_at=task.finished_at,
        size_total=task.size_total,
        size_completed=task.size_completed,
    )


def _device_to_type(device: DeviceInfo) -> DeviceType:
    return DeviceType(device_path=device.device_path, mount_point=device.mount_point)


def _safe_list_directory(path: str) -> List[str]:
    path_obj = Path(path).expanduser()
    if not path_obj.exists():
        return []
    if path_obj.is_file():
        path_obj = path_obj.parent
    try:
        entries = os.listdir(path_obj)
    except OSError as exc:
        logger.warning("Unable to list directory %s: %s", path_obj, exc)
        return []
    return sorted(entries)


@strawberry.type
class Query:
    @strawberry.field
    async def config(self) -> ConfigType:
        runtime_config = await get_config()
        return _config_to_type(runtime_config)

    @strawberry.field
    async def backup_tasks(self, limit: int = 20, offset: int = 0) -> List[BackupTaskType]:
        tasks = await backup_manager.list_tasks(limit=limit, offset=offset)
        return [_task_to_type(task) for task in tasks]

    @strawberry.field
    async def backup_task(self, backup_id: strawberry.ID) -> Optional[BackupTaskType]:
        task = await backup_manager.get_task(str(backup_id))
        if task is None:
            return None
        return _task_to_type(task)

    @strawberry.field
    def available_devices(self) -> List[DeviceType]:
        devices = list_available_devices()
        return [_device_to_type(device) for device in devices]

    @strawberry.field
    def list_directory(self, path: str) -> List[str]:
        return _safe_list_directory(path)


@strawberry.type
class Mutation:
    @strawberry.mutation
    async def start_manual_backup(self, source: str, target: str) -> strawberry.ID:
        backup_id = await backup_manager.start_manual_backup(source, target)
        return strawberry.ID(backup_id)

    @strawberry.mutation
    async def cancel_backup(self, backup_id: strawberry.ID) -> bool:
        return await backup_manager.cancel_backup(str(backup_id))

    @strawberry.mutation
    async def update_config(self, config: ConfigInput) -> bool:
        await update_config(
            auto_backup_enabled=config.auto_backup_enabled,
            auto_backup_target_path=config.auto_backup_target_path,
        )
        return True


@strawberry.type
class Subscription:
    @strawberry.subscription
    async def progress(self, backup_id: strawberry.ID) -> AsyncGenerator[BackupProgressType, None]:
        async for size_completed, size_total in backup_manager.subscribe_progress(str(backup_id)):
            yield BackupProgressType(size_completed=size_completed, size_total=size_total)

    @strawberry.subscription
    async def backup_tasks_updated(self) -> AsyncGenerator[List[BackupTaskType], None]:
        # Emit initial state
        tasks = await backup_manager.list_tasks(limit=50)
        yield [_task_to_type(task) for task in tasks]
        # Stream updates
        async for tasks in task_event_bus.stream():
            yield [_task_to_type(task) for task in tasks]

    @strawberry.subscription
    async def devices_updated(self) -> AsyncGenerator[List[DeviceType], None]:
        # Emit initial state
        devices = list_available_devices()
        yield [_device_to_type(device) for device in devices]
        # Stream updates
        async for devices in device_event_bus.stream():
            yield [_device_to_type(device) for device in devices]


schema = strawberry.Schema(query=Query, mutation=Mutation, subscription=Subscription)
