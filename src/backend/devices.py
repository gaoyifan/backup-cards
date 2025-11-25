from __future__ import annotations

import logging
from typing import Dict, List

import pyudev

from backend.models import DeviceInfo

logger = logging.getLogger(__name__)


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

