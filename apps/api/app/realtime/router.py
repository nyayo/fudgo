"""WebSocket endpoints for real-time order tracking + courier location."""

from __future__ import annotations

import asyncio
import json
import uuid
from contextlib import suppress
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.jwt import decode_token
from app.core.config import get_settings
from app.realtime.connection_manager import make_event
from app.realtime.heartbeat import heartbeat_loop, is_pong

router = APIRouter()


# ---------------------------------------------------------------------------
# Channel conventions (kept in one place; see app.realtime.connection_manager)
# ---------------------------------------------------------------------------

def channel_order(order_id: uuid.UUID | str) -> str:
    return f"order:{order_id}"


def channel_restaurant_orders(restaurant_id: uuid.UUID | str) -> str:
    return f"restaurant:{restaurant_id}:orders"


CHANNEL_COURIER_AVAILABLE = "courier:available"


def channel_courier_mine(courier_id: uuid.UUID | str) -> str:
    return f"courier:{courier_id}:assigned"


# ---------------------------------------------------------------------------
# Helper: get the JWT-authenticated user from the WS handshake
# ---------------------------------------------------------------------------

async def _resolve_user(websocket: WebSocket) -> dict[str, Any] | None:
    """Validate ?token=... and return the decoded claims (with ``sub`` = user id)."""
    token = websocket.query_params.get("token")
    if not token:
        return None
    try:
        decoded = decode_token(token)
        # ``decode_token`` returns a TokenPayload (pydantic model or dict);
        # the WS routers only need the dict-like access.
        if hasattr(decoded, "model_dump"):
            return decoded.model_dump()
        return dict(decoded)
    except Exception:
        return None


async def _get_manager() -> Any:
    from app.deliveries.runtime import get_connection_manager

    return get_connection_manager()


# ---------------------------------------------------------------------------
# WS: /ws/orders/{order_id}/track  (customer)
# ---------------------------------------------------------------------------


@router.websocket("/ws/orders/{order_id}/track")
async def ws_order_track(
    websocket: WebSocket, order_id: uuid.UUID
) -> None:
    payload = await _resolve_user(websocket)
    if payload is None:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason="auth")
        return
    user_id = uuid.UUID(payload["sub"])

    # Verify the user is the order's customer
    from app.db.session import AsyncSessionLocal
    from app.orders.models import Order
    from app.users.models import CustomerProfile

    async with AsyncSessionLocal() as session:
        order = (
            await session.execute(select(Order).where(Order.id == order_id))
        ).scalar_one_or_none()
        if order is None:
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason="order not found")
            return
        cp = (
            await session.execute(
                select(CustomerProfile).where(CustomerProfile.user_id == user_id)
            )
        ).scalar_one_or_none()
        if cp is None or order.customer_id != cp.id:
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason="forbidden")
            return

    manager = await _get_manager()
    if manager is None:
        await websocket.close(code=status.WS_1011_INTERNAL_ERROR, reason="no manager")
        return

    channel = channel_order(order_id)
    ok = await manager.connect(channel, websocket, str(user_id))
    if not ok:
        return

    # Send a hello event so the client can verify the connection.
    await websocket.send_text(json.dumps(make_event("hello", {"order_id": str(order_id)})))

    # Run the receive + heartbeat loops concurrently
    hb_task = asyncio.create_task(heartbeat_loop(websocket, manager, channel))
    try:
        while True:
            raw = await websocket.receive_text()
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if is_pong(msg):
                continue
            # Clients can also send "subscribe" / "unsubscribe" hints,
            # but v1 is fixed to the channel set at connect time.
    except WebSocketDisconnect:
        pass
    finally:
        hb_task.cancel()
        with suppress(Exception):
            await hb_task
        manager.disconnect(channel, websocket)


# ---------------------------------------------------------------------------
# WS: /ws/restaurants/{restaurant_id}/orders  (restaurant staff)
# ---------------------------------------------------------------------------


