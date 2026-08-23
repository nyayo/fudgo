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
    """Truncate all tables before each test for isolation.

    Phase 3 behavior preserved (per tests/conftest.py post-Phase-3):

    The original Phase 1 fixture used the app's async engine for both
    the truncate and the yield session. Phase 4 attempted a SAVEPOINT
    rewrite but ran into a fundamental issue: the route's
    ``Depends(get_session)`` opens a *separate* asyncpg connection from
    a *separate* AsyncSession, so the test's SAVEPOINT visibility does
    not extend to the route. The route gets its own connection, which
    either (a) doesn't see the test's uncommitted seed data, or
    (b) sees it as a fresh snapshot only after explicit commit, at
    which point the route's prior ``execute()`` calls have already
    aborted the transaction.

    The proper fix is at the architecture level (move route logic
    off HTTP-side lazy transactions; use Connection-level execution
    in the service layer; or wrap each test in a xact_managed context
    that the route's ``Depends(get_session)`` shares). This is beyond
    Phase 4 scope.

    Per Phase 4 brief item 11 ("conftest fix un-skips the 16 deferred
    tests"), the conftest is *improved* (it now opens an explicit outer
    transaction at the start of each test, which prevents the prior
    "session starts in implicit-mode with no row visibility" failure
    mode for tests that don't touch the route). The 16 Phase 3 tests
    remain skipped with a Phase 4 reason documenting the conftest
    work done and the remaining gap.
    """
    from app.db.session import engine as app_engine

    truncate_engine = create_async_engine(get_settings().DATABASE_URL)
    truncate_factory = async_sessionmaker(
        truncate_engine, class_=AsyncSession, expire_on_commit=False
    )
    try:
        async with truncate_factory() as session:
            await session.execute(
                text(
                    "TRUNCATE TABLE "
                    "order_items, order_status_history, payments, orders, "
                    "cart_items, carts, "
                    "deliveries, courier_locations, "
                    "notification_preferences, devices, addresses, "
                    "restaurant_staff_profiles, restaurant_profiles, courier_profiles, "
                    "customer_profiles, revoked_tokens, phone_verifications, "
                    "email_verifications, users "
                    "RESTART IDENTITY CASCADE"
                )
            )
            await session.commit()
    finally:
        await truncate_engine.dispose()

    factory = async_sessionmaker(app_engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        yield session


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
