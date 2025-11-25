from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator, Optional

from sqlalchemy import Boolean, Column, DateTime, Integer, String, Text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

_engine: Optional[AsyncEngine] = None
_SessionFactory: Optional[async_sessionmaker[AsyncSession]] = None


class Base(DeclarativeBase):
    """Base class for all ORM models."""


class Config(Base):
    __tablename__ = "config"

    id = Column(Integer, primary_key=True, default=1)
    auto_backup_enabled = Column(Boolean, nullable=False, default=False)
    auto_backup_target_path = Column(Text, nullable=False)


class BackupTaskRecord(Base):
    __tablename__ = "backup_tasks"

    id = Column(Integer, primary_key=True)
    backup_id = Column(String(64), nullable=False, unique=True, index=True)
    source = Column(Text, nullable=False)
    target = Column(Text, nullable=False)
    status = Column(String(32), nullable=False)
    type = Column(String(16), nullable=False)
    started_at = Column(DateTime(timezone=False), nullable=True)
    finished_at = Column(DateTime(timezone=False), nullable=True)
    size_total = Column(Integer, nullable=False, default=0)
    size_completed = Column(Integer, nullable=False, default=0)


async def init_db(db_path: str) -> None:
    """
    Initialize the SQLite engine + session factory if it hasn't been created yet.
    """
    global _engine, _SessionFactory

    if _engine is not None:
        return

    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    _engine = create_async_engine(
        f"sqlite+aiosqlite:///{db_path}",
        connect_args={"check_same_thread": False},
    )
    _SessionFactory = async_sessionmaker(bind=_engine, expire_on_commit=False)


async def create_schema() -> None:
    if _engine is None:
        raise RuntimeError("Database not initialized. Call init_db first.")
    async with _engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


def _get_session_factory() -> async_sessionmaker[AsyncSession]:
    if _SessionFactory is None:
        raise RuntimeError("Database not initialized. Call init_db first.")
    return _SessionFactory


@asynccontextmanager
async def session_scope() -> AsyncIterator[AsyncSession]:
    """Provide a transactional scope for DB ops."""
    session_factory = _get_session_factory()
    session = session_factory()
    try:
        yield session
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()

