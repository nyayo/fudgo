"""Notification helpers — ports of v1's users/helpers.py wrappers."""

from __future__ import annotations

from typing import Any


def send_order_notification(user: Any, title: str, order: Any) -> None:
    """v1 port: fan out push (+ in-app row) for an order event."""
    from app.notifications.tasks import send_push_notification_to_user

    send_push_notification_to_user.delay(
        str(user.id),
        f"Order {title}",
        f"Your order #{order.order_number} has been {title.lower()}!",
        {"order_id": str(order.id), "type": "order_update"},
    )


def notify_new_promotion(promotion: Any, user_ids: list[Any]) -> None:
    """v1 port: fan out push + email for a new promotion."""
    from app.notifications.tasks import (
        send_fcm_to_multiple_users,
        send_promotion_email,
    )

    send_fcm_to_multiple_users.delay(
        [str(uid) for uid in user_ids],
        "New Promotion!",
        f"{promotion.name} - {promotion.discount}% off",
        {"promotion_id": str(promotion.id), "type": "promotion"},
    )
    send_promotion_email.delay(str(promotion.id), [str(uid) for uid in user_ids])
