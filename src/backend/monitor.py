import pyudev
import threading
import logging
from typing import Callable, Optional

logger = logging.getLogger(__name__)

class DeviceMonitor:
    def __init__(self, callback: Callable[[pyudev.Device], None]):
        self.context = pyudev.Context()
        self.monitor = pyudev.Monitor.from_netlink(self.context)
        self.monitor.filter_by(subsystem="block", device_type="partition")
        self.callback = callback
        self.running = False
        self.thread: Optional[threading.Thread] = None

    def match_device(self, d: pyudev.Device) -> bool:
        try:
            return all([
                d.subsystem == "block",
                getattr(d, "action", "") == "add",
                d.device_type == "partition",
                d.get("ID_BUS") == "usb",
                d.sys_number == "1",
                d.get("ID_FS_TYPE", "").lower() in {"exfat", "fat32", "udf"},
            ])
        except Exception as e:
            logger.error(f"[Error matching device]: {e}")
            return False

    def _monitor_loop(self):
        logger.info("Starting device monitor loop...")
        for action, dev in self.monitor:
            if not self.running:
                break
            if self.match_device(dev):
                logger.info(f"[MATCH] device_node = {dev.device_node}")
                try:
                    self.callback(dev)
                except Exception as e:
                    logger.error(f"Error in device callback: {e}")

    def start(self):
        if self.running:
            return
        self.running = True
        self.monitor.start()
        self.thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self.thread.start()
        logger.info("DeviceMonitor started.")

    def stop(self):
        self.running = False
        # pyudev monitor is blocking, so it might not stop immediately until an event occurs
        # or we force it. For now, daemon thread will be killed on exit.
        logger.info("DeviceMonitor stopped.")
