import asyncio
import datetime
import logging
import os
import subprocess
from typing import Optional

import pyudev

from backend.config import get_config

logger = logging.getLogger(__name__)


class BackupManager:
    def __init__(self):
        self.current_process: Optional[asyncio.subprocess.Process] = None
        self._lock = asyncio.Lock()

    def is_active(self) -> bool:
        process = self.current_process
        return process is not None and process.returncode is None

    async def mount_device(self, device: pyudev.Device) -> str:
        device_node = device.device_node
        uuid = device.get("ID_FS_UUID", "unknown")
        return await asyncio.to_thread(self._mount_device_sync, device_node, uuid)

    def _mount_device_sync(self, device_node: str, uuid: str) -> str:
        with open("/proc/mounts", "r") as f:
            for line in f:
                parts = line.split()
                if parts[0] == device_node:
                    logger.info(f"Device {device_node} already mounted at {parts[1]}")
                    return parts[1]

        runtime_config = get_config()
        mount_point_template = runtime_config.mount_point_template
        mount_point = mount_point_template.format(uuid=uuid)

        if not os.path.exists(mount_point):
            os.makedirs(mount_point, exist_ok=True)

        logger.info(f"Mounting {device_node} to {mount_point}")
        subprocess.run(["mount", device_node, mount_point], check=True)
        return mount_point

    async def resolve_target_path(self, device: pyudev.Device, source_path: str) -> str:
        uuid = device.get("ID_FS_UUID", "unknown")
        return await asyncio.to_thread(self._resolve_target_path_sync, uuid, source_path)

    def _resolve_target_path_sync(self, uuid: str, source_path: str) -> str:
        runtime_config = get_config()
        target_template = runtime_config.target_path_template
        uuid_short = uuid[:4] if len(uuid) >= 4 else uuid

        earliest_mtime = None
        try:
            for root, dirs, files in os.walk(source_path):
                for name in files:
                    filepath = os.path.join(root, name)
                    try:
                        mtime = os.path.getmtime(filepath)
                        if earliest_mtime is None or mtime < earliest_mtime:
                            earliest_mtime = mtime
                    except OSError:
                        continue
        except Exception as e:
            logger.warning(f"Error scanning files for mtime: {e}")

        if earliest_mtime:
            dt = datetime.datetime.fromtimestamp(earliest_mtime)
        else:
            dt = datetime.datetime.now()

        date_str = dt.strftime("%Y%m%d")
        hour_str = dt.strftime("%H")
        minute_str = dt.strftime("%M")

        target_path = target_template.format(
            date=date_str,
            hour=hour_str,
            minute=minute_str,
            uuid=uuid,
            uuid_short=uuid_short,
        )
        return os.path.expanduser(target_path)

    async def perform_backup(self, source: str, target: str) -> None:
        async with self._lock:
            if self.is_active():
                raise RuntimeError("A backup is already in progress.")

            await asyncio.to_thread(os.makedirs, target, exist_ok=True)
            cmd = ["rsync", "-av", "--info=progress2", f"{source}/", f"{target}/"]
            logger.info(f"Starting backup: {' '.join(cmd)}")

            self.current_process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )

        try:
            if self.current_process and self.current_process.stdout:
                while True:
                    line = await self.current_process.stdout.readline()
                    if not line:
                        break
                    decoded = line.decode().strip()
                    if decoded:
                        logger.debug(f"rsync: {decoded}")

            if self.current_process:
                returncode = await self.current_process.wait()
                if returncode != 0:
                    raise subprocess.CalledProcessError(returncode, cmd)

            logger.info("Backup completed successfully.")
        except Exception as e:
            logger.error(f"Backup failed: {e}")
            raise
        finally:
            self.current_process = None

    async def cancel_backup(self):
        process = self.current_process
        if not process or process.returncode is not None:
            logger.info("No backup to cancel.")
            return

        logger.info("Cancelling backup...")
        process.terminate()
        try:
            await asyncio.wait_for(process.wait(), timeout=5)
        except asyncio.TimeoutError:
            process.kill()
            await process.wait()
        finally:
            self.current_process = None
            logger.info("Backup cancelled.")
