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
    """Truncate all Phase-1 tables before each test for isolation.

    Reuses the app's async engine (single NullPool connection per call) so
    asyncpg's cross-loop check passes.
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
