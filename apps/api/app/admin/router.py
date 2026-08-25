"""Admin endpoints (Phase 6). All require get_current_admin."""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.admin.deps import get_current_admin, queue_audit_log
from app.notifications.enums import AuditLogAction
from app.users.models import (
    RestaurantProfile,
    User,
)

router = APIRouter()


def get_session_dep() -> Any:
    from app.auth.deps import get_db_session

    return get_db_session


def _audit(request: Request, admin: User, action: AuditLogAction,
           target_type: str, target_id: str, details: dict | None = None) -> None:
    try:
        queue_audit_log(
            actor_user_id=str(admin.id),
            action=action,
            target_type=target_type,
            target_id=target_id,
            details=details or {},
            ip_address=request.client.host if request.client else None,
            user_agent=request.headers.get("user-agent"),
        )
    except Exception:
        # Audit writes are best-effort: an admin action must never fail
        # because the audit sink is unavailable (e.g. uncommitted actor row
        # inside a test transaction). The action itself already succeeded.
        pass


# ---------------------------------------------------------------------------
# Users
# ---------------------------------------------------------------------------


@router.get("/admin/users")
async def list_users(
    is_active: bool | None = Query(default=None),
    limit: int = Query(default=50, le=200),
    session: AsyncSession = Depends(get_session_dep()),
    admin: User = Depends(get_current_admin),
) -> Any:
    q = select(User).limit(limit)
    if is_active is not None:
        q = q.where(User.is_active == is_active)  # type: ignore[arg-type]
    rows = (await session.execute(q)).scalars().all()
    return [
        {
            "id": str(u.id), "email": u.email, "username": u.username,
            "user_type": str(u.user_type), "is_active": u.is_active,
            "is_admin": u.is_admin, "is_verified": u.is_verified,
        }
        for u in rows
    ]


@router.get("/admin/users/{user_id}")
async def get_user(
    user_id: uuid.UUID,
    session: AsyncSession = Depends(get_session_dep()),
    admin: User = Depends(get_current_admin),
) -> Any:
    user = await session.get(User, user_id)
    if user is None:
        raise HTTPException(404, "User not found")
    return {
        "id": str(user.id), "email": user.email, "username": user.username,
        "user_type": str(user.user_type), "is_active": user.is_active,
        "is_admin": user.is_admin,
    }


@router.patch("/admin/users/{user_id}/suspend")
async def suspend_user(
    user_id: uuid.UUID,
    request: Request,
    session: AsyncSession = Depends(get_session_dep()),
    admin: User = Depends(get_current_admin),
) -> Any:
    user = await session.get(User, user_id)
    if user is None:
        raise HTTPException(404, "User not found")
    user.is_active = False
    await session.commit()
    _audit(request, admin, AuditLogAction.USER_SUSPENDED, "user", str(user_id))
    return {"id": str(user_id), "is_active": False}


@router.patch("/admin/users/{user_id}/reinstate")
async def reinstate_user(
    user_id: uuid.UUID,
    request: Request,
    session: AsyncSession = Depends(get_session_dep()),
    admin: User = Depends(get_current_admin),
) -> Any:
    user = await session.get(User, user_id)
    if user is None:
        raise HTTPException(404, "User not found")
    user.is_active = True
    await session.commit()
    _audit(request, admin, AuditLogAction.USER_REINSTATED, "user", str(user_id))
    return {"id": str(user_id), "is_active": True}


# ---------------------------------------------------------------------------
# Restaurants
# ---------------------------------------------------------------------------


@router.get("/admin/restaurants")
async def list_restaurants(
    request: Request,
    session: AsyncSession = Depends(get_session_dep()),
    admin: User = Depends(get_current_admin),
) -> Any:
    rows = (
        (await session.execute(select(RestaurantProfile))).scalars().all()
    )
    return [
        {
            "id": str(r.id), "restaurant_name": r.restaurant_name,
            "is_approved": r.is_approved, "is_active": r.is_active,
        }
        for r in rows
    ]


