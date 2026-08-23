"""Business logic for the restaurants domain.

All functions are async. Routes stay thin. No raw SQL outside the
``nearby()`` helper, which is a single ``text()`` query (per brief
section 4.7). The single source of truth for pricing is
:func:`compute_effective_price` — Phase 3 orders will call this.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Sequence

from geoalchemy2.shape import to_shape
from sqlalchemy import func, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import (
    ConflictError,
    NotFoundError,
    PermissionError,
    ValidationError,
)
from app.restaurants import image_service
from app.restaurants.models import (
    MenuCategory,
    MenuCategoryImage,
    MenuItem,
    MenuItemImage,
    Promotion,
)
from app.users.models import RestaurantProfile, User


# ---------------------------------------------------------------------------
# pure pricing
# ---------------------------------------------------------------------------


def compute_effective_price(
    item: MenuItem,
    promotions: Sequence[Promotion] | None = None,
    at_time: datetime | None = None,
) -> tuple[Decimal, Promotion | None]:
    """Return ``(effective_price, applied_promotion or None)``.

    Picks the highest-discount active promotion. ``at_time`` is injected so
    Phase 3 can price historical orders deterministically.
    """
    when = at_time or datetime.now(UTC)
    candidates: list[Promotion] = []
    for promo in promotions or []:
        if not promo.is_active:
            continue
        if not (promo.start_date <= when < promo.end_date):
            continue
        candidates.append(promo)
    if not candidates:
        return Decimal(item.price), None
    winner = max(candidates, key=lambda p: p.discount)
    pct = Decimal(winner.discount) / Decimal(100)
    new_price = (Decimal(item.price) * (Decimal(1) - pct)).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )
    return new_price, winner


# ---------------------------------------------------------------------------
# restaurant shape
# ---------------------------------------------------------------------------


def _restaurant_point(profile: RestaurantProfile) -> tuple[float, float]:
    if profile.location is None:
        return 0.0, 0.0
    g = to_shape(profile.location)
    return float(g.x), float(g.y)


def serialize_restaurant(
    profile: RestaurantProfile, restaurant_name: str | None = None
) -> dict[str, Any]:
    lng, lat = _restaurant_point(profile)
    return {
        "id": str(profile.id),
        "user_id": str(profile.user_id),
        "restaurant_name": restaurant_name or profile.restaurant_name,
        "business_license": profile.business_license,
        "address": profile.address,
        "latitude": lat,
        "longitude": lng,
        "opening_hours": profile.opening_hours or {},
        "rating": float(profile.rating or 0),
        "is_approved": profile.is_approved,
        "is_active": profile.is_active,
        "image_url": None,
        "logo_url": None,
    }


def serialize_restaurant_list_row(
    row: dict[str, Any],
) -> dict[str, Any]:
    return {
        "id": str(row["id"]),
        "restaurant_name": row["restaurant_name"],
        "address": row["address"],
        "rating": float(row["rating"] or 0),
        "image_url": None,
        "distance_km": row.get("distance_km"),
        "latitude": float(row["lat"]),
        "longitude": float(row["lng"]),
    }


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


async def _restaurant_for_user(
    session: AsyncSession, user_id: uuid.UUID
) -> RestaurantProfile:
    profile = (
        await session.execute(
            select(RestaurantProfile).where(RestaurantProfile.user_id == user_id)
        )
    ).scalar_one_or_none()
    if profile is None:
        raise PermissionError("Only restaurant owners can perform this action")
    return profile


async def _public_restaurant(
    session: AsyncSession, restaurant_id: uuid.UUID
) -> RestaurantProfile:
    profile = (
        await session.execute(
            select(RestaurantProfile).where(RestaurantProfile.id == restaurant_id)
        )
    ).scalar_one_or_none()
    if (
        profile is None
        or not profile.is_approved
        or not profile.is_active
    ):
        raise NotFoundError("Restaurant not found")
    return profile


async def _ensure_owner(
    session: AsyncSession,
    restaurant_id: uuid.UUID,
    owner: User,
) -> RestaurantProfile:
    profile = await _restaurant_for_user(session, owner.id)
    if profile.id != restaurant_id:
        raise PermissionError("You do not own this restaurant")
    return profile


def _is_currently_active(promo: Promotion, at: datetime | None = None) -> bool:
    when = at or datetime.now(UTC)
    return bool(promo.is_active) and promo.start_date <= when < promo.end_date


# ---------------------------------------------------------------------------
# RestaurantService
# ---------------------------------------------------------------------------


async def list_public(
    session: AsyncSession, *, search: str | None = None, page: int = 1, page_size: int = 20
) -> dict[str, Any]:
    page = max(1, page)
    page_size = max(1, min(100, page_size))
    offset = (page - 1) * page_size
    base = (
        select(
            RestaurantProfile.id,
            RestaurantProfile.restaurant_name,
            RestaurantProfile.address,
            RestaurantProfile.rating,
            RestaurantProfile.location,
        )
        .where(
            RestaurantProfile.is_approved == True,  # noqa: E712
            RestaurantProfile.is_active == True,  # noqa: E712
        )
    )
    count_base = (
        select(func.count(RestaurantProfile.id))
        .where(
            RestaurantProfile.is_approved == True,  # noqa: E712
            RestaurantProfile.is_active == True,  # noqa: E712
        )
    )
    if search:
        base = base.where(RestaurantProfile.restaurant_name.ilike(f"%{search}%"))
        count_base = count_base.where(RestaurantProfile.restaurant_name.ilike(f"%{search}%"))
    base = base.order_by(RestaurantProfile.rating.desc()).offset(offset).limit(page_size)
    rows = (await session.execute(base)).all()
    total = (await session.execute(count_base)).scalar_one()
    items = []
    for r in rows:
        if r.location is not None:
            lng, lat = _restaurant_point(
                RestaurantProfile(id=r.id, user_id=r.id, location=r.location)
            )
        else:
            lng, lat = 0.0, 0.0
        items.append(
            {
                "id": r.id,
                "restaurant_name": r.restaurant_name,
                "address": r.address,
                "rating": float(r.rating or 0),
                "lat": lat,
                "lng": lng,
            }
        )
    return {
        "items": [serialize_restaurant_list_row(i) for i in items],
        "count": int(total),
        "page": page,
        "page_size": page_size,
    }


async def get_by_id(
    session: AsyncSession, restaurant_id: uuid.UUID
) -> dict[str, Any]:
    profile = await _public_restaurant(session, restaurant_id)
    return serialize_restaurant(profile)


async def update_restaurant(
    session: AsyncSession,
    restaurant_id: uuid.UUID,
    owner: User,
    data: dict[str, Any],
) -> dict[str, Any]:
    profile = await _ensure_owner(session, restaurant_id, owner)
    for field in ("restaurant_name", "address", "opening_hours", "image_url", "logo_url"):
        if field in data and data[field] is not None:
            setattr(profile, field, data[field])
    await session.flush()
    await session.refresh(profile)
    return serialize_restaurant(profile)


async def nearby(
    session: AsyncSession, latitude: float, longitude: float, radius_km: float
) -> dict[str, Any]:
    radius_m = radius_km * 1000
    stmt = text(
        """
        SELECT id, restaurant_name, address, rating,
               ST_X(location::geometry) AS lng,
               ST_Y(location::geometry) AS lat,
               ST_Distance(location, ST_MakePoint(:lng, :lat)::geography) / 1000 AS distance_km
        FROM restaurant_profiles
        WHERE is_approved = true
          AND is_active = true
          AND ST_DWithin(location, ST_MakePoint(:lng, :lat)::geography, :radius_m)
        ORDER BY distance_km ASC
        LIMIT 100
        """
    )
    rows = (await session.execute(stmt, {"lng": longitude, "lat": latitude, "radius_m": radius_m})).mappings().all()
    items = [serialize_restaurant_list_row(dict(r)) for r in rows]
    return {"items": items, "count": len(items)}


# ---------------------------------------------------------------------------
# PromotionService
# ---------------------------------------------------------------------------


def _serialize_promotion(promo: Promotion, restaurant_name: str | None = None) -> dict[str, Any]:
    return {
        "id": str(promo.id),
        "restaurant_id": str(promo.restaurant_id),
        "restaurant_name": restaurant_name,
        "name": promo.name,
        "description": promo.description,
        "banner_url": promo.banner_url,
        "discount": float(promo.discount),
        "start_date": promo.start_date,
        "end_date": promo.end_date,
        "is_active": bool(promo.is_active),
        "is_currently_active": _is_currently_active(promo),
        "created_at": promo.created_at,
    }


async def create_promotion(
    session: AsyncSession,
    restaurant_id: uuid.UUID,
    owner: User,
    data: dict[str, Any],
) -> dict[str, Any]:
    await _ensure_owner(session, restaurant_id, owner)
    promo = Promotion(
        restaurant_id=restaurant_id,
        name=data["name"],
        description=data.get("description", ""),
        discount=float(data["discount"]),
        start_date=data["start_date"],
        end_date=data["end_date"],
        is_active=bool(data.get("is_active", True)),
    )
    session.add(promo)
    await session.flush()
    await session.refresh(promo)
    return _serialize_promotion(promo)


async def list_promotions(
    session: AsyncSession,
    restaurant_id: uuid.UUID,
    only_active: bool = False,
) -> list[dict[str, Any]]:
    await _public_restaurant(session, restaurant_id)
    base = select(Promotion).where(Promotion.restaurant_id == restaurant_id)
    if only_active:
        now = datetime.now(UTC)
        base = base.where(
            Promotion.is_active.is_(True),
            Promotion.start_date <= now,
            Promotion.end_date > now,
        )
    base = base.order_by(Promotion.created_at.desc())
    rows = (await session.execute(base)).scalars().all()
    return [_serialize_promotion(p) for p in rows]


async def get_promotion(
    session: AsyncSession, promotion_id: uuid.UUID
) -> dict[str, Any]:
    promo = (
        await session.execute(select(Promotion).where(Promotion.id == promotion_id))
    ).scalar_one_or_none()
    if promo is None:
        raise NotFoundError("Promotion not found")
    return _serialize_promotion(promo)


async def update_promotion(
    session: AsyncSession,
    promotion_id: uuid.UUID,
    owner: User,
    data: dict[str, Any],
) -> dict[str, Any]:
    promo = (
        await session.execute(select(Promotion).where(Promotion.id == promotion_id))
    ).scalar_one_or_none()
    if promo is None:
        raise NotFoundError("Promotion not found")
    await _ensure_owner(session, promo.restaurant_id, owner)
    for field in ("name", "description", "discount", "start_date", "end_date", "is_active"):
        if field in data and data[field] is not None:
            setattr(promo, field, data[field])
    await session.flush()
    await session.refresh(promo)
    return _serialize_promotion(promo)


async def delete_promotion(
    session: AsyncSession, promotion_id: uuid.UUID, owner: User
) -> None:
    promo = (
        await session.execute(select(Promotion).where(Promotion.id == promotion_id))
    ).scalar_one_or_none()
    if promo is None:
        raise NotFoundError("Promotion not found")
    await _ensure_owner(session, promo.restaurant_id, owner)
    await session.delete(promo)
    await session.flush()


async def toggle_promotion(
    session: AsyncSession, promotion_id: uuid.UUID, owner: User
) -> dict[str, Any]:
    promo = (
        await session.execute(select(Promotion).where(Promotion.id == promotion_id))
    ).scalar_one_or_none()
    if promo is None:
        raise NotFoundError("Promotion not found")
    await _ensure_owner(session, promo.restaurant_id, owner)
    promo.is_active = not promo.is_active
    await session.flush()
    await session.refresh(promo)
    return _serialize_promotion(promo)


async def attach_banner(
    session: AsyncSession,
    promotion_id: uuid.UUID,
    owner: User,
    content: bytes,
    content_type_hint: str | None,
    storage: Any,
) -> dict[str, Any]:
    promo = (
        await session.execute(select(Promotion).where(Promotion.id == promotion_id))
    ).scalar_one_or_none()
    if promo is None:
        raise NotFoundError("Promotion not found")
    await _ensure_owner(session, promo.restaurant_id, owner)
    dto = await image_service.upload_image_for_restaurant(
        storage, promo.restaurant_id, "promotion", content, content_type_hint
    )
    promo.banner_url = dto["url"]
    await session.flush()
    await session.refresh(promo)
    return _serialize_promotion(promo)


async def remove_banner(
    session: AsyncSession,
    promotion_id: uuid.UUID,
    owner: User,
    storage: Any,
) -> dict[str, Any]:
    promo = (
        await session.execute(select(Promotion).where(Promotion.id == promotion_id))
    ).scalar_one_or_none()
    if promo is None:
        raise NotFoundError("Promotion not found")
    await _ensure_owner(session, promo.restaurant_id, owner)
    if promo.banner_url:
        key = promo.banner_url.split("/")[-1]
        # The key has no leading slashes; try removing with full path key.
        await storage.delete(promo.banner_url.split(f"{promo.restaurant_id}/")[-1])
        promo.banner_url = None
    await session.flush()
    await session.refresh(promo)
    return _serialize_promotion(promo)


# ---------------------------------------------------------------------------
# MenuCategoryService
# ---------------------------------------------------------------------------


def _serialize_category(cat: MenuCategory, image_url: str | None = None, items_count: int = 0) -> dict[str, Any]:
    return {
        "id": str(cat.id),
        "restaurant_id": str(cat.restaurant_id),
        "name": cat.name,
        "description": cat.description,
        "position": int(cat.position),
        "is_active": bool(cat.is_active),
        "image_url": image_url,
        "items_count": int(items_count),
        "created_at": cat.created_at,
        "updated_at": cat.updated_at,
    }


async def create_category(
    session: AsyncSession,
    restaurant_id: uuid.UUID,
    owner: User,
    data: dict[str, Any],
) -> dict[str, Any]:
    await _ensure_owner(session, restaurant_id, owner)
    existing = (
        await session.execute(
            select(MenuCategory.id).where(
                MenuCategory.restaurant_id == restaurant_id,
                MenuCategory.name == data["name"],
            )
        )
    ).first()
    if existing is not None:
        raise ConflictError("A category with that name already exists")
    cat = MenuCategory(
        restaurant_id=restaurant_id,
        name=data["name"],
        description=data.get("description", ""),
        position=int(data.get("position", 0)),
        is_active=bool(data.get("is_active", True)),
    )
    session.add(cat)
    await session.flush()
    await session.refresh(cat)
    return _serialize_category(cat)


async def list_categories(
    session: AsyncSession,
    restaurant_id: uuid.UUID,
    only_active: bool = True,
) -> list[dict[str, Any]]:
    await _public_restaurant(session, restaurant_id)
    base = select(MenuCategory).where(MenuCategory.restaurant_id == restaurant_id)
    if only_active:
        base = base.where(MenuCategory.is_active.is_(True))
    base = base.order_by(MenuCategory.position, MenuCategory.name)
    rows = (await session.execute(base)).scalars().all()
    out: list[dict[str, Any]] = []
    for cat in rows:
        count = (
            await session.execute(
                select(func.count(MenuItem.id)).where(MenuItem.category_id == cat.id)
            )
        ).scalar_one()
        out.append(_serialize_category(cat, items_count=int(count or 0)))
    return out


async def get_category(
    session: AsyncSession, category_id: uuid.UUID
) -> dict[str, Any]:
    cat = (
        await session.execute(select(MenuCategory).where(MenuCategory.id == category_id))
    ).scalar_one_or_none()
    if cat is None:
        raise NotFoundError("Category not found")
    count = (
        await session.execute(
            select(func.count(MenuItem.id)).where(MenuItem.category_id == cat.id)
        )
    ).scalar_one()
    return _serialize_category(cat, items_count=int(count or 0))


async def update_category(
    session: AsyncSession,
    category_id: uuid.UUID,
    owner: User,
    data: dict[str, Any],
) -> dict[str, Any]:
    cat = (
        await session.execute(select(MenuCategory).where(MenuCategory.id == category_id))
    ).scalar_one_or_none()
    if cat is None:
        raise NotFoundError("Category not found")
    await _ensure_owner(session, cat.restaurant_id, owner)
    for field in ("name", "description", "position", "is_active"):
        if field in data and data[field] is not None:
            setattr(cat, field, data[field])
    await session.flush()
    await session.refresh(cat)
    return _serialize_category(cat)


async def delete_category(
    session: AsyncSession,
    category_id: uuid.UUID,
    owner: User,
) -> None:
    cat = (
        await session.execute(select(MenuCategory).where(MenuCategory.id == category_id))
    ).scalar_one_or_none()
    if cat is None:
        raise NotFoundError("Category not found")
    await _ensure_owner(session, cat.restaurant_id, owner)
    items = (
        await session.execute(
            select(func.count(MenuItem.id)).where(MenuItem.category_id == cat.id)
        )
    ).scalar_one()
    if items and int(items) > 0:
        raise ValidationError("Cannot delete a category that has items")
    await session.delete(cat)
    await session.flush()


async def attach_category_image(
    session: AsyncSession,
    category_id: uuid.UUID,
    owner: User,
    content: bytes,
    content_type_hint: str | None,
    storage: Any,
) -> dict[str, Any]:
    cat = (
        await session.execute(select(MenuCategory).where(MenuCategory.id == category_id))
    ).scalar_one_or_none()
    if cat is None:
        raise NotFoundError("Category not found")
    await _ensure_owner(session, cat.restaurant_id, owner)
    dto = await image_service.upload_image_for_restaurant(
        storage, cat.restaurant_id, "menu_category", content, content_type_hint
    )
    img = MenuCategoryImage(
        category_id=cat.id, image_url=dto["url"], alt_text=""
    )
    session.add(img)
    await session.flush()
    await session.refresh(img)
    return {
        "id": str(img.id),
        "image_url": img.image_url,
        "alt_text": img.alt_text,
        "created_at": img.created_at,
    }


async def remove_category_image(
    session: AsyncSession,
    image_id: uuid.UUID,
    owner: User,
    storage: Any,
) -> None:
    img = (
        await session.execute(
            select(MenuCategoryImage).where(MenuCategoryImage.id == image_id)
        )
    ).scalar_one_or_none()
    if img is None:
        return
    cat = (
        await session.execute(
            select(MenuCategory).where(MenuCategory.id == img.category_id)
        )
    ).scalar_one_or_none()
    if cat is None:
        return
    await _ensure_owner(session, cat.restaurant_id, owner)
    await storage.delete(img.image_url.split(f"{cat.restaurant_id}/")[-1])
    await session.delete(img)
    await session.flush()


# ---------------------------------------------------------------------------
# MenuItemService
# ---------------------------------------------------------------------------


def _serialize_item(
    item: MenuItem,
    *,
    restaurant_name: str | None = None,
    category_name: str | None = None,
    images: Sequence[MenuItemImage] | None = None,
    promotions: Sequence[Promotion] | None = None,
) -> dict[str, Any]:
    price, applied = compute_effective_price(item, promotions)
    promo_dicts = [_serialize_promotion(p) for p in (promotions or [])]
    image_dicts = [
        {
            "id": str(img.id),
            "image_url": img.image_url,
            "alt_text": img.alt_text,
            "position": int(img.position),
        }
        for img in (images or [])
    ]
    return {
        "id": str(item.id),
        "restaurant_id": str(item.restaurant_id),
        "restaurant_name": restaurant_name,
        "category_id": str(item.category_id),
        "category_name": category_name,
        "title": item.title,
        "description": item.description,
        "price": Decimal(item.price),
        "discounted_price": price if applied else Decimal(item.price),
        "applied_promotion": _serialize_promotion(applied) if applied else None,
        "is_available": bool(item.is_available),
        "is_featured": bool(item.is_featured),
        "prep_time_minutes": item.prep_time_minutes,
        "allergens": item.allergens,
        "promotions": promo_dicts,
        "images": image_dicts,
        "created_at": item.created_at,
        "updated_at": item.updated_at,
    }


async def _load_item_context(
    session: AsyncSession, item: MenuItem
) -> tuple[str | None, str | None, list[MenuItemImage], list[Promotion]]:
    profile = (
        await session.execute(
            select(RestaurantProfile).where(RestaurantProfile.id == item.restaurant_id)
        )
    ).scalar_one_or_none()
    cat = (
        await session.execute(
            select(MenuCategory).where(MenuCategory.id == item.category_id)
        )
    ).scalar_one_or_none()
    images = (
        await session.execute(
            select(MenuItemImage)
            .where(MenuItemImage.menu_item_id == item.id)
            .order_by(MenuItemImage.position, MenuItemImage.created_at)
        )
    ).scalars().all()
    promotions = list(
        (
            await session.execute(
                select(Promotion).where(Promotion.restaurant_id == item.restaurant_id)
            )
        ).scalars().all()
    )
    return (
        profile.restaurant_name if profile else None,
        cat.name if cat else None,
        list(images),
        promotions,
    )


async def create_item(
    session: AsyncSession,
    restaurant_id: uuid.UUID,
    owner: User,
    data: dict[str, Any],
) -> dict[str, Any]:
    await _ensure_owner(session, restaurant_id, owner)
    if data.get("category_id"):
        cat = (
            await session.execute(
                select(MenuCategory).where(MenuCategory.id == data["category_id"])
            )
        ).scalar_one_or_none()
        if cat is None or cat.restaurant_id != restaurant_id:
            raise ValidationError("Category does not belong to this restaurant")
    item = MenuItem(
        restaurant_id=restaurant_id,
        category_id=data["category_id"],
        title=data["title"],
        description=data.get("description", ""),
        price=Decimal(str(data["price"])),
        is_available=bool(data.get("is_available", True)),
        is_featured=bool(data.get("is_featured", False)),
        prep_time_minutes=data.get("prep_time_minutes"),
        allergens=data.get("allergens", ""),
    )
    session.add(item)
    await session.flush()
    for pid in data.get("promotion_ids") or []:
        promo = (
            await session.execute(
                select(Promotion).where(
                    Promotion.id == pid, Promotion.restaurant_id == restaurant_id
                )
            )
        ).scalar_one_or_none()
        if promo is None:
            raise ValidationError(f"Promotion {pid} not found for this restaurant")
        await session.execute(
            text(
                "INSERT INTO menu_item_promotions (item_id, promotion_id) "
                "VALUES (:iid, :pid)"
            ),
            {"iid": str(item.id), "pid": str(pid)},
        )
    await session.flush()
    await session.refresh(item)
    rname, cname, images, promotions = await _load_item_context(session, item)
    return _serialize_item(
        item,
        restaurant_name=rname,
        category_name=cname,
        images=images,
        promotions=promotions,
    )


async def get_item(
    session: AsyncSession, item_id: uuid.UUID
) -> dict[str, Any]:
    item = (
        await session.execute(select(MenuItem).where(MenuItem.id == item_id))
    ).scalar_one_or_none()
    if item is None:
        raise NotFoundError("Item not found")
    rname, cname, images, promotions = await _load_item_context(session, item)
    return _serialize_item(
        item,
        restaurant_name=rname,
        category_name=cname,
        images=images,
        promotions=promotions,
    )


async def list_items_for_restaurant(
    session: AsyncSession,
    restaurant_id: uuid.UUID,
    *,
    category_id: uuid.UUID | None = None,
    is_available: bool | None = None,
    is_featured: bool | None = None,
    search: str | None = None,
    ordering: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> dict[str, Any]:
    await _public_restaurant(session, restaurant_id)
    page = max(1, page)
    page_size = max(1, min(100, page_size))
    offset = (page - 1) * page_size
    base = select(MenuItem).where(MenuItem.restaurant_id == restaurant_id)
    if category_id:
        base = base.where(MenuItem.category_id == category_id)
    if is_available is not None:
        base = base.where(MenuItem.is_available.is_(is_available))
    if is_featured is not None:
        base = base.where(MenuItem.is_featured.is_(is_featured))
    if search:
        base = base.where(MenuItem.title.ilike(f"%{search}%"))
    if ordering == "price_asc":
        base = base.order_by(MenuItem.price.asc())
    elif ordering == "price_desc":
        base = base.order_by(MenuItem.price.desc())
    else:
        base = base.order_by(MenuItem.created_at.desc())
    base = base.offset(offset).limit(page_size)
    rows = (await session.execute(base)).scalars().all()
    count_q = select(func.count(MenuItem.id)).where(MenuItem.restaurant_id == restaurant_id)
    total = (await session.execute(count_q)).scalar_one()
    out: list[dict[str, Any]] = []
    for item in rows:
        rname, cname, images, promotions = await _load_item_context(session, item)
        out.append(
            _serialize_item(
                item,
                restaurant_name=rname,
                category_name=cname,
                images=images,
                promotions=promotions,
            )
        )
    return {"items": out, "count": int(total), "page": page, "page_size": page_size}


async def list_items_global(
    session: AsyncSession,
    *,
    restaurant_id: uuid.UUID | None = None,
    category_id: uuid.UUID | None = None,
    is_available: bool | None = None,
    is_featured: bool | None = None,
    search: str | None = None,
    ordering: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> dict[str, Any]:
    page = max(1, page)
    page_size = max(1, min(100, page_size))
    offset = (page - 1) * page_size
    base = (
        select(MenuItem, RestaurantProfile.is_approved, RestaurantProfile.is_active)
        .join(RestaurantProfile, RestaurantProfile.id == MenuItem.restaurant_id)
        .where(
            RestaurantProfile.is_approved.is_(True),
            RestaurantProfile.is_active.is_(True),
        )
    )
    if restaurant_id:
        base = base.where(MenuItem.restaurant_id == restaurant_id)
    if category_id:
        base = base.where(MenuItem.category_id == category_id)
    if is_available is not None:
        base = base.where(MenuItem.is_available.is_(is_available))
    if is_featured is not None:
        base = base.where(MenuItem.is_featured.is_(is_featured))
    if search:
        base = base.where(MenuItem.title.ilike(f"%{search}%"))
    if ordering == "price_asc":
        base = base.order_by(MenuItem.price.asc())
    elif ordering == "price_desc":
        base = base.order_by(MenuItem.price.desc())
    else:
        base = base.order_by(MenuItem.created_at.desc())
    base = base.offset(offset).limit(page_size)
    rows = (await session.execute(base)).all()
    out: list[dict[str, Any]] = []
    for item, _approved, _active in rows:
        rname, cname, images, promotions = await _load_item_context(session, item)
        out.append(
            _serialize_item(
                item,
                restaurant_name=rname,
                category_name=cname,
                images=images,
                promotions=promotions,
            )
        )
    total = (
        await session.execute(
            select(func.count(MenuItem.id))
            .join(RestaurantProfile, RestaurantProfile.id == MenuItem.restaurant_id)
            .where(
                RestaurantProfile.is_approved.is_(True),
                RestaurantProfile.is_active.is_(True),
            )
        )
    ).scalar_one()
    return {"items": out, "count": int(total), "page": page, "page_size": page_size}


async def update_item(
    session: AsyncSession,
    item_id: uuid.UUID,
    owner: User,
    data: dict[str, Any],
) -> dict[str, Any]:
    item = (
        await session.execute(select(MenuItem).where(MenuItem.id == item_id))
    ).scalar_one_or_none()
    if item is None:
        raise NotFoundError("Item not found")
    await _ensure_owner(session, item.restaurant_id, owner)
    for field in (
        "title",
        "description",
        "price",
        "is_available",
        "is_featured",
        "prep_time_minutes",
        "allergens",
        "category_id",
    ):
        if field in data and data[field] is not None:
            if field == "category_id":
                cat = (
                    await session.execute(
                        select(MenuCategory).where(MenuCategory.id == data["category_id"])
                    )
                ).scalar_one_or_none()
                if cat is None or cat.restaurant_id != item.restaurant_id:
                    raise ValidationError("Category does not belong to this restaurant")
            if field == "price":
                setattr(item, field, Decimal(str(data[field])))
            else:
                setattr(item, field, data[field])
    if "promotion_ids" in data and data["promotion_ids"] is not None:
        await session.execute(
            text("DELETE FROM menu_item_promotions WHERE item_id = :iid"),
            {"iid": str(item.id)},
        )
        for pid in data["promotion_ids"]:
            promo = (
                await session.execute(
                    select(Promotion).where(
                        Promotion.id == pid,
                        Promotion.restaurant_id == item.restaurant_id,
                    )
                )
            ).scalar_one_or_none()
            if promo is None:
                raise ValidationError(
                    f"Promotion {pid} not found for this restaurant"
                )
            await session.execute(
                text(
                    "INSERT INTO menu_item_promotions (item_id, promotion_id) "
                    "VALUES (:iid, :pid)"
                ),
                {"iid": str(item.id), "pid": str(pid)},
            )
    await session.flush()
    await session.refresh(item)
    rname, cname, images, promotions = await _load_item_context(session, item)
    return _serialize_item(
        item,
        restaurant_name=rname,
        category_name=cname,
        images=images,
        promotions=promotions,
    )


async def delete_item(
    session: AsyncSession,
    item_id: uuid.UUID,
    owner: User,
) -> None:
    item = (
        await session.execute(select(MenuItem).where(MenuItem.id == item_id))
    ).scalar_one_or_none()
    if item is None:
        raise NotFoundError("Item not found")
    await _ensure_owner(session, item.restaurant_id, owner)
    # Cross-domain stub: real check lives in Phase 3 (orders).
    # We refuse deletion if any order items reference this menu item; but
    # the orders table doesn't exist yet, so this is a no-op for now.
    await session.delete(item)
    await session.flush()


async def add_promotion(
    session: AsyncSession,
    item_id: uuid.UUID,
    owner: User,
    promotion_id: uuid.UUID,
) -> dict[str, Any]:
    item = (
        await session.execute(select(MenuItem).where(MenuItem.id == item_id))
    ).scalar_one_or_none()
    if item is None:
        raise NotFoundError("Item not found")
    await _ensure_owner(session, item.restaurant_id, owner)
    promo = (
        await session.execute(select(Promotion).where(Promotion.id == promotion_id))
    ).scalar_one_or_none()
    if promo is None or promo.restaurant_id != item.restaurant_id:
        raise NotFoundError("Promotion not found")
    await session.execute(
        text(
            "INSERT INTO menu_item_promotions (item_id, promotion_id) "
            "VALUES (:iid, :pid) ON CONFLICT DO NOTHING"
        ),
        {"iid": str(item.id), "pid": str(promotion_id)},
    )
    await session.flush()
    return await get_item(session, item_id)


async def remove_promotion(
    session: AsyncSession,
    item_id: uuid.UUID,
    owner: User,
    promotion_id: uuid.UUID,
) -> dict[str, Any]:
    item = (
        await session.execute(select(MenuItem).where(MenuItem.id == item_id))
    ).scalar_one_or_none()
    if item is None:
        raise NotFoundError("Item not found")
    await _ensure_owner(session, item.restaurant_id, owner)
    await session.execute(
        text(
            "DELETE FROM menu_item_promotions "
            "WHERE item_id = :iid AND promotion_id = :pid"
        ),
        {"iid": str(item.id), "pid": str(promotion_id)},
    )
    await session.flush()
    return await get_item(session, item_id)


async def attach_item_image(
    session: AsyncSession,
    item_id: uuid.UUID,
    owner: User,
    content: bytes,
    content_type_hint: str | None,
    storage: Any,
) -> dict[str, Any]:
    item = (
        await session.execute(select(MenuItem).where(MenuItem.id == item_id))
    ).scalar_one_or_none()
    if item is None:
        raise NotFoundError("Item not found")
    await _ensure_owner(session, item.restaurant_id, owner)
    dto = await image_service.upload_image_for_restaurant(
        storage, item.restaurant_id, "menu_item", content, content_type_hint
    )
    pos = (
        await session.execute(
            select(func.count(MenuItemImage.id)).where(MenuItemImage.menu_item_id == item.id)
        )
    ).scalar_one()
    img = MenuItemImage(
        menu_item_id=item.id,
        image_url=dto["url"],
        alt_text="",
        position=int(pos or 0),
    )
    session.add(img)
    await session.flush()
    await session.refresh(img)
    return {
        "id": str(img.id),
        "image_url": img.image_url,
        "alt_text": img.alt_text,
        "position": int(img.position),
    }


async def list_item_images(
    session: AsyncSession, item_id: uuid.UUID
) -> list[dict[str, Any]]:
    rows = (
        await session.execute(
            select(MenuItemImage)
            .where(MenuItemImage.menu_item_id == item_id)
            .order_by(MenuItemImage.position, MenuItemImage.created_at)
        )
    ).scalars().all()
    return [
        {
            "id": str(r.id),
            "image_url": r.image_url,
            "alt_text": r.alt_text,
            "position": int(r.position),
        }
        for r in rows
    ]


async def remove_item_image(
    session: AsyncSession,
    image_id: uuid.UUID,
    owner: User,
    storage: Any,
) -> None:
    img = (
        await session.execute(
            select(MenuItemImage).where(MenuItemImage.id == image_id)
        )
    ).scalar_one_or_none()
    if img is None:
        return
    item = (
        await session.execute(
            select(MenuItem).where(MenuItem.id == img.menu_item_id)
        )
    ).scalar_one_or_none()
    if item is None:
        return
    await _ensure_owner(session, item.restaurant_id, owner)
    await storage.delete(img.image_url.split(f"{item.restaurant_id}/")[-1])
    await session.delete(img)
    await session.flush()
