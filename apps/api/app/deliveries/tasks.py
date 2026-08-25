"""Auto-assign courier — port of v1's delivery/tasks.py:auto_assign_courier.

Adapted to take order_id (v1 took delivery_id but the logic was
order-based). Finds the nearest available courier via PostGIS, uses
row-level locking to prevent races, retries with backoff.
"""

from __future__ import annotations

import logging
import math
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import text

from app.core.celery_app import celery_app

logger = logging.getLogger(__name__)


def _haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    r = 6371.0088
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lng2 - lng1)
    a = (
        math.sin(dp / 2) ** 2
        + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    )
    return r * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


@celery_app.task(
    bind=True,
    max_retries=3,
    default_retry_delay=60,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_backoff_max=300,
    name="deliveries.auto_assign_courier",
)
def auto_assign_courier(self: Any, order_id: str) -> str:
    """Assign the nearest available courier to an order's delivery.

    No-ops (does not retry) when the order already has a courier or is
    not in READY state -- a manual claim won the race.
    """
    from app.deliveries.enums import DeliveryStatus
    from app.deliveries.models import Delivery
    from app.orders.enums import OrderStatus
    from app.orders.models import Order
    from app.users.models import CourierProfile
    from geoalchemy2.shape import to_shape

    maker = __import__(
        "app.db.sync_session", fromlist=["get_sync_session_maker"]
    ).get_sync_session_maker()

    with maker() as session:
        order = session.get(Order, order_id)
        if not order:
            return "Order not found"
        if order.courier_id is not None:
            return "Order already has a courier"
        if order.status != OrderStatus.READY:
            return f"Order not READY (current: {order.status})"
        if order.restaurant is None or order.delivery_address_id is None:
            return "Order missing restaurant or address"

        restaurant = session.get(
            __import__(
                "app.users.models", fromlist=["RestaurantProfile"]
            ).RestaurantProfile,
            order.restaurant_id,
        )
        if restaurant is None or restaurant.location is None:
            return "Restaurant location missing"

        couriers = (
            session.query(CourierProfile)
            .filter_by(is_available=True, is_approved=True)
            .all()
        )
        candidates = [c for c in couriers if c.current_location is not None]
        if not candidates:
            return "No available couriers"

        rest_pt = to_shape(restaurant.location)
        nearest = None
        nearest_km = float("inf")
        for c in candidates:
            pt = to_shape(c.current_location)
            d = _haversine_km(rest_pt.y, rest_pt.x, pt.y, pt.x)
            if d < nearest_km:
                nearest = c
                nearest_km = d
        if nearest is None:
            return "No courier found"

        # Row lock on the courier to prevent double assignment.
        courier = (
            session.query(CourierProfile)
            .filter_by(id=nearest.id)
            .with_for_update()
            .one()
        )
        if not courier.is_available:
            return "Courier became unavailable"

        order.courier_id = courier.id
        courier.is_available = False
        delivery = (
            session.query(Delivery).filter_by(order_id=order.id).first()
        )
        now = datetime.now(UTC)
        if delivery is not None:
            delivery.courier_id = courier.id
            delivery.status = DeliveryStatus.ASSIGNED.value
            delivery.assigned_at = now
        else:
            drop_addr = session.get(
                __import__(
                    "app.users.models", fromlist=["Address"]
                ).Address,
                order.delivery_address_id,
            )
            drop_pt = to_shape(drop_addr.location) if drop_addr else None
            session.add(
                Delivery(
                    order_id=order.id,
                    courier_id=courier.id,
                    status=DeliveryStatus.ASSIGNED.value,
                    assigned_at=now,
                    pickup_address=restaurant.address,
                    pickup_lat=rest_pt.y,
                    pickup_lng=rest_pt.x,
                    dropoff_address=drop_addr.street if drop_addr else "",
                    dropoff_lat=drop_pt.y if drop_pt else 0.0,
                    dropoff_lng=drop_pt.x if drop_pt else 0.0,
                )
            )
        session.commit()
    return f"Assigned courier {courier.id} to order {order_id}"
