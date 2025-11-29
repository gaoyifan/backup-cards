from __future__ import annotations

import asyncio
import logging
import platform
from typing import Awaitable, Callable, Optional

import pyudev

from backend.devices import is_storage_device, publish_device_update

logger = logging.getLogger(__name__)


def monitoring_supported() -> bool:
    """Return True if pyudev monitoring is supported on this host."""
    return platform.system() == "Linux"


class DeviceMonitor:
    def __init__(self, callback: Callable[[pyudev.Device], Awaitable[None]]):
        if not monitoring_supported():
            raise RuntimeError("Device monitoring requires Linux with pyudev available.")
        self.context = pyudev.Context()
        self.monitor = pyudev.Monitor.from_netlink(self.context)
        self.monitor.filter_by(subsystem="block", device_type="partition")
        self.callback = callback
        self.running = False
        self.loop: Optional[asyncio.AbstractEventLoop] = None

    def _handle_event(self):
        if not self.running:
            return

        while True:
            device = self.monitor.poll(0)
            if device is None:
                break

            # Publish device update for any block device event (add/remove)
            asyncio.create_task(publish_device_update())

            if not is_storage_device(device, action="add"):
                continue
            logger.info(f"[MATCH] device_node = {device.device_node}")
            task = asyncio.create_task(self.callback(device))

            def _done_callback(fut: asyncio.Future):
                try:
                    fut.result()
                except Exception as exc:
                    logger.error(f"Error in device callback: {exc}")

            task.add_done_callback(_done_callback)

    async def start(self):
        if self.running:
            return
        self.running = True
        self.loop = asyncio.get_running_loop()
        self.monitor.start()
        self.loop.add_reader(self.monitor.fileno(), self._handle_event)
        logger.info("DeviceMonitor started.")

    async def stop(self):
        if not self.running:
            return
        self.running = False
        if self.loop:
            self.loop.remove_reader(self.monitor.fileno())
        logger.info("DeviceMonitor stopped.")
