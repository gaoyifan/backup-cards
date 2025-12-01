import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from backend.backup import MountHandle
from backend.config import Config
from backend.schema import backup_manager


class TestAutoBackup(unittest.IsolatedAsyncioTestCase):
    async def test_handle_device_triggers_backup(self):
        mock_device = MagicMock()
        mock_device.device_node = "/dev/sdb1"
        mock_device.get.side_effect = lambda key, default=None: {
            "ID_FS_UUID": "1234-5678",
            "ID_BUS": "usb",
        }.get(key, default)

        config = Config(auto_backup_enabled=True, auto_backup_target_path="~/backups/{date}")

        mount_handle = MountHandle(path="/mnt/test", owned=True)

        with (
            patch("backend.backup.get_config", AsyncMock(return_value=config)),
            patch.object(backup_manager, "_mount_device", AsyncMock(return_value=mount_handle)) as mock_mount,
            patch("backend.backup.resolve_target_path", return_value="/data/backups"),
            patch.object(type(backup_manager), "_enqueue_backup", AsyncMock(return_value="abc123")) as mock_enqueue,
            patch("backend.backup.auto_backup_supported", return_value=True),
        ):
            backup_id = await backup_manager.handle_device(mock_device)

        mock_mount.assert_awaited_once_with(mock_device)
        mock_enqueue.assert_awaited_once()
        self.assertEqual(backup_id, "abc123")

    async def test_handle_device_skips_when_unsupported(self):
        mock_device = MagicMock()
        mock_device.device_node = "/dev/disk2s1"

        with patch("backend.backup.auto_backup_supported", return_value=False):
            backup_id = await backup_manager.handle_device(mock_device)

        self.assertIsNone(backup_id)


if __name__ == "__main__":
    unittest.main()