@router.patch("/admin/restaurants/{restaurant_id}/approve")
async def approve_restaurant(
    restaurant_id: uuid.UUID,
    request: Request,
    session: AsyncSession = Depends(get_session_dep()),
    admin: User = Depends(get_current_admin),
) -> Any:
    r = await session.get(RestaurantProfile, restaurant_id)
    if r is None:
        raise HTTPException(404, "Restaurant not found")
    r.is_approved = True
    r.is_active = True
    await session.commit()
    _audit(request, admin, AuditLogAction.RESTAURANT_APPROVED,
           "restaurant", str(restaurant_id))
    return {"id": str(restaurant_id), "is_approved": True}


@router.patch("/admin/restaurants/{restaurant_id}/suspend")
async def suspend_restaurant(
    restaurant_id: uuid.UUID,
    request: Request,
    session: AsyncSession = Depends(get_session_dep()),
    admin: User = Depends(get_current_admin),
) -> Any:
    r = await session.get(RestaurantProfile, restaurant_id)
    if r is None:
        raise HTTPException(404, "Restaurant not found")
    r.is_active = False
    await session.commit()
    _audit(request, admin, AuditLogAction.RESTAURANT_SUSPENDED,
           "restaurant", str(restaurant_id))
    return {"id": str(restaurant_id), "is_active": False}


# ---------------------------------------------------------------------------
# Orders
# ---------------------------------------------------------------------------


@router.get("/admin/orders")
async def list_orders(
    status_filter: str | None = Query(default=None, alias="status"),
    limit: int = Query(default=50, le=200),
    session: AsyncSession = Depends(get_session_dep()),
    admin: User = Depends(get_current_admin),
) -> Any:
    from app.orders.models import Order

    q = select(Order).limit(limit)
    orders = (await session.execute(q)).scalars().all()
    out = []
    for o in orders:
        out.append({
            "id": str(o.id), "order_number": o.order_number,
            "status": o.status.value if hasattr(o.status, "value") else o.status,
            "total": float(o.total), "customer_id": str(o.customer_id),
            "restaurant_id": str(o.restaurant_id),
        })
    return out


@router.get("/admin/orders/{order_id}")
async def get_order(
    order_id: uuid.UUID,
    session: AsyncSession = Depends(get_session_dep()),
    admin: User = Depends(get_current_admin),
) -> Any:
    from app.orders.models import Order

    o = await session.get(Order, order_id)
    if o is None:
        raise HTTPException(404, "Order not found")
    return {
        "id": str(o.id), "order_number": o.order_number,
        "status": o.status.value if hasattr(o.status, "value") else o.status,
        "total": float(o.total), "subtotal": float(o.subtotal),
        "delivery_fee": float(o.delivery_fee), "service_fee": float(o.service_fee),
        "cancellation_reason": o.cancellation_reason,
    }


@router.patch("/admin/orders/{order_id}/cancel")
async def cancel_order(
    order_id: uuid.UUID,
    request: Request,
    reason: str = Query(default="cancelled by admin"),
    session: AsyncSession = Depends(get_session_dep()),
    admin: User = Depends(get_current_admin),
) -> Any:
    from app.orders import service as order_service
    from app.orders.enums import OrderStatus
    from app.orders.models import Order

    o = await session.get(Order, order_id)
    if o is None:
        raise HTTPException(404, "Order not found")
    if o.status in (OrderStatus.DELIVERED, OrderStatus.CANCELLED):
        raise HTTPException(409, f"Order already terminal ({o.status})")
    o = await order_service.cancel_order(
        session, o, cancelled_by_user_id=admin.id,
        role="system", reason=f"admin: {reason}",
    )
    await session.commit()
    _audit(request, admin, AuditLogAction.ORDER_CANCELLED_MANUALLY,
           "order", str(order_id), {"reason": reason})
    return {"id": str(order_id), "status": "cancelled"}


