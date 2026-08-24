"""Payments service layer (Phase 5).

Two main concerns:

1. ``initiate_payment`` -- customer pays for an order that's in
   ``PENDING_PAYMENT``. Creates a Stripe PaymentIntent (for ``method=card``)
   or a M-Pesa STK Push (for ``method=mpesa``); persists a
   ``PaymentAttempt`` row.
2. ``handle_stripe_webhook`` / ``handle_mpesa_callback`` -- once the
   provider tells us the result, transition the Payment and the Order.

Plus ``customer_refund_payment`` (Stripe-only in v1; M-Pesa is stubbed)
and ``sweep_stale_pending_payments`` (the Celery Beat task).
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.orders.enums import OrderStatus, PaymentMethod, PaymentStatus
from app.orders.models import Order, OrderItem, Payment
from app.payments.enums import PaymentAttemptStatus, WebhookProvider
from app.payments.models import PaymentAttempt, PaymentWebhookEvent
from app.payments.mpesa_client import MpesaClient, get_mpesa_client
from app.payments.stripe_client import (
    FakeStripeClient,
    StripeClient,
    StripeInvalidRequest,
    get_stripe_client,
)


# ---------------------------------------------------------------------------
# Custom exceptions
# ---------------------------------------------------------------------------


class PaymentError(Exception):
    """Base for all payments-domain errors."""


class PaymentNotFound(PaymentError):
    pass


class PaymentMethodNotSupported(PaymentError):
    pass


class PaymentProviderNotConfigured(PaymentError):
    pass


class PaymentInvalidState(PaymentError):
    pass


class PaymentAttemptExists(PaymentError):
    pass


# ---------------------------------------------------------------------------
# Initiate payment
# ---------------------------------------------------------------------------


async def _existing_attempt(
    session: AsyncSession, payment_id: uuid.UUID, idempotency_key: str | None
) -> PaymentAttempt | None:
    if not idempotency_key:
        return None
    return (
        await session.execute(
            select(PaymentAttempt).where(
                PaymentAttempt.payment_id == payment_id,
                PaymentAttempt.idempotency_key == idempotency_key,
            )
        )
    ).scalar_one_or_none()


async def initiate_payment(
    session: AsyncSession,
    *,
    order: Order,
    payment: Payment,
    method: PaymentMethod,
    phone_e164: str | None,
    idempotency_key: str | None,
    stripe_client: StripeClient | None = None,
    mpesa_client: MpesaClient | None = None,
) -> PaymentAttempt:
    """Create a new PaymentAttempt against an existing Order in PENDING_PAYMENT.

    Returns the attempt. If a prior attempt exists with the same idempotency_key,
    returns that one (idempotency).
    """
    if method not in (PaymentMethod.CARD, PaymentMethod.MPESA):
        raise PaymentMethodNotSupported(f"Method {method.value} not supported")

    if order.status != OrderStatus.PENDING_PAYMENT:
        raise PaymentInvalidState(
            f"Order must be in PENDING_PAYMENT, was {order.status.value}"
        )
    if payment.status != PaymentStatus.PENDING:
        raise PaymentInvalidState(
            f"Payment must be PENDING, was {payment.status.value}"
        )

    existing = await _existing_attempt(session, payment.id, idempotency_key)
    if existing is not None:
        return existing

    next_number = (
        await session.execute(
            select(PaymentAttempt.attempt_number)
            .where(PaymentAttempt.payment_id == payment.id)
            .order_by(PaymentAttempt.attempt_number.desc())
            .limit(1)
        )
    ).scalar_one_or_none() or 0
    next_number += 1

    attempt = PaymentAttempt(
        payment_id=payment.id,
        attempt_number=next_number,
        method=method.value,
        status=PaymentAttemptStatus.INITIATED.value,
        idempotency_key=idempotency_key,
    )
    session.add(attempt)
    await session.flush()

    if method == PaymentMethod.CARD:
        sc = stripe_client or get_stripe_client()
        if not sc.is_configured:
            raise PaymentProviderNotConfigured("Stripe is not configured")
        amount = Decimal(str(order.total))
        currency = "kes"  # single-currency v1
        metadata = {
            "order_id": str(order.id),
            "order_number": order.order_number,
        }
        result = await sc.create_payment_intent(
            amount=amount,
            currency=currency,
            metadata=metadata,
            idempotency_key=idempotency_key or str(attempt.id),
        )
        attempt.stripe_payment_intent_id = result.get("id")
        attempt.stripe_client_secret = result.get("client_secret")
        attempt.request_payload = {
            "amount_minor": int(amount * 100),
            "currency": currency,
            "metadata": metadata,
        }
    elif method == PaymentMethod.MPESA:
        mc = mpesa_client or get_mpesa_client()
        if not mc.is_configured:
            raise PaymentProviderNotConfigured("M-Pesa is not configured")
        if not phone_e164:
            raise PaymentMethodNotSupported("phone is required for MPESA")
        amount_kes = int(Decimal(str(order.total)))
        try:
            result = await mc.stk_push(
                amount_kes=amount_kes,
                phone_e164=phone_e164,
                account_reference=order.order_number,
                transaction_desc=f"Fudgo order {order.order_number}",
            )
        except Exception as exc:
            attempt.status = PaymentAttemptStatus.FAILED.value  # type: ignore[assignment]
            attempt.failed_at = datetime.now(UTC)
            attempt.failure_reason = str(exc)[:500]
            await session.flush()
            raise
        attempt.mpesa_checkout_request_id = result.get("CheckoutRequestID")
        attempt.mpesa_merchant_request_id = result.get("MerchantRequestID")
        attempt.mpesa_phone_e164 = phone_e164
        attempt.request_payload = {
            "amount_kes": amount_kes,
            "phone": phone_e164,
            "account_reference": order.order_number,
        }

    await session.flush()
    return attempt


# ---------------------------------------------------------------------------
# Webhook handlers
# ---------------------------------------------------------------------------


async def _record_webhook(
    session: AsyncSession,
    *,
    provider: WebhookProvider,
    event_id: str,
    event_type: str,
    payload: dict[str, Any],
) -> PaymentWebhookEvent | None:
    """Dedup + insert a webhook event. Returns None if it's a duplicate."""
    existing = (
        await session.execute(
            select(PaymentWebhookEvent).where(
                PaymentWebhookEvent.provider == provider.value,
                PaymentWebhookEvent.event_id == event_id,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        return None
    evt = PaymentWebhookEvent(
        provider=provider.value,
        event_id=event_id,
        event_type=event_type,
        payload=payload,
    )
    session.add(evt)
    await session.flush()
    return evt


async def _attempt_by_stripe_pi(
    session: AsyncSession, payment_intent_id: str
) -> PaymentAttempt | None:
    return (
        await session.execute(
            select(PaymentAttempt).where(
                PaymentAttempt.stripe_payment_intent_id == payment_intent_id
            )
        )
    ).scalar_one_or_none()


async def _attempt_by_mpesa_checkout(
    session: AsyncSession, checkout_request_id: str
) -> PaymentAttempt | None:
    return (
        await session.execute(
            select(PaymentAttempt).where(
                PaymentAttempt.mpesa_checkout_request_id == checkout_request_id
            )
        )
    ).scalar_one_or_none()


async def _broadcast(
    channel: str, event_type: str, data: dict[str, Any]
) -> None:
    """Fire-and-forget via the Phase 4 ConnectionManager."""
    try:
        from app.deliveries.runtime import get_connection_manager
        from app.realtime.connection_manager import make_event

        manager = get_connection_manager()
        if manager is None:
            return
        event = make_event(event_type, data)
        asyncio.create_task(manager.broadcast(channel, event))
    except RuntimeError:
        pass


async def _move_order_to_placed(
    session: AsyncSession, order: Order, *, by_role: str
) -> None:
    """Transition PENDING_PAYMENT -> PLACED + delete the cart."""
    from app.orders import service as order_service

    await order_service.transition_order(
        session,
        order,
        OrderStatus.PLACED,
        changed_by_user_id=None,
        changed_by_role=by_role,
        note="payment succeeded",
    )
    # Delete the cart now that the order is real.
    cart = order.cart  # may be None if the FK doesn't exist; tolerate it
    if cart is not None:
        for item in list(cart.items):
            await session.delete(item)
        await session.delete(cart)
    await session.flush()


async def handle_stripe_webhook(
    session: AsyncSession,
    *,
    event: dict[str, Any],
    stripe_client: StripeClient | None = None,
) -> dict[str, Any]:
    """Process a verified Stripe webhook event.

    Returns a small dict ``{status: ..., ...}``. Idempotent: duplicate
    ``event.id`` returns ``{"status": "duplicate"}`` without re-processing.
    """
    event_id = event.get("id") or ""
    event_type = event.get("type") or ""

    stored = await _record_webhook(
        session,
        provider=WebhookProvider.STRIPE,
        event_id=event_id,
        event_type=event_type,
        payload=event,
    )
    if stored is None:
        return {"status": "duplicate", "event_id": event_id}

    if event_type == "payment_intent.succeeded":
        pi = (event.get("data", {}).get("object", {}).get("id")) or ""
        attempt = await _attempt_by_stripe_pi(session, pi)
        if attempt is None:
            stored.error = "no matching attempt"
            await session.flush()
            return {"status": "unmatched", "event_id": event_id}
        attempt.status = PaymentAttemptStatus.SUCCEEDED.value  # type: ignore[assignment]
        attempt.succeeded_at = datetime.now(UTC)
        payment = (
            await session.execute(select(Payment).where(Payment.id == attempt.payment_id))
        ).scalar_one()
        payment.status = PaymentStatus.SUCCEEDED
        payment.succeeded_at = datetime.now(UTC)
        payment.external_reference = pi
        order = (
            await session.execute(select(Order).where(Order.id == payment.order_id))
        ).scalar_one()
        await _move_order_to_placed(session, order, by_role="system")
        stored.processed_at = datetime.now(UTC)
        await _broadcast(
            f"order:{order.id}",
            "order.status_changed",
            {
                "order_id": str(order.id),
                "from_status": OrderStatus.PENDING_PAYMENT.value,
                "to_status": OrderStatus.PLACED.value,
                "at": datetime.now(UTC).isoformat(),
            },
        )
        return {"status": "ok", "order_id": str(order.id)}

    if event_type == "payment_intent.payment_failed":
        pi = (event.get("data", {}).get("object", {}).get("id")) or ""
        attempt = await _attempt_by_stripe_pi(session, pi)
        if attempt is not None:
            attempt.status = PaymentAttemptStatus.FAILED.value  # type: ignore[assignment]
            attempt.failed_at = datetime.now(UTC)
            attempt.failure_reason = (
                event.get("data", {}).get("object", {}).get("last_payment_error", {}).get("message", "")
                or "payment_failed"
            )
            payment = (
                await session.execute(
                    select(Payment).where(Payment.id == attempt.payment_id)
                )
            ).scalar_one()
            payment.status = PaymentStatus.FAILED
            payment.failed_at = datetime.now(UTC)
            payment.failure_reason = attempt.failure_reason
        stored.processed_at = datetime.now(UTC)
        return {"status": "ok", "event_id": event_id}

    if event_type == "payment_intent.canceled":
        pi = (event.get("data", {}).get("object", {}).get("id")) or ""
        attempt = await _attempt_by_stripe_pi(session, pi)
        if attempt is not None:
            attempt.status = PaymentAttemptStatus.CANCELLED.value  # type: ignore[assignment]
            attempt.failed_at = datetime.now(UTC)
            payment = (
                await session.execute(
                    select(Payment).where(Payment.id == attempt.payment_id)
                )
            ).scalar_one()
            payment.status = PaymentStatus.FAILED
            payment.failure_reason = "cancelled"
        stored.processed_at = datetime.now(UTC)
        return {"status": "ok", "event_id": event_id}

    if event_type == "charge.refunded":
        charge = event.get("data", {}).get("object", {})
        pi = charge.get("payment_intent") or ""
        attempt = await _attempt_by_stripe_pi(session, pi)
        if attempt is not None:
            payment = (
                await session.execute(
                    select(Payment).where(Payment.id == attempt.payment_id)
                )
            ).scalar_one()
            payment.status = PaymentStatus.REFUNDED
            payment.refunded_at = datetime.now(UTC)
            payment.external_reference = (
                f"{payment.external_reference or ''},refund={charge.get('id', '')}"
            ).strip(",")
        stored.processed_at = datetime.now(UTC)
        return {"status": "ok", "event_id": event_id}

    # Unhandled event type: store it but don't error.
    stored.processed_at = datetime.now(UTC)
    stored.error = f"unhandled event type: {event_type}"
    await session.flush()
    return {"status": "ignored", "event_type": event_type}


async def handle_mpesa_callback(
    session: AsyncSession,
    *,
    body: dict[str, Any],
) -> dict[str, Any]:
    """Process a Daraja STK Push callback."""
    callback = body.get("Body", {}).get("stkCallback", {})
    checkout_id = callback.get("CheckoutRequestID") or ""
    result_code = callback.get("ResultCode")
    metadata_items = callback.get("CallbackMetadata", {}).get("Item", []) or []
    result_desc = callback.get("ResultDesc") or ""

    # Generate a deterministic event_id for dedup (CheckoutRequestID + result_code)
    event_id_seed = f"{checkout_id}:{result_code}".encode()
    event_id = hashlib.sha256(event_id_seed).hexdigest()

    stored = await _record_webhook(
        session,
        provider=WebhookProvider.MPESA,
        event_id=event_id,
        event_type="stk_callback",
        payload=body,
    )
    if stored is None:
        return {"status": "duplicate", "event_id": event_id}

    attempt = await _attempt_by_mpesa_checkout(session, checkout_id)
    if attempt is None:
        stored.error = "no matching attempt"
        await session.flush()
        return {"status": "unmatched", "checkout_id": checkout_id}

    if int(result_code) == 0:
        attempt.status = PaymentAttemptStatus.SUCCEEDED.value  # type: ignore[assignment]
        attempt.succeeded_at = datetime.now(UTC)
        # Extract receipt number from CallbackMetadata if present
        for item in metadata_items:
            if item.get("Name") == "MpesaReceiptNumber":
                attempt.request_payload = attempt.request_payload or {}
                attempt.request_payload["mpesa_receipt"] = item.get("Value")
        payment = (
            await session.execute(select(Payment).where(Payment.id == attempt.payment_id))
        ).scalar_one()
        payment.status = PaymentStatus.SUCCEEDED
        payment.succeeded_at = datetime.now(UTC)
        order = (
            await session.execute(select(Order).where(Order.id == payment.order_id))
        ).scalar_one()
        await _move_order_to_placed(session, order, by_role="system")
        stored.processed_at = datetime.now(UTC)
        await _broadcast(
            f"order:{order.id}",
            "order.status_changed",
            {
                "order_id": str(order.id),
                "from_status": OrderStatus.PENDING_PAYMENT.value,
                "to_status": OrderStatus.PLACED.value,
                "at": datetime.now(UTC).isoformat(),
            },
        )
        return {"status": "ok", "order_id": str(order.id)}

    # Failure
    attempt.status = PaymentAttemptStatus.FAILED.value  # type: ignore[assignment]
    attempt.failed_at = datetime.now(UTC)
    attempt.failure_reason = (result_desc or "M-Pesa failure")[:500]
    payment = (
        await session.execute(select(Payment).where(Payment.id == attempt.payment_id))
    ).scalar_one()
    payment.status = PaymentStatus.FAILED
    payment.failed_at = datetime.now(UTC)
    payment.failure_reason = attempt.failure_reason
    stored.processed_at = datetime.now(UTC)
    return {"status": "ok", "event_type": "failure"}


# ---------------------------------------------------------------------------
# Refund
# ---------------------------------------------------------------------------


async def customer_refund_payment(
    session: AsyncSession,
    *,
    payment: Payment,
    customer_user_id: uuid.UUID,
    idempotency_key: str | None,
    stripe_client: StripeClient | None = None,
) -> Payment:
    """Customer-initiated refund.

    Stripe: real refund call. M-Pesa: STUBBED (logs intent + marks REFUNDED
    but doesn't call B2C API -- requires additional Safaricom approval; see
    Phase 6 handoff).
    """
    if payment.status != PaymentStatus.SUCCEEDED:
        raise PaymentInvalidState(
            f"Cannot refund payment in status {payment.status.value}"
        )
    order = (
        await session.execute(select(Order).where(Order.id == payment.order_id))
    ).scalar_one_or_none()
    if order is None:
        raise PaymentNotFound("Order not found")
    if order.customer_id is None:
        raise PaymentInvalidState("Order has no customer")
    # The customer's customer_profile.id == order.customer_id (Phase 3 convention)
    # but the customer_user_id is the User.id. The auth check happens at the
    # route layer; we trust it's the right user here.

    if order.status not in (OrderStatus.PLACED, OrderStatus.CONFIRMED):
        raise PaymentInvalidState(
            f"Order is in {order.status.value}; can only refund before PREPARING"
        )

    # 24-hour window from placed_at
    if order.placed_at:
        age = datetime.now(UTC) - order.placed_at
        if age > timedelta(hours=24):
            raise PaymentInvalidState("Order is older than 24 hours; refund window closed")

    if payment.method == PaymentMethod.CARD:
        sc = stripe_client or get_stripe_client()
        if not sc.is_configured:
            raise PaymentProviderNotConfigured("Stripe is not configured")
        # Find the successful attempt to get the payment_intent_id
        attempt = (
            await session.execute(
                select(PaymentAttempt)
                .where(
                    PaymentAttempt.payment_id == payment.id,
                    PaymentAttempt.status == PaymentAttemptStatus.SUCCEEDED.value,
                )
                .order_by(PaymentAttempt.attempt_number.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        if attempt is None or not attempt.stripe_payment_intent_id:
            raise PaymentInvalidState("No successful card attempt to refund")
        await sc.create_refund(
            payment_intent_id=attempt.stripe_payment_intent_id,
            amount=None,  # full refund
            idempotency_key=idempotency_key,
        )
    elif payment.method == PaymentMethod.MPESA:
        # STUB: M-Pesa B2C requires additional API access. Mark REFUNDED
        # but don't actually call the B2C endpoint.
        payment.failure_reason = (
            payment.failure_reason or ""
        ) + " [STUB: M-Pesa B2C refund pending; see docs/PHASE_5_HANDOFF.md]"
    else:
        raise PaymentMethodNotSupported(
            f"Refund for {payment.method.value} not supported"
        )

    payment.status = PaymentStatus.REFUNDED
    payment.refunded_at = datetime.now(UTC)
    # Transition order to CANCELLED
    from app.orders import service as order_service

    await order_service.transition_order(
        session,
        order,
        OrderStatus.CANCELLED,
        changed_by_user_id=customer_user_id,
        changed_by_role="customer",
        note="customer refund",
    )
    order.cancellation_reason = "customer refund"
    await session.flush()
    await _broadcast(
        f"order:{order.id}",
        "order.status_changed",
        {
            "order_id": str(order.id),
            "from_status": "refunded",
            "to_status": OrderStatus.CANCELLED.value,
            "at": datetime.now(UTC).isoformat(),
        },
    )
    return payment
