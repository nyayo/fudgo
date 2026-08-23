"""Delivery + courier HTTP + WebSocket routes."""

from __future__ import annotations

import asyncio
import uuid
from typing import Any

from fastapi import APIRouter, Depends, Query, WebSocket, WebSocketDisconnect, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.deps import get_current_user, get_session
from app.deliveries.enums import DeliveryStatus, LocationProvider
from app.deliveries.exceptions import (
    DeliveryNotFound,
    DeliveryProofRequired,
)
from app.deliveries.models import Delivery
from app.deliveries.schemas import (
    AvailabilityRequest,
    CourierLocationResponse,
    DeliveryCancelRequest,
    DeliveryFailRequest,
    DeliveryProofRequest,
    DeliveryResponse,
    DeliveryTransitionRequest,
    ETAResponse,
    HeartbeatRequest,
)
from app.deliveries.service import (
    assert_transition_delivery,
    attach_proof,
    cancel_delivery,
    claim_delivery,
    compute_eta_for_order,
    fail_delivery,
    get_delivery_by_id,
    get_delivery_for_order,
    heartbeat,
    latest_courier_location,
    list_active_deliveries_for_courier,
    record_courier_location,
    transition_delivery,
)
from app.realtime.auth import authenticate_websocket
from app.realtime.connection_manager import make_event
from app.realtime.heartbeat import heartbeat_loop, is_pong
from app.users.enums import UserType
from app.users.models import User

router = APIRouter()


# ---------------------------------------------------------------------------
# Customer / courier / restaurant delivery reads
# ---------------------------------------------------------------------------


@router.get(
    "/orders/{order_id}/delivery",
    response_model=DeliveryResponse,
)
async def get_delivery_by_order(
    order_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
) -> Any:
    delivery = await get_delivery_for_order(session, order_id)
    if delivery is None:
        # Match Phase 1/2/3 convention: return 404, not 403.
        raise DeliveryNotFound("Delivery not found")
    # AuthZ: order's customer, restaurant staff, or assigned courier.
    # The caller of this endpoint is the customer (or staff / courier);
    # we resolve via user.user_type + a join through the order.
    from app.orders.models import Order
    from app.users.models import CourierProfile, RestaurantProfile, RestaurantStaffProfile

    order = (
        await session.execute(select(Order).where(Order.id == order_id))
    ).scalar_one_or_none()
    if order is None:
        raise DeliveryNotFound("Delivery not found")
    if user.user_type == UserType.customer:
        cid = await _async_resolve_customer_id(session, user.id)
        if cid is None or order.customer_id != cid:
            raise DeliveryNotFound("Delivery not found")
    elif user.user_type == UserType.restaurant_staff:
        staff = (
            await session.execute(
                select(RestaurantStaffProfile).where(
                    RestaurantStaffProfile.user_id == user.id
                )
            )
        ).scalar_one_or_none()
        if staff is None or order.restaurant_id != staff.restaurant_id:
            raise DeliveryNotFound("Delivery not found")
    elif user.user_type == UserType.courier:
        courier = (
            await session.execute(
                select(CourierProfile).where(CourierProfile.user_id == user.id)
            )
        ).scalar_one_or_none()
        if courier is None or delivery.courier_id != courier.id:
            raise DeliveryNotFound("Delivery not found")
    else:
        raise DeliveryNotFound("Delivery not found")
    return delivery


async def _async_resolve_customer_id(
    session: AsyncSession, user_id: uuid.UUID
) -> uuid.UUID | None:
    from app.users.models import CustomerProfile

    cp = (
        await session.execute(
            select(CustomerProfile).where(CustomerProfile.user_id == user_id)
        )
    ).scalar_one_or_none()
    return cp.id if cp is not None else None


# ---------------------------------------------------------------------------
# Customer ETA + courier location HTTP fallbacks
# ---------------------------------------------------------------------------


from sqlalchemy import select as _select  # noqa: E402  (re-export for above)


