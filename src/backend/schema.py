import strawberry
import asyncio
from typing import AsyncGenerator, List
from strawberry.types import Info
from backend.config import get_config, update_config as update_config_store
from backend.backup import BackupManager
import logging

logger = logging.getLogger(__name__)

# Global state for simplicity in this scale
backup_manager = BackupManager()
logs: List[str] = []

def add_log(message: str):
    logs.append(message)
    # In a real app, we might want to trim logs or persist them

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
    def current_status(self) -> BackupStatus:
        active = backup_manager.current_process is not None and backup_manager.current_process.poll() is None
        return BackupStatus(active=active, message="Backup in progress" if active else "Idle")

@strawberry.type
class Mutation:
    @strawberry.mutation
    def start_manual_backup(self, source: str, target: str) -> str:
        try:
            # Run in background or thread? 
            # perform_backup blocks until rsync finishes. We should run it in a thread so mutation returns immediately?
            # Or maybe the user expects it to block? Usually mutations return result.
            # But backup can take long.
            # Let's run it in a thread.
            import threading
            def run():
                try:
                    add_log(f"Starting backup from {source} to {target}")
                    backup_manager.perform_backup(source, target)
                    add_log("Backup finished successfully")
                except Exception as e:
                    add_log(f"Backup failed: {e}")

            t = threading.Thread(target=run, daemon=True)
            t.start()
            return "Backup started"
        except Exception as e:
            return f"Failed to start backup: {e}"

    @strawberry.mutation
    def cancel_backup(self) -> str:
        try:
            backup_manager.cancel_backup()
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
