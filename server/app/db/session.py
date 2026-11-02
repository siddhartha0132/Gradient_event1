"""Database engines: async for the API and scheduler, sync for worker processes."""

from collections.abc import AsyncIterator
from functools import lru_cache

from sqlalchemy import create_engine, event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.settings import get_settings

from .models import Base, EventLog


def _sqlite_pragmas(dbapi_connection, _record):
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")  # readers never block the writer
    cursor.execute("PRAGMA busy_timeout=10000")  # several processes share the file
    cursor.execute("PRAGMA synchronous=NORMAL")
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


@lru_cache
def async_engine():
    settings = get_settings()
    settings.database_path.parent.mkdir(parents=True, exist_ok=True)
    engine = create_async_engine(settings.database_url)
    event.listen(engine.sync_engine, "connect", _sqlite_pragmas)
    return engine


@lru_cache
def async_sessions() -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(async_engine(), expire_on_commit=False)


@lru_cache
def sync_engine():
    settings = get_settings()
    settings.database_path.parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(settings.sync_database_url)
    event.listen(engine, "connect", _sqlite_pragmas)
    return engine


@lru_cache
def sync_sessions() -> sessionmaker[Session]:
    return sessionmaker(sync_engine(), expire_on_commit=False)


def create_tables() -> None:
    Base.metadata.create_all(sync_engine())


async def get_session() -> AsyncIterator[AsyncSession]:
    async with async_sessions()() as session:
        yield session


def log_event(session: Session | AsyncSession, type_: str, payload: dict, audience: str = "all") -> None:
    """Record a state change. It reaches clients once the surrounding transaction commits."""
    session.add(EventLog(type=type_, audience=audience, payload=payload))
