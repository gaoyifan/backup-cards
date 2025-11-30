from __future__ import annotations

from dataclasses import dataclass
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


@dataclass
class DeviceInfo:
    device_path: str
    mount_point: Optional[str]
