"""Cart + order + payment service layer.

All functions are async. No FastAPI imports here. Routes are thin.

Pricing math lives in :mod:`app.orders.pricing`. The state machine
lives in :mod:`app.orders.enums` (``can_transition``). This module wires
them together with the database.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal
from math import asin, cos, radians, sin, sqrt
from typing import Any

from geoalchemy2.shape import to_shape
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.orders.enums import (
    COURIER_CANCELLABLE_STATES,
    CUSTOMER_CANCELLABLE_STATES,
    OrderStatus,
    RESTAURANT_CANCELLABLE_STATES,
    can_transition,
)
from app.orders.exceptions import (
    CartEmpty,
    DeliveryAddressNotOwned,
    DeliveryAddressOutOfRange,
    MenuItemUnavailable,
    MinOrderAmountNotMet,
    OrderInvalidTransition,
    OrderNotCancellable,
    RestaurantClosed,
    RestaurantMismatch,
)
from app.orders.models import (
    Cart,
    CartItem,
    Order,
    OrderItem,
    OrderStatusHistory,
    Payment,
)
from app.orders.pricing import (
    compute_cart_subtotal,
    compute_cart_total,
    compute_discount_amount,
    compute_service_fee,
    price_cart_line,
)
from app.restaurants.models import MenuCategory, MenuItem, Promotion
from app.users.models import Address, CustomerProfile, RestaurantProfile


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _is_open_now(opening_hours: dict[str, Any], now: datetime | None = None) -> bool:
    """Read ``opening_hours`` (e.g. ``{"mon": "09:00-22:00", ...}``) and check
    if the restaurant is currently open. Missing/empty dict returns True
    (back-compat: don't block unknown formats in v1).
    """
    if not opening_hours:
        return True
    when = now or datetime.now(UTC)
    day = when.strftime("%a").lower()  # "mon", "tue", ...
    window = opening_hours.get(day)
    if not window or not isinstance(window, str):
        return True
    try:
        start_str, end_str = window.split("-")
        sh, sm = (int(x) for x in start_str.split(":"))
        eh, em = (int(x) for x in end_str.split(":"))
        start_min = sh * 60 + sm
        end_min = eh * 60 + em
        now_min = when.hour * 60 + when.minute
        return start_min <= now_min < end_min
    except (ValueError, AttributeError):
        return True


def _distance_meters(point_a: Any, point_b: Any) -> float | None:
    """Haversine distance between two geography points, in meters."""
    if point_a is None or point_b is None:
        return None
    try:
        a = to_shape(point_a)
        b = to_shape(point_b)
    except Exception:
        return None
    lat1, lon1, lat2, lon2 = map(radians, [a.y, a.x, b.y, b.x])
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    h = sin(dlat / 2) ** 2 + cos(lat1) * cos(lat2) * sin(dlon / 2) ** 2
    return 2 * 6371000 * asin(sqrt(h))


# ---------------------------------------------------------------------------
# Cart CRUD
# ---------------------------------------------------------------------------


async def _cart_with_items(
    session: AsyncSession, cart: Cart
) -> list[CartItem]:
    """Load a cart's items explicitly (no relationship backref)."""
    return list(
        (
            await session.execute(
                select(CartItem)
                .where(CartItem.cart_id == cart.id)
                .order_by(CartItem.created_at)
            )
        ).scalars().all()
    )


async def get_or_create_cart(
    session: AsyncSession, customer_id: uuid.UUID
) -> Cart:
    cart = (
        await session.execute(select(Cart).where(Cart.customer_id == customer_id))
    ).scalar_one_or_none()
    if cart is None:
        cart = Cart(customer_id=customer_id)
        session.add(cart)
        await session.flush()
    return cart


async def get_cart_for_customer(
    session: AsyncSession, customer_id: uuid.UUID
) -> Cart:
    cart = (
        await session.execute(select(Cart).where(Cart.customer_id == customer_id))
    ).scalar_one_or_none()
    if cart is None:
        raise NotFoundError("No active cart")
    return cart


async def add_item_to_cart(
    session: AsyncSession,
    cart: Cart,
    menu_item_id: uuid.UUID,
    quantity: int,
    special_instructions: str | None,
) -> CartItem:
    """Add or increment a cart line. Enforces single-restaurant cart."""
    item = (
        await session.execute(select(MenuItem).where(MenuItem.id == menu_item_id))
    ).scalar_one_or_none()
    if item is None or not item.is_available:
        raise MenuItemUnavailable("Menu item is unavailable")
    existing_items = await _cart_with_items(session, cart)
    if existing_items:
        first = existing_items[0]
        if first.menu_item_id == menu_item_id:
            first.quantity = first.quantity + quantity
            if special_instructions is not None:
                first.special_instructions = special_instructions
            await session.flush()
            return first
        existing = (
            await session.execute(
                select(MenuItem).where(MenuItem.id == first.menu_item_id)
            )
        ).scalar_one_or_none()
        if existing is not None and existing.restaurant_id != item.restaurant_id:
            raise RestaurantMismatch(
                "All cart items must be from the same restaurant"
            )
    line = CartItem(
        cart_id=cart.id,
        menu_item_id=menu_item_id,
        quantity=quantity,
        special_instructions=special_instructions,
    )
    session.add(line)
    await session.flush()
    return line


async def update_cart_item(
    session: AsyncSession,
    cart: Cart,
    item_id: uuid.UUID,
    *,
    quantity: int | None = None,
    special_instructions: str | None = None,
) -> CartItem:
    line = (
        await session.execute(
            select(CartItem).where(CartItem.id == item_id, CartItem.cart_id == cart.id)
        )
    ).scalar_one_or_none()
    if line is None:
        raise NotFoundError("Cart item not found")
    if quantity is not None:
        line.quantity = quantity
    if special_instructions is not None:
        line.special_instructions = special_instructions
    await session.flush()
    return line


async def remove_cart_item(
    session: AsyncSession, cart: Cart, item_id: uuid.UUID
) -> None:
    line = (
        await session.execute(
            select(CartItem).where(CartItem.id == item_id, CartItem.cart_id == cart.id)
        )
    ).scalar_one_or_none()
    if line is None:
        raise NotFoundError("Cart item not found")
    await session.delete(line)
    await session.flush()


async def clear_cart(session: AsyncSession, cart: Cart) -> None:
    items = await _cart_with_items(session, cart)
    for line in items:
        await session.delete(line)
    await session.flush()


# ---------------------------------------------------------------------------
# Cart pricing read
# ---------------------------------------------------------------------------


async def _load_cart_item_promotions(
    session: AsyncSession, menu_item_ids: list[uuid.UUID]
) -> dict[uuid.UUID, list[Promotion]]:
    if not menu_item_ids:
        return {}
    rows = (
        await session.execute(
            text(
                "SELECT item_id, promotion_id FROM menu_item_promotions "
                "WHERE item_id = ANY(:ids)"
            ),
            {"ids": [str(i) for i in menu_item_ids]},
        )
    ).all()
    promo_ids = list({r[1] for r in rows})
    if not promo_ids:
        return {i: [] for i in menu_item_ids}
    promos = (
        await session.execute(
            select(Promotion).where(
                Promotion.id.in_([uuid.UUID(str(p)) for p in promo_ids])
            )
        )
    ).scalars().all()
    by_promo: dict[uuid.UUID, Promotion] = {p.id: p for p in promos}
    out: dict[uuid.UUID, list[Promotion]] = {i: [] for i in menu_item_ids}
    for item_id_str, promo_id_str in rows:
        out[uuid.UUID(item_id_str)].append(by_promo[uuid.UUID(promo_id_str)])
    return out


async def build_cart_response(
    session: AsyncSession, cart: Cart
) -> dict[str, Any]:
    cart_items = await _cart_with_items(session, cart)
    if not cart_items:
        return {
            "id": str(cart.id),
            "customer_id": str(cart.customer_id),
            "restaurant_id": None,
            "items": [],
            "item_count": 0,
            "subtotal": Decimal("0.00"),
            "delivery_fee": Decimal("0.00"),
            "service_fee": Decimal("0.00"),
            "discount_amount": Decimal("0.00"),
            "total": Decimal("0.00"),
            "is_open_now": True,
            "min_order_amount": Decimal("0.00"),
        }
    item_ids = [line.menu_item_id for line in cart_items]
    items = (
        await session.execute(select(MenuItem).where(MenuItem.id.in_(item_ids)))
    ).scalars().all()
    by_id: dict[uuid.UUID, MenuItem] = {i.id: i for i in items}
    promos_by_item = await _load_cart_item_promotions(session, item_ids)
    now = datetime.now(UTC)
    first_item = by_id[cart_items[0].menu_item_id]
    restaurant_id = first_item.restaurant_id

    line_items: list[dict[str, Any]] = []
    line_pre_totals: list[Decimal] = []
    line_post_totals: list[Decimal] = []
    for line in cart_items:
        item = by_id.get(line.menu_item_id)
        if item is None:
            continue
        item_promos = promos_by_item.get(item.id, [])
        unit_pre, line_total, applied = price_cart_line(
            item, item_promos, line.quantity, at_time=now
        )
        effective_unit = line_total / Decimal(line.quantity) if line.quantity else unit_pre
        line_items.append(
            {
                "id": str(line.id),
                "menu_item_id": str(item.id),
                "menu_item_name": item.title,
                "menu_item_image_url": None,
                "unit_price": unit_pre,
                "effective_unit_price": effective_unit,
                "line_subtotal": line_total,
                "quantity": line.quantity,
                "special_instructions": line.special_instructions,
            }
        )
        line_pre_totals.append(unit_pre * line.quantity)
        line_post_totals.append(line_total)

    subtotal = compute_cart_subtotal(line_post_totals)
    discount = compute_discount_amount(line_pre_totals, line_post_totals)
    restaurant = (
        await session.execute(
            select(RestaurantProfile).where(RestaurantProfile.id == restaurant_id)
        )
    ).scalar_one()
    delivery_fee = Decimal(str(restaurant.delivery_fee or 0))
    service_fee = compute_service_fee(subtotal)
    total = compute_cart_total(subtotal, delivery_fee, service_fee)

    return {
        "id": str(cart.id),
        "customer_id": str(cart.customer_id),
        "restaurant_id": str(restaurant_id),
        "items": line_items,
        "item_count": sum(line.quantity for line in cart_items),
        "subtotal": subtotal,
        "delivery_fee": delivery_fee,
        "service_fee": service_fee,
        "discount_amount": discount,
        "total": total,
        "is_open_now": _is_open_now(restaurant.opening_hours or {}, now),
        "min_order_amount": Decimal(str(restaurant.min_order_amount or 0)),
    }


# ---------------------------------------------------------------------------
# Checkout
# ---------------------------------------------------------------------------


async def _resolve_customer_user_id(
    session: AsyncSession, customer_id: uuid.UUID
) -> uuid.UUID:
    cust = (
        await session.execute(
            select(CustomerProfile).where(CustomerProfile.id == customer_id)
        )
    ).scalar_one_or_none()
    if cust is None:
        raise NotFoundError("Customer profile not found")
    return cust.user_id


async def _address_belongs_to_customer(
    session: AsyncSession, address: Address, customer_id: uuid.UUID
) -> bool:
    cust_user_id = await _resolve_customer_user_id(session, customer_id)
    return address.user_id == cust_user_id


async def _restaurant_in_range(
    session: AsyncSession,
    restaurant: RestaurantProfile,
    address: Address,
    radius_m: float,
) -> bool:
    """PostGIS ST_DWithin; haversine fallback if PostGIS comparison fails.

    NOTE on parameter binding: asyncpg does not support SQLAlchemy's
    ``:param::type`` cast syntax (the ``:`` collides with asyncpg's own
    placeholder prefix and produces "syntax error at or near \":\"").
    Use ``ST_GeogFromText(CAST(:wkt AS text))`` or pass WKT through a
    function call instead. See docs/PHASE_5_HANDOFF.md for the full
    post-mortem -- this exact bug was the root cause of the Phase 3/4
    "InFailedSQLTransaction" conftest mystery.
    """
    from geoalchemy2.shape import to_shape

    try:
        rest_wkt = to_shape(restaurant.location).wkt
        addr_wkt = to_shape(address.location).wkt
        result = (
            await session.execute(
                text(
                    "SELECT ST_DWithin("
                    "ST_GeogFromText(CAST(:addr AS text)), "
                    "ST_GeogFromText(CAST(:rest AS text)), "
                    ":r)"
                ),
                {"addr": addr_wkt, "rest": rest_wkt, "r": radius_m},
            )
        ).scalar()
        return bool(result)
    except Exception:
        dist = _distance_meters(restaurant.location, address.location)
        return dist is None or dist <= radius_m


def _timestamp_field_for(to_status: OrderStatus) -> str | None:
    return {
        OrderStatus.CONFIRMED: "confirmed_at",
        OrderStatus.PREPARING: "preparing_at",
        OrderStatus.READY: "ready_at",
        OrderStatus.PICKED_UP: "picked_up_at",
        OrderStatus.DELIVERED: "delivered_at",
        OrderStatus.CANCELLED: "cancelled_at",
    }.get(to_status)


def _build_order_number(today: datetime, sequence: int) -> str:
    return f"FUDGO-{today.strftime('%Y%m%d')}-{sequence:06d}"


async def checkout_cart(
    session: AsyncSession,
    customer_id: uuid.UUID,
    delivery_address_id: uuid.UUID,
    idempotency_key: str | None = None,
) -> Order:
    if idempotency_key:
        existing = (
            await session.execute(
                select(Order).where(Order.idempotency_key == idempotency_key)
            )
        ).scalar_one_or_none()
        if existing is not None:
            return existing

    cart = await get_or_create_cart(session, customer_id)
    cart_items = await _cart_with_items(session, cart)
    if not cart_items:
        raise CartEmpty("Cart is empty")

    address = (
        await session.execute(
            select(Address).where(Address.id == delivery_address_id)
        )
    ).scalar_one_or_none()
    if address is None:
        raise NotFoundError("Delivery address not found")
    if not await _address_belongs_to_customer(session, address, customer_id):
        raise DeliveryAddressNotOwned(
            "Delivery address does not belong to the current customer"
        )

    item_ids = [line.menu_item_id for line in cart_items]
    items = (
        await session.execute(select(MenuItem).where(MenuItem.id.in_(item_ids)))
    ).scalars().all()
    by_id: dict[uuid.UUID, MenuItem] = {i.id: i for i in items}
    if len(by_id) != len(item_ids):
        raise MenuItemUnavailable("A cart item is no longer available")
    restaurant_ids = {i.restaurant_id for i in by_id.values()}
    if len(restaurant_ids) > 1:
        raise RestaurantMismatch("All cart items must be from the same restaurant")
    restaurant_id = next(iter(restaurant_ids))
    for item in by_id.values():
        if not item.is_available:
            raise MenuItemUnavailable("One or more menu items are unavailable")
        cat = (
            await session.execute(
                select(MenuCategory).where(MenuCategory.id == item.category_id)
            )
        ).scalar_one_or_none()
        if cat is None or not cat.is_active:
            raise MenuItemUnavailable("A category is no longer active")
    restaurant = (
        await session.execute(
            select(RestaurantProfile).where(RestaurantProfile.id == restaurant_id)
        )
    ).scalar_one()
    if not restaurant.is_approved or not restaurant.is_active:
        raise NotFoundError("Restaurant not found")
    if not _is_open_now(restaurant.opening_hours or {}):
        raise RestaurantClosed("Restaurant is not currently accepting orders")

    promos_by_item = await _load_cart_item_promotions(session, item_ids)
    now = datetime.now(UTC)
    line_data: list[
        tuple[CartItem, MenuItem, list[Promotion], Decimal, Decimal, Promotion | None]
    ] = []
    line_pre_totals: list[Decimal] = []
    line_post_totals: list[Decimal] = []
    for line in cart_items:
        item = by_id[line.menu_item_id]
        item_promos = promos_by_item.get(item.id, [])
        unit_pre, line_total, applied = price_cart_line(
            item, item_promos, line.quantity, at_time=now
        )
        line_data.append((line, item, item_promos, unit_pre, line_total, applied))
        line_pre_totals.append(unit_pre * line.quantity)
        line_post_totals.append(line_total)
    subtotal = compute_cart_subtotal(line_post_totals)
    if subtotal < Decimal(str(restaurant.min_order_amount or 0)):
        raise MinOrderAmountNotMet(
            f"Subtotal {subtotal} is below the restaurant's minimum order amount of {restaurant.min_order_amount}"
        )
    radius_m = float(restaurant.delivery_radius_km or 5.0) * 1000
    if not await _restaurant_in_range(session, restaurant, address, radius_m):
        raise DeliveryAddressOutOfRange(
            "Delivery address is outside restaurant's delivery radius"
        )

    # Build the order
    discount = compute_discount_amount(line_pre_totals, line_post_totals)
    delivery_fee = Decimal(str(restaurant.delivery_fee or 0))
    service_fee = compute_service_fee(subtotal)
    total = compute_cart_total(subtotal, delivery_fee, service_fee)
    today = datetime.now(UTC)
    sequence = (
        await session.execute(text("SELECT nextval('order_number_seq')"))
    ).scalar_one()
    order_number = _build_order_number(today, int(sequence))

    order = Order(
        order_number=order_number,
        customer_id=customer_id,
        restaurant_id=restaurant.id,
        delivery_address_id=address.id,
        subtotal=subtotal,
        delivery_fee=delivery_fee,
        service_fee=service_fee,
        total_discount_amount=discount,
        total=total,
        status=OrderStatus.PENDING_PAYMENT,
        idempotency_key=idempotency_key,
    )
    session.add(order)
    await session.flush()

    for line, item, _promos, unit_pre, line_total, applied in line_data:
        eff_unit = (
            line_total / Decimal(line.quantity) if line.quantity else unit_pre
        )
        oi = OrderItem(
            order_id=order.id,
            menu_item_id=item.id,
            name_snapshot=item.title,
            unit_price_snapshot=unit_pre,
            effective_unit_price_snapshot=eff_unit,
            applied_promotion_id=applied.id if applied is not None else None,
            applied_promotion_name_snapshot=applied.name if applied is not None else None,
            applied_promotion_discount_snapshot=(
                float(applied.discount) if applied is not None else None
            ),
            quantity=line.quantity,
            line_subtotal=line_total,
            special_instructions=line.special_instructions,
        )
        session.add(oi)

    session.add(
        OrderStatusHistory(
            order_id=order.id,
            from_status=None,
            to_status=OrderStatus.PENDING_PAYMENT,
            changed_by_role="customer",
        )
    )

    session.add(
        Payment(
            order_id=order.id,
            method="stub",
            status="pending",
            amount=total,
        )
    )
    # Phase 5: cart is preserved on PENDING_PAYMENT; the cart is deleted
    # only by the payment-success webhook (handle_stripe_webhook /
    # handle_mpesa_callback) when the order transitions to PLACED. If the
    # customer never pays, the cart stays put and the Celery sweep
    # eventually CANCELS the order without destroying the cart.
    return order


# ---------------------------------------------------------------------------
# Order state transitions
# ---------------------------------------------------------------------------


async def _load_order(session: AsyncSession, order_id: uuid.UUID) -> Order:
    order = (
        await session.execute(select(Order).where(Order.id == order_id))
    ).scalar_one_or_none()
    if order is None:
        raise NotFoundError("Order not found")
    return order


async def transition_order(
    session: AsyncSession,
    order: Order,
    to_status: OrderStatus,
    *,
    changed_by_user_id: uuid.UUID | None = None,
    changed_by_role: str,
    note: str | None = None,
    courier_id: uuid.UUID | None = None,
) -> Order:
    from_status = order.status
    if not can_transition(from_status, to_status):
        raise OrderInvalidTransition(
            f"Order cannot transition from {from_status} to {to_status}"
        )
    order.status = to_status
    ts_field = _timestamp_field_for(to_status)
    if ts_field is not None:
        setattr(order, ts_field, datetime.now(UTC))
    if to_status == OrderStatus.PICKED_UP and courier_id is not None:
        order.courier_id = courier_id
    session.add(
        OrderStatusHistory(
            order_id=order.id,
            from_status=from_status,
            to_status=to_status,
            changed_by_user_id=changed_by_user_id,
            changed_by_role=changed_by_role,
            note=note,
        )
    )
    await session.flush()
    return order


async def cancel_order(
    session: AsyncSession,
    order: Order,
    *,
    cancelled_by_user_id: uuid.UUID,
    role: str,
    reason: str,
) -> Order:
    if role == "customer" and order.status not in CUSTOMER_CANCELLABLE_STATES:
        raise OrderNotCancellable(
            f"Customer cannot cancel order in {order.status} state"
        )
    if role == "restaurant" and order.status not in RESTAURANT_CANCELLABLE_STATES:
        raise OrderNotCancellable(
            f"Restaurant cannot cancel order in {order.status} state"
        )
    if role == "courier" and order.status not in COURIER_CANCELLABLE_STATES:
        raise OrderNotCancellable(
            f"Courier cannot cancel order in {order.status} state"
        )
    order.cancellation_reason = reason
    order.cancelled_by = cancelled_by_user_id
    return await transition_order(
        session,
        order,
        OrderStatus.CANCELLED,
        changed_by_user_id=cancelled_by_user_id,
        changed_by_role=role,
        note=reason,
    )


# ---------------------------------------------------------------------------
# Order listing
# ---------------------------------------------------------------------------


async def list_customer_orders(
    session: AsyncSession,
    customer_id: uuid.UUID,
    *,
    status: OrderStatus | None = None,
    limit: int = 20,
    cursor_id: uuid.UUID | None = None,
) -> tuple[list[Order], int]:
    base = select(Order).where(Order.customer_id == customer_id)
    if status is not None:
        base = base.where(Order.status == status)
    if cursor_id is not None:
        base = base.where(Order.id < cursor_id)
    base = base.order_by(Order.placed_at.desc(), Order.id.desc()).limit(limit)
    rows = (await session.execute(base)).scalars().all()
    count_q = select(func.count(Order.id)).where(Order.customer_id == customer_id)
    if status is not None:
        count_q = count_q.where(Order.status == status)
    total = (await session.execute(count_q)).scalar_one()
    return list(rows), int(total)


async def list_restaurant_orders(
    session: AsyncSession,
    restaurant_id: uuid.UUID,
    *,
    status: OrderStatus | None = None,
    limit: int = 20,
    cursor_id: uuid.UUID | None = None,
) -> tuple[list[Order], int]:
    base = select(Order).where(Order.restaurant_id == restaurant_id)
    if status is not None:
        base = base.where(Order.status == status)
    if cursor_id is not None:
        base = base.where(Order.id < cursor_id)
    base = base.order_by(Order.placed_at.desc(), Order.id.desc()).limit(limit)
    rows = (await session.execute(base)).scalars().all()
    count_q = select(func.count(Order.id)).where(Order.restaurant_id == restaurant_id)
    if status is not None:
        count_q = count_q.where(Order.status == status)
    total = (await session.execute(count_q)).scalar_one()
    return list(rows), int(total)


async def list_courier_orders(
    session: AsyncSession,
    courier_id: uuid.UUID,
    *,
    status: OrderStatus | None = None,
    limit: int = 20,
    cursor_id: uuid.UUID | None = None,
) -> tuple[list[Order], int]:
    base = select(Order).where(Order.courier_id == courier_id)
    if status is not None:
        base = base.where(Order.status == status)
    if cursor_id is not None:
        base = base.where(Order.id < cursor_id)
    base = base.order_by(Order.placed_at.desc(), Order.id.desc()).limit(limit)
    rows = (await session.execute(base)).scalars().all()
    count_q = select(func.count(Order.id)).where(Order.courier_id == courier_id)
    if status is not None:
        count_q = count_q.where(Order.status == status)
    total = (await session.execute(count_q)).scalar_one()
    return list(rows), int(total)


async def list_available_for_courier(
    session: AsyncSession,
    *,
    near_lng: float | None = None,
    near_lat: float | None = None,
    radius_km: float | None = None,
    restaurant_id: uuid.UUID | None = None,
    limit: int = 50,
) -> list[Order]:
    base = select(Order).where(
        Order.status == OrderStatus.READY,
        Order.courier_id.is_(None),  # type: ignore[union-attr]
    )
    if restaurant_id is not None:
        base = base.where(Order.restaurant_id == restaurant_id)
    if near_lng is not None and near_lat is not None and radius_km:
        radius_m = float(radius_km) * 1000
        rows = (
            await session.execute(
                text(
                    "SELECT o.id FROM orders o "
                    "JOIN restaurant_profiles r ON r.id = o.restaurant_id "
                    "WHERE o.status = 'ready' AND o.courier_id IS NULL "
                    "AND ST_DWithin(r.location::geography, "
                    "  ST_MakePoint(:lng, :lat)::geography, :r) "
                    "ORDER BY o.placed_at DESC LIMIT :limit"
                ),
                {"lng": near_lng, "lat": near_lat, "r": radius_m, "limit": limit},
            )
        ).all()
        ids = [r[0] for r in rows]
        if not ids:
            return []
        full = (
            await session.execute(select(Order).where(Order.id.in_(ids)))
        ).scalars().all()
        order_map = {o.id: o for o in full}
        return [order_map[i] for i in ids if i in order_map]
    base = base.order_by(Order.placed_at.desc()).limit(limit)
    return list((await session.execute(base)).scalars().all())


async def get_payment_for_order(
    session: AsyncSession, order_id: uuid.UUID
) -> Payment | None:
    return (
        await session.execute(select(Payment).where(Payment.order_id == order_id))
    ).scalar_one_or_none()
