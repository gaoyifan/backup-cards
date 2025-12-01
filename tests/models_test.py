"""Tests for backend/models.py data models."""

from backend.models import BackupStatus, BackupTaskDTO, BackupType, DeviceInfo


class TestBackupStatus:
    """Tests for BackupStatus enum."""

    def test_status_values(self):
        """Test that all expected status values exist."""
        assert BackupStatus.PENDING.value == "PENDING"
        assert BackupStatus.IN_PROGRESS.value == "IN_PROGRESS"
        assert BackupStatus.COMPLETED.value == "COMPLETED"
        assert BackupStatus.FAILED.value == "FAILED"
        assert BackupStatus.CANCELLED.value == "CANCELLED"

    def test_status_is_str_enum(self):
        """Test that BackupStatus is a string enum."""
        assert isinstance(BackupStatus.PENDING, str)
        assert BackupStatus.PENDING == "PENDING"


class TestBackupType:
    """Tests for BackupType enum."""

    def test_type_values(self):
        """Test that all expected type values exist."""
        assert BackupType.AUTO.value == "AUTO"
        assert BackupType.MANUAL.value == "MANUAL"


class TestBackupTaskDTO:
    """Tests for BackupTaskDTO dataclass."""

    def test_new_creates_pending_task(self):
        """Test that new() creates a task with PENDING status."""
        task = BackupTaskDTO.new(
            source="/src",
            target="/dst",
            backup_type=BackupType.MANUAL,
        )
        assert task.status == BackupStatus.PENDING
        assert task.source == "/src"
        assert task.target == "/dst"
        assert task.type == BackupType.MANUAL
        assert task.started_at is None
        assert task.finished_at is None
        assert task.size_total == 0
        assert task.size_completed == 0

    def test_new_generates_unique_ids(self):
        """Test that new() generates unique backup IDs."""
        task1 = BackupTaskDTO.new(source="/a", target="/b", backup_type=BackupType.MANUAL)
        task2 = BackupTaskDTO.new(source="/a", target="/b", backup_type=BackupType.MANUAL)
        assert task1.backup_id != task2.backup_id

    def test_new_with_size_total(self):
        """Test that new() accepts initial size_total."""
        task = BackupTaskDTO.new(
            source="/src",
            target="/dst",
            backup_type=BackupType.AUTO,
            size_total=1024,
        )
        assert task.size_total == 1024

    def test_with_size_total_returns_new_instance(self):
        """Test that with_size_total returns a new instance."""
        original = BackupTaskDTO.new(
            source="/src",
            target="/dst",
            backup_type=BackupType.MANUAL,
        )
        updated = original.with_size_total(2048)

        assert updated.size_total == 2048
        assert original.size_total == 0  # Original unchanged
        assert updated.backup_id == original.backup_id

    def test_with_size_total_preserves_other_fields(self):
        """Test that with_size_total preserves all other fields."""
        original = BackupTaskDTO.new(
            source="/my/source",
            target="/my/target",
            backup_type=BackupType.AUTO,
        )
        updated = original.with_size_total(5000)

        assert updated.source == "/my/source"
        assert updated.target == "/my/target"
        assert updated.type == BackupType.AUTO
        assert updated.status == BackupStatus.PENDING


class TestDeviceInfo:
    """Tests for DeviceInfo dataclass."""

    def test_device_with_mount_point(self):
        """Test DeviceInfo with a mount point."""
        device = DeviceInfo(device_path="/dev/sda1", mount_point="/mnt/usb")
        assert device.device_path == "/dev/sda1"
        assert device.mount_point == "/mnt/usb"

    def test_device_without_mount_point(self):
        """Test DeviceInfo without a mount point (not mounted)."""
        device = DeviceInfo(device_path="/dev/sdb1", mount_point=None)
        assert device.device_path == "/dev/sdb1"
        assert device.mount_point is None

    def test_device_equality(self):
        """Test DeviceInfo equality comparison."""
        device1 = DeviceInfo(device_path="/dev/sda1", mount_point="/mnt/a")
        device2 = DeviceInfo(device_path="/dev/sda1", mount_point="/mnt/a")
        device3 = DeviceInfo(device_path="/dev/sdb1", mount_point="/mnt/a")

        assert device1 == device2
        assert device1 != device3

