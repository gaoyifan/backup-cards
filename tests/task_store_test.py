"""Tests for backend/task_store.py task persistence."""

import datetime

import pytest

from backend.models import BackupStatus, BackupTaskDTO, BackupType
from backend.task_store import TaskStore


@pytest.mark.asyncio
class TestTaskStore:
    """Tests for TaskStore class."""

    async def test_create_and_get_task(self, fresh_db):
        """Test creating and retrieving a task."""
        task = BackupTaskDTO.new(
            source="/src",
            target="/dst",
            backup_type=BackupType.MANUAL,
            size_total=1000,
        )
        await TaskStore.create(task)

        retrieved = await TaskStore.get(task.backup_id)
        assert retrieved is not None
        assert retrieved.backup_id == task.backup_id
        assert retrieved.source == "/src"
        assert retrieved.target == "/dst"
        assert retrieved.status == BackupStatus.PENDING
        assert retrieved.type == BackupType.MANUAL
        assert retrieved.size_total == 1000

    async def test_get_nonexistent_task(self, fresh_db):
        """Test that getting a nonexistent task returns None."""
        result = await TaskStore.get("nonexistent-id")
        assert result is None

    async def test_list_tasks_empty(self, fresh_db):
        """Test listing tasks when none exist."""
        tasks = await TaskStore.list()
        assert tasks == []

    async def test_list_tasks_returns_recent_first(self, fresh_db):
        """Test that list returns tasks in reverse chronological order."""
        task1 = BackupTaskDTO.new(source="/a", target="/b", backup_type=BackupType.MANUAL)
        task2 = BackupTaskDTO.new(source="/c", target="/d", backup_type=BackupType.MANUAL)
        task3 = BackupTaskDTO.new(source="/e", target="/f", backup_type=BackupType.AUTO)

        await TaskStore.create(task1)
        await TaskStore.create(task2)
        await TaskStore.create(task3)

        tasks = await TaskStore.list()
        assert len(tasks) == 3
        # Most recent first
        assert tasks[0].backup_id == task3.backup_id
        assert tasks[1].backup_id == task2.backup_id
        assert tasks[2].backup_id == task1.backup_id

    async def test_list_with_limit(self, fresh_db):
        """Test listing tasks with a limit."""
        for i in range(5):
            task = BackupTaskDTO.new(source=f"/src{i}", target=f"/dst{i}", backup_type=BackupType.MANUAL)
            await TaskStore.create(task)

        tasks = await TaskStore.list(limit=3)
        assert len(tasks) == 3

    async def test_list_with_offset(self, fresh_db):
        """Test listing tasks with offset for pagination."""
        for i in range(5):
            task = BackupTaskDTO.new(source=f"/src{i}", target=f"/dst{i}", backup_type=BackupType.MANUAL)
            await TaskStore.create(task)

        tasks = await TaskStore.list(limit=2, offset=2)
        assert len(tasks) == 2

    async def test_update_status(self, fresh_db):
        """Test updating task status."""
        task = BackupTaskDTO.new(source="/src", target="/dst", backup_type=BackupType.MANUAL)
        await TaskStore.create(task)

        await TaskStore.update_status(task.backup_id, status=BackupStatus.IN_PROGRESS)

        updated = await TaskStore.get(task.backup_id)
        assert updated.status == BackupStatus.IN_PROGRESS

    async def test_update_status_nonexistent(self, fresh_db):
        """Test that updating nonexistent task doesn't raise."""
        # Should not raise
        await TaskStore.update_status("nonexistent", status=BackupStatus.FAILED)

    async def test_finalize_task(self, fresh_db):
        """Test finalizing a task with completion status."""
        task = BackupTaskDTO.new(source="/src", target="/dst", backup_type=BackupType.MANUAL, size_total=1000)
        await TaskStore.create(task)

        started = datetime.datetime.utcnow()
        result = await TaskStore.finalize(task.backup_id, status=BackupStatus.COMPLETED, started_at=started)

        assert result is not None
        size_completed, size_total = result
        assert size_completed == 1000  # Should be set to total on completion
        assert size_total == 1000

        finalized = await TaskStore.get(task.backup_id)
        assert finalized.status == BackupStatus.COMPLETED
        assert finalized.finished_at is not None

    async def test_finalize_nonexistent(self, fresh_db):
        """Test that finalizing nonexistent task returns None."""
        result = await TaskStore.finalize("nonexistent", status=BackupStatus.COMPLETED, started_at=datetime.datetime.utcnow())
        assert result is None

    async def test_update_progress(self, fresh_db):
        """Test updating task progress."""
        task = BackupTaskDTO.new(source="/src", target="/dst", backup_type=BackupType.MANUAL, size_total=1000)
        await TaskStore.create(task)

        result = await TaskStore.update_progress(task.backup_id, size_completed=500)
        assert result is not None
        assert result == (500, 1000)

        updated = await TaskStore.get(task.backup_id)
        assert updated.size_completed == 500

    async def test_update_progress_with_total_hint(self, fresh_db):
        """Test updating progress with size_total hint."""
        task = BackupTaskDTO.new(source="/src", target="/dst", backup_type=BackupType.MANUAL, size_total=0)
        await TaskStore.create(task)

        result = await TaskStore.update_progress(task.backup_id, size_completed=100, size_total_hint=500)
        assert result == (100, 500)

        updated = await TaskStore.get(task.backup_id)
        assert updated.size_total == 500

    async def test_update_progress_no_change(self, fresh_db):
        """Test that update_progress returns None when no change."""
        task = BackupTaskDTO.new(source="/src", target="/dst", backup_type=BackupType.MANUAL, size_total=1000)
        await TaskStore.create(task)

        # First update
        await TaskStore.update_progress(task.backup_id, size_completed=500)

        # Same value - no change
        result = await TaskStore.update_progress(task.backup_id, size_completed=500)
        assert result is None

    async def test_update_progress_force_publish(self, fresh_db):
        """Test force_publish returns values even without change."""
        task = BackupTaskDTO.new(source="/src", target="/dst", backup_type=BackupType.MANUAL, size_total=1000)
        await TaskStore.create(task)

        await TaskStore.update_progress(task.backup_id, size_completed=500)
        result = await TaskStore.update_progress(task.backup_id, size_completed=500, force_publish=True)
        assert result is not None

    async def test_fail_stale_tasks(self, fresh_db):
        """Test marking stale tasks as failed."""
        # Create tasks in different states
        pending = BackupTaskDTO.new(source="/a", target="/b", backup_type=BackupType.MANUAL)
        in_progress = BackupTaskDTO.new(source="/c", target="/d", backup_type=BackupType.MANUAL)
        completed = BackupTaskDTO.new(source="/e", target="/f", backup_type=BackupType.MANUAL)

        await TaskStore.create(pending)
        await TaskStore.create(in_progress)
        await TaskStore.create(completed)

        # Update statuses
        await TaskStore.update_status(in_progress.backup_id, status=BackupStatus.IN_PROGRESS)
        await TaskStore.finalize(completed.backup_id, status=BackupStatus.COMPLETED, started_at=datetime.datetime.utcnow())

        # Fail stale PENDING and IN_PROGRESS tasks
        count = await TaskStore.fail_stale_tasks([BackupStatus.PENDING, BackupStatus.IN_PROGRESS])
        assert count == 2

        # Check they're now failed
        t1 = await TaskStore.get(pending.backup_id)
        t2 = await TaskStore.get(in_progress.backup_id)
        t3 = await TaskStore.get(completed.backup_id)

        assert t1.status == BackupStatus.FAILED
        assert t2.status == BackupStatus.FAILED
        assert t3.status == BackupStatus.COMPLETED  # Unchanged
