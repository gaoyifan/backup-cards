from __future__ import annotations

import datetime
import json
import logging
import os
import platform
import shutil
import subprocess
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

DEFAULT_MOUNT_ROOT = "/mnt"
MOUNT_PREFIX = "sd-backup"
EXIFTOOL_BIN = os.environ.get("EXIFTOOL_BIN", "exiftool")
IMAGE_EXTENSIONS = frozenset({".jpg", ".jpeg", ".dng", ".hif"})
VIDEO_EXTENSIONS = frozenset({".mp4"})
IMAGE_FIELD_ORDER = ("ProductName", "UniqueCameraModel", "Model", "SonyModelID")
VIDEO_FIELD_ORDER = ("Encoder", "DeviceModelName")
_missing_exiftool_warned = False


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
    dt = _find_earliest_timestamp(source_path)
    model_value = _find_exif_tag(source_path, IMAGE_EXTENSIONS, IMAGE_FIELD_ORDER) or _find_exif_tag(
        source_path, VIDEO_EXTENSIONS, VIDEO_FIELD_ORDER
    )
    return os.path.expanduser(
        template.format(
            date=dt.strftime("%Y%m%d"),
            hour=dt.strftime("%H"),
            minute=dt.strftime("%M"),
            uuid=uuid_value,
            uuid_short=uuid_value[:4] if len(uuid_value) >= 4 else uuid_value,
            fs_label=fs_label,
            model=model_value or "UNKNOWN",
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


def _find_earliest_timestamp(source_path: str, *, now: datetime.datetime | None = None) -> datetime.datetime:
    """Pick the earliest mtime preferring files from the last year, then five years, then ≥1980."""
    now = now or datetime.datetime.now()
    tzinfo = now.tzinfo
    one_year_ago = now - datetime.timedelta(days=365)
    five_years_ago = now - datetime.timedelta(days=5 * 365)
    baseline = datetime.datetime(1980, 1, 1, tzinfo=tzinfo)

    mtimes: list[float] = []
    try:
        for root, _, files in os.walk(source_path):
            for name in files:
                try:
                    mtimes.append(os.path.getmtime(os.path.join(root, name)))
                except OSError:
                    continue
    except Exception as exc:
        logger.warning("Error scanning %s for timestamps: %s", source_path, exc)
    if not mtimes:
        return now

    mtimes.sort()
    thresholds = (
        (one_year_ago.timestamp(), float("inf")),
        (five_years_ago.timestamp(), one_year_ago.timestamp()),
        (baseline.timestamp(), five_years_ago.timestamp()),
    )
    for lower, upper in thresholds:
        candidate = next((ts for ts in mtimes if lower <= ts < upper), None)
        if candidate is not None:
            return datetime.datetime.fromtimestamp(candidate, tz=tzinfo)
    return now


def _find_exif_tag(source_path: str, extensions: frozenset[str], tag_order: tuple[str, ...]) -> str | None:
    try:
        for root, _, files in os.walk(source_path):
            for name in files:
                ext = os.path.splitext(name)[1].lower()
                if ext not in extensions:
                    continue
                metadata = _read_metadata(os.path.join(root, name))
                if not metadata:
                    continue
                for field in tag_order:
                    value = metadata.get(field)
                    if isinstance(value, list):
                        value = value[0] if value else ""
                    if value is None:
                        continue
                    text = str(value).strip().strip("\x00")
                    if text:
                        return text
    except Exception as exc:  # pragma: no cover - filesystem edge cases
        logger.debug("Error scanning %s for media metadata: %s", source_path, exc)
    return None


def _read_metadata(path: str) -> dict[str, Any]:
    global _missing_exiftool_warned
    try:
        result = subprocess.run(
            [EXIFTOOL_BIN, "-json", path],
            capture_output=True,
            check=True,
            text=True,
        )
    except FileNotFoundError:
        if not _missing_exiftool_warned:
            logger.warning("exiftool binary not found; {model} template variable will remain empty.")
            _missing_exiftool_warned = True
        return {}
    except subprocess.CalledProcessError as exc:  # pragma: no cover - depends on external tool
        logger.debug("exiftool failed for %s: %s", path, exc)
        return {}

    try:
        parsed = json.loads(result.stdout or "[]")
    except json.JSONDecodeError:  # pragma: no cover - malformed tool output
        logger.debug("Failed to parse exiftool output for %s", path)
        return {}

    if isinstance(parsed, list) and parsed:
        first = parsed[0]
        if isinstance(first, dict):
            return first

    return {}
