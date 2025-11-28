import asyncio
import logging
from typing import Awaitable, Callable, Optional

import pyudev

from backend.devices import publish_device_update

logger = logging.getLogger(__name__)


class DeviceMonitor:
    def __init__(self, callback: Callable[[pyudev.Device], Awaitable[None]]):
        self.context = pyudev.Context()
        self.monitor = pyudev.Monitor.from_netlink(self.context)
        self.monitor.filter_by(subsystem="block", device_type="partition")
        self.callback = callback
        self.running = False
        self.loop: Optional[asyncio.AbstractEventLoop] = None

    def match_device(self, d: pyudev.Device) -> bool:
        try:
            return all(
                [
                    d.subsystem == "block",
                    getattr(d, "action", "") == "add",
                    d.device_type == "partition",
                    d.get("ID_BUS") == "usb",
                    d.sys_number == "1",
                    d.get("ID_FS_TYPE", "").lower() in {"exfat", "fat32", "udf"},
                ]
            )
        except Exception as e:
            logger.error(f"[Error matching device]: {e}")
            return False

    def _handle_event(self):
        if not self.running:
            return

        while True:
            device = self.monitor.poll(0)
            if device is None:
                break

            # Publish device update for any block device event (add/remove)
            asyncio.create_task(publish_device_update())

            if not self.match_device(device):
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
