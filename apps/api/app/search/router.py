"""Phase 8 discovery endpoints: search, reviews, favorites, prefs, taxonomy."""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.admin.deps import get_current_admin
from app.auth.deps import get_current_user
from app.cache.deps import get_cache as get_cache_dep
from app.core.envelope import success_envelope
from app.users.models import CustomerProfile, User


router = APIRouter()


def _session():
    from app.auth.deps import get_db_session

    return Depends(get_db_session)


async def _customer_profile(session: AsyncSession, user: User) -> CustomerProfile:
    from app.core.exceptions import NotFoundError

    cp = (
        await session.execute(
            select(CustomerProfile).where(CustomerProfile.user_id == user.id)
        )
    ).scalar_one_or_none()
    if cp is None:
        raise NotFoundError("Customer profile not found")
    return cp


# ---------------------------------------------------------------------------
# Taxonomy (public, cached)
# ---------------------------------------------------------------------------


@router.get("/cuisines")
async def list_cuisines(
    session: AsyncSession = _session(),
    cache: Any = Depends(get_cache_dep),
) -> dict[str, Any]:
    from app.users.preferences_service import list_cuisines as svc

    return success_envelope(await svc(session, cache))


@router.get("/dietary-tags")
async def list_dietary_tags(
    session: AsyncSession = _session(),
    cache: Any = Depends(get_cache_dep),
) -> dict[str, Any]:
    from app.users.preferences_service import list_dietary_tags as svc

    return success_envelope(await svc(session, cache))


# ---------------------------------------------------------------------------
# Search (public)
# ---------------------------------------------------------------------------


@router.get("/search/restaurants")
async def search_restaurants_ep(
    q: str | None = Query(default=None),
    cuisine: list[str] | None = Query(default=None),
    dietary: list[str] | None = Query(default=None),
    min_rating: float | None = Query(default=None, ge=0, le=5),
    lat: float | None = Query(default=None),
    lng: float | None = Query(default=None),
    radius_km: float | None = Query(default=None, gt=0, le=50),
    cursor: str | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=100),
    session: AsyncSession = _session(),
) -> dict[str, Any]:
    from app.search.service import search_restaurants

    results, next_cursor = await search_restaurants(
        session,
        q=q,
        cuisine_slugs=cuisine,
        dietary_slugs=dietary,
        min_rating=min_rating,
        lat=lat,
        lng=lng,
        radius_km=radius_km,
        cursor=cursor,
        limit=limit,
    )
    return success_envelope({"results": results, "next_cursor": next_cursor})


@router.get("/search/menu-items")
async def search_menu_items_ep(
    q: str | None = Query(default=None),
    restaurant_id: uuid.UUID | None = Query(default=None),
    dietary: list[str] | None = Query(default=None),
    price_max: float | None = Query(default=None, gt=0),
    cursor: str | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=100),
    session: AsyncSession = _session(),
) -> dict[str, Any]:
    from app.search.service import search_menu_items

    results, next_cursor = await search_menu_items(
        session,
        q=q,
        restaurant_id=restaurant_id,
        dietary_slugs=dietary,
        price_max=price_max,
        cursor=cursor,
        limit=limit,
    )
    return success_envelope({"results": results, "next_cursor": next_cursor})


@router.get("/search/global")
async def search_global_ep(
    q: str = Query(min_length=1),
    limit: int = Query(default=10, ge=1, le=50),
    session: AsyncSession = _session(),
) -> dict[str, Any]:
    from app.search.service import search_global

    return success_envelope(await search_global(session, q, limit))


@router.get("/search/popular")
async def search_popular_ep(
    lat: float = Query(...),
    lng: float = Query(...),
    radius_km: float = Query(default=5.0, gt=0, le=50),
    session: AsyncSession = _session(),
    cache: Any = Depends(get_cache_dep),
) -> dict[str, Any]:
    from app.search.service import get_popular_nearby

    results = await get_popular_nearby(session, cache, lat, lng, radius_km)
    return success_envelope({"results": results})


# ---------------------------------------------------------------------------
# Restaurant reviews
# ---------------------------------------------------------------------------


