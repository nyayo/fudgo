"""Favorites + customer preference service (Phase 8)."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.reviews.models import (
    DietaryTag,
    customer_favorite_menu_items,
    customer_favorite_restaurants,
)
from app.users.models import CustomerProfile


class InvalidDietaryTag(Exception):
    pass


async def update_customer_preferences(
    session: AsyncSession,
    *,
    customer: CustomerProfile,
    dietary_preferences: list[str] | None = None,
    allergens: list[str] | None = None,
) -> CustomerProfile:
    """Update dietary prefs + allergens. Slugs validated against dietary_tags."""
    if dietary_preferences is not None:
        rows = (
            await session.execute(
                select(DietaryTag.slug).where(
                    DietaryTag.slug.in_(dietary_preferences),  # type: ignore[arg-type]
                    DietaryTag.is_active == True,  # noqa: E712
                    DietaryTag.is_allergen == False,  # noqa: E712
                )
            )
        ).scalars().all()
        invalid = set(dietary_preferences) - set(rows)
        if invalid:
            raise InvalidDietaryTag(f"Unknown dietary tags: {sorted(invalid)}")
        customer.dietary_preferences = dietary_preferences  # type: ignore[assignment]

    if allergens is not None:
        rows = (
            await session.execute(
                select(DietaryTag.slug).where(
                    DietaryTag.slug.in_(allergens),  # type: ignore[arg-type]
                    DietaryTag.is_active == True,  # noqa: E712
                    DietaryTag.is_allergen == True,  # noqa: E712
                )
            )
        ).scalars().all()
        invalid = set(allergens) - set(rows)
        if invalid:
            raise InvalidDietaryTag(f"Unknown allergen tags: {sorted(invalid)}")
        customer.allergens = allergens  # type: ignore[assignment]

    await session.flush()
    return customer


# ---------------------------------------------------------------------------
# Favorites (idempotent M2M)
# ---------------------------------------------------------------------------


async def add_favorite_restaurant(
    session: AsyncSession, *, customer_id: UUID, restaurant_id: UUID
) -> None:
    await session.execute(
        text(
            "INSERT INTO customer_favorite_restaurants (customer_id, restaurant_id) "
            "VALUES (:c, :r) ON CONFLICT DO NOTHING"
        ),
        {"c": str(customer_id), "r": str(restaurant_id)},
    )


async def remove_favorite_restaurant(
    session: AsyncSession, *, customer_id: UUID, restaurant_id: UUID
) -> int:
    result = await session.execute(
        text(
            "DELETE FROM customer_favorite_restaurants "
            "WHERE customer_id = :c AND restaurant_id = :r"
        ),
        {"c": str(customer_id), "r": str(restaurant_id)},
    )
    return int(result.rowcount or 0)


async def list_favorite_restaurant_ids(
    session: AsyncSession, *, customer_id: UUID, limit: int = 50
) -> list[UUID]:
    rows = (
        await session.execute(
            select(customer_favorite_restaurants.c.restaurant_id)
            .where(customer_favorite_restaurants.c.customer_id == customer_id)
            .order_by(customer_favorite_restaurants.c.added_at.desc())
            .limit(limit)
        )
    ).scalars().all()
    return list(rows)


async def add_favorite_menu_item(
    session: AsyncSession, *, customer_id: UUID, menu_item_id: UUID
) -> None:
    await session.execute(
        text(
            "INSERT INTO customer_favorite_menu_items (customer_id, menu_item_id) "
            "VALUES (:c, :m) ON CONFLICT DO NOTHING"
        ),
        {"c": str(customer_id), "m": str(menu_item_id)},
    )


async def remove_favorite_menu_item(
    session: AsyncSession, *, customer_id: UUID, menu_item_id: UUID
) -> int:
    result = await session.execute(
        text(
            "DELETE FROM customer_favorite_menu_items "
            "WHERE customer_id = :c AND menu_item_id = :m"
        ),
        {"c": str(customer_id), "m": str(menu_item_id)},
    )
    return int(result.rowcount or 0)


async def list_favorite_menu_item_ids(
    session: AsyncSession, *, customer_id: UUID, limit: int = 100
) -> list[UUID]:
    rows = (
        await session.execute(
            select(customer_favorite_menu_items.c.menu_item_id)
            .where(customer_favorite_menu_items.c.customer_id == customer_id)
            .order_by(customer_favorite_menu_items.c.added_at.desc())
            .limit(limit)
        )
    ).scalars().all()
    return list(rows)


# ---------------------------------------------------------------------------
# Taxonomy listings (cache-friendly; callers pass CacheService | None)
# ---------------------------------------------------------------------------


async def list_cuisines(session: AsyncSession, cache: Any = None) -> list[dict[str, Any]]:
    async def _load() -> list[dict[str, Any]]:
        from app.reviews.models import Cuisine

        rows = (
            await session.execute(
                select(Cuisine)
                .where(Cuisine.is_active == True)  # noqa: E712
                .order_by(Cuisine.display_order.asc())
            )
        ).scalars().all()
        return [
            {
                "id": str(c.id),
                "slug": c.slug,
                "name": c.name,
                "icon_url": c.icon_url,
                "display_order": c.display_order,
            }
            for c in rows
        ]

    if cache is None:
        return await _load()
    from app.core.config import get_settings

    # Long TTL — invalidated on admin CRUD.
    return await cache.get_or_set(
        "cache:cuisines:all", _load, ttl_s=get_settings().CACHE_DEFAULT_TTL_S
    )


async def list_dietary_tags(session: AsyncSession, cache: Any = None) -> list[dict[str, Any]]:
    async def _load() -> list[dict[str, Any]]:
        rows = (
            await session.execute(
                select(DietaryTag)
                .where(DietaryTag.is_active == True)  # noqa: E712
                .order_by(DietaryTag.name.asc())
            )
        ).scalars().all()
        return [
            {
                "id": str(t.id),
                "slug": t.slug,
                "name": t.name,
                "is_allergen": t.is_allergen,
            }
            for t in rows
        ]

    if cache is None:
        return await _load()
    from app.core.config import get_settings

    return await cache.get_or_set(
        "cache:dietary_tags:all", _load, ttl_s=get_settings().CACHE_DEFAULT_TTL_S
    )
