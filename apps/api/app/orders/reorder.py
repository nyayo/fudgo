"""Reorder flow (Phase 8): re-create a cart from a past delivered order."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.orders.enums import OrderStatus
from app.restaurants.models import MenuItem
from app.orders.models import CartItem, Order


class ReorderError(Exception):
    pass


class OrderNotFound(ReorderError):
    pass


class ReorderNotAllowed(ReorderError):
    pass


class ItemsUnavailable(ReorderError):
    def __init__(self, unavailable: list[str]) -> None:
        self.unavailable = unavailable
        super().__init__(f"Items no longer available: {unavailable}")


async def reorder_from_order(
    session: AsyncSession, *, customer_id: UUID, order_id: UUID
) -> tuple[Any, list[str]]:
    """Build a cart from a past delivered order.

    Returns (cart, skipped_items). Skips (does not fail on) items that are
    no longer available; raises when the restaurant itself is gone.
    """
    from app.orders.service import get_or_create_cart
    from app.restaurants.models import MenuCategory, RestaurantProfile

    order = await session.get(Order, order_id)
    if order is None or order.customer_id != customer_id:
        raise OrderNotFound("Order not found")
    if order.status != OrderStatus.DELIVERED:
        raise ReorderNotAllowed("Can only reorder from a delivered order")

    restaurant = await session.get(RestaurantProfile, order.restaurant_id)
    if restaurant is None or not restaurant.is_active or not restaurant.is_approved:
        raise ReorderNotAllowed("Restaurant is no longer available")

    # Load the order's line items + current menu-item state.
    from app.orders.models import OrderItem

    lines = (
        await session.execute(
            select(OrderItem).where(OrderItem.order_id == order_id)
        )
    ).scalars().all()

    cart = await get_or_create_cart(session, customer_id)
    skipped: list[str] = []
    for line in lines:
        item = await session.get(MenuItem, line.menu_item_id)
        cat = (
            await session.get(MenuCategory, item.category_id)
            if item is not None
            else None
        )
        if (
            item is None
            or not item.is_available
            or cat is None
            or not cat.is_active
        ):
            skipped.append(line.name_snapshot)
            continue
        existing = (
            await session.execute(
                select(CartItem.id).where(
                    CartItem.cart_id == cart.id,
                    CartItem.menu_item_id == line.menu_item_id,
                )
            )
        ).scalar_one_or_none()
        if existing is not None:
            continue  # already in cart; don't double-add
        session.add(
            CartItem(
                cart_id=cart.id,
                menu_item_id=line.menu_item_id,
                quantity=line.quantity,
                special_instructions=line.special_instructions,
            )
        )
    await session.flush()
    return cart, skipped
