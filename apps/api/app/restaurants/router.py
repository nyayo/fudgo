"""Restaurant + menu + promotion + image endpoints.

All routes are thin: they parse input, call the service layer, return the
envelope. Public reads (list/detail/nearby/menu browse) require no auth.
Owner-only mutations are gated by ``require_restaurant_owner``.
"""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.deps import get_current_user, get_session
from app.core.envelope import success_envelope
from app.restaurants import service as rest_service
from app.restaurants.schemas import (
    MenuCategoryCreate,
    MenuCategoryResponse,
    MenuCategoryUpdate,
    MenuItemCreate,
    MenuItemResponse,
    MenuItemUpdate,
    PromotionCreate,
    PromotionResponse,
    PromotionUpdate,
    RestaurantResponse,
    RestaurantUpdate,
)
from app.users.models import User

router = APIRouter()


def _require_owner(restaurant_id: uuid.UUID, current: User) -> None:
    """Thin guard: defer the actual restaurant lookup to the service for
    defense-in-depth, but bail here if the caller is not a restaurant owner."""
    from app.users.enums import UserType

    if current.user_type not in (UserType.restaurant, UserType.restaurant_staff):
        from app.core.exceptions import PermissionError

        raise PermissionError("Only restaurants can perform this action")
    _ = restaurant_id  # checked inside the service


# ---------------------------------------------------------------------------
# Restaurants
# ---------------------------------------------------------------------------