@router.get("/restaurants/{restaurant_id}/reviews")
async def list_restaurant_reviews(
    restaurant_id: uuid.UUID,
    min_rating: int | None = Query(default=None, ge=1, le=5),
    limit: int = Query(default=20, ge=1, le=100),
    session: AsyncSession = _session(),
) -> dict[str, Any]:
    from app.reviews.service import list_reviews

    items, _ = await list_reviews(
        session,
        review_type="restaurant",
        entity_column="restaurant_id",
        entity_id=restaurant_id,
        min_rating=min_rating,
        limit=limit,
    )
    return success_envelope({"results": items})


@router.post("/restaurants/{restaurant_id}/reviews", status_code=201)
async def create_restaurant_review(
    restaurant_id: uuid.UUID,
    payload: dict[str, Any],
    current: User = Depends(get_current_user),
    session: AsyncSession = _session(),
) -> dict[str, Any]:
    from app.core.exceptions import ConflictError, ValidationError
    from app.reviews.service import (
        ReviewAlreadyExists,
        ReviewNotVerified,
    )
    from app.reviews import service as review_svc

    cp = await _customer_profile(session, current)
    try:
        review = await review_svc.create_restaurant_review(
            session,
            customer_id=cp.id,
            restaurant_id=restaurant_id,
            rating=int(payload["rating"]),
            comment=payload.get("comment"),
            photo_urls=payload.get("photo_urls") or [],
        )
    except ReviewNotVerified as exc:
        raise ValidationError(str(exc))
    except ReviewAlreadyExists as exc:
        raise ConflictError(str(exc))
    await session.commit()
    return success_envelope(
        {
            "id": str(review.id),
            "rating": review.rating,
            "comment": review.comment,
        }
    )


async def _own_review_common(
    session: AsyncSession, user: User, review_id: uuid.UUID, model: Any
):
    from app.core.exceptions import NotFoundError, PermissionError
    from app.reviews.service import ReviewForbidden, ReviewNotFound

    cp = await _customer_profile(session, user)
    review = await session.get(model, review_id)
    if review is None:
        raise NotFoundError("Review not found")
    if review.customer_id != cp.id:
        raise PermissionError("Only the author can modify this review")
    return review, cp


@router.patch("/restaurants/{restaurant_id}/reviews/{review_id}")
async def update_restaurant_review(
    restaurant_id: uuid.UUID,
    review_id: uuid.UUID,
    payload: dict[str, Any],
    current: User = Depends(get_current_user),
    session: AsyncSession = _session(),
) -> dict[str, Any]:
    from app.reviews.models import RestaurantReview
    from app.reviews.service import ReviewNotFound

    review, _cp = await _own_review_common(session, current, review_id, RestaurantReview)
    if payload.get("rating") is not None:
        review.rating = int(payload["rating"])
    if payload.get("comment") is not None:
        review.comment = payload["comment"]
    if payload.get("photo_urls") is not None:
        review.photo_urls = payload["photo_urls"]
    await session.commit()
    return success_envelope({"id": str(review.id), "rating": review.rating})


@router.delete("/restaurants/{restaurant_id}/reviews/{review_id}")
async def delete_restaurant_review(
    restaurant_id: uuid.UUID,
    review_id: uuid.UUID,
    current: User = Depends(get_current_user),
    session: AsyncSession = _session(),
) -> dict[str, Any]:
    from app.reviews.models import RestaurantReview

    review, _cp = await _own_review_common(session, current, review_id, RestaurantReview)
    await session.delete(review)
    await session.commit()
    return success_envelope({"deleted": True})


