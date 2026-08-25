"""Cached endpoint tests: GET /menu-items/{id} + invalidation on PATCH/DELETE."""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any

import pytest

fakeredis = pytest.importorskip("fakeredis")


@pytest.fixture
def fake_cache(app: Any = None) -> Any:
    """Wire a fakeredis-backed CacheService into both the invalidation
    module and app.state so endpoint deps can resolve it."""
    from app.cache.cache_service import CacheService
    from app.cache.invalidation import set_cache

    from fakeredis import aioredis as fr

    cache = CacheService(fr.FakeRedis(decode_responses=True))
    set_cache(cache)
    from app.main import app as fastapi_app

    fastapi_app.state.cache = cache
    yield cache
    set_cache(None)


async def _restaurant_with_item(db_session: Any) -> tuple[Any, Any, Any]:
    from geoalchemy2.shape import from_shape
    from shapely.geometry import Point

    from app.restaurants.models import MenuCategory, MenuItem, RestaurantProfile
    from app.users.models import User

    owner = User(
        email=f"ro_{uuid.uuid4().hex[:6]}@x.com",
        username=f"ro_{uuid.uuid4().hex[:6]}",
        first_name="R", last_name="O",
        user_type="restaurant", is_verified=True,
    )
    db_session.add(owner)
    await db_session.flush()
    r = RestaurantProfile(
        user_id=owner.id, restaurant_name="Cafe7",
        business_license=f"LIC-{uuid.uuid4().hex[:6]}",
        address="1 Rd", location=from_shape(Point(36.8, -1.3), srid=4326),
        delivery_fee=Decimal("50"), delivery_radius_km=10.0,
        min_order_amount=Decimal("0"), opening_hours={},
        is_approved=True, is_active=True,
    )
    db_session.add(r)
    await db_session.flush()
    cat = MenuCategory(restaurant_id=r.id, name="Mains", is_active=True)
    db_session.add(cat)
    await db_session.flush()
    item = MenuItem(
        restaurant_id=r.id, category_id=cat.id, title="Chai",
        price=Decimal("100.00"), is_available=True,
    )
    db_session.add(item)
    await db_session.flush()
    return r, item, owner


def _hdr(user: Any) -> dict[str, str]:
    from app.auth.jwt import create_access_token

    return {"Authorization": f"Bearer {create_access_token(user.id)}"}


async def test_get_menu_item_cache_hit_then_invalidate(
    client: Any, db_session: Any, fake_cache: Any,
) -> None:
    from app.auth.jwt import create_access_token

    r, item, owner = await _restaurant_with_item(db_session)

    # First GET: miss -> DB -> populate.
    resp1 = await client.get(f"/api/v2/menu-items/{item.id}")
    assert resp1.status_code == 200
    key = f"cache:menu_item:{item.id}"
    assert await fake_cache.get(key) is not None

    # Second GET served from cache (key still present).
    resp2 = await client.get(f"/api/v2/menu-items/{item.id}")
    assert resp2.status_code == 200

    # PATCH invalidates via the Celery task.
    patch = await client.patch(
        f"/api/v2/restaurants/{r.id}/categories/{item.category_id}/items/{item.id}",
        json={"price": "120.00"},
        headers=_hdr(owner),
    )
    assert patch.status_code == 200
    assert await fake_cache.get(key) is None  # invalidated

    # Next GET repopulates from DB with the new price.
    resp3 = await client.get(f"/api/v2/menu-items/{item.id}")
    assert resp3.json()["data"]["price"] == "120.00"
    assert await fake_cache.get(key) is not None


async def test_delete_menu_item_invalidates(
    client: Any, db_session: Any, fake_cache: Any,
) -> None:
    r, item, owner = await _restaurant_with_item(db_session)
    key = f"cache:menu_item:{item.id}"
    await fake_cache.set(key, {"stale": True})

    resp = await client.delete(
        f"/api/v2/restaurants/{r.id}/categories/{item.category_id}/items/{item.id}",
        headers=_hdr(owner),
    )
    assert resp.status_code == 200
    assert await fake_cache.get(key) is None


async def test_promotions_active_cached(
    client: Any, db_session: Any, fake_cache: Any,
) -> None:
    resp = await client.get("/api/v2/promotions/active")
    assert resp.status_code == 200
    assert await fake_cache.get("cache:promotion:active:global") is not None
