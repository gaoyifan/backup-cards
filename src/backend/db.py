from __future__ import annotations

from pathlib import Path
from typing import Optional

from sqlalchemy import Column, Integer, Text, create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

_engine = None
_SessionFactory: Optional[sessionmaker] = None


class Base(DeclarativeBase):
    """Base class for all ORM models."""


class Config(Base):
    __tablename__ = "config"

    id = Column(Integer, primary_key=True, default=1)
    mount_point_template = Column(Text, nullable=False)
    target_path_template = Column(Text, nullable=False)


def init_db(db_path: str) -> None:
    """
    Initialize the SQLite engine + session factory if it hasn't been created yet.
    """
    global _engine, _SessionFactory

    if _engine is not None:
        return

    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    _engine = create_engine(
        f"sqlite:///{db_path}",
        connect_args={"check_same_thread": False},
    )
    _SessionFactory = sessionmaker(bind=_engine, expire_on_commit=False)


def create_schema() -> None:
    if _engine is None:
        raise RuntimeError("Database not initialized. Call init_db first.")
    Base.metadata.create_all(_engine)


def get_session() -> Session:
    if _SessionFactory is None:
        raise RuntimeError("Database not initialized. Call init_db first.")
    return _SessionFactory()

