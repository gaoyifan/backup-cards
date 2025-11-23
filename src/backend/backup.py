import subprocess
import os
import logging
import datetime
import shutil
import pyudev
from typing import Optional
from config import load_config

logger = logging.getLogger(__name__)

class BackupManager:
    def __init__(self):
        self.current_process: Optional[subprocess.Popen] = None

    def mount_device(self, device: pyudev.Device) -> str:
        """
        Mounts the device if not already mounted.
        Returns the mount point path.
        """
        # Check if already mounted
        # device.device_node is like /dev/sdb1
        # We can check /proc/mounts or use psutil, but let's stick to simple checks or udisks if needed.
        # For simplicity and root assumption, we can use `mount` command.
        
        # First check if it's already mounted
        with open("/proc/mounts", "r") as f:
            for line in f:
                parts = line.split()
                if parts[0] == device.device_node:
                    logger.info(f"Device {device.device_node} already mounted at {parts[1]}")
                    return parts[1]

        config = load_config()
        uuid = device.get("ID_FS_UUID", "unknown")
        mount_point_template = config.get("mount_point_template", "/media/sd-backup-{uuid}")
        mount_point = mount_point_template.format(uuid=uuid)

        if not os.path.exists(mount_point):
            os.makedirs(mount_point, exist_ok=True)

        logger.info(f"Mounting {device.device_node} to {mount_point}")
        try:
            subprocess.run(["mount", device.device_node, mount_point], check=True)
            return mount_point
        except subprocess.CalledProcessError as e:
            logger.error(f"Failed to mount device: {e}")
            raise

    def resolve_target_path(self, device: pyudev.Device, source_path: str) -> str:
        config = load_config()
        target_template = config.get("target_path_template", "~/backups/{date}")
        
        # Get UUID
        uuid = device.get("ID_FS_UUID", "unknown")
        uuid_short = uuid[:4] if len(uuid) >= 4 else uuid

        # Scan for earliest modification time
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
                # Just scan top level or shallow? "among the files on the storage card" implies potentially all.
                # But walking deep might be slow. Let's assume we walk.
                # Optimization: maybe just check the root dir files or stop after some limit?
                # User requirement: "earliest modification time among the files".
                pass
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
            uuid_short=uuid_short
        )
        
        # Expand user tilde
        target_path = os.path.expanduser(target_path)
        return target_path

    def perform_backup(self, source: str, target: str) -> None:
        if self.current_process and self.current_process.poll() is None:
            raise RuntimeError("A backup is already in progress.")

        if not os.path.exists(target):
            os.makedirs(target, exist_ok=True)

        cmd = ["rsync", "-av", "--info=progress2", source + "/", target + "/"]
        logger.info(f"Starting backup: {' '.join(cmd)}")

        try:
            self.current_process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True
            )
            
            # We are not parsing output, but we need to consume it to prevent buffer filling?
            # Or just let it run. If we don't read, it might block if buffer fills.
            # We should probably read it and maybe log it or just discard it if user said "No output parsing".
            # User said "Remove this feature" regarding "Parse output for progress updates".
            # But we still need to ensure the process runs smoothly.
            # Let's read line by line and log debug.
            if self.current_process.stdout:
                for line in self.current_process.stdout:
                    logger.debug(f"rsync: {line.strip()}")
            
            self.current_process.wait()
            
            if self.current_process.returncode != 0:
                raise subprocess.CalledProcessError(self.current_process.returncode, cmd)
            
            logger.info("Backup completed successfully.")

        except Exception as e:
            logger.error(f"Backup failed: {e}")
            raise
        finally:
            self.current_process = None

    def cancel_backup(self):
        if self.current_process and self.current_process.poll() is None:
            logger.info("Cancelling backup...")
            self.current_process.terminate()
            try:
                self.current_process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.current_process.kill()
            logger.info("Backup cancelled.")
        else:
            logger.info("No backup to cancel.")
