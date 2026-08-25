"""Payout tasks: daily batch, execute one, retry failed."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from app.core.celery_app import celery_app


def _task(name: str) -> Any:
    def deco(fn: Any) -> Any:
        return celery_app.task(name=name)(fn)

    return deco


def _maker() -> Any:
    from app.db.sync_session import get_sync_session_maker

    return get_sync_session_maker()


@_task("payouts.process_pending_payouts")
def process_pending_payouts() -> int:
    """Beat schedule: daily 02:00 UTC.

    Finds orders DELIVERED more than PAYOUT_MIN_ORDER_AGE_HOURS ago that
    don't yet have payouts, and creates restaurant + courier payout rows.
    """
    from app.core.config import get_settings
    from app.deliveries.models import Delivery
    from app.notifications.enums import PayoutMethod, PayoutStatus
    from app.notifications.models_payouts import Payout
    from app.orders.enums import OrderStatus
    from app.orders.models import Order
    from app.payouts.pricing import compute_courier_net, compute_restaurant_net

    s = get_settings()
    cutoff = datetime.now(UTC) - timedelta(hours=s.PAYOUT_MIN_ORDER_AGE_HOURS)
    created = 0

    with _maker() as session:
        eligible = (
            session.query(Order)
            .filter(
                Order.status == OrderStatus.DELIVERED,
                Order.delivered_at < cutoff
            )
            .all()
        )
        for order in eligible:
            existing = (
                session.query(Payout).filter_by(order_id=order.id).first()
            )
            if existing is not None:
                continue
            gross = order.total
            net = compute_restaurant_net(gross, s.PLATFORM_FEE_PERCENT)
            fee = gross - net
            session.add(
                Payout(
                    order_id=order.id,
                    restaurant_id=order.restaurant_id,
                    method=PayoutMethod.MPESA_B2C.value,
                    status=PayoutStatus.SCHEDULED.value,
                    gross_amount=gross,
                    platform_fee=fee,
                    net_amount=net,
                    mpesa_occasion=f"Order {order.order_number} payout",
                )
            )
            # Courier side (linked to delivery)
            delivery = (
                session.query(Delivery)
                .filter_by(order_id=order.id, delivered_at=None)
                .first()
            )
            delivery2 = (
                session.query(Delivery).filter_by(order_id=order.id).first()
            )
            if (
                delivery2 is not None
                and delivery2.courier_id is not None
                and delivery == delivery2
            ):
                pass  # same row; handled below
            if delivery2 is not None and delivery2.courier_id is not None:
                dfee = order.delivery_fee
                cnet = compute_courier_net(dfee, s.COURIER_DELIVERY_FEE_PERCENT)
                cfee = dfee - cnet
                session.add(
                    Payout(
                        order_id=order.id,
                        delivery_id=delivery2.id,
                        courier_id=delivery2.courier_id,
                        method=PayoutMethod.MPESA_B2C.value,
                        status=PayoutStatus.SCHEDULED.value,
                        gross_amount=dfee,
                        platform_fee=cfee,
                        net_amount=cnet,
                        mpesa_occasion=f"Order {order.order_number} courier payout",
                    )
                )
                created += 1
            created += 1
        session.commit()
    return created


@_task("payouts.execute_payout")
def execute_payout(payout_id: str) -> str:
    """Execute a single SCHEDULED payout via M-Pesa B2C."""
    from app.notifications.enums import PayoutAttemptStatus, PayoutStatus
    from app.notifications.models_payouts import Payout, PayoutAttempt

    maker = _maker()
    with maker() as session:
        payout = session.get(Payout, payout_id)
        if payout is None:
            return "Payout not found"
        if payout.status != PayoutStatus.SCHEDULED.value:
            return f"Payout not SCHEDULED (current: {payout.status})"

        attempt_count = (
            session.query(PayoutAttempt).filter_by(payout_id=payout.id).count()
        )
        attempt = PayoutAttempt(
            payout_id=payout.id,
            attempt_number=attempt_count + 1,
            status=PayoutAttemptStatus.INITIATED.value,
            request_payload={
                "phone": payout.mpesa_phone_e164 or "",
                "amount": int(payout.net_amount),
                "occasion": payout.mpesa_occasion or "",
            },
        )
        session.add(attempt)

        payout.status = PayoutStatus.PROCESSING.value
        payout.processed_at = datetime.now(UTC)

        try:
            from app.payouts.mpesa_b2c_client import MpesaB2CClient

            client = MpesaB2CClient()
            if not client.is_configured:
                raise RuntimeError("M-Pesa B2C not configured")
            result = client.b2c_payment(
                phone_e164=payout.mpesa_phone_e164 or "+254700000000",
                amount_kes=int(payout.net_amount),
                occasion=payout.mpesa_occasion or "Fudgo payout",
            )
            attempt.status = PayoutAttemptStatus.SUCCEEDED.value  # type: ignore[assignment]
            attempt.completed_at = datetime.now(UTC)
            attempt.mpesa_conversation_id = result.get("ConversationID")
            payout.status = PayoutStatus.COMPLETED.value
            payout.completed_at = datetime.now(UTC)
        except Exception as exc:
            attempt.status = PayoutAttemptStatus.FAILED.value  # type: ignore[assignment]
            attempt.failed_at = datetime.now(UTC)
            attempt.error_message = str(exc)[:500]
            payout.status = PayoutStatus.FAILED.value
            payout.failed_at = datetime.now(UTC)
            payout.failure_reason = str(exc)[:500]
        session.commit()
    return f"Payout {payout_id}: {payout.status}"


@_task("payouts.retry_failed_payouts")
def retry_failed_payouts(payout_id: str) -> str:
    """Retry a FAILED payout by resetting it to SCHEDULED then executing."""
    from app.notifications.enums import PayoutStatus
    from app.notifications.models_payouts import Payout

    with _maker() as session:
        payout = session.get(Payout, payout_id)
        if payout is None:
            return "Payout not found"
        if payout.status != PayoutStatus.FAILED.value:
            return f"Payout not FAILED (current: {payout.status})"
        payout.status = PayoutStatus.SCHEDULED.value
        payout.failure_reason = None
        session.commit()
    return execute_payout(payout_id)
