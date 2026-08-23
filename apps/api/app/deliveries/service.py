"""Delivery service layer (DB + business logic)."""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.deliveries.enums import (
    ALLOWED_DELIVERY_TRANSITIONS,
    DeliveryStatus,
    LocationProvider,
    can_transition_delivery,
)
from app.deliveries.exceptions import (
    DeliveryAlreadyClaimed,
    DeliveryInvalidTransition,
    DeliveryNotFound,
    DeliveryProofRequired,
)
from app.deliveries.models import CourierLocation, Delivery
from app.deliveries.eta import (
    compute_delivery_eta,
    compute_pickup_eta,
    haversine_km,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _broadcast_event(
    channel: str, event_type: str, data: dict[str, Any]
) -> None:
    """Fire-and-forget broadcast via the in-process ConnectionManager."""
    try:
        from app.deliveries.runtime import get_connection_manager
        from app.realtime.connection_manager import make_event

        manager = get_connection_manager()
        if manager is None:
            return
        event = make_event(event_type, data)
        asyncio.create_task(manager.broadcast(channel, event))
    except RuntimeError:
        # No event loop; tests that don't start the lifespan skip this.
        pass


# ---------------------------------------------------------------------------
# Delivery CRUD
# ---------------------------------------------------------------------------


async def get_delivery_for_order(
    session: AsyncSession, order_id: uuid.UUID
) -> Delivery | None:
    return (
        await session.execute(select(Delivery).where(Delivery.order_id == order_id))
    ).scalar_one_or_none()


async def get_delivery_by_id(
    session: AsyncSession, delivery_id: uuid.UUID
) -> Delivery | None:
    return (
        await session.execute(select(Delivery).where(Delivery.id == delivery_id))
    ).scalar_one_or_none()


async def create_delivery_at_checkout(
    session: AsyncSession,
    order_id: uuid.UUID,
    pickup_address: str,
    pickup_lat: float,
    pickup_lng: float,
    dropoff_address: str,
    dropoff_lat: float,
    dropoff_lng: float,
) -> Delivery:
    """Create a delivery row at the moment a checkout succeeds.

    The delivery starts with ``courier_id=None``; the courier claims it
    later via the courier accept endpoint.
    """
    delivery = Delivery(
        order_id=order_id,
        courier_id=None,
        status=DeliveryStatus.ASSIGNED.value,
        pickup_address=pickup_address,
        pickup_lat=pickup_lat,
        pickup_lng=pickup_lng,
        dropoff_address=dropoff_address,
        dropoff_lat=dropoff_lat,
        dropoff_lng=dropoff_lng,
    )
    session.add(delivery)
    await session.flush()
    return delivery


async def claim_delivery(
    session: AsyncSession,
    delivery: Delivery,
    courier_id: uuid.UUID,
) -> Delivery:
    """Courier accepts an unassigned delivery. Sets courier_id + assigned_at."""
    if delivery.courier_id is not None and delivery.courier_id != courier_id:
        raise DeliveryAlreadyClaimed("Delivery already claimed by another courier")
    if delivery.status != DeliveryStatus.ASSIGNED.value:
        raise DeliveryInvalidTransition(
            f"Cannot claim delivery in status {delivery.status}"
        )
    delivery.courier_id = courier_id
    delivery.assigned_at = datetime.now(UTC)
    await session.flush()
    # Broadcast to the order's channel
    await _broadcast_event(
        f"order:{delivery.order_id}",
        "order.courier_assigned",
        {
            "order_id": str(delivery.order_id),
            "courier_id": str(courier_id),
            "at": datetime.now(UTC).isoformat(),
        },
    )
    return delivery


# ---------------------------------------------------------------------------
# State machine
# ---------------------------------------------------------------------------


def assert_transition_delivery(
    from_status: DeliveryStatus, to_status: DeliveryStatus
) -> None:
    if not can_transition_delivery(from_status, to_status):
        raise DeliveryInvalidTransition(
            f"Cannot transition delivery from {from_status} to {to_status}"
        )


_TS_ATTRS: dict[DeliveryStatus, str] = {
    DeliveryStatus.EN_ROUTE_PICKUP: "en_route_pickup_at",
    DeliveryStatus.ARRIVED_AT_PICKUP: "arrived_at_pickup_at",
    DeliveryStatus.PICKED_UP: "picked_up_at",
    DeliveryStatus.EN_ROUTE_DELIVERY: "en_route_delivery_at",
    DeliveryStatus.DELIVERED: "delivered_at",
}


async def transition_delivery(
    session: AsyncSession,
    delivery: Delivery,
    to_status: DeliveryStatus,
    *,
    require_proof: bool = False,
    proof_image_url: str | None = None,
    proof_notes: str | None = None,
    note: str | None = None,
) -> Delivery:
    current = DeliveryStatus(delivery.status)
    assert_transition_delivery(current, to_status)
    if require_proof:
        if not proof_image_url and not proof_notes:
            raise DeliveryProofRequired(
                "Either proof_image_url or proof_notes is required to mark delivered"
            )
    delivery.status = to_status
    attr = _TS_ATTRS.get(to_status)
    if attr is not None:
        setattr(delivery, attr, datetime.now(UTC))
    if to_status == DeliveryStatus.DELIVERED:
        if proof_image_url is not None:
            delivery.proof_image_url = proof_image_url
        if proof_notes is not None:
            delivery.proof_notes = proof_notes
    await session.flush()
    # Broadcast
    await _broadcast_event(
        f"order:{delivery.order_id}",
        "order.status_changed",
        {
            "order_id": str(delivery.order_id),
            "from_status": current.value,
            "to_status": to_status.value,
            "at": datetime.now(UTC).isoformat(),
        },
    )
    if to_status == DeliveryStatus.PICKED_UP or to_status == DeliveryStatus.EN_ROUTE_DELIVERY:
        # Notify couriers watching for available orders that this one
        # is no longer up for grabs.
        await _broadcast_event(
            "courier:available",
            "courier.available_taken",
            {
                "order_id": str(delivery.order_id),
                "at": datetime.now(UTC).isoformat(),
            },
        )
    return delivery


async def cancel_delivery(
    session: AsyncSession, delivery: Delivery, reason: str | None
) -> Delivery:
    current = DeliveryStatus(delivery.status)
    if current in (DeliveryStatus.DELIVERED, DeliveryStatus.CANCELLED, DeliveryStatus.FAILED):
        raise DeliveryInvalidTransition(
            f"Cannot cancel a {current} delivery"
        )
    delivery.status = DeliveryStatus.CANCELLED.value  # type: ignore[assignment]
    delivery.cancelled_reason = reason
    await session.flush()
    await _broadcast_event(
        f"order:{delivery.order_id}",
        "order.status_changed",
        {
            "order_id": str(delivery.order_id),
            "from_status": current.value,
            "to_status": DeliveryStatus.CANCELLED.value,
            "at": datetime.now(UTC).isoformat(),
        },
    )
    return delivery


async def fail_delivery(
    session: AsyncSession, delivery: Delivery, reason: str
) -> Delivery:
    current = DeliveryStatus(delivery.status)
    if current in (DeliveryStatus.DELIVERED, DeliveryStatus.CANCELLED, DeliveryStatus.FAILED):
        raise DeliveryInvalidTransition(f"Cannot fail a {current} delivery")
    delivery.status = DeliveryStatus.FAILED.value  # type: ignore[assignment]
    delivery.failure_reason = reason
    await session.flush()
    await _broadcast_event(
        f"order:{delivery.order_id}",
        "order.status_changed",
        {
            "order_id": str(delivery.order_id),
            "from_status": current.value,
            "to_status": DeliveryStatus.FAILED.value,
            "at": datetime.now(UTC).isoformat(),
        },
    )
    return delivery


async def attach_proof(
    session: AsyncSession,
    delivery: Delivery,
    image_url: str | None,
    notes: str | None,
) -> Delivery:
    if image_url is not None:
        delivery.proof_image_url = image_url
    if notes is not None:
        delivery.proof_notes = notes
    await session.flush()
    return delivery


# ---------------------------------------------------------------------------
# Courier location
# ---------------------------------------------------------------------------


async def record_courier_location(
    session: AsyncSession,
    courier_id: uuid.UUID,
    lat: float,
    lng: float,
    *,
    heading_degrees: float | None = None,
    speed_kmh: float | None = None,
    accuracy_m: float | None = None,
    battery_level: int | None = None,
    source: LocationProvider = LocationProvider.GPS,
    wkt_point: str | None = None,
) -> CourierLocation:
    """Append a CourierLocation row.

    ``wkt_point`` must be the PostGIS ``ST_GeomFromText(:wkt, 4326)``
    string for the ``location`` geography column.
    """
    if wkt_point is None:
        from geoalchemy2 import WKTElement
        wkt_point = f"POINT({lng} {lat})"
    if isinstance(wkt_point, str):
        wkt = WKTElement(wkt_point, srid=4326)
    else:
        wkt = wkt_point
    loc = CourierLocation(
        courier_id=courier_id,
        location=wkt,
        heading_degrees=heading_degrees,
        speed_kmh=speed_kmh,
        accuracy_m=accuracy_m,
        battery_level=battery_level,
        source=source.value if hasattr(source, "value") else source,
    )
    session.add(loc)
    await session.flush()
    return loc


async def latest_courier_location(
    session: AsyncSession, courier_id: uuid.UUID
) -> CourierLocation | None:
    return (
        await session.execute(
            select(CourierLocation)
            .where(CourierLocation.courier_id == courier_id)
            .order_by(CourierLocation.recorded_at.desc())
            .limit(1)
        )
    ).scalars().first()


async def _broadcast_location_for_active_delivery(
    session: AsyncSession,
    courier_id: uuid.UUID,
    lat: float,
    lng: float,
    heading: float | None,
    speed: float | None,
    recorded_at: datetime,
) -> None:
    """Broadcast a courier location to its active order's channel + ETA."""
    delivery = (
        await session.execute(
            select(Delivery).where(
                Delivery.courier_id == courier_id,
                Delivery.status.in_(
                    [
                        DeliveryStatus.EN_ROUTE_PICKUP.value,
                        DeliveryStatus.ARRIVED_AT_PICKUP.value,
                        DeliveryStatus.PICKED_UP.value,
                        DeliveryStatus.EN_ROUTE_DELIVERY.value,
                    ]
                ),
            )
        )
    ).scalars().first()
    if delivery is None:
        return
    await _broadcast_event(
        f"order:{delivery.order_id}",
        "order.courier_location",
        {
            "order_id": str(delivery.order_id),
            "courier_id": str(courier_id),
            "lat": lat,
            "lng": lng,
            "heading": heading,
            "speed": speed,
            "recorded_at": recorded_at.isoformat(),
        },
    )
    pickup_eta = compute_pickup_eta(delivery, lat, lng)
    delivery_eta = compute_delivery_eta(delivery, lat, lng)
    await _broadcast_event(
        f"order:{delivery.order_id}",
        "order.courier_eta",
        {
            "order_id": str(delivery.order_id),
            "pickup_eta_minutes": pickup_eta,
            "delivery_eta_minutes": delivery_eta,
            "at": datetime.now(UTC).isoformat(),
        },
    )


async def heartbeat(
    session: AsyncSession,
    courier_id: uuid.UUID,
    *,
    lat: float,
    lng: float,
    heading_degrees: float | None = None,
    speed_kmh: float | None = None,
    accuracy_m: float | None = None,
    battery_level: int | None = None,
    is_available: bool = True,
    source: LocationProvider = LocationProvider.GPS,
) -> CourierLocation:
    """Record a heartbeat: location row + courier_profiles.is_available + broadcast."""
    from app.users.models import CourierProfile

    loc = await record_courier_location(
        session,
        courier_id,
        lat,
        lng,
        heading_degrees=heading_degrees,
        speed_kmh=speed_kmh,
        accuracy_m=accuracy_m,
        battery_level=battery_level,
        source=source,
    )
    # Update CourierProfile.is_available + last_heartbeat_at
    profile = (
        await session.execute(
            select(CourierProfile).where(CourierProfile.id == courier_id)
        )
    ).scalar_one_or_none()
    now = datetime.now(UTC)
    if profile is not None:
        profile.is_available = is_available
        profile.last_heartbeat_at = now
    await _broadcast_location_for_active_delivery(
        session, courier_id, lat, lng, heading_degrees, speed_kmh, now
    )
    return loc


# ---------------------------------------------------------------------------
# ETA computation (DB-touching)
# ---------------------------------------------------------------------------


async def compute_eta_for_order(
    session: AsyncSession, order_id: uuid.UUID
) -> dict[str, Any]:
    """Pickup + delivery ETA + distance from courier's latest location."""
    delivery = await get_delivery_for_order(session, order_id)
    if delivery is None or delivery.courier_id is None:
        return {
            "pickup_eta_minutes": 0,
            "delivery_eta_minutes": 0,
            "distance_to_pickup_km": 0.0,
            "distance_to_delivery_km": 0.0,
            "courier_last_seen_at": None,
        }
    last = await latest_courier_location(session, delivery.courier_id)
    if last is None:
        # Without a location we can't project; return zeros with no last_seen.
        return {
            "pickup_eta_minutes": 0,
            "delivery_eta_minutes": 0,
            "distance_to_pickup_km": 0.0,
            "distance_to_delivery_km": 0.0,
            "courier_last_seen_at": None,
        }
    # Read WKB to (lng, lat) via geoalchemy2
    from geoalchemy2.shape import to_shape

    try:
        point = to_shape(last.location)
        lng = float(point.x)
        lat = float(point.y)
    except Exception:
        lat, lng = 0.0, 0.0
    pickup_eta = compute_pickup_eta(delivery, lat, lng)
    delivery_eta = compute_delivery_eta(delivery, lat, lng)
    pickup_dist = haversine_km(lat, lng, delivery.pickup_lat, delivery.pickup_lng)
    delivery_dist = haversine_km(
        lat, lng, delivery.dropoff_lat, delivery.dropoff_lng
    )
    return {
        "pickup_eta_minutes": pickup_eta,
        "delivery_eta_minutes": delivery_eta,
        "distance_to_pickup_km": round(pickup_dist, 3),
        "distance_to_delivery_km": round(delivery_dist, 3),
        "courier_last_seen_at": last.recorded_at,
    }


# ---------------------------------------------------------------------------
# Courier listings
# ---------------------------------------------------------------------------


async def list_active_deliveries_for_courier(
    session: AsyncSession, courier_id: uuid.UUID
) -> list[Delivery]:
    return list(
        (
            await session.execute(
                select(Delivery).where(
                    Delivery.courier_id == courier_id,
                    Delivery.status.in_(
                        [
                            DeliveryStatus.EN_ROUTE_PICKUP.value,
                            DeliveryStatus.ARRIVED_AT_PICKUP.value,
                            DeliveryStatus.PICKED_UP.value,
                            DeliveryStatus.EN_ROUTE_DELIVERY.value,
                        ]
                    ),
                )
            )
        ).scalars().all()
    )
