"""Per-domain conftest for restaurants tests.

Provides storage override (InMemoryStorageService) so no R2 calls happen
during tests, and a few factory helpers for restaurant + menu setup.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from geoalchemy2.shape import from_shape
from shapely.geometry import Point
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.storage import InMemoryStorageService, get_storage_service
from app.main import app
from app.users.enums import AuthProvider, UserType
from app.users.models import RestaurantProfile, User


@pytest.fixture
def storage() -> Any:
    """Swap storage for an in-memory implementation."""
    s = InMemoryStorageService()
    app.dependency_overrides[get_storage_service] = lambda: s
    try:
        yield s
    finally:
        app.dependency_overrides.pop(get_storage_service, None)


@pytest.fixture
def make_restaurant_owner():
    """Factory: create a User (restaurant) + RestaurantProfile."""

    async def _make(
        session: AsyncSession,
        *,
        email: str = "owner@example.com",
        is_approved: bool = True,
        is_active: bool = True,
        restaurant_name: str = "Test Restaurant",
        address: str = "1 Main St",
        lng: float = 36.8,
        lat: float = -1.3,
    ) -> tuple[User, RestaurantProfile]:
        user = User(
            email=email,
            username=f"owner_{uuid.uuid4().hex[:8]}",
            first_name="Owner",
            last_name="X",
            user_type=UserType.restaurant,
            auth_provider=AuthProvider.email,
            is_verified=True,
        )
        session.add(user)
        await session.flush()
        profile = RestaurantProfile(
            user_id=user.id,
            restaurant_name=restaurant_name,
            business_license=f"LIC-{uuid.uuid4().hex[:8]}",
            address=address,
            location=from_shape(Point(lng, lat), srid=4326),
            is_approved=is_approved,
            is_active=is_active,
        )
        session.add(profile)
        await session.flush()
        return user, profile

    return _make
