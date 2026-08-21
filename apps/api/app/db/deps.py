"""FastAPI dependency for the AsyncSession.

Routes depend on ``get_session`` (defined in ``app/db/session.py``). This
wrapper exists so the dependency is injected cleanly and typed explicitly.
"""

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import AsyncSessionLocal


async def get_session() -> AsyncGenerator["AsyncSession", None]:
    """Yield an AsyncSession, rolling back on exception and always closing."""
    session = AsyncSessionLocal()
    try:
        yield session
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()