@router.get(
    "/orders/{order_id}/eta",
    response_model=ETAResponse,
)
async def get_order_eta(
    order_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
) -> Any:
    # Customer-only for v1
    if user.user_type != UserType.customer:
        raise DeliveryNotFound("ETA is only available to the order's customer")
    cid = await _async_resolve_customer_id(session, user.id)
    if cid is None:
        raise DeliveryNotFound("Customer profile not found")
    from app.orders.models import Order

    order = (
        await session.execute(_select(Order).where(Order.id == order_id))
    ).scalar_one_or_none()
    if order is None or order.customer_id != cid:
        raise DeliveryNotFound("Order not found")
    return await compute_eta_for_order(session, order_id)


@router.get(
    "/orders/{order_id}/courier-location",
    response_model=CourierLocationResponse | None,
)
async def get_order_courier_location(
    order_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
) -> Any:
    delivery = await get_delivery_for_order(session, order_id)
    if delivery is None or delivery.courier_id is None:
        return None
    last = await latest_courier_location(session, delivery.courier_id)
    if last is None:
        return None
    from geoalchemy2.shape import to_shape

    try:
        p = to_shape(last.location)
        lng, lat = float(p.x), float(p.y)
    except Exception:
        return None
    return CourierLocationResponse(
        courier_id=delivery.courier_id,
        lat=lat,
        lng=lng,
        heading_degrees=last.heading_degrees,
        speed_kmh=last.speed_kmh,
        accuracy_m=last.accuracy_m,
        battery_level=last.battery_level,
        recorded_at=last.recorded_at,
    )


# ---------------------------------------------------------------------------
# Courier self-service
# ---------------------------------------------------------------------------


