"""Top-level /menu-items and /promotions shortcuts for cross-restaurant search."""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.deps import get_session
from app.cache.deps import get_cache as get_cache_dep
from app.core.envelope import success_envelope
from app.restaurants import service as rest_service
from app.restaurants.schemas import (
    PromotionCreate,
    PromotionResponse,
    PromotionUpdate,
    MenuItemResponse,
)
from app.users.models import User
from app.auth.deps import get_current_user
from app.users.enums import UserType
from app.core.exceptions import PermissionError

router = APIRouter()


@router.get("/menu-items")
async def list_menu_items_global(
    restaurant_id: uuid.UUID | None = None,
    category_id: uuid.UUID | None = None,
    is_available: bool | None = None,
    is_featured: bool | None = None,
    search: str | None = None,
    ordering: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    payload = await rest_service.list_items_global(
        session,
        restaurant_id=restaurant_id,
        category_id=category_id,
        is_available=is_available,
        is_featured=is_featured,
        search=search,
        ordering=ordering,
        page=page,
        page_size=page_size,
    )
    return success_envelope(payload)


@router.get("/menu-items/{item_id}")
async def get_menu_item(
    item_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
    cache: Any = Depends(get_cache_dep),
) -> dict[str, Any]:
    key = None
    if cache is not None:
        key = f"cache:menu_item:{item_id}"
        cached = await cache.get(key)
        if cached is not None:
            return success_envelope(cached)
    payload = await rest_service.get_item(session, item_id)
    data = MenuItemResponse.model_validate(payload).model_dump()
    if key is not None and data is not None:
        await cache.set(key, data)
    return success_envelope(data)


@router.get("/promotions")
async def list_promotions_global(
    restaurant_id: uuid.UUID | None = None,
    only_active: bool = True,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    if restaurant_id:
        items = await rest_service.list_promotions(session, restaurant_id, only_active)
        return success_envelope(items)
    # Cross-restaurant scan: load all currently-active promotions.
    from datetime import UTC, datetime

    from app.restaurants.models import Promotion
    from sqlalchemy import select

    now = datetime.now(UTC)
    stmt = select(Promotion).where(
        Promotion.is_active == True,  # noqa: E712
        Promotion.start_date <= now,
        Promotion.end_date > now,
    )
    rows = (await session.execute(stmt)).scalars().all()
    return success_envelope([rest_service._serialize_promotion(p) for p in rows])


@router.get("/promotions/active")
async def list_active_promotions(
    session: AsyncSession = Depends(get_session),
    cache: Any = Depends(get_cache_dep),
) -> dict[str, Any]:
    from datetime import UTC, datetime

    from app.restaurants.models import Promotion
    from sqlalchemy import select

    async def _load() -> list[dict[str, Any]]:
        now = datetime.now(UTC)
        rows = (
            await session.execute(
                select(Promotion).where(
                    Promotion.is_active == True,  # noqa: E712
                    Promotion.start_date <= now,
                    Promotion.end_date > now,
                )
            )
        ).scalars().all()
        return [rest_service._serialize_promotion(p) for p in rows]

    if cache is None:
        return success_envelope(await _load())
    data = await cache.get_or_set("cache:promotion:active:global", _load)
    return success_envelope(data)


@router.get("/promotions/{promotion_id}")
async def get_promotion(
    promotion_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    payload = await rest_service.get_promotion(session, promotion_id)
    return success_envelope(PromotionResponse.model_validate(payload).model_dump())


@router.post("/promotions")
async def create_promotion(
    payload: PromotionCreate,
    current: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    if current.user_type != UserType.restaurant:
        raise PermissionError("Only restaurants can create promotions")
    restaurant_id = payload.restaurant_id if hasattr(payload, "restaurant_id") else None
    if not restaurant_id:
        raise PermissionError("restaurant_id required")
    result = await rest_service.create_promotion(
        session, restaurant_id, current, payload.model_dump()
    )
    await session.commit()
    return success_envelope(PromotionResponse.model_validate(result).model_dump())


@router.patch("/promotions/{promotion_id}")
async def update_promotion(
    promotion_id: uuid.UUID,
    payload: PromotionUpdate,
    current: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    result = await rest_service.update_promotion(
        session, promotion_id, current, payload.model_dump(exclude_unset=True)
    )
    await session.commit()
    return success_envelope(PromotionResponse.model_validate(result).model_dump())


@router.delete("/promotions/{promotion_id}")
async def delete_promotion(
    promotion_id: uuid.UUID,
    current: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    await rest_service.delete_promotion(session, promotion_id, current)
    await session.commit()
    return success_envelope({"message": "Promotion deleted"})


@router.post("/promotions/{promotion_id}/toggle-active")
async def toggle_promotion(
    promotion_id: uuid.UUID,
    current: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    result = await rest_service.toggle_promotion(session, promotion_id, current)
    await session.commit()
    return success_envelope(PromotionResponse.model_validate(result).model_dump())
