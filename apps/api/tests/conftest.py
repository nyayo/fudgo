"""pytest configuration.

``asyncio_mode = "auto"`` is set in ``pyproject.toml`` so tests don't need
decorators. The engine fixture runs Alembic migrations once per session against
the configured DB (dev Compose starts PostGIS at ``localhost:5432``). The
client fixture injects the ASGI app into httpx so no real server is needed.
"""

import subprocess
from collections.abc import AsyncGenerator
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import get_settings
from app.main import app

REPO_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="session")
def settings():
    """Return the application settings singleton."""
    return get_settings()


@pytest.fixture(scope="session")
def db_ready():
    """Ensure Alembic migrations are applied before tests hit the DB."""
    proc = subprocess.run(
        ["uv", "run", "alembic", "upgrade", "head"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"alembic upgrade failed: {proc.stdout}\n{proc.stderr}")
    yield


@pytest.fixture(scope="session")
def engine(db_ready):  # noqa: ARG001
    """Session-scoped lifecycle hook; engine reuse happens in session fixture."""
    yield


@pytest.fixture
async def client() -> AsyncGenerator[AsyncClient, None]:
    """ASGI-injected httpx client; no real server needed."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


@pytest.fixture
async def session() -> AsyncGenerator[AsyncSession, None]:
    """Open a session directly against the real (migrated) DB."""
    engine = create_async_engine(get_settings().DATABASE_URL)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        async with factory() as s:
            yield s
    finally:
        await engine.dispose()
