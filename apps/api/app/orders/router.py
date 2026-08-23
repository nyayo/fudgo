"""FastAPI router for the cart + orders + payments domain.

All endpoints under /api/v2/cart, /api/v2/orders, /api/v2/payments,
/api/v2/restaurants/{id}/orders, /api/v2/courier/orders.
"""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, Header, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.deps import get_current_user, get_session
from app.core.envelope import success_envelope
from app.orders import service as order_service
from app.orders.enums import OrderStatus
from app.orders.models import Order
from app.orders.schemas import (
    CancelOrderRequest,
    CartItemAddRequest,
    CartItemUpdateRequest,
    CartResponse,
    CheckoutRequest,
    MessageResponse,
    OrderListResponse,
    OrderResponse,
    PaymentResponse,
)
from app.users.models import User

router = APIRouter()


def _serialize_order(order: Order) -> dict[str, Any]:
    return OrderResponse.model_validate(order, from_attributes=True).model_dump(mode="json")


# ---------------------------------------------------------------------------
# Cart
# ---------------------------------------------------------------------------


@router.get("/cart")
async def get_cart(
    current: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    from app.core.exceptions import NotFoundError

    try:
        cart = await order_service.get_cart_for_customer(session, current.id)
    except Exception:
        raise NotFoundError("No active cart")
    payload = await order_service.build_cart_response(session, cart)
    return success_envelope(CartResponse.model_validate(payload).model_dump(mode="json"))


@router.post("/cart/items")
async def add_cart_item(
    payload: CartItemAddRequest,
    current: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    from app.users.models import CustomerProfile

    cust = (
        await session.execute(
            __import__("sqlmodel").select(CustomerProfile).where(
                CustomerProfile.user_id == current.id
            )
        )
    ).scalar_one_or_none()
    if cust is None:
        from app.core.exceptions import PermissionError

        raise PermissionError("Only customers have carts")
    cart = await order_service.get_or_create_cart(session, cust.id)
    await order_service.add_item_to_cart(
        session, cart, payload.menu_item_id, payload.quantity, payload.special_instructions
    )
    await session.commit()
    payload_dict = await order_service.build_cart_response(session, cart)
    return success_envelope(CartResponse.model_validate(payload_dict).model_dump(mode="json"))


@router.patch("/cart/items/{item_id}")
async def update_cart_item(
    item_id: uuid.UUID,
    payload: CartItemUpdateRequest,
    current: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    from app.users.models import CustomerProfile

    cust = (
        await session.execute(
            __import__("sqlmodel").select(CustomerProfile).where(
                CustomerProfile.user_id == current.id
            )
        )
    ).scalar_one_or_none()
    if cust is None:
        from app.core.exceptions import PermissionError

        raise PermissionError("Only customers have carts")
    cart = await order_service.get_or_create_cart(session, cust.id)
    await order_service.update_cart_item(
        session,
        cart,
        item_id,
        quantity=payload.quantity,
        special_instructions=payload.special_instructions,
    )
    await session.commit()
    payload_dict = await order_service.build_cart_response(session, cart)
    return success_envelope(CartResponse.model_validate(payload_dict).model_dump(mode="json"))


@router.delete("/cart/items/{item_id}")
async def remove_cart_item(
    item_id: uuid.UUID,
    current: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    from app.users.models import CustomerProfile

    cust = (
        await session.execute(
            __import__("sqlmodel").select(CustomerProfile).where(
                CustomerProfile.user_id == current.id
            )
        )
    ).scalar_one_or_none()
    if cust is None:
        from app.core.exceptions import PermissionError

        raise PermissionError("Only customers have carts")
    cart = await order_service.get_or_create_cart(session, cust.id)
    await order_service.remove_cart_item(session, cart, item_id)
    await session.commit()
    return success_envelope({"message": "Item removed"})


@router.delete("/cart")
async def clear_cart(
    current: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    from app.users.models import CustomerProfile

    cust = (
        await session.execute(
            __import__("sqlmodel").select(CustomerProfile).where(
                CustomerProfile.user_id == current.id
            )
        )
    ).scalar_one_or_none()
    if cust is None:
        from app.core.exceptions import PermissionError

        raise PermissionError("Only customers have carts")
    cart = await order_service.get_or_create_cart(session, cust.id)
    await order_service.clear_cart(session, cart)
    await session.commit()
    return success_envelope({"message": "Cart cleared"})


# ---------------------------------------------------------------------------
# Checkout
# ---------------------------------------------------------------------------


@router.post("/cart/checkout")
async def checkout(
    payload: CheckoutRequest,
    current: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> dict[str, Any]:
    from app.users.models import CustomerProfile

    cust = (
        await session.execute(
            __import__("sqlmodel").select(CustomerProfile).where(
                CustomerProfile.user_id == current.id
            )
        )
    ).scalar_one_or_none()
    if cust is None:
        from app.core.exceptions import PermissionError

        raise PermissionError("Only customers can check out")
    order = await order_service.checkout_cart(
        session, cust.id, payload.delivery_address_id, idempotency_key
    )
    await session.commit()
    await session.refresh(order, ["items", "status_history", "payment"])
    return success_envelope(_serialize_order(order))


# ---------------------------------------------------------------------------
# Customer order endpoints
# ---------------------------------------------------------------------------


@router.get("/orders")
async def list_my_orders(
    status_filter: OrderStatus | None = Query(default=None, alias="status"),
    limit: int = Query(default=20, ge=1, le=100),
    cursor: uuid.UUID | None = Query(default=None),
    current: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    from app.users.models import CustomerProfile

    cust = (
        await session.execute(
            __import__("sqlmodel").select(CustomerProfile).where(
                CustomerProfile.user_id == current.id
            )
        )
    ).scalar_one_or_none()
    if cust is None:
        from app.core.exceptions import PermissionError

        raise PermissionError("Only customers can list their own orders here")
    rows, count = await order_service.list_customer_orders(
        session, cust.id, status=status_filter, limit=limit, cursor_id=cursor
    )
    next_cursor = str(rows[-1].id) if len(rows) == limit else None
    return success_envelope(
        OrderListResponse(
            items=[_serialize_order(o) for o in rows],
            count=count,
            next_cursor=next_cursor,
        ).model_dump(mode="json")
    )


@router.get("/orders/{order_id}")
async def get_order(
    order_id: uuid.UUID,
    current: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    order = await order_service._load_order(session, order_id)
    # Authorization: customer must own it, restaurant staff must be theirs,
    # courier must be theirs. Otherwise 404 (don't reveal existence).
    from app.users.models import CustomerProfile

    cust = (
        await session.execute(
            __import__("sqlmodel").select(CustomerProfile).where(
                CustomerProfile.user_id == current.id
            )
        )
    ).scalar_one_or_none()
    is_customer = cust is not None and order.customer_id == cust.id
    is_restaurant = current.user_type.value == "restaurant" and any(
        r.id == order.restaurant_id
        for r in (await session.execute(
            __import__("sqlmodel").select(__import__("app.users.models", fromlist=["RestaurantProfile"]).RestaurantProfile).where(
                __import__("app.users.models", fromlist=["RestaurantProfile"]).RestaurantProfile.user_id == current.id
            )
        )).scalars().all()
    )
    is_courier = current.user_type.value == "courier" and order.courier_id is not None
    if is_courier:
        from app.users.models import CourierProfile

        courier = (
            await session.execute(
                __import__("sqlmodel").select(CourierProfile).where(
                    CourierProfile.user_id == current.id
                )
            )
        ).scalar_one_or_none()
        is_courier = courier is not None and order.courier_id == courier.id
    if not (is_customer or is_restaurant or is_courier):
        from app.core.exceptions import NotFoundError

        raise NotFoundError("Order not found")
    return success_envelope(_serialize_order(order))


@router.post("/orders/{order_id}/cancel")
async def cancel_my_order(
    order_id: uuid.UUID,
    payload: CancelOrderRequest,
    current: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    from app.users.models import CustomerProfile

    order = await order_service._load_order(session, order_id)
    cust = (
        await session.execute(
            __import__("sqlmodel").select(CustomerProfile).where(
                CustomerProfile.user_id == current.id
            )
        )
    ).scalar_one_or_none()
    if cust is None or order.customer_id != cust.id:
        from app.core.exceptions import PermissionError

        raise PermissionError("Cannot cancel this order")
    await order_service.cancel_order(
        session, order, cancelled_by_user_id=current.id, role="customer", reason=payload.reason
    )
    await session.commit()
    await session.refresh(order, ["items", "status_history", "payment"])
    return success_envelope(_serialize_order(order))


# ---------------------------------------------------------------------------
# Restaurant order endpoints
# ---------------------------------------------------------------------------


@router.get("/restaurants/{restaurant_id}/orders")
async def list_restaurant_orders(
    restaurant_id: uuid.UUID,
    status_filter: OrderStatus | None = Query(default=None, alias="status"),
    limit: int = Query(default=20, ge=1, le=100),
    cursor: uuid.UUID | None = Query(default=None),
    current: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    from app.users.models import RestaurantProfile

    prof = (
        await session.execute(
            __import__("sqlmodel").select(RestaurantProfile).where(
                RestaurantProfile.user_id == current.id
            )
        )
    ).scalar_one_or_none()
    if prof is None or prof.id != restaurant_id:
        from app.core.exceptions import PermissionError

        raise PermissionError("Not a member of this restaurant")
    rows, count = await order_service.list_restaurant_orders(
        session, restaurant_id, status=status_filter, limit=limit, cursor_id=cursor
    )
    next_cursor = str(rows[-1].id) if len(rows) == limit else None
    return success_envelope(
        OrderListResponse(
            items=[_serialize_order(o) for o in rows],
            count=count,
            next_cursor=next_cursor,
        ).model_dump(mode="json")
    )


@router.post("/orders/{order_id}/confirm")
async def confirm_order(
    order_id: uuid.UUID,
    current: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    from app.users.models import RestaurantProfile

    order = await order_service._load_order(session, order_id)
    prof = (
        await session.execute(
            __import__("sqlmodel").select(RestaurantProfile).where(
                RestaurantProfile.user_id == current.id
            )
        )
    ).scalar_one_or_none()
    if prof is None or order.restaurant_id != prof.id:
        from app.core.exceptions import PermissionError

        raise PermissionError("Not your restaurant's order")
    await order_service.transition_order(
        session, order, OrderStatus.CONFIRMED,
        changed_by_user_id=current.id, changed_by_role="restaurant",
    )
    await session.commit()
    await session.refresh(order, ["items", "status_history", "payment"])
    return success_envelope(_serialize_order(order))


@router.post("/orders/{order_id}/start-preparing")
async def start_preparing(
    order_id: uuid.UUID,
    current: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    from app.users.models import RestaurantProfile

    order = await order_service._load_order(session, order_id)
    prof = (
        await session.execute(
            __import__("sqlmodel").select(RestaurantProfile).where(
                RestaurantProfile.user_id == current.id
            )
        )
    ).scalar_one_or_none()
    if prof is None or order.restaurant_id != prof.id:
        from app.core.exceptions import PermissionError

        raise PermissionError("Not your restaurant's order")
    await order_service.transition_order(
        session, order, OrderStatus.PREPARING,
        changed_by_user_id=current.id, changed_by_role="restaurant",
    )
    await session.commit()
    await session.refresh(order, ["items", "status_history", "payment"])
    return success_envelope(_serialize_order(order))


@router.post("/orders/{order_id}/mark-ready")
async def mark_ready(
    order_id: uuid.UUID,
    current: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    from app.users.models import RestaurantProfile

    order = await order_service._load_order(session, order_id)
    prof = (
        await session.execute(
            __import__("sqlmodel").select(RestaurantProfile).where(
                RestaurantProfile.user_id == current.id
            )
        )
    ).scalar_one_or_none()
    if prof is None or order.restaurant_id != prof.id:
        from app.core.exceptions import PermissionError

        raise PermissionError("Not your restaurant's order")
    await order_service.transition_order(
        session, order, OrderStatus.READY,
        changed_by_user_id=current.id, changed_by_role="restaurant",
    )
    await session.commit()
    await session.refresh(order, ["items", "status_history", "payment"])
    return success_envelope(_serialize_order(order))


@router.post("/orders/{order_id}/cancel")
async def cancel_as_restaurant(
    order_id: uuid.UUID,
    payload: CancelOrderRequest,
    current: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    from app.users.models import RestaurantProfile

    order = await order_service._load_order(session, order_id)
    prof = (
        await session.execute(
            __import__("sqlmodel").select(RestaurantProfile).where(
                RestaurantProfile.user_id == current.id
            )
        )
    ).scalar_one_or_none()
    if prof is None or order.restaurant_id != prof.id:
        from app.core.exceptions import PermissionError

        raise PermissionError("Not your restaurant's order")
    await order_service.cancel_order(
        session, order, cancelled_by_user_id=current.id, role="restaurant", reason=payload.reason
    )
    await session.commit()
    await session.refresh(order, ["items", "status_history", "payment"])
    return success_envelope(_serialize_order(order))


# ---------------------------------------------------------------------------
# Courier endpoints
# ---------------------------------------------------------------------------


@router.get("/courier/orders/available")
async def list_available_orders(
    near_lat: float | None = Query(default=None),
    near_lng: float | None = Query(default=None),
    radius_km: float | None = Query(default=None),
    restaurant_id: uuid.UUID | None = Query(default=None),
    current: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    if current.user_type.value != "courier":
        from app.core.exceptions import PermissionError

        raise PermissionError("Courier role required")
    rows = await order_service.list_available_for_courier(
        session,
        near_lng=near_lng,
        near_lat=near_lat,
        radius_km=radius_km,
        restaurant_id=restaurant_id,
    )
    return success_envelope([_serialize_order(o) for o in rows])


@router.post("/courier/orders/{order_id}/accept")
async def accept_order(
    order_id: uuid.UUID,
    current: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    from app.users.models import CourierProfile

    if current.user_type.value != "courier":
        from app.core.exceptions import PermissionError

        raise PermissionError("Courier role required")
    courier = (
        await session.execute(
            __import__("sqlmodel").select(CourierProfile).where(
                CourierProfile.user_id == current.id
            )
        )
    ).scalar_one_or_none()
    if courier is None:
        from app.core.exceptions import PermissionError

        raise PermissionError("Courier profile not found")
    order = await order_service._load_order(session, order_id)
    if order.courier_id is not None:
        from app.orders.exceptions import OrderInvalidTransition

        raise OrderInvalidTransition("Order already accepted by another courier")
    await order_service.transition_order(
        session, order, OrderStatus.PICKED_UP,
        changed_by_user_id=current.id, changed_by_role="courier",
        courier_id=courier.id,
    )
    await session.commit()
    await session.refresh(order, ["items", "status_history", "payment"])
    return success_envelope(_serialize_order(order))


@router.post("/courier/orders/{order_id}/on-the-way")
async def on_the_way(
    order_id: uuid.UUID,
    current: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    from app.users.models import CourierProfile

    if current.user_type.value != "courier":
        from app.core.exceptions import PermissionError

        raise PermissionError("Courier role required")
    courier = (
        await session.execute(
            __import__("sqlmodel").select(CourierProfile).where(
                CourierProfile.user_id == current.id
            )
        )
    ).scalar_one_or_none()
    order = await order_service._load_order(session, order_id)
    if courier is None or order.courier_id != courier.id:
        from app.core.exceptions import PermissionError

        raise PermissionError("Not your accepted order")
    await order_service.transition_order(
        session, order, OrderStatus.ON_THE_WAY,
        changed_by_user_id=current.id, changed_by_role="courier",
    )
    await session.commit()
    await session.refresh(order, ["items", "status_history", "payment"])
    return success_envelope(_serialize_order(order))


@router.post("/courier/orders/{order_id}/delivered")
async def mark_delivered(
    order_id: uuid.UUID,
    current: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    from app.users.models import CourierProfile

    if current.user_type.value != "courier":
        from app.core.exceptions import PermissionError

        raise PermissionError("Courier role required")
    courier = (
        await session.execute(
            __import__("sqlmodel").select(CourierProfile).where(
                CourierProfile.user_id == current.id
            )
        )
    ).scalar_one_or_none()
    order = await order_service._load_order(session, order_id)
    if courier is None or order.courier_id != courier.id:
        from app.core.exceptions import PermissionError

        raise PermissionError("Not your accepted order")
    await order_service.transition_order(
        session, order, OrderStatus.DELIVERED,
        changed_by_user_id=current.id, changed_by_role="courier",
    )
    await session.commit()
    await session.refresh(order, ["items", "status_history", "payment"])
    return success_envelope(_serialize_order(order))


@router.get("/courier/orders/mine")
async def list_my_courier_orders(
    status_filter: OrderStatus | None = Query(default=None, alias="status"),
    limit: int = Query(default=20, ge=1, le=100),
    cursor: uuid.UUID | None = Query(default=None),
    current: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    from app.users.models import CourierProfile

    if current.user_type.value != "courier":
        from app.core.exceptions import PermissionError

        raise PermissionError("Courier role required")
    courier = (
        await session.execute(
            __import__("sqlmodel").select(CourierProfile).where(
                CourierProfile.user_id == current.id
            )
        )
    ).scalar_one_or_none()
    if courier is None:
        return success_envelope({"items": [], "count": 0, "next_cursor": None})
    rows, count = await order_service.list_courier_orders(
        session, courier.id, status=status_filter, limit=limit, cursor_id=cursor
    )
    next_cursor = str(rows[-1].id) if len(rows) == limit else None
    return success_envelope(
        OrderListResponse(
            items=[_serialize_order(o) for o in rows],
            count=count,
            next_cursor=next_cursor,
        ).model_dump(mode="json")
    )


@router.post("/courier/orders/{order_id}/cancel")
async def cancel_as_courier(
    order_id: uuid.UUID,
    payload: CancelOrderRequest,
    current: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    from app.users.models import CourierProfile

    if current.user_type.value != "courier":
        from app.core.exceptions import PermissionError

        raise PermissionError("Courier role required")
    courier = (
        await session.execute(
            __import__("sqlmodel").select(CourierProfile).where(
                CourierProfile.user_id == current.id
            )
        )
    ).scalar_one_or_none()
    order = await order_service._load_order(session, order_id)
    if courier is None or order.courier_id != courier.id:
        from app.core.exceptions import PermissionError

        raise PermissionError("Not your accepted order")
    await order_service.cancel_order(
        session, order, cancelled_by_user_id=current.id, role="courier", reason=payload.reason
    )
    await session.commit()
    await session.refresh(order, ["items", "status_history", "payment"])
    return success_envelope(_serialize_order(order))


# ---------------------------------------------------------------------------
# Payments
# ---------------------------------------------------------------------------


@router.post("/orders/{order_id}/pay")
async def pay(
    order_id: uuid.UUID,
    current: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Payment is auto-succeeded at checkout (stub); this endpoint is a
    re-attempt for clients that want to confirm idempotently. If the
    payment already exists, return it.
    """
    from app.orders.models import Payment

    order = await order_service._load_order(session, order_id)
    from app.users.models import CustomerProfile

    cust = (
        await session.execute(
            __import__("sqlmodel").select(CustomerProfile).where(
                CustomerProfile.user_id == current.id
            )
        )
    ).scalar_one_or_none()
    if cust is None or order.customer_id != cust.id:
        from app.core.exceptions import PermissionError

        raise PermissionError("Not your order")
    existing = await order_service.get_payment_for_order(session, order_id)
    if existing is not None:
        return success_envelope(
            PaymentResponse.model_validate(existing, from_attributes=True).model_dump(mode="json")
        )
    payment = Payment(
        order_id=order.id,
        method="stub",
        status="succeeded",
        amount=order.total,
        succeeded_at=__import__("datetime").datetime.now(__import__("datetime").UTC),
    )
    session.add(payment)
    await session.commit()
    await session.refresh(payment)
    return success_envelope(
        PaymentResponse.model_validate(payment, from_attributes=True).model_dump(mode="json")
    )


@router.get("/payments/{payment_id}")
async def get_payment(
    payment_id: uuid.UUID,
    current: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    from app.orders.models import Payment
    from app.users.models import CourierProfile, CustomerProfile, RestaurantProfile

    payment = (
        await session.execute(select(Payment).where(Payment.id == payment_id))
    ).scalar_one_or_none()
    if payment is None:
        from app.core.exceptions import NotFoundError

        raise NotFoundError("Payment not found")
    order = await order_service._load_order(session, payment.order_id)
    cust = (
        await session.execute(
            __import__("sqlmodel").select(CustomerProfile).where(
                CustomerProfile.user_id == current.id
            )
        )
    ).scalar_one_or_none()
    is_customer = cust is not None and order.customer_id == cust.id
    rest = (
        await session.execute(
            __import__("sqlmodel").select(RestaurantProfile).where(
                RestaurantProfile.user_id == current.id
            )
        )
    ).scalar_one_or_none()
    is_restaurant = rest is not None and order.restaurant_id == rest.id
    cour = (
        await session.execute(
            __import__("sqlmodel").select(CourierProfile).where(
                CourierProfile.user_id == current.id
            )
        )
    ).scalar_one_or_none()
    is_courier = cour is not None and order.courier_id == cour.id
    if not (is_customer or is_restaurant or is_courier):
        from app.core.exceptions import PermissionError

        raise PermissionError("Cannot view this payment")
    return success_envelope(
        PaymentResponse.model_validate(payment, from_attributes=True).model_dump(mode="json")
    )
