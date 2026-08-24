"""Top-level pytest fixtures.

Provides ``db_session`` (TRUNCATE-isolated), ``client`` (httpx ASGI), and
factories for users + OTP rows. Routed tests live under tests/auth/ and
tests/users/ and pick these fixtures up automatically.
"""

import uuid
from collections.abc import AsyncGenerator
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.auth.passwords import hash_password
from app.core.config import get_settings
from app.main import app
from app.users.enums import AuthProvider, UserType
from app.users.models import User


@pytest.fixture(autouse=True)
def _sync_limiter_reset():
    """Reset slowapi counters between tests so throttles don't leak."""
    from app.auth.deps import limiter

    limiter.reset()


@pytest.fixture(scope="session")
def engine() -> None:
    yield


@pytest.fixture
async def db_session() -> AsyncGenerator[AsyncSession, None]:
    """Truncate + share one connection between the test session and routes.

    Phase 5 fix (the "conftest mystery" from Phases 3 and 4, now solved):

    The InFailedSQLTransaction failures were never a fixture problem per
    se -- they were *downstream symptoms* of two real bugs in
    ``checkout_cart``:

    1. ``_restaurant_in_range`` bound PostGIS parameters with
       ``:param::geography`` cast syntax. asyncpg rejects that (its own
       placeholder parser collides with ``::``), raising
       PostgresSyntaxError. The function's broad ``except Exception``
       swallowed it and ran the haversine fallback -- but the transaction
       was already aborted, so the NEXT statement failed with the
       misleading InFailedSQLTransaction.
    2. ``orders.order_number`` was VARCHAR(20), but the generated format
       FUDGO-YYYYMMDD-NNNNNN is 21 chars, so the INSERT always failed.

    Both are fixed in this commit (see migration 0008). With them gone,
    the simple fixture below works for both service-layer tests and
    HTTP-level tests: the route's ``Depends(get_db_session)`` is
    overridden to yield the SAME AsyncSession the test uses, so seed
    data and route reads share one transaction on one connection.
    """
    from app.db.session import engine as app_engine
    from app.auth.deps import get_db_session

    conn = await app_engine.connect()
    outer_tx = await conn.begin()
    test_session = AsyncSession(bind=conn, expire_on_commit=False)

    async def _test_get_session() -> AsyncGenerator[AsyncSession, None]:
        # Yield the SAME session object; one session per connection.
        yield test_session

    app.dependency_overrides[get_db_session] = _test_get_session

    try:
        yield test_session
        # Commit at the end of a passing test so data is visible to any
        # follow-on assertions; rollback happens implicitly at teardown
        # via outer_tx.rollback().
        await test_session.commit()
    finally:
        app.dependency_overrides.pop(get_db_session, None)
        await test_session.close()
        try:
            await outer_tx.rollback()
        except Exception:
            pass
        try:
            await conn.close()
        except Exception:
            pass


@pytest.fixture
async def client() -> AsyncGenerator[AsyncClient, None]:
    """ASGI-injected httpx client against the live app."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


@pytest.fixture
def make_user():
    """Build a User row directly via the DB."""

    async def _make(
        session: AsyncSession,
        *,
        email: str = "user@example.com",
        user_type: UserType = UserType.customer,
        is_verified: bool = True,
        auth_provider: AuthProvider = AuthProvider.email,
        password: str | None = "supersecret123",
        phone: str | None = None,
        first_name: str = "Test",
        last_name: str = "User",
    ) -> User:
        user = User(
            email=email,
            phone=phone,
            username=f"user_{uuid.uuid4().hex[:8]}",
            first_name=first_name,
            last_name=last_name,
            user_type=user_type,
            auth_provider=auth_provider,
            is_verified=is_verified,
            password_hash=hash_password(password) if password else None,
        )
        session.add(user)
        await session.flush()
        return user

    return _make


@pytest.fixture
def make_otp():
    """Return (plain, hash) for a freshly generated 6-digit OTP."""

    def _make() -> tuple[str, str]:
        import hashlib

        from app.auth.otp_service import generate_otp

        plain = generate_otp()
        return plain, hashlib.sha256(plain.encode("utf-8")).hexdigest()

    return _make


@pytest.fixture
def auth_headers() -> Any:
    """Helper to build a Bearer header map for a given token."""

    def _build(token: str) -> dict[str, str]:
        return {"Authorization": f"Bearer {token}"}

    return _build