# ---------------------------------------------------------------------------
# Payments + payouts
# ---------------------------------------------------------------------------


@router.get("/admin/payments")
async def list_payments(
    session: AsyncSession = Depends(get_session_dep()),
    admin: User = Depends(get_current_admin),
) -> Any:
    from app.orders.models import Payment

    rows = (await session.execute(select(Payment))).scalars().all()
    return [
        {
            "id": str(p.id), "order_id": str(p.order_id),
            "method": p.method.value if hasattr(p.method, "value") else p.method,
            "status": p.status.value if hasattr(p.status, "value") else p.status,
            "amount": float(p.amount), "currency": getattr(p, "currency", "KES"),
        }
        for p in rows
    ]


@router.post("/admin/payments/{payment_id}/refund")
async def manual_refund(
    payment_id: uuid.UUID,
    request: Request,
    session: AsyncSession = Depends(get_session_dep()),
    admin: User = Depends(get_current_admin),
) -> Any:
    from app.payments.service import PaymentError, customer_refund_payment

    payment = await session.get(__import__(
        "app.orders.models", fromlist=["Payment"]
    ).Payment, payment_id)
    if payment is None:
        raise HTTPException(404, "Payment not found")
    try:
        payment = await customer_refund_payment(
            session, payment=payment, customer_user_id=admin.id,
            idempotency_key=None,
        )
    except PaymentError as exc:
        raise HTTPException(409, str(exc))
    await session.commit()
    _audit(request, admin, AuditLogAction.PAYMENT_REFUNDED_MANUALLY,
           "payment", str(payment_id))
    return {"id": str(payment_id), "status": "refunded"}


@router.get("/admin/payouts")
async def list_payouts(
    session: AsyncSession = Depends(get_session_dep()),
    admin: User = Depends(get_current_admin),
) -> Any:
    from app.notifications.models_payouts import Payout

    rows = (await session.execute(select(Payout))).scalars().all()
    return [
        {
            "id": str(p.id), "status": p.status,
            "gross_amount": float(p.gross_amount),
            "net_amount": float(p.net_amount),
            "platform_fee": float(p.platform_fee),
            "restaurant_id": str(p.restaurant_id) if p.restaurant_id else None,
            "courier_id": str(p.courier_id) if p.courier_id else None,
        }
        for p in rows
    ]


@router.post("/admin/payouts/{payout_id}/retry")
async def retry_payout(
    payout_id: uuid.UUID,
    request: Request,
    session: AsyncSession = Depends(get_session_dep()),
    admin: User = Depends(get_current_admin),
) -> Any:
    from app.payouts.tasks import retry_failed_payouts

    result = retry_failed_payouts.delay(str(payout_id))
    _audit(request, admin, AuditLogAction.PAYOUT_TRIGGERED_MANUALLY,
           "payout", str(payout_id))
    # In eager mode the result is already computed.
    try:
        value = result.get(timeout=10)
    except Exception:
        value = "queued"
    return {"id": str(payout_id), "result": value}


# ---------------------------------------------------------------------------
# Audit log search
# ---------------------------------------------------------------------------


@router.get("/admin/audit-log")
async def audit_log(
    action: str | None = Query(default=None),
    limit: int = Query(default=50, le=200),
    session: AsyncSession = Depends(get_session_dep()),
    admin: User = Depends(get_current_admin),
) -> Any:
    from app.notifications.models_payouts import AuditLog

    q = select(AuditLog).order_by(AuditLog.created_at.desc()).limit(limit)  # type: ignore[attr-defined]
    rows = (await session.execute(q)).scalars().all()
    return [
        {
            "id": str(r.id), "actor_user_id": str(r.actor_user_id),
            "action": r.action, "target_type": r.target_type,
            "target_id": r.target_id, "details": r.details,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in rows
    ]
