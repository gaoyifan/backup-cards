import plistlib

import psutil

from backend import devices
from backend.models import DeviceInfo


def test_list_available_devices_macos(monkeypatch):
    monkeypatch.setattr(devices.platform, "system", lambda: "Darwin")
    fake_partition = psutil._common.sdiskpart("/dev/disk2s1", "/Volumes/USB", "exfat", "rw")
    monkeypatch.setattr(devices.psutil, "disk_partitions", lambda all=False: [fake_partition])

    disk_info = {
        "DeviceNode": "/dev/disk2s1",
        "Internal": False,
        "RemovableMedia": True,
        "MountPoint": "/Volumes/USB",
    }
    monkeypatch.setattr(
        devices.subprocess,
        "check_output",
        lambda *args, **kwargs: plistlib.dumps(disk_info),
    )

    assert devices.list_available_devices() == [DeviceInfo(device_path="/dev/disk2s1", mount_point="/Volumes/USB")]
