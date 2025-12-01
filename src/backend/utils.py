from __future__ import annotations

import datetime
import logging
import os
import platform
import shutil
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)

DEFAULT_MOUNT_ROOT = "/mnt"
MOUNT_PREFIX = "sd-backup"


def find_rsync() -> str:
    """Return the preferred rsync binary path or 'rsync' as fallback."""
    candidates = [
        "/usr/local/bin/rsync",
        "/opt/homebrew/bin/rsync",
        "/usr/bin/rsync",
        shutil.which("rsync"),
    ]
    return next((c for c in candidates if c and os.path.exists(c)), "rsync")


def check_rsync_available() -> None:
    """Check if rsync is available. Raises RuntimeError if not found."""
    rsync_bin = find_rsync()
    if not rsync_bin:
        raise RuntimeError("rsync is required but not found.")
    try:
        result = subprocess.run([rsync_bin, "--version"], capture_output=True, check=True, text=True)
        logger.info("Using %s via %s", result.stdout.split("\n", 1)[0], rsync_bin)
    except FileNotFoundError as exc:
        raise RuntimeError("rsync is required but not found.") from exc


def auto_backup_supported() -> bool:
    return platform.system() == "Linux"


def calculate_size(path: Path) -> int:
    """Calculate total size of a file or directory in bytes."""
    if path.is_file():
        try:
            return path.stat().st_size
        except OSError:
            return 0
    total = 0
    for root, _, files in os.walk(path):
        for name in files:
            try:
                total += (Path(root) / name).stat().st_size
            except OSError:
                pass
    return total


def resolve_target_path(uuid_value: str, fs_label: str, source_path: str, template: str) -> str:
    """Resolve target path template with device info and earliest file timestamp."""
    earliest_mtime = None
    try:
        for root, _, files in os.walk(source_path):
            for name in files:
                try:
                    mtime = os.path.getmtime(os.path.join(root, name))
                    if earliest_mtime is None or mtime < earliest_mtime:
                        earliest_mtime = mtime
                except OSError:
                    pass
    except Exception as exc:
        logger.warning("Error scanning %s for timestamps: %s", source_path, exc)

    dt = datetime.datetime.fromtimestamp(earliest_mtime) if earliest_mtime else datetime.datetime.now()
    return os.path.expanduser(
        template.format(
            date=dt.strftime("%Y%m%d"),
            hour=dt.strftime("%H"),
            minute=dt.strftime("%M"),
            uuid=uuid_value,
            uuid_short=uuid_value[:4] if len(uuid_value) >= 4 else uuid_value,
            fs_label=fs_label,
        )
    )


def find_mount_point(device_node: str) -> str | None:
    """Return existing mount point for device, or None if not mounted."""
    with open("/proc/mounts", "r", encoding="utf-8") as f:
        for line in f:
            parts = line.split()
            if parts and parts[0] == device_node:
                return os.path.realpath(parts[1])
    return None


def mount_device(device_node: str, uuid_value: str) -> tuple[str, bool]:
    """Mount device if not already mounted. Returns (mount_path, owned)."""
    if existing := find_mount_point(device_node):
        logger.info("Device %s already mounted at %s", device_node, existing)
        return existing, False

    mount_point = os.path.join(DEFAULT_MOUNT_ROOT, f"{MOUNT_PREFIX}-{uuid_value}")
    os.makedirs(mount_point, exist_ok=True)
    logger.info("Mounting %s to %s", device_node, mount_point)
    subprocess.run(["mount", device_node, mount_point], check=True)
    return os.path.realpath(mount_point), True


def unmount_device(mount_point: str) -> None:
    """Unmount device and remove temp mount directory if applicable."""
    try:
        subprocess.run(["umount", mount_point], check=True)
    except subprocess.CalledProcessError as exc:
        logger.warning("Failed to unmount %s: %s", mount_point, exc)
        return

    # Clean up temp mount dir
    try:
        path = Path(mount_point).resolve()
        root = Path(DEFAULT_MOUNT_ROOT).resolve()
        if path.parent == root and path.name.startswith(f"{MOUNT_PREFIX}-"):
            path.rmdir()
            logger.debug("Removed temporary mount directory %s", path)
    except (OSError, FileNotFoundError):
        pass
