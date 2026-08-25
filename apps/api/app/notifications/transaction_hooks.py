"""Transaction hooks — v1's orders/signals.py pattern adapted to v2 services.

Call these AFTER the service commits so tasks only fire for persisted state.
"""

from __future__ import annotations

from typing import Any

_TITLE_MAP = {
    "confirmed": "Accepted",
    "preparing": "Being Prepared",
    "ready": "Ready for Pickup",
    "picked_up": "Picked Up",
    "on_the_way": "On the Way",
    "delivered": "Delivered",
    "cancelled": "Cancelled",
    "pending_payment": "Awaiting Payment",
    "placed": "Placed",
}


def on_order_placed(order: Any) -> None:
    """Fire tasks when an order reaches PLACED (payment confirmed)."""
    from app.notifications.tasks import (
        notify_restaurant_new_order,
        send_order_confirmation_email,
    )

    send_order_confirmation_email.delay(str(order.id))
    notify_restaurant_new_order.delay(str(order.id))


def on_order_status_changed(
    order: Any,
    from_status: str,
    to_status: str,
    reason: str | None = None,
) -> None:
    """Fire tasks when an order transitions between states."""
    from app.notifications.helpers import send_order_notification
    from app.notifications.tasks import (
        notify_restaurant_order_cancelled,
        notify_restaurant_order_status,
        send_order_delivered_email,
    )

    # Customer notification needs the User row; resolve lazily inside the task
    # by passing customer profile id through order attrs when available.
    customer_user = getattr(getattr(order, "customer", None), "user", None)
    if customer_user is not None:
        title = _TITLE_MAP.get(to_status, to_status.title())
        send_order_notification(customer_user, title, order)

    if to_status == "cancelled":
        notify_restaurant_order_cancelled.delay(str(order.id), reason=reason)
    else:
        notify_restaurant_order_status.delay(str(order.id), from_status, to_status)

    if to_status == "delivered":
        send_order_delivered_email.delay(str(order.id))
