"""Review service — verified purchase, CRUD, helpful votes, moderation."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.deliveries.models import Delivery
from app.orders.enums import OrderStatus
from app.orders.models import Order, OrderItem
from app.reviews.models import (
    CourierReview,
    MenuItemReview,
    RestaurantReview,
    ReviewHelpfulVote,
)
from app.restaurants.models import MenuItem


class ReviewError(Exception):
    pass


class ReviewNotVerified(ReviewError):
    pass


class ReviewAlreadyExists(ReviewError):
    pass


class ReviewNotFound(ReviewError):
    pass


class ReviewForbidden(ReviewError):
    pass


# ---------------------------------------------------------------------------
# Verified-purchase checks (strict: a DELIVERED order must exist)
# ---------------------------------------------------------------------------


async def _verified_order_id(
    session: AsyncSession,
    customer_id: UUID,
    restaurant_id: UUID | None = None,
) -> UUID:
    stmt = select(Order.id).where(
        Order.customer_id == customer_id,
        Order.status == OrderStatus.DELIVERED,
    )
    if restaurant_id is not None:
        stmt = stmt.where(Order.restaurant_id == restaurant_id)
    stmt = stmt.order_by(Order.placed_at.desc()).limit(1)
    order_id = (await session.execute(stmt)).scalar_one_or_none()
    if order_id is None:
        raise ReviewNotVerified(
            "No delivered order found for this customer/restaurant pair"
        )
    return order_id  # type: ignore[return-value]


async def assert_verified_purchase_restaurant(
    session: AsyncSession, customer_id: UUID, restaurant_id: UUID
) -> UUID:
    return await _verified_order_id(session, customer_id, restaurant_id)


async def assert_verified_purchase_menu_item(
    session: AsyncSession, customer_id: UUID, menu_item_id: UUID
) -> UUID:
    # The item's restaurant must appear in one of the customer's delivered orders.
    item = await session.get(MenuItem, menu_item_id)
    if item is None:
        raise ReviewNotFound("Menu item not found")
    return await _verified_order_id(session, customer_id, item.restaurant_id)


async def assert_verified_purchase_delivery(
    session: AsyncSession, customer_id: UUID, delivery_id: UUID
) -> tuple[UUID, UUID]:
    """Returns (order_id, courier_id). Delivery must belong to the customer
    and be in a delivered state."""
    row = (
        await session.execute(
            select(Delivery, Order)
            .join(Order, Order.id == Delivery.order_id)
            .where(
                Delivery.id == delivery_id,
                Order.customer_id == customer_id,
                Order.status == OrderStatus.DELIVERED,
            )
        )
    ).first()
    if row is None:
        raise ReviewNotVerified("No delivered delivery found for this customer")
    delivery, order = row
    if delivery.courier_id is None:
        raise ReviewNotVerified("Delivery has no courier to review")
    return order.id, delivery.courier_id


# ---------------------------------------------------------------------------
# Create / update / delete
# ---------------------------------------------------------------------------


async def create_restaurant_review(
    session: AsyncSession,
    *,
    customer_id: UUID,
    restaurant_id: UUID,
    rating: int,
    comment: str | None = None,
    photo_urls: list[str] | None = None,
) -> RestaurantReview:
    order_id = await assert_verified_purchase_restaurant(
        session, customer_id, restaurant_id
    )
    dup = (
        await session.execute(
            select(RestaurantReview.id).where(
                RestaurantReview.customer_id == customer_id,
                RestaurantReview.restaurant_id == restaurant_id,
            )
        )
    ).scalar_one_or_none()
    if dup is not None:
        raise ReviewAlreadyExists("You have already reviewed this restaurant")
    review = RestaurantReview(
        customer_id=customer_id,
        restaurant_id=restaurant_id,
        order_id=order_id,
        rating=int(rating),
        comment=comment,
        photo_urls=photo_urls or [],
    )
    session.add(review)
    await session.flush()
    return review


async def create_menu_item_review(
    session: AsyncSession,
    *,
    customer_id: UUID,
    menu_item_id: UUID,
    rating: int,
    comment: str | None = None,
    photo_urls: list[str] | None = None,
) -> MenuItemReview:
    order_id = await assert_verified_purchase_menu_item(
        session, customer_id, menu_item_id
    )
    dup = (
        await session.execute(
            select(MenuItemReview.id).where(
                MenuItemReview.customer_id == customer_id,
                MenuItemReview.menu_item_id == menu_item_id,
            )
        )
    ).scalar_one_or_none()
    if dup is not None:
        raise ReviewAlreadyExists("You have already reviewed this item")
    review = MenuItemReview(
        customer_id=customer_id,
        menu_item_id=menu_item_id,
        order_id=order_id,
        rating=int(rating),
        comment=comment,
        photo_urls=photo_urls or [],
    )
    session.add(review)
    await session.flush()
    return review


async def create_courier_review(
    session: AsyncSession,
    *,
    customer_id: UUID,
    delivery_id: UUID,
    rating: int,
    comment: str | None = None,
) -> CourierReview:
    order_id, courier_id = await assert_verified_purchase_delivery(
        session, customer_id, delivery_id
    )
    dup = (
        await session.execute(
            select(CourierReview.id).where(
                CourierReview.customer_id == customer_id,
                CourierReview.delivery_id == delivery_id,
            )
        )
    ).scalar_one_or_none()
    if dup is not None:
        raise ReviewAlreadyExists("You have already reviewed this delivery")
    review = CourierReview(
        customer_id=customer_id,
        courier_id=courier_id,
        delivery_id=delivery_id,
        order_id=order_id,
        rating=int(rating),
        comment=comment,
    )
    session.add(review)
    await session.flush()
    return review


async def _get_own_review(
    session: AsyncSession,
    model: Any,
    review_id: UUID,
    customer_id: UUID,
) -> Any:
    review = await session.get(model, review_id)
    if review is None:
        raise ReviewNotFound("Review not found")
    if review.customer_id != customer_id:
        raise ReviewForbidden("Only the author can modify this review")
    return review


async def update_restaurant_review(
    session: AsyncSession, *, review_id: UUID, customer_id: UUID, **fields: Any
) -> RestaurantReview:
    review = await _get_own_review(
        session, RestaurantReview, review_id, customer_id
    )
    for key in ("rating", "comment", "photo_urls"):
        if fields.get(key) is not None:
            setattr(review, key, fields[key])
    review.updated_at = datetime.now(UTC)
    await session.flush()
    return review


async def delete_restaurant_review(
    session: AsyncSession, *, review_id: UUID, customer_id: UUID
) -> None:
    review = await _get_own_review(
        session, RestaurantReview, review_id, customer_id
    )
    await session.delete(review)
    await session.flush()


async def update_menu_item_review(
    session: AsyncSession, *, review_id: UUID, customer_id: UUID, **fields: Any
) -> MenuItemReview:
    review = await _get_own_review(session, MenuItemReview, review_id, customer_id)
    for key in ("rating", "comment", "photo_urls"):
        if fields.get(key) is not None:
            setattr(review, key, fields[key])
    review.updated_at = datetime.now(UTC)
    await session.flush()
    return review


async def delete_menu_item_review(
    session: AsyncSession, *, review_id: UUID, customer_id: UUID
) -> None:
    review = await _get_own_review(session, MenuItemReview, review_id, customer_id)
    await session.delete(review)
    await session.flush()


# ---------------------------------------------------------------------------
# Restaurant response
# ---------------------------------------------------------------------------


async def add_restaurant_response(
    session: AsyncSession,
    *,
    review_id: UUID,
    responder_user_id: UUID,
    response: str,
    staff_restaurant_ids: set[UUID] | None = None,
) -> RestaurantReview:
    review = await session.get(RestaurantReview, review_id)
    if review is None:
        raise ReviewNotFound("Review not found")
    # Authorization handled at router via staff check; double-check here when
    # the caller passes the staff's allowed restaurant ids.
    if staff_restaurant_ids is not None and review.restaurant_id not in staff_restaurant_ids:
        raise ReviewForbidden("Not staff of this restaurant")
    review.response = response
    review.response_at = datetime.now(UTC)
    review.responder_user_id = responder_user_id
    await session.flush()
    return review


# ---------------------------------------------------------------------------
# Helpful votes
# ---------------------------------------------------------------------------


async def add_helpful_vote(
    session: AsyncSession,
    *,
    user_id: UUID,
    review_id: UUID,
    review_type: str,
) -> bool:
    """Insert a vote; returns False if it already existed (no-op)."""
    from sqlalchemy.exc import IntegrityError

    exists = (
        await session.execute(
            select(ReviewHelpfulVote.id).where(
                ReviewHelpfulVote.review_id == review_id,
                ReviewHelpfulVote.user_id == user_id,
                ReviewHelpfulVote.review_type == review_type,
            )
        )
    ).scalar_one_or_none()
    if exists is not None:
        return False
    session.add(
        ReviewHelpfulVote(
            user_id=user_id, review_id=review_id, review_type=review_type
        )
    )
    try:
        await session.commit()
        return True
    except IntegrityError:
        await session.rollback()
        return False


async def hide_review(
    session: AsyncSession,
    *,
    review_id: UUID,
    review_type: str,
    admin_user_id: UUID,
    reason: str,
) -> RestaurantReview | MenuItemReview | CourierReview:
    model: Any = {
        "restaurant": RestaurantReview,
        "menu_item": MenuItemReview,
        "courier": CourierReview,
    }[review_type]
    review = await session.get(model, review_id)
    if review is None:
        raise ReviewNotFound("Review not found")
    review.is_hidden = True  # type: ignore[attr-defined]
    review.hidden_by_user_id = admin_user_id  # type: ignore[attr-defined]
    review.hidden_reason = reason[:500]  # type: ignore[attr-defined]
    await session.commit()
    return review  # type: ignore[func-returns-value]


# ---------------------------------------------------------------------------
# Listing
# ---------------------------------------------------------------------------

_VOTE_JOIN = {
    "restaurant": RestaurantReview,
    "menu_item": MenuItemReview,
    "courier": CourierReview,
}


async def list_reviews(
    session: AsyncSession,
    *,
    review_type: str,
    entity_column: str,
    entity_id: UUID,
    min_rating: int | None = None,
    limit: int = 20,
) -> tuple[list[dict[str, Any]], str | None]:
    model = _VOTE_JOIN[review_type]
    ent_col = getattr(model, entity_column)
    stmt: Any = (
        select(
            model,
            func.count(ReviewHelpfulVote.id).label("helpful_count"),
        )
        .outerjoin(
            ReviewHelpfulVote,
            and_(
                ReviewHelpfulVote.review_id == model.id,
                ReviewHelpfulVote.review_type == review_type,
            ),
        )
        .where(ent_col == entity_id, model.is_hidden == False)  # noqa: E712
        .group_by(model.id)
        .order_by(model.created_at.desc())
        .limit(limit)
    )
    if min_rating is not None:
        stmt = stmt.where(model.rating >= int(min_rating))
    rows = (await session.execute(stmt)).all()

    out: list[dict[str, Any]] = []
    for review, helpful_count in rows:
        d: dict[str, Any] = {
            "id": str(review.id),
            "customer_id": str(review.customer_id),
            "rating": review.rating,
            "comment": review.comment,
            "created_at": review.created_at.isoformat() if review.created_at else None,
            "helpful_count": int(helpful_count),
        }
        if hasattr(review, "photo_urls"):
            d["photo_urls"] = review.photo_urls or []
        if review_type == "restaurant":
            d["response"] = review.response
            d["response_at"] = (
                review.response_at.isoformat() if review.response_at else None
            )
        out.append(d)
    return out, None


async def get_courier_review_summary(
    session: AsyncSession, courier_id: UUID
) -> dict[str, Any]:
    row = (
        await session.execute(
            select(
                func.avg(CourierReview.rating),
                func.count(CourierReview.id),
            ).where(
                CourierReview.courier_id == courier_id,
                CourierReview.is_hidden == False,  # noqa: E712
            )
        )
    ).one()
    avg, count = row
    return {
        "courier_id": str(courier_id),
        "rating": round(float(avg), 2) if avg is not None else None,
        "review_count": int(count),
    }
