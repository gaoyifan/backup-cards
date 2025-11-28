from __future__ import annotations

import asyncio
import logging
from typing import AsyncIterator, Dict, List, Optional

import pyudev

from backend.models import DeviceInfo

logger = logging.getLogger(__name__)


def is_storage_device(device: pyudev.Device, action: Optional[str] = None) -> bool:
    """Check if device matches storage device criteria for auto-backup.

    Args:
        device: pyudev Device to check
        action: Expected device action (e.g., 'add' for new devices, None for existing).
    """
    try:
        return all([
            device.subsystem == "block",
            getattr(device, "action") == action,
            device.device_type == "partition",
            device.get("ID_BUS") in {"usb", "mmc"},
            device.sys_number == "1",
            device.get("ID_FS_TYPE", "").lower() in {"exfat", "vfat", "udf"},
        ])
    except Exception as e:
        logger.error(f"Error matching device: {e}")
        return False


class DeviceEventBus:
    """Pub/sub bus for device list updates."""

    def __init__(self):
        self._queues: set[asyncio.Queue] = set()
        self._lock = asyncio.Lock()

    async def publish(self, devices: List[DeviceInfo]) -> None:
        async with self._lock:
            queues = list(self._queues)
        for queue in queues:
            queue.put_nowait(devices)

    async def stream(self) -> AsyncIterator[List[DeviceInfo]]:
        queue: asyncio.Queue = asyncio.Queue()
        async with self._lock:
            self._queues.add(queue)

        try:
            while True:
                yield await queue.get()
        finally:
            async with self._lock:
                self._queues.discard(queue)


# Global device event bus instance
device_event_bus = DeviceEventBus()


async def publish_device_update() -> None:
    """Fetch current device list and publish to subscribers."""
    devices = list_available_devices()
    await device_event_bus.publish(devices)


def list_available_devices() -> List[DeviceInfo]:
    """Return detected removable block devices."""
    context = pyudev.Context()
    mounts = _current_mounts()
    devices: List[DeviceInfo] = []

    for device in context.list_devices(subsystem="block", DEVTYPE="partition"):
        device_path = getattr(device, "device_node", None)
        if not device_path:
            continue
        bus = device.get("ID_BUS")
        if bus not in {"usb", "mmc"}:
            continue
        mount_point = mounts.get(device_path)
        devices.append(DeviceInfo(device_path=device_path, mount_point=mount_point))
    return devices


def get_device_by_path(device_path: str) -> Optional[pyudev.Device]:
    """Get a pyudev Device object from a device path like /dev/sda1."""
    context = pyudev.Context()
    try:
        return pyudev.Devices.from_device_file(context, device_path)
    except (pyudev.DeviceNotFoundByFileError, ValueError) as exc:
        logger.warning("Device not found for path %s: %s", device_path, exc)
        return None


def _current_mounts() -> Dict[str, str]:
    mounts: Dict[str, str] = {}
    try:
        with open("/proc/mounts", "r", encoding="utf-8") as fh:
            for line in fh:
                parts = line.split()
                if len(parts) >= 2:
                    mounts[parts[0]] = parts[1]
    except OSError as exc:
        logger.warning("Failed to read /proc/mounts: %s", exc)
    return mounts

