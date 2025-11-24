import asyncio
import logging
from typing import AsyncGenerator, List, Set

import strawberry

from backend.backup import BackupManager
from backend.config import get_config, update_config as update_config_store

logger = logging.getLogger(__name__)

backup_manager = BackupManager()
logs: List[str] = []
_background_tasks: Set[asyncio.Task] = set()


def add_log(message: str):
    logs.append(message)


def _track_background_task(task: asyncio.Task):
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)


async def _run_manual_backup(source: str, target: str):
    try:
        add_log(f"Starting backup from {source} to {target}")
        await backup_manager.perform_backup(source, target)
        add_log("Backup finished successfully")
    except Exception as exc:
        add_log(f"Backup failed: {exc}")
        logger.exception("Manual backup failed")

@strawberry.type
class Config:
    mount_point_template: str
    target_path_template: str

@strawberry.type
class LogEntry:
    message: str

@strawberry.type
class BackupStatus:
    active: bool
    message: str

@strawberry.type
class Query:
    @strawberry.field
    def config(self) -> Config:
        runtime_config = get_config()
        return Config(
            mount_point_template=runtime_config.mount_point_template,
            target_path_template=runtime_config.target_path_template,
        )

    @strawberry.field
    def logs(self) -> List[LogEntry]:
        return [LogEntry(message=m) for m in logs]

    @strawberry.field
    async def current_status(self) -> BackupStatus:
        active = backup_manager.is_active()
        return BackupStatus(active=active, message="Backup in progress" if active else "Idle")

@strawberry.type
class Mutation:
    @strawberry.mutation
    async def start_manual_backup(self, source: str, target: str) -> str:
        if backup_manager.is_active():
            return "Backup already in progress"

        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = asyncio.get_event_loop()

        try:
            task = loop.create_task(_run_manual_backup(source, target))
            _track_background_task(task)
            return "Backup started"
        except Exception as e:
            logger.error(f"Failed to schedule manual backup: {e}")
            return f"Failed to start backup: {e}"

    @strawberry.mutation
    async def cancel_backup(self) -> str:
        try:
            await backup_manager.cancel_backup()
            add_log("Backup cancelled by user")
            return "Backup cancelled"
        except Exception as e:
            return f"Failed to cancel backup: {e}"

    @strawberry.mutation
    def update_config(self, key: str, value: str) -> str:
        key_map = {
            "mount_point_template": "mount_point_template",
            "target_path_template": "target_path_template",
        }
        if key not in key_map:
            return "Unsupported config key"
        kwargs = {key_map[key]: value}
        try:
            update_config_store(**kwargs)
            return "Config updated"
        except Exception as e:
            return f"Failed to update config: {e}"

@strawberry.type
class Subscription:
    @strawberry.subscription
    async def backup_progress(self) -> AsyncGenerator[str, None]:
        # Simple polling for logs or status changes for now
        # In a real rsync parsing scenario, we'd yield progress percentages.
        # Here we just yield new logs or status.
        last_idx = len(logs)
        while True:
            if len(logs) > last_idx:
                for i in range(last_idx, len(logs)):
                    yield logs[i]
                last_idx = len(logs)
            await asyncio.sleep(0.5)

schema = strawberry.Schema(query=Query, mutation=Mutation, subscription=Subscription)
