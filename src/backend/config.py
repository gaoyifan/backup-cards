from __future__ import annotations

import json
from typing import Optional

import strawberry

from backend.db import Config as ConfigTable
from backend.db import create_schema, init_db, session_scope

DEFAULT_AUTO_TEMPLATE = "~/sd-backups/{date}-{uuid_short}"


@strawberry.type
class Config:
    """User configuration for backup settings."""

    auto_backup_enabled: bool = strawberry.field(name="autoBackupEnabled")
    auto_backup_target_path: str = strawberry.field(name="autoBackupTargetPath")
    exclude_patterns: list[str] = strawberry.field(name="excludePatterns", default_factory=list)
    include_patterns: list[str] = strawberry.field(name="includePatterns", default_factory=list)


def _parse_patterns(json_str: str) -> list[str]:
    """Parse JSON-encoded pattern list, returning empty list on error."""
    try:
        patterns = json.loads(json_str)
        return patterns if isinstance(patterns, list) else []
    except (json.JSONDecodeError, TypeError):
        return []


async def init_config_store(db_path: str) -> None:
    """Prepare the SQLite store and ensure a default config row exists."""
    await init_db(db_path)
    await create_schema()

    async with session_scope() as session:
        config = await session.get(ConfigTable, 1)
        if config is None:
            config = ConfigTable(
                id=1,
                auto_backup_enabled=False,
                auto_backup_target_path=DEFAULT_AUTO_TEMPLATE,
                exclude_patterns="[]",
                include_patterns="[]",
            )
            session.add(config)


async def get_config() -> Config:
    async with session_scope() as session:
        row = await session.get(ConfigTable, 1)
        if row is None:
            raise RuntimeError("Config missing. Did init_config_store run?")
        return Config(
            auto_backup_enabled=row.auto_backup_enabled,
            auto_backup_target_path=row.auto_backup_target_path,
            exclude_patterns=_parse_patterns(row.exclude_patterns),
            include_patterns=_parse_patterns(row.include_patterns),
        )


async def update_config(
    *,
    auto_backup_enabled: Optional[bool] = None,
    auto_backup_target_path: Optional[str] = None,
    exclude_patterns: Optional[list[str]] = None,
    include_patterns: Optional[list[str]] = None,
) -> Config:
    async with session_scope() as session:
        row = await session.get(ConfigTable, 1)
        if row is None:
            raise RuntimeError("Config missing. Did init_config_store run?")

        if auto_backup_enabled is not None:
            row.auto_backup_enabled = auto_backup_enabled
        if auto_backup_target_path is not None:
            row.auto_backup_target_path = auto_backup_target_path
        if exclude_patterns is not None:
            row.exclude_patterns = json.dumps(exclude_patterns)
        if include_patterns is not None:
            row.include_patterns = json.dumps(include_patterns)

        session.add(row)
        await session.flush()
        await session.refresh(row)

        return Config(
            auto_backup_enabled=row.auto_backup_enabled,
            auto_backup_target_path=row.auto_backup_target_path,
            exclude_patterns=_parse_patterns(row.exclude_patterns),
            include_patterns=_parse_patterns(row.include_patterns),
        )
