"""db.py — async SQLAlchemy engine + session. Lazy so importing the app never
needs a live database; ping() fails soft so /health works even when DB is down."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

from .config import get_settings

log = logging.getLogger("axon.db")

_engine: AsyncEngine | None = None
_sessionmaker: async_sessionmaker[AsyncSession] | None = None


def engine() -> AsyncEngine:
    global _engine, _sessionmaker
    if _engine is None:
        s = get_settings()
        kwargs: dict = {"future": True}
        if s.db_use_nullpool:
            kwargs["poolclass"] = NullPool  # tests: avoid pooled conns crossing loops
        else:
            kwargs["pool_pre_ping"] = True
        _engine = create_async_engine(s.database_url, **kwargs)
        # pgvector wiring: the `Vector` column type (pgvector.sqlalchemy, used in
        # tables.py) serializes embeddings to the `vector` text form, which asyncpg
        # sends untyped and Postgres parses server-side. No separate asyncpg binary
        # codec is registered — registering one collides with the Vector type's own
        # text encoding ("could not convert string to float").
        _sessionmaker = async_sessionmaker(
            _engine, class_=AsyncSession, expire_on_commit=False
        )
    return _engine


def session_factory() -> async_sessionmaker[AsyncSession]:
    if _sessionmaker is None:
        engine()
    assert _sessionmaker is not None
    return _sessionmaker


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency: `session: AsyncSession = Depends(get_session)`."""
    async with session_factory()() as session:
        yield session


async def ping() -> bool:
    try:
        async with engine().connect() as conn:
            await conn.execute(text("SELECT 1"))
        return True
    except Exception:
        return False


async def dispose() -> None:
    global _engine, _sessionmaker
    if _engine is not None:
        await _engine.dispose()
        _engine, _sessionmaker = None, None