@router.websocket("/ws/restaurants/{restaurant_id}/orders")
async def ws_restaurant_orders(
    websocket: WebSocket, restaurant_id: uuid.UUID
) -> None:
    payload = await _resolve_user(websocket)
    if payload is None:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason="auth")
        return
    user_id = uuid.UUID(payload["sub"])

    # Verify staff membership
    from app.db.session import AsyncSessionLocal
    from app.users.models import RestaurantStaffProfile

    async with AsyncSessionLocal() as session:
        staff = (
            await session.execute(
                select(RestaurantStaffProfile).where(
                    RestaurantStaffProfile.user_id == user_id
                )
            )
        ).scalar_one_or_none()
        if staff is None or staff.restaurant_id != restaurant_id:
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason="forbidden")
            return

    manager = await _get_manager()
    if manager is None:
        await websocket.close(code=status.WS_1011_INTERNAL_ERROR, reason="no manager")
        return

    channel = channel_restaurant_orders(restaurant_id)
    ok = await manager.connect(channel, websocket, str(user_id))
    if not ok:
        return
    await websocket.send_text(
        json.dumps(make_event("hello", {"restaurant_id": str(restaurant_id)}))
    )
    hb_task = asyncio.create_task(heartbeat_loop(websocket, manager, channel))
    try:
        while True:
            raw = await websocket.receive_text()
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if is_pong(msg):
                continue
    except WebSocketDisconnect:
        pass
    finally:
        hb_task.cancel()
        with suppress(Exception):
            await hb_task
        manager.disconnect(channel, websocket)


# ---------------------------------------------------------------------------
# WS: /ws/courier/orders/available  (courier, must be on shift)
# ---------------------------------------------------------------------------


@router.websocket("/ws/courier/orders/available")
async def ws_courier_available(websocket: WebSocket) -> None:
    payload = await _resolve_user(websocket)
    if payload is None:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason="auth")
        return
    user_id = uuid.UUID(payload["sub"])

    from app.db.session import AsyncSessionLocal
    from app.users.enums import UserType
    from app.users.models import CourierProfile

    async with AsyncSessionLocal() as session:
        courier = (
            await session.execute(
                select(CourierProfile).where(CourierProfile.user_id == user_id)
            )
        ).scalar_one_or_none()
        if courier is None:
            await websocket.close(
                code=status.WS_1008_POLICY_VIOLATION, reason="not a courier"
            )
            return

    manager = await _get_manager()
    if manager is None:
        await websocket.close(code=status.WS_1011_INTERNAL_ERROR, reason="no manager")
        return

    channel = CHANNEL_COURIER_AVAILABLE
    ok = await manager.connect(channel, websocket, str(user_id))
    if not ok:
        return
    await websocket.send_text(json.dumps(make_event("hello", {"channel": "available"})))
    hb_task = asyncio.create_task(heartbeat_loop(websocket, manager, channel))
    try:
        while True:
            raw = await websocket.receive_text()
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if is_pong(msg):
                continue
    except WebSocketDisconnect:
        pass
    finally:
        hb_task.cancel()
        with suppress(Exception):
            await hb_task
        manager.disconnect(channel, websocket)


# ---------------------------------------------------------------------------
# WS: /ws/courier/orders/mine  (courier, own accepted orders)
# ---------------------------------------------------------------------------


@router.websocket("/ws/courier/orders/mine")
async def ws_courier_mine(websocket: WebSocket) -> None:
    payload = await _resolve_user(websocket)
    if payload is None:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason="auth")
        return
    user_id = uuid.UUID(payload["sub"])

    from app.db.session import AsyncSessionLocal
    from app.users.models import CourierProfile

    async with AsyncSessionLocal() as session:
        courier = (
            await session.execute(
                select(CourierProfile).where(CourierProfile.user_id == user_id)
            )
        ).scalar_one_or_none()
        if courier is None:
            await websocket.close(
                code=status.WS_1008_POLICY_VIOLATION, reason="not a courier"
            )
            return
        courier_id = courier.id

    manager = await _get_manager()
    if manager is None:
        await websocket.close(code=status.WS_1011_INTERNAL_ERROR, reason="no manager")
        return

    channel = channel_courier_mine(courier_id)
    ok = await manager.connect(channel, websocket, str(user_id))
    if not ok:
        return
    await websocket.send_text(json.dumps(make_event("hello", {"courier_id": str(courier_id)})))
    hb_task = asyncio.create_task(heartbeat_loop(websocket, manager, channel))
    try:
        while True:
            raw = await websocket.receive_text()
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if is_pong(msg):
                continue
    except WebSocketDisconnect:
        pass
    finally:
        hb_task.cancel()
        with suppress(Exception):
            await hb_task
        manager.disconnect(channel, websocket)
