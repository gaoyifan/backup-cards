import unittest
from unittest.mock import MagicMock, patch
import os
import shutil
from backend.server import device_callback
from backend.schema import backup_manager

class TestAutoBackup(unittest.TestCase):
    def setUp(self):
        # Reset backup manager state
        backup_manager.current_process = None
        
        # Setup dummy paths
        self.test_dir = "/tmp/sd-backup-auto-test"
        self.mount_point = os.path.join(self.test_dir, "mount")
        self.target_base = os.path.join(self.test_dir, "backups")
        
        if os.path.exists(self.test_dir):
            shutil.rmtree(self.test_dir)
        os.makedirs(self.mount_point)
        os.makedirs(self.target_base)
        
        # Create dummy files in mount point
        with open(os.path.join(self.mount_point, "photo.jpg"), "w") as f:
            f.write("dummy data")

    @patch("backend.backup.subprocess.run")
    @patch("backend.backup.subprocess.Popen")
    @patch("backend.backup.load_config")
    def test_auto_backup_flow(self, mock_load_config, mock_popen, mock_run):
        # Mock config
        mock_load_config.return_value = {
            "mount_point_template": self.mount_point, # Force mount point to our test dir
            "target_path_template": os.path.join(self.target_base, "{date}"),
        }
        
        # Mock rsync process
        mock_process = MagicMock()
        mock_process.poll.return_value = None
        mock_process.wait.return_value = None
        mock_process.returncode = 0
        mock_popen.return_value = mock_process
        
        # Mock device
        mock_device = MagicMock()
        mock_device.device_node = "/dev/sdb1"
        mock_device.get.side_effect = lambda k, d=None: {
            "ID_FS_UUID": "1234-5678",
            "ID_BUS": "usb",
            "ID_FS_TYPE": "fat32"
        }.get(k, d)
        
        # We need to patch mount_device to avoid real mount and return our test mount point
        # But wait, if we set mount_point_template to our existing dir, mount_device will try to mount.
        # We should mock mount_device entirely or mock the subprocess.run call in it.
        # The `mount_device` function checks /proc/mounts.
        # Let's patch `backend.backup.BackupManager.mount_device` to be easier.
        
        with patch.object(backup_manager, "mount_device", return_value=self.mount_point) as mock_mount:
            # Trigger callback
            device_callback(mock_device)
            
            # Verify mount called
            mock_mount.assert_called_once_with(mock_device)
            
            # Verify rsync started
            mock_popen.assert_called_once()
            args = mock_popen.call_args[0][0]
            self.assertEqual(args[0], "rsync")
            self.assertIn(self.mount_point + "/", args)
            # Target path should contain date
            self.assertTrue(any(self.target_base in arg for arg in args))

if __name__ == "__main__":
    unittest.main()
