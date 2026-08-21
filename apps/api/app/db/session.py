"""Async SQLAlchemy engine + AsyncSession factory.

The engine is built from the settings' asyncpg URL. ``get_session`` is the
FastAPI dependency that routes use to obtain an :class:`AsyncSession`; it
rolls back on exception and always closes. In Phase 0 no ORM models are
registered — Alembic owns the schema — but this stack proves async DB access
works end-to-end.
"""

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import get_settings

settings = get_settings()

engine = create_async_engine(
    settings.DATABASE_URL,
    echo=settings.DB_ECHO,
    pool_size=settings.DB_POOL_MIN_SIZE,
    max_overflow=settings.DB_POOL_MAX_SIZE,
    pool_pre_ping=True,
)

AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def get_session() -> AsyncGenerator["AsyncSession", None]:
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