@router.get("/restaurants")
async def list_restaurants(
    search: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    payload = await rest_service.list_public(
        session, search=search, page=page, page_size=page_size
    )
    return success_envelope(payload)


@router.get("/restaurants/nearby")
async def nearby_restaurants(
    latitude: float = Query(..., ge=-90.0, le=90.0),
    longitude: float = Query(..., ge=-180.0, le=180.0),
    radius_km: float = Query(5.0, gt=0.0),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    from app.core.config import get_settings
    from app.core.exceptions import ValidationError

    settings = get_settings()
    if radius_km > settings.MAX_SEARCH_RADIUS_KM:
        raise ValidationError(
            f"radius_km must be <= {settings.MAX_SEARCH_RADIUS_KM}"
        )
    payload = await rest_service.nearby(session, latitude, longitude, radius_km)
    return success_envelope(payload)


@router.get("/restaurants/{restaurant_id}")
async def get_restaurant(
    restaurant_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    payload = await rest_service.get_by_id(session, restaurant_id)
    return success_envelope(RestaurantResponse.model_validate(payload).model_dump())


@router.patch("/restaurants/{restaurant_id}")
async def update_restaurant(
    restaurant_id: uuid.UUID,
    payload: RestaurantUpdate,
    current: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    _require_owner(restaurant_id, current)
    data = payload.model_dump(exclude_unset=True)
    result = await rest_service.update_restaurant(session, restaurant_id, current, data)
    await session.commit()
    return success_envelope(RestaurantResponse.model_validate(result).model_dump())


# ---------------------------------------------------------------------------
# Categories
# ---------------------------------------------------------------------------


@router.get("/restaurants/{restaurant_id}/categories")
async def list_categories(
    restaurant_id: uuid.UUID,
    only_active: bool = True,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    items = await rest_service.list_categories(session, restaurant_id, only_active)
    return success_envelope(items)


@router.post("/restaurants/{restaurant_id}/categories")
async def create_category(
    restaurant_id: uuid.UUID,
    payload: MenuCategoryCreate,
    current: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    _require_owner(restaurant_id, current)
    result = await rest_service.create_category(
        session, restaurant_id, current, payload.model_dump()
    )
    await session.commit()
    return success_envelope(MenuCategoryResponse.model_validate(result).model_dump())


@router.get("/restaurants/{restaurant_id}/categories/{category_id}")
async def get_category(
    restaurant_id: uuid.UUID,
    category_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    result = await rest_service.get_category(session, category_id)
    return success_envelope(MenuCategoryResponse.model_validate(result).model_dump())


@router.patch("/restaurants/{restaurant_id}/categories/{category_id}")
async def update_category(
    restaurant_id: uuid.UUID,
    category_id: uuid.UUID,
    payload: MenuCategoryUpdate,
    current: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    _require_owner(restaurant_id, current)
    result = await rest_service.update_category(
        session, category_id, current, payload.model_dump(exclude_unset=True)
    )
    await session.commit()
    return success_envelope(MenuCategoryResponse.model_validate(result).model_dump())


@router.delete("/restaurants/{restaurant_id}/categories/{category_id}")
async def delete_category(
    restaurant_id: uuid.UUID,
    category_id: uuid.UUID,
    current: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    _require_owner(restaurant_id, current)
    await rest_service.delete_category(session, category_id, current)
    await session.commit()
    return success_envelope({"message": "Category deleted"})


@router.post("/restaurants/{restaurant_id}/categories/{category_id}/image")
async def attach_category_image(
    restaurant_id: uuid.UUID,
    category_id: uuid.UUID,
    file: UploadFile = File(...),
    current: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
    storage: Any = Depends(__import__("app.core.storage", fromlist=["get_storage_service"]).get_storage_service),
) -> dict[str, Any]:
    _require_owner(restaurant_id, current)
    content = await file.read()
    result = await rest_service.attach_category_image(
        session, category_id, current, content, file.content_type, storage
    )
    await session.commit()
    return success_envelope(result)


@router.delete("/restaurants/{restaurant_id}/categories/{category_id}/image")
async def remove_category_image(
    restaurant_id: uuid.UUID,
    category_id: uuid.UUID,
    image_id: uuid.UUID,
    current: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
    storage: Any = Depends(__import__("app.core.storage", fromlist=["get_storage_service"]).get_storage_service),
) -> dict[str, Any]:
    _require_owner(restaurant_id, current)
    await rest_service.remove_category_image(session, image_id, current, storage)
    await session.commit()
    return success_envelope({"message": "Image removed"})


# ---------------------------------------------------------------------------
# Items (nested under category, plus flat global + per-restaurant)
# ---------------------------------------------------------------------------


@router.get("/restaurants/{restaurant_id}/items")
async def list_items_for_restaurant(
    restaurant_id: uuid.UUID,
    category_id: uuid.UUID | None = None,
    is_available: bool | None = None,
    is_featured: bool | None = None,
    search: str | None = None,
    ordering: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    payload = await rest_service.list_items_for_restaurant(
        session,
        restaurant_id,
        category_id=category_id,
        is_available=is_available,
        is_featured=is_featured,
        search=search,
        ordering=ordering,
        page=page,
        page_size=page_size,
    )
    return success_envelope(payload)


@router.get("/restaurants/{restaurant_id}/categories/{category_id}/items")
async def list_items_in_category(
    restaurant_id: uuid.UUID,
    category_id: uuid.UUID,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    payload = await rest_service.list_items_for_restaurant(
        session, restaurant_id, category_id=category_id, page=page, page_size=page_size
    )
    return success_envelope(payload)


@router.post("/restaurants/{restaurant_id}/categories/{category_id}/items")
async def create_item(
    restaurant_id: uuid.UUID,
    category_id: uuid.UUID,
    payload: MenuItemCreate,
    current: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    _require_owner(restaurant_id, current)
    if payload.category_id != category_id:
        from app.core.exceptions import ValidationError
        raise ValidationError("category_id in path and body must match")
    result = await rest_service.create_item(
        session, restaurant_id, current, payload.model_dump()
    )
    await session.commit()
    return success_envelope(result)


@router.get("/restaurants/{restaurant_id}/categories/{category_id}/items/{item_id}")
async def get_item(
    restaurant_id: uuid.UUID,
    category_id: uuid.UUID,
    item_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    result = await rest_service.get_item(session, item_id)
    return success_envelope(MenuItemResponse.model_validate(result).model_dump())


def _invalidate_item_cache(item_id, restaurant_id) -> None:
    """Fire cache invalidation tasks after a menu-item write (Phase 7)."""
    try:
        from app.cache.invalidation import (
            invalidate_menu_item,
            invalidate_restaurant,
        )

        invalidate_menu_item.delay(str(item_id), str(restaurant_id))
        invalidate_restaurant.delay(str(restaurant_id))
    except Exception:
        pass


@router.patch("/restaurants/{restaurant_id}/categories/{category_id}/items/{item_id}")
async def update_item(
    restaurant_id: uuid.UUID,
    category_id: uuid.UUID,
    item_id: uuid.UUID,
    payload: MenuItemUpdate,
    current: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    _require_owner(restaurant_id, current)
    result = await rest_service.update_item(
        session, item_id, current, payload.model_dump(exclude_unset=True)
    )
    await session.commit()
    _invalidate_item_cache(item_id, restaurant_id)
    return success_envelope(MenuItemResponse.model_validate(result).model_dump())


@router.delete("/restaurants/{restaurant_id}/categories/{category_id}/items/{item_id}")
async def delete_item(
    restaurant_id: uuid.UUID,
    category_id: uuid.UUID,
    item_id: uuid.UUID,
    current: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    _require_owner(restaurant_id, current)
    await rest_service.delete_item(session, item_id, current)
    await session.commit()
    _invalidate_item_cache(item_id, restaurant_id)
    return success_envelope({"message": "Item deleted"})


# Item images


@router.post("/restaurants/{restaurant_id}/categories/{category_id}/items/{item_id}/images")
async def attach_item_image(
    restaurant_id: uuid.UUID,
    category_id: uuid.UUID,
    item_id: uuid.UUID,
    file: UploadFile = File(...),
    current: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
    storage: Any = Depends(__import__("app.core.storage", fromlist=["get_storage_service"]).get_storage_service),
) -> dict[str, Any]:
    _require_owner(restaurant_id, current)
    content = await file.read()
    result = await rest_service.attach_item_image(
        session, item_id, current, content, file.content_type, storage
    )
    await session.commit()
    return success_envelope(result)


@router.get("/restaurants/{restaurant_id}/categories/{category_id}/items/{item_id}/images")
async def list_item_images(
    restaurant_id: uuid.UUID,
    category_id: uuid.UUID,
    item_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    items = await rest_service.list_item_images(session, item_id)
    return success_envelope(items)


@router.delete("/restaurants/{restaurant_id}/categories/{category_id}/items/{item_id}/images/{image_id}")
async def remove_item_image(
    restaurant_id: uuid.UUID,
    category_id: uuid.UUID,
    item_id: uuid.UUID,
    image_id: uuid.UUID,
    current: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
    storage: Any = Depends(__import__("app.core.storage", fromlist=["get_storage_service"]).get_storage_service),
) -> dict[str, Any]:
    _require_owner(restaurant_id, current)
    await rest_service.remove_item_image(session, image_id, current, storage)
    await session.commit()
    return success_envelope({"message": "Image removed"})


# Item promotions


@router.post("/restaurants/{restaurant_id}/categories/{category_id}/items/{item_id}/promotions")
async def add_item_promotion(
    restaurant_id: uuid.UUID,
    category_id: uuid.UUID,
    item_id: uuid.UUID,
    promotion_id: uuid.UUID,
    current: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    _require_owner(restaurant_id, current)
    result = await rest_service.add_promotion(session, item_id, current, promotion_id)
    await session.commit()
    return success_envelope(MenuItemResponse.model_validate(result).model_dump())


@router.delete("/restaurants/{restaurant_id}/categories/{category_id}/items/{item_id}/promotions/{promotion_id}")
async def remove_item_promotion(
    restaurant_id: uuid.UUID,
    category_id: uuid.UUID,
    item_id: uuid.UUID,
    promotion_id: uuid.UUID,
    current: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    _require_owner(restaurant_id, current)
    result = await rest_service.remove_promotion(session, item_id, current, promotion_id)
    await session.commit()
    return success_envelope(MenuItemResponse.model_validate(result).model_dump())


# ---------------------------------------------------------------------------
# Promotions
# ---------------------------------------------------------------------------


@router.get("/restaurants/{restaurant_id}/promotions")
async def list_promotions(
    restaurant_id: uuid.UUID,
    only_active: bool = False,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    items = await rest_service.list_promotions(session, restaurant_id, only_active)
    return success_envelope(items)


@router.post("/restaurants/{restaurant_id}/promotions")
async def create_promotion(
    restaurant_id: uuid.UUID,
    payload: PromotionCreate,
    current: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    _require_owner(restaurant_id, current)
    result = await rest_service.create_promotion(
        session, restaurant_id, current, payload.model_dump()
    )
    await session.commit()
    return success_envelope(PromotionResponse.model_validate(result).model_dump())


@router.get("/restaurants/{restaurant_id}/promotions/{promotion_id}")
async def get_promotion(
    restaurant_id: uuid.UUID,
    promotion_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    result = await rest_service.get_promotion(session, promotion_id)
    return success_envelope(PromotionResponse.model_validate(result).model_dump())


@router.patch("/restaurants/{restaurant_id}/promotions/{promotion_id}")
async def update_promotion(
    restaurant_id: uuid.UUID,
    promotion_id: uuid.UUID,
    payload: PromotionUpdate,
    current: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    _require_owner(restaurant_id, current)
    result = await rest_service.update_promotion(
        session, promotion_id, current, payload.model_dump(exclude_unset=True)
    )
    await session.commit()
    return success_envelope(PromotionResponse.model_validate(result).model_dump())


@router.delete("/restaurants/{restaurant_id}/promotions/{promotion_id}")
async def delete_promotion(
    restaurant_id: uuid.UUID,
    promotion_id: uuid.UUID,
    current: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    _require_owner(restaurant_id, current)
    await rest_service.delete_promotion(session, promotion_id, current)
    await session.commit()
    return success_envelope({"message": "Promotion deleted"})


@router.post("/restaurants/{restaurant_id}/promotions/{promotion_id}/toggle-active")
async def toggle_promotion(
    restaurant_id: uuid.UUID,
    promotion_id: uuid.UUID,
    current: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    _require_owner(restaurant_id, current)
    result = await rest_service.toggle_promotion(session, promotion_id, current)
    await session.commit()
    return success_envelope(PromotionResponse.model_validate(result).model_dump())


@router.post("/restaurants/{restaurant_id}/promotions/{promotion_id}/banner")
async def attach_promotion_banner(
    restaurant_id: uuid.UUID,
    promotion_id: uuid.UUID,
    file: UploadFile = File(...),
    current: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
    storage: Any = Depends(__import__("app.core.storage", fromlist=["get_storage_service"]).get_storage_service),
) -> dict[str, Any]:
    _require_owner(restaurant_id, current)
    content = await file.read()
    result = await rest_service.attach_banner(
        session, promotion_id, current, content, file.content_type, storage
    )
    await session.commit()
    return success_envelope(PromotionResponse.model_validate(result).model_dump())


@router.delete("/restaurants/{restaurant_id}/promotions/{promotion_id}/banner")
async def remove_promotion_banner(
    restaurant_id: uuid.UUID,
    promotion_id: uuid.UUID,
    current: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
    storage: Any = Depends(__import__("app.core.storage", fromlist=["get_storage_service"]).get_storage_service),
) -> dict[str, Any]:
    _require_owner(restaurant_id, current)
    result = await rest_service.remove_banner(session, promotion_id, current, storage)
    await session.commit()
    return success_envelope(PromotionResponse.model_validate(result).model_dump())


@router.get("/restaurants/{restaurant_id}/promotions/{promotion_id}/menu-items")
async def list_promotion_items(
    restaurant_id: uuid.UUID,
    promotion_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    from sqlalchemy import text

    result = await session.execute(
        text(
            "SELECT mi.id FROM menu_item_promotions mip "
            "JOIN menu_items mi ON mi.id = mip.item_id "
            "WHERE mip.promotion_id = :pid"
        ),
        {"pid": str(promotion_id)},
    )
    item_ids = [r[0] for r in result.all()]
    out: list[dict[str, Any]] = []
    from app.restaurants.service import get_item as _get_item

    for iid in item_ids:
        try:
            out.append(await _get_item(session, iid))
        except Exception:
            continue
    return success_envelope(out)
