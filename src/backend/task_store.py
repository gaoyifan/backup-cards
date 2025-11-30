from __future__ import annotations

import datetime
from typing import Optional, Sequence

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db import BackupTaskRecord, session_scope
from backend.models import BackupStatus, BackupTaskDTO, BackupType


class TaskStore:
    """Encapsulates all persistence logic for backup tasks."""

    async def fail_stale_tasks(self, stale_statuses: Sequence[BackupStatus]) -> int:
        stale_values = [status.value for status in stale_statuses]
        now = datetime.datetime.utcnow()
        async with session_scope() as session:
            stmt = update(BackupTaskRecord).where(BackupTaskRecord.status.in_(stale_values)).values(status=BackupStatus.FAILED.value, finished_at=now)
            result = await session.execute(stmt)
            return result.rowcount

    async def list(self, limit: int = 20, offset: int = 0) -> list[BackupTaskDTO]:
        async with session_scope() as session:
            stmt = select(BackupTaskRecord).order_by(BackupTaskRecord.id.desc()).offset(offset).limit(limit)
            records = (await session.execute(stmt)).scalars().all()
            return [self._record_to_dto(record) for record in records]

    async def get(self, backup_id: str) -> Optional[BackupTaskDTO]:
        async with session_scope() as session:
            record = await self._fetch_record(session, backup_id)
            if record is None:
                return None
            return self._record_to_dto(record)

    async def create(
        self,
        *,
        backup_id: str,
        source: str,
        target: str,
        status: BackupStatus,
        backup_type: BackupType,
        size_total: int,
    ) -> None:
        created_at = datetime.datetime.utcnow()
        async with session_scope() as session:
            record = BackupTaskRecord(
                backup_id=backup_id,
                source=source,
                target=target,
                status=status.value,
                type=backup_type.value,
                started_at=created_at,
                finished_at=None,
                size_total=size_total,
                size_completed=0,
            )
            session.add(record)

    async def update_status(
        self,
        backup_id: str,
        *,
        status: BackupStatus,
        started_at: Optional[datetime.datetime] = None,
    ) -> None:
        async with session_scope() as session:
            record = await self._fetch_record(session, backup_id)
            if record is None:
                return
            record.status = status.value
            if started_at is not None:
                record.started_at = started_at
            session.add(record)

    async def finalize(
        self,
        backup_id: str,
        *,
        status: BackupStatus,
        started_at: datetime.datetime,
    ) -> Optional[tuple[int, int]]:
        finished_at = datetime.datetime.utcnow()
        async with session_scope() as session:
            record = await self._fetch_record(session, backup_id)
            if record is None:
                return None
            record.status = status.value
            record.started_at = record.started_at or started_at
            record.finished_at = finished_at
            if status == BackupStatus.COMPLETED and record.size_total and record.size_completed < record.size_total:
                record.size_completed = record.size_total
            session.add(record)
            return record.size_completed, record.size_total

    async def update_progress(
        self,
        backup_id: str,
        *,
        size_completed: Optional[int],
        size_total_hint: Optional[int] = None,
        force_publish: bool = False,
    ) -> Optional[tuple[int, int]]:
        updated = False
        async with session_scope() as session:
            record = await self._fetch_record(session, backup_id)
            if record is None:
                return None

            size_total_value = record.size_total
            size_completed_value = record.size_completed

            if size_total_hint is not None and size_total_hint > 0 and size_total_hint != record.size_total:
                record.size_total = size_total_hint
                size_total_value = size_total_hint
                updated = True

            if size_completed is not None and size_completed != record.size_completed:
                record.size_completed = size_completed
                size_completed_value = size_completed
                updated = True

            if updated:
                session.add(record)

        if updated or force_publish:
            return size_completed_value, size_total_value
        return None

    async def _fetch_record(self, session: AsyncSession, backup_id: str) -> Optional[BackupTaskRecord]:
        stmt = select(BackupTaskRecord).where(BackupTaskRecord.backup_id == backup_id)
        result = await session.execute(stmt)
        return result.scalars().one_or_none()

    def _record_to_dto(self, record: BackupTaskRecord) -> BackupTaskDTO:
        return BackupTaskDTO(
            backup_id=record.backup_id,
            source=record.source,
            target=record.target,
            status=BackupStatus(record.status),
            type=BackupType(record.type),
            started_at=record.started_at,
            finished_at=record.finished_at,
            size_total=record.size_total,
            size_completed=record.size_completed,
        )
