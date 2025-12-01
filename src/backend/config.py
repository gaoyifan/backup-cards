from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Optional

from backend.db import Config as ConfigTable
from backend.db import create_schema, init_db, session_scope

DEFAULT_AUTO_TEMPLATE = "~/sd-backups/{date}-{uuid_short}"


@dataclass
class Config:
    auto_backup_enabled: bool
    auto_backup_target_path: str
    exclude_patterns: list[str] = field(default_factory=list)
    include_patterns: list[str] = field(default_factory=list)


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
        config = await session.get(ConfigTable, 1)
        if config is None:
            raise RuntimeError("Config missing. Did init_config_store run?")
        return Config(
            auto_backup_enabled=config.auto_backup_enabled,
            auto_backup_target_path=config.auto_backup_target_path,
            exclude_patterns=_parse_patterns(config.exclude_patterns),
            include_patterns=_parse_patterns(config.include_patterns),
        )


async def update_config(
    *,
    auto_backup_enabled: Optional[bool] = None,
    auto_backup_target_path: Optional[str] = None,
    exclude_patterns: Optional[list[str]] = None,
    include_patterns: Optional[list[str]] = None,
) -> Config:
    async with session_scope() as session:
        config = await session.get(ConfigTable, 1)
        if config is None:
            raise RuntimeError("Config missing. Did init_config_store run?")

        if auto_backup_enabled is not None:
            config.auto_backup_enabled = auto_backup_enabled
        if auto_backup_target_path is not None:
            config.auto_backup_target_path = auto_backup_target_path
        if exclude_patterns is not None:
            config.exclude_patterns = json.dumps(exclude_patterns)
        if include_patterns is not None:
            config.include_patterns = json.dumps(include_patterns)

        session.add(config)
        await session.flush()
        await session.refresh(config)

        return Config(
            auto_backup_enabled=config.auto_backup_enabled,
            auto_backup_target_path=config.auto_backup_target_path,
            exclude_patterns=_parse_patterns(config.exclude_patterns),
            include_patterns=_parse_patterns(config.include_patterns),
        )
