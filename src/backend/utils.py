from __future__ import annotations

import datetime
import logging
import os
import platform
import shutil
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)


def find_rsync() -> str:
    """Return the preferred rsync binary path or 'rsync' as fallback."""
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


def calculate_size(path: Path) -> int:
    """Calculate total size of a file or directory in bytes."""
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


def resolve_target_path(uuid_value: str, fs_label: str, source_path: str, template: str) -> str:
    """Resolve target path template with device info and earliest file timestamp."""
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

    dt = datetime.datetime.fromtimestamp(earliest_mtime) if earliest_mtime else datetime.datetime.now()
    target_path = template.format(
        date=dt.strftime("%Y%m%d"),
        hour=dt.strftime("%H"),
        minute=dt.strftime("%M"),
        uuid=uuid_value,
        uuid_short=uuid_short,
        fs_label=fs_label,
    )
    return os.path.expanduser(target_path)
