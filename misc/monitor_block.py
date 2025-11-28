#!/usr/bin/env python3
import pyudev
from rich import inspect

def match_device(d):
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
        print(f"[Error matching device]: {e}")
        return False

def main():
    context = pyudev.Context()
    monitor = pyudev.Monitor.from_netlink(context)
    monitor.filter_by(subsystem="block", device_type="partition")
    monitor.start()

    print("Listening for matching block/usb/partition events...")

    for action, dev in monitor:
        inspect(dev)
        if match_device(dev):
            print(f"[MATCH] device_node = {dev.device_node}")

if __name__ == "__main__":
    main()

