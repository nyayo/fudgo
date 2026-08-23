"""Direct tests for restaurant + promotion + menu service-layer helpers.

These exercise the service layer without going through HTTP, so the
test suite is not blocked by the asgi-event-loop hang documented in the
Phase 1 handoff.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.storage import InMemoryStorageService
from app.restaurants import service as rest_service
from app.restaurants.models import (
    MenuCategory,
    MenuItem,
    MenuItemImage,
    Promotion,
)
from app.users.enums import AuthProvider, UserType
from app.users.models import RestaurantProfile, User


pytestmark = pytest.mark.asyncio


async def _create_owner_restaurant(
    session: AsyncSession, *, is_approved: bool = True, is_active: bool = True,
    lng: float = 36.8, lat: float = -1.3,
) -> tuple[User, RestaurantProfile]:
    user = User(
        email=f"o-{uuid.uuid4().hex[:6]}@example.com",
        username=f"o_{uuid.uuid4().hex[:6]}",
        first_name="O",
        last_name="W",
        user_type=UserType.restaurant,
        auth_provider=AuthProvider.email,
        is_verified=True,
    )
    session.add(user)
    await session.flush()
    from geoalchemy2.shape import from_shape
    from shapely.geometry import Point

    profile = RestaurantProfile(
        user_id=user.id,
        restaurant_name="Diner",
        business_license=f"LIC-{uuid.uuid4().hex[:8]}",
        address="1 Main St",
        location=from_shape(Point(lng, lat), srid=4326),
        is_approved=is_approved,
        is_active=is_active,
    )
    session.add(profile)
    await session.flush()
    return user, profile


# ---------------------------------------------------------------------------
# compute_effective_price coverage
# ---------------------------------------------------------------------------


async def test_promotion_create_and_get(db_session: AsyncSession) -> None:
    owner, profile = await _create_owner_restaurant(db_session)
    promo = await rest_service.create_promotion(
        db_session,
        profile.id,
        owner,
        {
            "name": "Holiday",
            "description": "x",
            "discount": 25.0,
            "start_date": datetime.now(UTC) - timedelta(hours=1),
            "end_date": datetime.now(UTC) + timedelta(hours=1),
        },
    )
    await db_session.commit()
    assert promo["name"] == "Holiday"
    assert promo["discount"] == 25.0
    assert promo["is_currently_active"] is True

    fetched = await rest_service.get_promotion(db_session, uuid.UUID(promo["id"]))
    assert fetched["id"] == promo["id"]


async def test_promotion_update_toggle_delete(db_session: AsyncSession) -> None:
    owner, profile = await _create_owner_restaurant(db_session)
    promo = await rest_service.create_promotion(
        db_session,
        profile.id,
        owner,
        {
            "name": "X",
            "description": "",
            "discount": 10.0,
            "start_date": datetime.now(UTC) - timedelta(hours=1),
            "end_date": datetime.now(UTC) + timedelta(hours=1),
        },
    )
    await db_session.commit()

    updated = await rest_service.update_promotion(
        db_session, uuid.UUID(promo["id"]), owner, {"name": "Y", "discount": 15.0}
    )
    assert updated["name"] == "Y"
    assert updated["discount"] == 15.0

    toggled = await rest_service.toggle_promotion(
        db_session, uuid.UUID(promo["id"]), owner
    )
    assert toggled["is_active"] is False

    await rest_service.delete_promotion(db_session, uuid.UUID(promo["id"]), owner)
    await db_session.commit()
    with pytest.raises(Exception):
        await rest_service.get_promotion(db_session, uuid.UUID(promo["id"]))


async def test_promotion_owner_mismatch_403(db_session: AsyncSession) -> None:
    owner, profile = await _create_owner_restaurant(db_session)
    intruder = User(
        email="intruder@example.com",
        username=f"i_{uuid.uuid4().hex[:6]}",
        first_name="I",
        last_name="X",
        user_type=UserType.restaurant,
        auth_provider=AuthProvider.email,
        is_verified=True,
    )
    db_session.add(intruder)
    await db_session.flush()
    promo = await rest_service.create_promotion(
        db_session,
        profile.id,
        owner,
        {
            "name": "X",
            "description": "",
            "discount": 10.0,
            "start_date": datetime.now(UTC) - timedelta(hours=1),
            "end_date": datetime.now(UTC) + timedelta(hours=1),
        },
    )
    await db_session.commit()
    from app.core.exceptions import PermissionError

    with pytest.raises(PermissionError):
        await rest_service.update_promotion(
            db_session, uuid.UUID(promo["id"]), intruder, {"name": "Z"}
        )


async def test_promotion_attach_banner_round_trip(
    db_session: AsyncSession,
) -> None:
    owner, profile = await _create_owner_restaurant(db_session)
    promo = await rest_service.create_promotion(
        db_session,
        profile.id,
        owner,
        {
            "name": "X",
            "description": "",
            "discount": 10.0,
            "start_date": datetime.now(UTC) - timedelta(hours=1),
            "end_date": datetime.now(UTC) + timedelta(hours=1),
        },
    )
    await db_session.commit()
    storage = InMemoryStorageService()
    png = _make_png_bytes(64, 64)
    updated = await rest_service.attach_banner(
        db_session, uuid.UUID(promo["id"]), owner, png, "image/png", storage
    )
    await db_session.commit()
    assert updated["banner_url"].startswith("https://test.local/")
    assert storage.uploads, "storage was not called"
    # remove
    removed = await rest_service.remove_banner(
        db_session, uuid.UUID(promo["id"]), owner, storage
    )
    assert removed["banner_url"] is None


# ---------------------------------------------------------------------------
# categories
# ---------------------------------------------------------------------------


async def test_category_unique_name_constraint(db_session: AsyncSession) -> None:
    from app.core.exceptions import ConflictError

    owner, profile = await _create_owner_restaurant(db_session)
    cat = await rest_service.create_category(
        db_session, profile.id, owner, {"name": "Mains"}
    )
    await db_session.commit()
    with pytest.raises(ConflictError):
        await rest_service.create_category(
            db_session, profile.id, owner, {"name": "Mains"}
        )


async def test_category_delete_with_items_fails(
    db_session: AsyncSession,
) -> None:
    from app.core.exceptions import ValidationError

    owner, profile = await _create_owner_restaurant(db_session)
    cat = await rest_service.create_category(
        db_session, profile.id, owner, {"name": "Drinks"}
    )
    await db_session.commit()
    db_session.add(
        MenuItem(
            restaurant_id=profile.id,
            category_id=uuid.UUID(cat["id"]),
            title="Cola",
            price=Decimal("2.50"),
        )
    )
    await db_session.commit()
    with pytest.raises(ValidationError):
        await rest_service.delete_category(
            db_session, uuid.UUID(cat["id"]), owner
        )


async def test_category_attach_image(db_session: AsyncSession) -> None:
    owner, profile = await _create_owner_restaurant(db_session)
    cat = await rest_service.create_category(
        db_session, profile.id, owner, {"name": "Drinks"}
    )
    await db_session.commit()
    storage = InMemoryStorageService()
    png = _make_png_bytes(48, 48)
    img = await rest_service.attach_category_image(
        db_session, uuid.UUID(cat["id"]), owner, png, "image/png", storage
    )
    await db_session.commit()
    assert img["image_url"].startswith("https://test.local/")
    assert storage.uploads


# ---------------------------------------------------------------------------
# items
# ---------------------------------------------------------------------------


async def test_item_create_and_pricing(db_session: AsyncSession) -> None:
    owner, profile = await _create_owner_restaurant(db_session)
    cat = await rest_service.create_category(
        db_session, profile.id, owner, {"name": "Mains"}
    )
    await db_session.commit()
    promo = await rest_service.create_promotion(
        db_session,
        profile.id,
        owner,
        {
            "name": "20off",
            "description": "",
            "discount": 20.0,
            "start_date": datetime.now(UTC) - timedelta(hours=1),
            "end_date": datetime.now(UTC) + timedelta(hours=1),
        },
    )
    await db_session.commit()
    item = await rest_service.create_item(
        db_session,
        profile.id,
        owner,
        {
            "category_id": uuid.UUID(cat["id"]),
            "title": "Burger",
            "price": "1500.00",
            "promotion_ids": [uuid.UUID(promo["id"])],
        },
    )
    assert Decimal(item["price"]) == Decimal("1500.00")
    assert Decimal(item["discounted_price"]) == Decimal("1200.00")
    assert item["applied_promotion"] is not None
    assert item["applied_promotion"]["id"] == promo["id"]


async def test_item_no_promotion_discounted_equals_price(
    db_session: AsyncSession,
) -> None:
    owner, profile = await _create_owner_restaurant(db_session)
    cat = await rest_service.create_category(
        db_session, profile.id, owner, {"name": "Mains"}
    )
    await db_session.commit()
    item = await rest_service.create_item(
        db_session,
        profile.id,
        owner,
        {
            "category_id": uuid.UUID(cat["id"]),
            "title": "Fries",
            "price": "300.00",
        },
    )
    assert Decimal(item["price"]) == Decimal("300.00")
    assert Decimal(item["discounted_price"]) == Decimal("300.00")
    assert item["applied_promotion"] is None


async def test_item_highest_discount_wins(db_session: AsyncSession) -> None:
    owner, profile = await _create_owner_restaurant(db_session)
    cat = await rest_service.create_category(
        db_session, profile.id, owner, {"name": "Mains"}
    )
    await db_session.commit()
    p20 = await rest_service.create_promotion(
        db_session,
        profile.id,
        owner,
        {
            "name": "20",
            "description": "",
            "discount": 20.0,
            "start_date": datetime.now(UTC) - timedelta(hours=1),
            "end_date": datetime.now(UTC) + timedelta(hours=1),
        },
    )
    p30 = await rest_service.create_promotion(
        db_session,
        profile.id,
        owner,
        {
            "name": "30",
            "description": "",
            "discount": 30.0,
            "start_date": datetime.now(UTC) - timedelta(hours=1),
            "end_date": datetime.now(UTC) + timedelta(hours=1),
        },
    )
    await db_session.commit()
    item = await rest_service.create_item(
        db_session,
        profile.id,
        owner,
        {
            "category_id": uuid.UUID(cat["id"]),
            "title": "Pizza",
            "price": "1000.00",
            "promotion_ids": [uuid.UUID(p20["id"]), uuid.UUID(p30["id"])],
        },
    )
    assert Decimal(item["discounted_price"]) == Decimal("700.00")
    assert item["applied_promotion"]["id"] == p30["id"]


async def test_item_invalid_category_rejected(db_session: AsyncSession) -> None:
    from app.core.exceptions import ValidationError

    owner, profile = await _create_owner_restaurant(db_session)
    # Use a random category id that does not exist.
    with pytest.raises(ValidationError):
        await rest_service.create_item(
            db_session,
            profile.id,
            owner,
            {
                "category_id": uuid.uuid4(),
                "title": "X",
                "price": "100.00",
            },
        )


async def test_item_image_upload(db_session: AsyncSession) -> None:
    owner, profile = await _create_owner_restaurant(db_session)
    cat = await rest_service.create_category(
        db_session, profile.id, owner, {"name": "Mains"}
    )
    await db_session.commit()
    item = await rest_service.create_item(
        db_session,
        profile.id,
        owner,
        {
            "category_id": uuid.UUID(cat["id"]),
            "title": "X",
            "price": "100.00",
        },
    )
    storage = InMemoryStorageService()
    img = await rest_service.attach_item_image(
        db_session, uuid.UUID(item["id"]), owner, _make_png_bytes(32, 32), "image/png", storage
    )
    await db_session.commit()
    assert img["image_url"].startswith("https://test.local/")

    imgs = await rest_service.list_item_images(db_session, uuid.UUID(item["id"]))
    assert len(imgs) == 1
    await rest_service.remove_item_image(
        db_session, uuid.UUID(img["id"]), owner, storage
    )
    await db_session.commit()


async def test_owner_isolation_across_restaurants(db_session: AsyncSession) -> None:
    from app.core.exceptions import PermissionError

    owner_a, prof_a = await _create_owner_restaurant(db_session)
    owner_b, prof_b = await _create_owner_restaurant(db_session)
    # B tries to update A's restaurant
    with pytest.raises(PermissionError):
        await rest_service.update_restaurant(
            db_session, prof_a.id, owner_b, {"restaurant_name": "Hacked"}
        )


async def test_public_list_filters_unapproved(db_session: AsyncSession) -> None:
    await _create_owner_restaurant(db_session)  # approved + active
    await _create_owner_restaurant(db_session, is_approved=False)
    await _create_owner_restaurant(db_session, is_active=False)
    payload = await rest_service.list_public(db_session)
    assert payload["count"] == 1


async def test_nearby_with_zero_results(db_session: AsyncSession) -> None:
    payload = await rest_service.nearby(
        db_session, latitude=0.0, longitude=0.0, radius_km=1.0
    )
    assert payload["count"] == 0
    assert payload["items"] == []


async def test_nearby_returns_close_restaurant(db_session: AsyncSession) -> None:
    await _create_owner_restaurant(db_session, lng=36.8, lat=-1.3)
    # 10 km east
    await _create_owner_restaurant(db_session, lng=36.9, lat=-1.3)
    payload = await rest_service.nearby(
        db_session, latitude=-1.3, longitude=36.8, radius_km=20.0
    )
    assert payload["count"] == 2
    # First should be the close one (lng=36.8)
    assert float(payload["items"][0]["longitude"]) == 36.8
    assert float(payload["items"][0]["distance_km"]) < 1.0


def _make_png_bytes(width: int = 32, height: int = 32) -> bytes:
    import io

    from PIL import Image

    img = Image.new("RGB", (width, height), "red")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()
