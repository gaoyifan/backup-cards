from __future__ import annotations

import uuid
from dataclasses import dataclass, replace
from datetime import datetime
from enum import Enum
from typing import Optional


class BackupStatus(str, Enum):
    PENDING = "PENDING"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class BackupType(str, Enum):
    AUTO = "AUTO"
    MANUAL = "MANUAL"


@dataclass
class BackupTaskDTO:
    backup_id: str
    source: str
    target: str
    status: BackupStatus
    type: BackupType
    started_at: Optional[datetime]
    finished_at: Optional[datetime]
    size_total: int
    size_completed: int

    @classmethod
    def new(cls, *, source: str, target: str, backup_type: BackupType, size_total: int = 0) -> BackupTaskDTO:
        return cls(
            backup_id=uuid.uuid4().hex,
            source=source,
            target=target,
            status=BackupStatus.PENDING,
            type=backup_type,
            started_at=None,
            finished_at=None,
            size_total=size_total,
            size_completed=0,
        )

    def with_size_total(self, size_total: int) -> BackupTaskDTO:
        return replace(self, size_total=size_total)


@dataclass
class DeviceInfo:
    device_path: str
    mount_point: Optional[str]
