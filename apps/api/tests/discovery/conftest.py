"""Shared factories for discovery tests."""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any

from geoalchemy2.shape import from_shape
from shapely.geometry import Point

from app.users.models import (
    CustomerProfile,
    RestaurantProfile,
    User,
)


async def make_customer(
    db_session: Any,
) -> tuple[User, CustomerProfile]:
    u = User(
        email=f"c_{uuid.uuid4().hex[:6]}@x.com",
        username=f"c_{uuid.uuid4().hex[:6]}",
        first_name="C", last_name="U",
        user_type="customer", is_verified=True,
    )
    db_session.add(u)
    await db_session.flush()
    cp = CustomerProfile(user_id=u.id)
    db_session.add(cp)
    await db_session.flush()
    return u, cp


async def make_customer_with_user(
    db_session: Any, user: User
) -> CustomerProfile:
    cp = CustomerProfile(user_id=user.id)
    db_session.add(cp)
    await db_session.flush()
    return cp


async def make_restaurant(
    db_session: Any,
    *,
    name: str = "Test Cafe",
    is_open: bool = True,
    lat: float = -1.3,
    lng: float = 36.8,
) -> RestaurantProfile:
    owner = User(
        email=f"ro_{uuid.uuid4().hex[:6]}@x.com",
        username=f"ro_{uuid.uuid4().hex[:6]}",
        first_name="R", last_name="O",
        user_type="restaurant", is_verified=True,
    )
    db_session.add(owner)
    await db_session.flush()
    hours = (
        {d: "00:00-23:59" for d in ("mon","tue","wed","thu","fri","sat","sun")}
        if is_open
        else {d: "03:00-03:01" for d in ("mon","tue","wed","thu","fri","sat","sun")}
    )
    r = RestaurantProfile(
        user_id=owner.id, restaurant_name=name,
        business_license=f"LIC-{uuid.uuid4().hex[:8]}",
        address="1 Main Rd", location=from_shape(Point(lng, lat), srid=4326),
        delivery_fee=Decimal("50"), delivery_radius_km=10.0,
        min_order_amount=Decimal("0"), opening_hours=hours,
        is_approved=True, is_active=True,
    )
    db_session.add(r)
    await db_session.flush()
    return r


async def make_menu_item(
    db_session: Any,
    r: RestaurantProfile,
    *,
    title: str = "Chai",
    price: str = "100.00",
    description: str | None = None,
    is_available: bool = True,
) -> Any:
    from app.restaurants.models import MenuCategory, MenuItem

    cat = MenuCategory(
        restaurant_id=r.id,
        name=f"Mains-{uuid.uuid4().hex[:6]}",
        is_active=True,
    )
    db_session.add(cat)
    await db_session.flush()
    item = MenuItem(
        restaurant_id=r.id, category_id=cat.id, title=title,
        description=description, price=Decimal(price),
        is_available=is_available,
    )
    db_session.add(item)
    await db_session.flush()
    return item


async def make_address(db_session: Any, user: User) -> Any:
    from app.users.models import Address

    a = Address(
        user_id=user.id, label="Home", street="1 Main St", city="Nairobi",
        phone="+14155550000",
        location=from_shape(Point(36.81, -1.31), srid=4326),
    )
    db_session.add(a)
    await db_session.flush()
    return a


async def make_delivered_order(
    db_session: Any,
    cp: CustomerProfile,
    r: RestaurantProfile,
    items: list[tuple[Any, int]],
) -> Any:
    """Create a DELIVERED order with the given (menu_item, qty) lines."""
    from datetime import UTC, datetime

    from app.orders.enums import OrderStatus, PaymentStatus
    from app.orders.models import Order, OrderItem, Payment

    subtotal = sum((Decimal(str(i.price)) * q for i, q in items), Decimal("0"))
    from app.users.models import User as _U
    from sqlalchemy import select as _sel

    owner_user = (
        await db_session.execute(_sel(User).where(User.id == cp.user_id))
    ).scalar_one()
    addr = await make_address(db_session, owner_user)
    order = Order(
        order_number=f"FUDGO-T-{uuid.uuid4().hex[:8].upper()}",
        customer_id=cp.id, restaurant_id=r.id,
        delivery_address_id=addr.id,
        subtotal=subtotal, delivery_fee=Decimal("50"),
        service_fee=Decimal("20"), total_discount_amount=Decimal("0"),
        total=subtotal + Decimal("70"),
        status=OrderStatus.DELIVERED,
        placed_at=datetime.now(UTC), delivered_at=datetime.now(UTC),
    )
    db_session.add(order)
    await db_session.flush()
    for item, qty in items:
        db_session.add(
            OrderItem(
                order_id=order.id, menu_item_id=item.id,
                name_snapshot=item.title,
                unit_price_snapshot=item.price,
                effective_unit_price_snapshot=item.price,
                quantity=qty,
                line_subtotal=Decimal(str(item.price)) * qty,
            )
        )
    db_session.add(
        Payment(order_id=order.id, method="stub",
                status=PaymentStatus.SUCCEEDED, amount=order.total)
    )
    await db_session.flush()
    return order


def hdr(user: Any) -> dict[str, str]:
    from app.auth.jwt import create_access_token

    return {"Authorization": f"Bearer {create_access_token(user.id)}"}