@router.post("/courier/heartbeat")
async def courier_heartbeat(
    payload: HeartbeatRequest,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    if user.user_type != UserType.courier:
        raise DeliveryNotFound("Courier role required")
    from app.users.models import CourierProfile

    cp = (
        await session.execute(
            select(CourierProfile).where(CourierProfile.user_id == user.id)
        )
    ).scalar_one_or_none()
    if cp is None:
        raise DeliveryNotFound("Courier profile not found")
    await heartbeat(
        session,
        cp.id,
        lat=payload.lat,
        lng=payload.lng,
        heading_degrees=payload.heading_degrees,
        speed_kmh=payload.speed_kmh,
        accuracy_m=payload.accuracy_m,
        battery_level=payload.battery_level,
        is_available=payload.is_available,
        source=payload.source,
    )
    return {"ok": True}


@router.post("/courier/me/availability")
async def courier_availability(
    payload: AvailabilityRequest,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    if user.user_type != UserType.courier:
        raise DeliveryNotFound("Courier role required")
    from app.users.models import CourierProfile

    cp = (
        await session.execute(
            select(CourierProfile).where(CourierProfile.user_id == user.id)
        )
    ).scalar_one_or_none()
    if cp is None:
        raise DeliveryNotFound("Courier profile not found")
    cp.is_available = payload.is_available
    cp.last_heartbeat_at = datetime.now(UTC)
    return {"ok": True, "is_available": cp.is_available}


@router.get("/courier/me/location", response_model=CourierLocationResponse | None)
async def courier_me_location(
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
) -> Any:
    if user.user_type != UserType.courier:
        raise DeliveryNotFound("Courier role required")
    from app.users.models import CourierProfile

    cp = (
        await session.execute(
            select(CourierProfile).where(CourierProfile.user_id == user.id)
        )
    ).scalar_one_or_none()
    if cp is None:
        raise DeliveryNotFound("Courier profile not found")
    last = await latest_courier_location(session, cp.id)
    if last is None:
        return None
    from geoalchemy2.shape import to_shape

    try:
        p = to_shape(last.location)
        lng, lat = float(p.x), float(p.y)
    except Exception:
        return None
    return CourierLocationResponse(
        courier_id=cp.id,
        lat=lat,
        lng=lng,
        heading_degrees=last.heading_degrees,
        speed_kmh=last.speed_kmh,
        accuracy_m=last.accuracy_m,
        battery_level=last.battery_level,
        recorded_at=last.recorded_at,
    )


@router.get(
    "/courier/me/active-deliveries",
    response_model=list[DeliveryResponse],
)
async def courier_active_deliveries(
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
) -> Any:
    if user.user_type != UserType.courier:
        raise DeliveryNotFound("Courier role required")
    from app.users.models import CourierProfile

    cp = (
        await session.execute(
            select(CourierProfile).where(CourierProfile.user_id == user.id)
        )
    ).scalar_one_or_none()
    if cp is None:
        raise DeliveryNotFound("Courier profile not found")
    return await list_active_deliveries_for_courier(session, cp.id)


# ---------------------------------------------------------------------------
# Delivery lifecycle (called by the courier)
# ---------------------------------------------------------------------------


@router.post("/deliveries/{delivery_id}/en-route-pickup")
async def courier_en_route_pickup(
    delivery_id: uuid.UUID,
    payload: DeliveryTransitionRequest | None = None,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
) -> Any:
    delivery = await _authorize_courier_delivery(session, user, delivery_id)
    return await transition_delivery(
        session, delivery, DeliveryStatus.EN_ROUTE_PICKUP
    )


@router.post("/deliveries/{delivery_id}/arrived-at-pickup")
async def courier_arrived_at_pickup(
    delivery_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
) -> Any:
    delivery = await _authorize_courier_delivery(session, user, delivery_id)
    return await transition_delivery(
        session, delivery, DeliveryStatus.ARRIVED_AT_PICKUP
    )


@router.post("/deliveries/{delivery_id}/picked-up")
async def courier_picked_up(
    delivery_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
) -> Any:
    delivery = await _authorize_courier_delivery(session, user, delivery_id)
    return await transition_delivery(session, delivery, DeliveryStatus.PICKED_UP)


@router.post("/deliveries/{delivery_id}/en-route-delivery")
async def courier_en_route_delivery(
    delivery_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
) -> Any:
    delivery = await _authorize_courier_delivery(session, user, delivery_id)
    return await transition_delivery(
        session, delivery, DeliveryStatus.EN_ROUTE_DELIVERY
    )


@router.post("/deliveries/{delivery_id}/delivered")
async def courier_delivered(
    delivery_id: uuid.UUID,
    payload: DeliveryProofRequest,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
) -> Any:
    delivery = await _authorize_courier_delivery(session, user, delivery_id)
    if not payload.image_url and not payload.notes:
        raise DeliveryProofRequired(
            "Either proof_image_url or proof_notes is required to mark delivered"
        )
    return await transition_delivery(
        session,
        delivery,
        DeliveryStatus.DELIVERED,
        require_proof=True,
        proof_image_url=payload.image_url,
        proof_notes=payload.notes,
    )


@router.post("/deliveries/{delivery_id}/cancel")
async def courier_cancel(
    delivery_id: uuid.UUID,
    payload: DeliveryCancelRequest,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
) -> Any:
    delivery = await _authorize_courier_delivery(session, user, delivery_id)
    return await cancel_delivery(session, delivery, payload.reason)


@router.post("/deliveries/{delivery_id}/fail")
async def courier_fail(
    delivery_id: uuid.UUID,
    payload: DeliveryFailRequest,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
) -> Any:
    delivery = await _authorize_courier_delivery(session, user, delivery_id)
    return await fail_delivery(session, delivery, payload.reason)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _authorize_courier_delivery(
    session: AsyncSession, user: User, delivery_id: uuid.UUID
) -> Delivery:
    from app.users.models import CourierProfile

    delivery = await get_delivery_by_id(session, delivery_id)
    if delivery is None:
        raise DeliveryNotFound("Delivery not found")
    if user.user_type != UserType.courier:
        raise DeliveryNotFound("Courier role required")
    cp = (
        await session.execute(
            select(CourierProfile).where(CourierProfile.user_id == user.id)
        )
    ).scalar_one_or_none()
    if cp is None:
        raise DeliveryNotFound("Courier profile not found")
    if delivery.courier_id != cp.id:
        raise DeliveryNotFound("Delivery not assigned to this courier")
    return delivery


from datetime import UTC, datetime  # noqa: E402  (last-position import)