@router.post("/restaurants/{restaurant_id}/reviews/{review_id}/response")
async def respond_to_review(
    restaurant_id: uuid.UUID,
    review_id: uuid.UUID,
    payload: dict[str, Any],
    current: User = Depends(get_current_user),
    session: AsyncSession = _session(),
) -> dict[str, Any]:
    from sqlalchemy import select as _select

    from app.core.exceptions import ForbiddenError
    from app.reviews.service import ReviewNotFound, add_restaurant_response
    from app.users.models import RestaurantStaffProfile

    staff = (
        await session.execute(
            _select(RestaurantStaffProfile).where(
                RestaurantStaffProfile.user_id == current.id,
                RestaurantStaffProfile.restaurant_id == restaurant_id,
                RestaurantStaffProfile.is_active == True,  # noqa: E712
            )
        )
    ).scalar_one_or_none()
    if staff is None:
        # Also allow the restaurant owner.
        from app.users.models import RestaurantProfile

        owner = (
            await session.execute(
                _select(RestaurantProfile).where(
                    RestaurantProfile.id == restaurant_id,
                    RestaurantProfile.user_id == current.id,
                )
            )
        ).scalar_one_or_none()
        if owner is None:
            raise PermissionError("Restaurant staff role required")

    try:
        review = await add_restaurant_response(
            session,
            review_id=review_id,
            responder_user_id=current.id,
            response=payload["response"],
        )
    except ReviewNotFound:
        from app.core.exceptions import NotFoundError

        raise NotFoundError("Review not found")
    if str(review.restaurant_id) != str(restaurant_id):
        raise PermissionError("Review does not belong to this restaurant")
    await session.commit()
    return success_envelope({"response": review.response})


@router.post("/restaurants/{restaurant_id}/reviews/{review_id}/helpful")
async def vote_restaurant_review_helpful(
    restaurant_id: uuid.UUID,
    review_id: uuid.UUID,
    current: User = Depends(get_current_user),
    session: AsyncSession = _session(),
) -> dict[str, Any]:
    from app.reviews.service import add_helpful_vote

    added = await add_helpful_vote(
        session, user_id=current.id, review_id=review_id, review_type="restaurant"
    )
    await session.commit()
    return success_envelope({"voted": added})


# ---------------------------------------------------------------------------
# Menu item reviews
# ---------------------------------------------------------------------------


@router.get("/menu-items/{item_id}/reviews")
async def list_menu_item_reviews(
    item_id: uuid.UUID,
    min_rating: int | None = Query(default=None, ge=1, le=5),
    limit: int = Query(default=20, ge=1, le=100),
    session: AsyncSession = _session(),
) -> dict[str, Any]:
    from app.reviews.service import list_reviews

    items, _ = await list_reviews(
        session,
        review_type="menu_item",
        entity_column="menu_item_id",
        entity_id=item_id,
        min_rating=min_rating,
        limit=limit,
    )
    return success_envelope({"results": items})


@router.post("/menu-items/{item_id}/reviews", status_code=201)
async def create_menu_item_review(
    item_id: uuid.UUID,
    payload: dict[str, Any],
    current: User = Depends(get_current_user),
    session: AsyncSession = _session(),
) -> dict[str, Any]:
    from app.core.exceptions import ConflictError, ValidationError
    from app.reviews.service import (
        ReviewAlreadyExists,
        ReviewNotVerified,
        create_menu_item_review,
    )

    cp = await _customer_profile(session, current)
    try:
        review = await create_menu_item_review(
            session,
            customer_id=cp.id,
            menu_item_id=item_id,
            rating=int(payload["rating"]),
            comment=payload.get("comment"),
            photo_urls=payload.get("photo_urls") or [],
        )
    except ReviewNotVerified as exc:
        raise ValidationError(str(exc))
    except ReviewAlreadyExists as exc:
        raise ConflictError(str(exc))
    await session.commit()
    return success_envelope({"id": str(review.id), "rating": review.rating})


@router.post("/menu-items/{item_id}/reviews/{review_id}/helpful")
async def vote_menu_item_review_helpful(
    item_id: uuid.UUID,
    review_id: uuid.UUID,
    current: User = Depends(get_current_user),
    session: AsyncSession = _session(),
) -> dict[str, Any]:
    from app.reviews.service import add_helpful_vote

    added = await add_helpful_vote(
        session, user_id=current.id, review_id=review_id, review_type="menu_item"
    )
    await session.commit()
    return success_envelope({"voted": added})


# ---------------------------------------------------------------------------
# Courier reviews
# ---------------------------------------------------------------------------


