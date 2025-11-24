from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from sqlalchemy.orm import Session

from backend.db import Config as ConfigTable, create_schema, get_session, init_db

DEFAULT_MOUNT_TEMPLATE = "/media/sd-backup-{uuid}"
DEFAULT_TARGET_TEMPLATE = "~/backups/{date}"


@dataclass
class Config:
    mount_point_template: str
    target_path_template: str


def init_config_store(db_path: str) -> None:
    """Prepare the SQLite store and ensure a default config row exists."""
    init_db(db_path)
    create_schema()

    with session_scope() as session:
        config = session.get(ConfigTable, 1)
        if config is None:
            config = ConfigTable(
                id=1,
                mount_point_template=DEFAULT_MOUNT_TEMPLATE,
                target_path_template=DEFAULT_TARGET_TEMPLATE,
            )
            session.add(config)
            session.commit()


def session_scope() -> Session:
    return get_session()


def get_config() -> Config:
    with session_scope() as session:
        config = session.get(ConfigTable, 1)
        if config is None:
            raise RuntimeError("Config missing. Did init_config_store run?")
        return Config(
            mount_point_template=config.mount_point_template,
            target_path_template=config.target_path_template,
        )


def update_config(
    *, mount_point_template: Optional[str] = None, target_path_template: Optional[str] = None
) -> Config:
    with session_scope() as session:
        config = session.get(ConfigTable, 1)
        if config is None:
            raise RuntimeError("Config missing. Did init_config_store run?")

        if mount_point_template is not None:
            config.mount_point_template = mount_point_template
        if target_path_template is not None:
            config.target_path_template = target_path_template

        session.add(config)
        session.commit()
        session.refresh(config)

        return Config(
            mount_point_template=config.mount_point_template,
            target_path_template=config.target_path_template,
        )

