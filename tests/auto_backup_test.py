import os
import shutil
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from backend.schema import backup_manager
from backend.server import device_callback


class TestAutoBackup(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        backup_manager.current_process = None
        self.test_dir = "/tmp/sd-backup-auto-test"
        self.mount_point = os.path.join(self.test_dir, "mount")
        self.target_base = os.path.join(self.test_dir, "backups")

        if os.path.exists(self.test_dir):
            shutil.rmtree(self.test_dir)
        os.makedirs(self.mount_point)
        os.makedirs(self.target_base)

    async def test_auto_backup_flow(self):
        mock_device = MagicMock()
        mock_device.device_node = "/dev/sdb1"
        mock_device.get.side_effect = lambda k, d=None: {
            "ID_FS_UUID": "1234-5678",
            "ID_BUS": "usb",
            "ID_FS_TYPE": "fat32",
        }.get(k, d)

        with patch.object(backup_manager, "mount_device", AsyncMock(return_value=self.mount_point)) as mock_mount, \
            patch.object(backup_manager, "resolve_target_path", AsyncMock(return_value=self.target_base)) as mock_resolve, \
            patch.object(backup_manager, "perform_backup", AsyncMock()) as mock_backup:

            await device_callback(mock_device)

            mock_mount.assert_awaited_once_with(mock_device)
            mock_resolve.assert_awaited_once_with(mock_device, self.mount_point)
            mock_backup.assert_awaited_once_with(self.mount_point, self.target_base)


if __name__ == "__main__":
    unittest.main()