@router.get("/couriers/{courier_id}/reviews/summary")
async def courier_review_summary(
    courier_id: uuid.UUID,
    session: AsyncSession = _session(),
) -> dict[str, Any]:
    from app.reviews.service import get_courier_review_summary

    return success_envelope(await get_courier_review_summary(session, courier_id))


@router.post("/deliveries/{delivery_id}/review", status_code=201)
async def create_courier_review(
    delivery_id: uuid.UUID,
    payload: dict[str, Any],
    current: User = Depends(get_current_user),
    session: AsyncSession = _session(),
) -> dict[str, Any]:
    from app.core.exceptions import ConflictError, ValidationError
    from app.reviews.service import (
        ReviewAlreadyExists,
        ReviewNotVerified,
        create_courier_review,
    )

    cp = await _customer_profile(session, current)
    try:
        review = await create_courier_review(
            session,
            customer_id=cp.id,
            delivery_id=delivery_id,
            rating=int(payload["rating"]),
            comment=payload.get("comment"),
        )
    except ReviewNotVerified as exc:
        raise ValidationError(str(exc))
    except ReviewAlreadyExists as exc:
        raise ConflictError(str(exc))
    await session.commit()
    return success_envelope({"id": str(review.id), "rating": review.rating})


@router.post("/deliveries/{delivery_id}/review/{review_id}/helpful")
async def vote_courier_review_helpful(
    delivery_id: uuid.UUID,
    review_id: uuid.UUID,
    current: User = Depends(get_current_user),
    session: AsyncSession = _session(),
) -> dict[str, Any]:
    from app.reviews.service import add_helpful_vote

    added = await add_helpful_vote(
        session, user_id=current.id, review_id=review_id, review_type="courier"
    )
    await session.commit()
    return success_envelope({"voted": added})


# ---------------------------------------------------------------------------
# Customer profile + favorites + reorder
# ---------------------------------------------------------------------------


@router.get("/customers/me/preferences")
async def get_my_preferences(
    current: User = Depends(get_current_user),
    session: AsyncSession = _session(),
) -> dict[str, Any]:
    cp = await _customer_profile(session, current)
    return success_envelope(
        {
            "dietary_preferences": cp.dietary_preferences or [],
            "allergens": cp.allergens or [],
        }
    )


@router.patch("/customers/me/preferences")
async def update_my_preferences(
    payload: dict[str, Any],
    current: User = Depends(get_current_user),
    session: AsyncSession = _session(),
) -> dict[str, Any]:
    from app.users.preferences_service import (
        InvalidDietaryTag,
        update_customer_preferences,
    )

    cp = await _customer_profile(session, current)
    try:
        cp = await update_customer_preferences(
            session,
            customer=cp,
            dietary_preferences=payload.get("dietary_preferences"),
            allergens=payload.get("allergens"),
        )
    except InvalidDietaryTag as exc:
        from app.core.exceptions import ValidationError

        raise ValidationError(str(exc))
    await session.commit()
    return success_envelope(
        {
            "dietary_preferences": cp.dietary_preferences or [],
            "allergens": cp.allergens or [],
        }
    )


@router.get("/customers/me/favorites/restaurants")
async def my_favorite_restaurants(
    current: User = Depends(get_current_user),
    session: AsyncSession = _session(),
) -> dict[str, Any]:
    from geoalchemy2.shape import to_shape

    from app.restaurants.schemas import MenuItemResponse  # noqa: F401
    from app.users.preferences_service import list_favorite_restaurant_ids
    from app.users.models import RestaurantProfile

    ids = await list_favorite_restaurant_ids(session, customer_id=(await _customer_profile(session, current)).id)
    out = []
    for rid in ids:
        r = await session.get(RestaurantProfile, rid)
        if r is None:
            continue
        out.append(
            {
                "id": str(r.id),
                "restaurant_name": r.restaurant_name,
                "rating": float(r.rating or 0),
                "rating_count": int(getattr(r, "rating_count", 0) or 0),
            }
        )
    return success_envelope({"results": out})


