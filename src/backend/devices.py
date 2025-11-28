from __future__ import annotations

import asyncio
import logging
from typing import AsyncIterator, Dict, List

import pyudev

from backend.models import DeviceInfo

logger = logging.getLogger(__name__)


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

