"""Async SQLAlchemy engine + AsyncSession factory.

The engine is built from the settings' asyncpg URL. ``get_session`` is the
FastAPI dependency that routes use to obtain an :class:`AsyncSession`; it
rolls back on exception and always closes. In Phase 0 no ORM models are
registered — Alembic owns the schema — but this stack proves async DB access
works end-to-end.

A NullPool is used in tests (``FUDGO_NULLPOOL=1``) so each connection binds to
the active event loop and asyncpg's "different loop" check passes.
"""

import os
from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import get_settings

settings = get_settings()

_engine_kwargs: dict = {
    "echo": settings.DB_ECHO,
    "pool_pre_ping": True,
}
if os.getenv("FUDGO_NULLPOOL") == "1":
    _engine_kwargs["poolclass"] = NullPool
else:
    _engine_kwargs["pool_size"] = settings.DB_POOL_MIN_SIZE
    _engine_kwargs["max_overflow"] = settings.DB_POOL_MAX_SIZE

engine = create_async_engine(settings.DATABASE_URL, **_engine_kwargs)

AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """Yield an AsyncSession, committing explicitly via the caller.

    Route code does the commit; on any error we roll back to avoid leaking
    partial transactions, and always close the session.
    """
    session = AsyncSessionLocal()
    try:
        yield session
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()
