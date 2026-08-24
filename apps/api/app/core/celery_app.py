"""Celery app instance (Phase 5).

Celery is used for ONE thing: the ``sweep_stale_pending_payments`` task.
Phase 6 expands this to FCM / SMTP / SMS senders, courier auto-assign,
restaurant payouts, etc.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from app.core.config import get_settings
from app.db.sync_session import get_sync_session_maker


def _make_celery_app() -> Any:
    """Lazy Celery factory so tests don't pay the import cost unless they
    actually call ``.task`` or ``.send_task``.
    """
    try:
        from celery import Celery
        from celery.schedules import timedelta as _td
    except ImportError:
        return None

    settings = get_settings()
    app = Celery(
        "fudgo",
        broker=settings.CELERY_BROKER_URL,
        backend=settings.CELERY_RESULT_BACKEND,
        include=["app.orders.service"],
    )
    app.conf.update(
        task_serializer="json",
        result_serializer="json",
        accept_content=["json"],
        timezone="UTC",
        enable_utc=True,
        task_track_started=True,
        task_acks_late=True,
        worker_prefetch_multiplier=1,
        task_always_eager=settings.CELERY_TASK_ALWAYS_EAGER,
        task_eager_propagates=True,
        broker_connection_retry_on_startup=True,
    )
    app.conf.beat_schedule = {
        "sweep-stale-pending-payments": {
            "task": "orders.sweep_stale_pending_payments",
            "schedule": _td(seconds=settings.PENDING_PAYMENT_SWEEP_INTERVAL_S),
            "options": {"queue": "default"},
        },
    }
    return app


celery_app = _make_celery_app()


# ---------------------------------------------------------------------------
# sweep_stale_pending_payments task (registered on the Celery app so
# `celery -A app.core.celery_app worker` discovers it).
# ---------------------------------------------------------------------------


def _sweep_sync() -> int:
    """Sync implementation of the sweep. Runs in the Celery worker.

    Finds orders in PENDING_PAYMENT older than
    ``PENDING_PAYMENT_CART_TTL_MINUTES``, cancels each one, marks the
    payment FAILED, leaves the cart intact (so the customer can retry
    payment without re-adding items).

    Uses SELECT ... FOR UPDATE SKIP LOCKED so two workers can run
    concurrently without double-processing.
    """
    from app.core.config import get_settings
    from app.orders.enums import OrderStatus, PaymentStatus
    from app.orders.models import Order, OrderStatusHistory, Payment

    settings = get_settings()
    cutoff = datetime.now(UTC) - timedelta(minutes=settings.PENDING_PAYMENT_CART_TTL_MINUTES)
    maker = get_sync_session_maker()
    cancelled_count = 0
    with maker() as session:
        with session.begin():
            stale = session.execute(
                __import__("sqlalchemy").select(Order)
                .where(
                    Order.status == OrderStatus.PENDING_PAYMENT,
                    Order.placed_at < cutoff,
                )
                .with_for_update(skip_locked=True)
            ).scalars().all()
            for order in stale:
                order.status = OrderStatus.CANCELLED
                order.cancelled_at = datetime.now(UTC)
                order.cancellation_reason = "payment timeout"
                payment = session.execute(
                    __import__("sqlalchemy").select(Payment).where(
                        Payment.order_id == order.id
                    )
                ).scalar_one_or_none()
                if payment is not None:
                    payment.status = PaymentStatus.FAILED
                    payment.failure_reason = "checkout abandoned"
                    payment.failed_at = datetime.now(UTC)
                session.add(OrderStatusHistory(
                    order_id=order.id,
                    from_status=OrderStatus.PENDING_PAYMENT,
                    to_status=OrderStatus.CANCELLED,
                    changed_by_role="system",
                    note="payment timeout sweep",
                ))
                cancelled_count += 1
    return cancelled_count


if celery_app is not None:
    @celery_app.task(  # type: ignore[untyped-decorator]
        name="orders.sweep_stale_pending_payments",
        bind=True,
        max_retries=3,
        default_retry_delay=60,
        autoretry_for=(Exception,),
        retry_backoff=True,
        retry_backoff_max=300,
    )
    def sweep_stale_pending_payments(self: Any) -> int:
        """Celery task entrypoint: cancel PENDING_PAYMENT orders older than TTL."""
        return _sweep_sync()
