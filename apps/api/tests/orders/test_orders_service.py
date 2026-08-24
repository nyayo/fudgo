"""Checkout + state-transition tests (restored in Phase 5).

These were the "deferred 16" from Phases 3/4. They never failed because
of the conftest -- the real culprits were two production bugs in
``checkout_cart`` (see tests/conftest.py docstring for the post-mortem):

1. ``_restaurant_in_range`` used asyncpg-incompatible ``:param::type``
   binding, aborting every checkout transaction.
2. ``orders.order_number`` was VARCHAR(20); the generated number is 21 chars.

With both fixed, these service-layer tests pass directly against
``db_session``. Assertions reflect the Phase 5 PENDING_PAYMENT flow.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any

import pytest
from geoalchemy2.shape import from_shape
from shapely.geometry import Point
from sqlalchemy import select, text

from app.orders import service as order_service
from app.orders.enums import OrderStatus, PaymentStatus
from app.orders.models import CartItem, Order, Payment
from app.restaurants.models import MenuCategory, MenuItem
from app.users.enums import UserType
from app.users.models import (
    Address,
    CustomerProfile,
    RestaurantProfile,
    User,
)


pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# Factories
# ---------------------------------------------------------------------------


async def _user(session: Any, *, user_type: UserType) -> User:
    u = User(
        email=f"u_{uuid.uuid4().hex[:6]}@x.com",
        username=f"u_{uuid.uuid4().hex[:6]}",
        first_name="U", last_name="X",
        user_type=user_type, is_verified=True,
    )
    session.add(u)
    await session.flush()
    return u


async def _customer(session: Any, user: User) -> CustomerProfile:
    cp = CustomerProfile(user_id=user.id)
    session.add(cp)
    await session.flush()
    return cp


async def _restaurant(
    session: Any, owner: User, *, name: str = "R", is_open: bool = True,
) -> RestaurantProfile:
    hours = {
        "mon": "00:00-23:59", "tue": "00:00-23:59", "wed": "00:00-23:59",
        "thu": "00:00-23:59", "fri": "00:00-23:59", "sat": "00:00-23:59",
        "sun": "00:00-23:59",
    } if is_open else {
        k: "00:00-00:01" for k in
        ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
    }
    r = RestaurantProfile(
        user_id=owner.id, restaurant_name=name,
        business_license=f"LIC-{uuid.uuid4().hex[:8]}",
        address="1 Main", location=from_shape(Point(36.8, -1.3), srid=4326),
        delivery_fee=Decimal("50.00"), delivery_radius_km=10.0,
        min_order_amount=Decimal("0.00"), opening_hours=hours,
        is_approved=True, is_active=True,
    )
    session.add(r)
    await session.flush()
    return r


async def _item(
    session: Any, r: RestaurantProfile, *, price: str = "1000.00",
    is_available: bool = True,
) -> MenuItem:
    cat = MenuCategory(restaurant_id=r.id, name="Mains", is_active=True)
    session.add(cat)
    await session.flush()
    item = MenuItem(
        restaurant_id=r.id, category_id=cat.id,
        title=f"Item {uuid.uuid4().hex[:4]}",
        price=Decimal(price), is_available=is_available,
    )
    session.add(item)
    await session.flush()
    return item


async def _address(
    session: Any, user: User, *, lng: float = 36.81, lat: float = -1.31,
) -> Address:
    a = Address(
        user_id=user.id, label="Home", street="1 Main St", city="Nairobi",
        phone="+14155550000",
        location=from_shape(Point(lng, lat), srid=4326),
    )
    session.add(a)
    await session.flush()
    return a


async def _cart_with_item(
    session: Any, cp: CustomerProfile, item: MenuItem, qty: int = 1,
) -> Any:
    cart = await order_service.get_or_create_cart(session, cp.id)
    await order_service.add_item_to_cart(session, cart, item.id, qty, None)
    return cart


async def _order_in_state(
    session: Any, target: OrderStatus,
) -> tuple[Order, User, User]:
    """Build an order then walk it to ``target`` through valid transitions."""
    cu = await _user(session, user_type=UserType.customer)
    cp = await _customer(session, cu)
    owner = await _user(session, user_type=UserType.restaurant)
    r = await _restaurant(session, owner)
    item = await _item(session, r)
    addr = await _address(session, cu)
    await _cart_with_item(session, cp, item)

    # Simulate payment success: PENDING_PAYMENT -> PLACED (valid transition).
    order = await order_service.checkout_cart(session, cp.id, addr.id, None)
    if target == OrderStatus.PENDING_PAYMENT:
        return order, cu, owner
    order = await order_service.transition_order(
        session, order, OrderStatus.PLACED,
        changed_by_user_id=None, changed_by_role="system",
    )

    ladder = [
        OrderStatus.CONFIRMED,
        OrderStatus.PREPARING,
        OrderStatus.READY,
        OrderStatus.PICKED_UP,
        OrderStatus.ON_THE_WAY,
        OrderStatus.DELIVERED,
    ]
    # Walk the ladder using the real state machine (validates each hop).
    current = order.status
    for st in ladder:
        if current == target:
            break
        order = await order_service.transition_order(
            session, order, st,
            changed_by_user_id=owner.id, changed_by_role="system",
        )
        current = st
    await session.flush()
    return order, cu, owner


# ---------------------------------------------------------------------------
# Checkout happy path + edge cases
# ---------------------------------------------------------------------------


async def test_checkout_creates_order_in_pending_payment(db_session: Any) -> None:
    cu = await _user(db_session, user_type=UserType.customer)
    cp = await _customer(db_session, cu)
    owner = await _user(db_session, user_type=UserType.restaurant)
    r = await _restaurant(db_session, owner)
    item = await _item(db_session, r)
    addr = await _address(db_session, cu)
    cart = await _cart_with_item(db_session, cp, item, qty=2)

    order = await order_service.checkout_cart(db_session, cp.id, addr.id, None)

    assert order.status == OrderStatus.PENDING_PAYMENT
    assert order.customer_id == cp.id
    assert order.restaurant_id == r.id
    assert order.delivery_address_id == addr.id
    assert order.subtotal == Decimal("2000.00")
    assert order.delivery_fee == Decimal("50.00")
    assert order.service_fee == Decimal("200.00")
    assert order.total == Decimal("2250.00")
    assert order.order_number.startswith("FUDGO-")
    # Cart preserved on PENDING_PAYMENT.
    fresh = await order_service.get_or_create_cart(db_session, cp.id)
    assert fresh.id == cart.id
    # Payment created in PENDING (not auto-SUCCEEDED).
    pay = (
        await db_session.execute(select(Payment).where(Payment.order_id == order.id))
    ).scalar_one()
    assert pay.status == PaymentStatus.PENDING


async def test_checkout_items_snapshot_frozen(db_session: Any) -> None:
    cu = await _user(db_session, user_type=UserType.customer)
    cp = await _customer(db_session, cu)
    owner = await _user(db_session, user_type=UserType.restaurant)
    r = await _restaurant(db_session, owner)
    item = await _item(db_session, r)
    addr = await _address(db_session, cu)
    await _cart_with_item(db_session, cp, item, qty=2)
    order = await order_service.checkout_cart(db_session, cp.id, addr.id, None)

    from app.orders.models import OrderItem
    items = (
        await db_session.execute(
            select(OrderItem).where(OrderItem.order_id == order.id)
        )
    ).scalars().all()
    assert len(items) == 1
    oi = items[0]
    assert oi.menu_item_id == item.id
    assert oi.name_snapshot == item.title
    assert oi.unit_price_snapshot == Decimal("1000.00")
    assert oi.quantity == 2
    assert oi.line_subtotal == Decimal("2000.00")


async def test_checkout_idempotency_key_returns_same_order(db_session: Any) -> None:
    cu = await _user(db_session, user_type=UserType.customer)
    cp = await _customer(db_session, cu)
    owner = await _user(db_session, user_type=UserType.restaurant)
    r = await _restaurant(db_session, owner)
    item = await _item(db_session, r)
    addr = await _address(db_session, cu)
    await _cart_with_item(db_session, cp, item)

    key = uuid.uuid4().hex
    o1 = await order_service.checkout_cart(db_session, cp.id, addr.id, key)
    o2 = await order_service.checkout_cart(db_session, cp.id, addr.id, key)
    assert o1.id == o2.id


async def test_checkout_empty_cart_raises(db_session: Any) -> None:
    from app.orders.exceptions import CartEmpty

    cu = await _user(db_session, user_type=UserType.customer)
    cp = await _customer(db_session, cu)
    addr = await _address(db_session, cu)
    with pytest.raises(CartEmpty):
        await order_service.checkout_cart(db_session, cp.id, addr.id, None)


async def test_checkout_foreign_address_raises(db_session: Any) -> None:
    from app.orders.exceptions import DeliveryAddressNotOwned

    cu = await _user(db_session, user_type=UserType.customer)
    cp = await _customer(db_session, cu)
    other = await _user(db_session, user_type=UserType.customer)
    foreign_addr = await _address(db_session, other)
    owner = await _user(db_session, user_type=UserType.restaurant)
    r = await _restaurant(db_session, owner)
    item = await _item(db_session, r)
    await _cart_with_item(db_session, cp, item)
    with pytest.raises(DeliveryAddressNotOwned):
        await order_service.checkout_cart(db_session, cp.id, foreign_addr.id, None)


async def test_checkout_closed_restaurant_raises(db_session: Any) -> None:
    from app.orders.exceptions import RestaurantClosed

    cu = await _user(db_session, user_type=UserType.customer)
    cp = await _customer(db_session, cu)
    owner = await _user(db_session, user_type=UserType.restaurant)
    r = await _restaurant(db_session, owner, is_open=False)
    item = await _item(db_session, r)
    addr = await _address(db_session, cu)
    await _cart_with_item(db_session, cp, item)
    with pytest.raises(RestaurantClosed):
        await order_service.checkout_cart(db_session, cp.id, addr.id, None)


async def test_checkout_unavailable_item_raises(db_session: Any) -> None:
    from app.orders.exceptions import MenuItemUnavailable

    cu = await _user(db_session, user_type=UserType.customer)
    cp = await _customer(db_session, cu)
    owner = await _user(db_session, user_type=UserType.restaurant)
    r = await _restaurant(db_session, owner)
    item = await _item(db_session, r, is_available=False)
    addr = await _address(db_session, cu)
    cart = await order_service.get_or_create_cart(db_session, cp.id)
    # Insert directly to bypass add_item's availability check.
    db_session.add(CartItem(cart_id=cart.id, menu_item_id=item.id, quantity=1))
    await db_session.flush()
    with pytest.raises(MenuItemUnavailable):
        await order_service.checkout_cart(db_session, cp.id, addr.id, None)


async def test_checkout_below_min_order_raises(db_session: Any) -> None:
    from sqlalchemy import update
    from app.orders.exceptions import MinOrderAmountNotMet

    cu = await _user(db_session, user_type=UserType.customer)
    cp = await _customer(db_session, cu)
    owner = await _user(db_session, user_type=UserType.restaurant)
    r = await _restaurant(db_session, owner)
    await db_session.execute(
        update(RestaurantProfile)
        .where(RestaurantProfile.id == r.id)  # type: ignore[arg-type]
        .values(min_order_amount=Decimal("9999.00"))
    )
    item = await _item(db_session, r, price="100.00")
    addr = await _address(db_session, cu)
    await _cart_with_item(db_session, cp, item)
    with pytest.raises(MinOrderAmountNotMet):
        await order_service.checkout_cart(db_session, cp.id, addr.id, None)


async def test_checkout_out_of_range_address_raises(db_session: Any) -> None:
    from app.orders.exceptions import DeliveryAddressOutOfRange

    cu = await _user(db_session, user_type=UserType.customer)
    cp = await _customer(db_session, cu)
    owner = await _user(db_session, user_type=UserType.restaurant)
    r = await _restaurant(db_session, owner)
    item = await _item(db_session, r)
    # Restaurant at (36.8, -1.3), radius 10km; address ~250km away.
    far_addr = await _address(db_session, cu, lng=39.0, lat=1.0)
    await _cart_with_item(db_session, cp, item)
    with pytest.raises(DeliveryAddressOutOfRange):
        await order_service.checkout_cart(db_session, cp.id, far_addr.id, None)


# ---------------------------------------------------------------------------
# Transitions + cancellation
# ---------------------------------------------------------------------------


async def test_confirm_transition_sets_timestamp(db_session: Any) -> None:
    order, cu, owner = await _order_in_state(db_session, OrderStatus.PLACED)
    order = await order_service.transition_order(
        db_session, order, OrderStatus.CONFIRMED,
        changed_by_user_id=owner.id, changed_by_role="restaurant",
    )
    assert order.status == OrderStatus.CONFIRMED
    assert order.confirmed_at is not None


async def test_restaurant_full_flow_to_ready(db_session: Any) -> None:
    order, cu, owner = await _order_in_state(db_session, OrderStatus.PLACED)
    for to in (OrderStatus.CONFIRMED, OrderStatus.PREPARING, OrderStatus.READY):
        order = await order_service.transition_order(
            db_session, order, to,
            changed_by_user_id=owner.id, changed_by_role="restaurant",
        )
    assert order.status == OrderStatus.READY
    assert order.ready_at is not None


async def test_invalid_transition_raises(db_session: Any) -> None:
    from app.orders.exceptions import OrderInvalidTransition

    order, cu, owner = await _order_in_state(db_session, OrderStatus.PLACED)
    with pytest.raises(OrderInvalidTransition):
        await order_service.transition_order(
            db_session, order, OrderStatus.READY,
            changed_by_user_id=owner.id, changed_by_role="restaurant",
        )


async def test_customer_cancel_before_preparing_ok(db_session: Any) -> None:
    order, cu, owner = await _order_in_state(db_session, OrderStatus.CONFIRMED)
    order = await order_service.cancel_order(
        db_session, order,
        cancelled_by_user_id=cu.id, role="customer", reason="changed mind",
    )
    assert order.status == OrderStatus.CANCELLED
    assert order.cancellation_reason == "changed mind"
    assert order.cancelled_by == cu.id


async def test_customer_cancel_after_preparing_raises(db_session: Any) -> None:
    from app.orders.exceptions import OrderNotCancellable

    order, cu, owner = await _order_in_state(db_session, OrderStatus.PREPARING)
    with pytest.raises(OrderNotCancellable):
        await order_service.cancel_order(
            db_session, order,
            cancelled_by_user_id=cu.id, role="customer", reason="x",
        )


async def test_restaurant_cancel_after_pickup_raises(db_session: Any) -> None:
    from app.orders.exceptions import OrderNotCancellable

    order, cu, owner = await _order_in_state(db_session, OrderStatus.PICKED_UP)
    with pytest.raises(OrderNotCancellable):
        await order_service.cancel_order(
            db_session, order,
            cancelled_by_user_id=owner.id, role="restaurant", reason="x",
        )


async def test_courier_cancel_after_pickup_raises(db_session: Any) -> None:
    """Couriers cannot cancel once they have the food (PICKED_UP is past
    the cancel window -- per Phase 3 brief, courier cancel is only valid
    between accept and pickup)."""
    from app.orders.exceptions import OrderNotCancellable

    order, cu, owner = await _order_in_state(db_session, OrderStatus.PICKED_UP)
    courier = await _user(db_session, user_type=UserType.courier)
    from app.users.models import CourierProfile
    db_session.add(CourierProfile(user_id=courier.id, vehicle_type="bike"))
    await db_session.flush()
    with pytest.raises(OrderNotCancellable):
        await order_service.cancel_order(
            db_session, order,
            cancelled_by_user_id=courier.id, role="courier", reason="vehicle broke",
        )