@router.post("/customers/me/favorites/restaurants/{restaurant_id}", status_code=201)
async def add_favorite_restaurant(
    restaurant_id: uuid.UUID,
    current: User = Depends(get_current_user),
    session: AsyncSession = _session(),
) -> dict[str, Any]:
    from app.users.preferences_service import add_favorite_restaurant as svc

    cp = await _customer_profile(session, current)
    await svc(session, customer_id=cp.id, restaurant_id=restaurant_id)
    await session.commit()
    return success_envelope({"added": True})


@router.delete("/customers/me/favorites/restaurants/{restaurant_id}")
async def remove_favorite_restaurant(
    restaurant_id: uuid.UUID,
    current: User = Depends(get_current_user),
    session: AsyncSession = _session(),
) -> dict[str, Any]:
    from app.users.preferences_service import remove_favorite_restaurant as svc

    cp = await _customer_profile(session, current)
    n = await svc(session, customer_id=cp.id, restaurant_id=restaurant_id)
    await session.commit()
    return success_envelope({"removed": n > 0})


@router.get("/customers/me/favorites/menu-items")
async def my_favorite_menu_items(
    current: User = Depends(get_current_user),
    session: AsyncSession = _session(),
) -> dict[str, Any]:
    from app.restaurants.models import MenuItem
    from app.users.preferences_service import list_favorite_menu_item_ids

    cp = await _customer_profile(session, current)
    ids = await list_favorite_menu_item_ids(session, customer_id=cp.id)
    out = []
    for mid in ids:
        m = await session.get(MenuItem, mid)
        if m is None:
            continue
        out.append(
            {"id": str(m.id), "title": m.title, "price": float(m.price or 0)}
        )
    return success_envelope({"results": out})


@router.post("/customers/me/favorites/menu-items/{item_id}", status_code=201)
async def add_favorite_menu_item(
    item_id: uuid.UUID,
    current: User = Depends(get_current_user),
    session: AsyncSession = _session(),
) -> dict[str, Any]:
    from app.users.preferences_service import add_favorite_menu_item as svc

    cp = await _customer_profile(session, current)
    await svc(session, customer_id=cp.id, menu_item_id=item_id)
    await session.commit()
    return success_envelope({"added": True})


@router.delete("/customers/me/favorites/menu-items/{item_id}")
async def remove_favorite_menu_item(
    item_id: uuid.UUID,
    current: User = Depends(get_current_user),
    session: AsyncSession = _session(),
) -> dict[str, Any]:
    from app.users.preferences_service import remove_favorite_menu_item as svc

    cp = await _customer_profile(session, current)
    n = await svc(session, customer_id=cp.id, menu_item_id=item_id)
    await session.commit()
    return success_envelope({"removed": n > 0})


@router.post("/orders/{order_id}/reorder")
async def reorder(
    order_id: uuid.UUID,
    current: User = Depends(get_current_user),
    session: AsyncSession = _session(),
) -> dict[str, Any]:
    from app.core.exceptions import NotFoundError, ValidationError
    from app.orders.reorder import (
        ItemsUnavailable,
        OrderNotFound,
        ReorderNotAllowed,
        reorder_from_order,
    )

    cp = await _customer_profile(session, current)
    try:
        cart, skipped = await reorder_from_order(
            session, customer_id=cp.id, order_id=order_id
        )
    except OrderNotFound:
        raise NotFoundError("Order not found")
    except ReorderNotAllowed as exc:
        raise ValidationError(str(exc))
    except ItemsUnavailable as exc:
        raise ValidationError(str(exc))
    await session.commit()
    return success_envelope(
        {"cart_id": str(cart.id), "skipped_unavailable": skipped}
    )


# ---------------------------------------------------------------------------
# Admin moderation
# ---------------------------------------------------------------------------


@router.post("/admin/reviews/hide")
async def admin_hide_review(
    payload: dict[str, Any],
    current: User = Depends(get_current_admin),
    session: AsyncSession = _session(),
) -> dict[str, Any]:
    from app.reviews.service import hide_review

    review = await hide_review(
        session,
        review_id=uuid.UUID(payload["review_id"]),
        review_type=payload["review_type"],
        admin_user_id=current.id,
        reason=payload.get("reason", "moderation"),
    )
    return success_envelope({"id": str(review.id), "is_hidden": True})



