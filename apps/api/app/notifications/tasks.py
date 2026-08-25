"""Notification Celery tasks — direct ports of v1's users/tasks.py.

Task names + signatures match v1 exactly. All tasks are sync (Celery
workers) and use the Phase 5 sync session maker.
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import create_engine  # noqa: F401
from sqlalchemy.orm import Session

from app.core.celery_app import celery_app

logger = logging.getLogger(__name__)


def _session() -> Session:
    from app.db.sync_session import get_sync_session_maker

    maker = get_sync_session_maker()
    session: Session = maker()
    return session


# ---------------------------------------------------------------------------
# FCM
# ---------------------------------------------------------------------------


@celery_app.task(name="notifications.send_fcm_notification_admin")
def send_fcm_notification_admin(
    user_id: str,
    title: str,
    body: str,
    data: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """v1 port: send FCM to all active devices for a user, respecting prefs."""
    from app.notifications.firebase_client import send_fcm
    from app.users.models import Device, NotificationPreference, User

    with _session() as session:
        user = session.get(User, user_id)
        if not user:
            return {"error": "User not found"}
        prefs = (
            session.query(NotificationPreference)
            .filter_by(user_id=user_id)
            .first()
        )
        if prefs and not prefs.receive_push:
            return {"skipped": True, "reason": "Push disabled"}
        devices = (
            session.query(Device).filter_by(user_id=user_id, active=True).all()
        )
        success_count = 0
        failed_tokens: list[str] = []
        for device in devices:
            try:
                send_fcm(device.registration_id, title, body, data)
                success_count += 1
            except Exception as e:
                if "Unregistered" in str(type(e).__name__) or "Unregistered" in str(e):
                    device.active = False
                    failed_tokens.append(device.registration_id)
        session.commit()
        # In-app notification row (v2 addition; v1 kept these in orders app)
        _write_in_app_notification(session, user_id, title, body, data)
        return {"success_count": success_count, "failed_count": len(failed_tokens)}


def _write_in_app_notification(
    session: Session,
    user_id: str,
    title: str,
    body: str,
    data: dict[str, Any] | None,
) -> None:
    try:
        from app.notifications.models import Notification

        order_id = (data or {}).get("order_id")
        event_type = (data or {}).get("type", "order_update")
        redirect_url = f"/orders/{order_id}" if order_id else None
        session.add(
            Notification(
                user_id=user_id,
                event_type=str(event_type)[:50],
                message=f"{title}: {body}"[:2000],
                order_id=order_id,
                redirect_url=redirect_url[:500] if redirect_url else None,
            )
        )
        session.commit()
    except Exception as e:
        logger.warning(f"In-app notification write failed: {e}")
        session.rollback()


@celery_app.task(name="notifications.send_push_notification_to_user")
def send_push_notification_to_user(
    user_id: str,
    title: str,
    body: str,
    data: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """v1 port: same as send_fcm_notification_admin under the v1 name."""
    return send_fcm_notification_admin(user_id, title, body, data)


@celery_app.task(name="notifications.send_fcm_to_multiple_users")
def send_fcm_to_multiple_users(
    user_ids: list[Any],
    title: str,
    body: str,
    data: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """v1 port: fan-out to many users."""
    for uid in user_ids:
        send_fcm_notification_admin.delay(str(uid), title, body, data)
    return {"queued": len(user_ids)}


# ---------------------------------------------------------------------------
# Email
# ---------------------------------------------------------------------------


@celery_app.task(
    bind=True,
    max_retries=3,
    default_retry_delay=60,
    autoretry_for=(Exception,),
    name="notifications.send_email_task",
)
def send_email_task(self: Any, email_data: dict) -> dict[str, Any]:
    """v1 port: send email via Plunk with 3 retries."""
    from app.notifications.plunk_client import PlunkClient

    plunk = PlunkClient()
    if not plunk.is_configured:
        return {"skipped": True, "reason": "Plunk not configured"}
    success = plunk.send_email(email_data)
    if not success:
        raise self.retry(exc=Exception("Plunk send returned False"))
    return {"success": True, "to_email": email_data.get("to_email")}


@celery_app.task(
    bind=True,
    max_retries=3,
    default_retry_delay=60,
    autoretry_for=(Exception,),
    name="notifications.send_templated_email_task",
)
def send_templated_email_task(
    self: Any, to_email: str, template_type: str, template_kwargs: dict
) -> dict[str, Any]:
    """v1 port: render Jinja-style template, then send via Plunk."""
    from app.notifications.email_templates import EmailTemplates

    template_data = EmailTemplates.get(template_type, **template_kwargs)
    return send_email_task(  # type: ignore[return-value]
        {
            "to_email": to_email,
            "email_subject": template_data["subject"],
            "email_body": template_data["plain"],
            "email_html": template_data["html"],
            "email_type": "html",
        }
    )


@celery_app.task(name="notifications.send_order_confirmation_email")
def send_order_confirmation_email(order_id: str) -> dict[str, Any]:
    """v1 port: send order confirmation email to customer."""
    from app.orders.models import Order
    from app.users.models import NotificationPreference

    with _session() as session:
        order = session.get(Order, order_id)
        if not order:
            return {"skipped": True, "reason": "Order not found"}
        from app.users.models import CustomerProfile

        cp = (
            session.query(CustomerProfile)
            .filter_by(id=order.customer_id)  # type: ignore[call-overload]
            .first()
        )
        if cp is None:
            return {"skipped": True, "reason": "Customer profile missing"}
        prefs = (
            session.query(NotificationPreference)
            .filter_by(user_id=cp.user_id)
            .first()
        )
        if prefs and not prefs.receive_email:
            return {"skipped": True, "reason": "Email disabled"}
        user = session.get(__import__("app.users.models", fromlist=["User"]).User, cp.user_id)
        if user is None or not user.email:
            return {"skipped": True, "reason": "No email on file"}
        send_templated_email_task.delay(
            user.email,
            "order_confirmation",
            {
                "order_number": order.order_number,
                "total": str(order.total),
            },
        )
        return {"queued": True, "to": user.email}


@celery_app.task(name="notifications.send_order_delivered_email")
def send_order_delivered_email(order_id: str) -> dict[str, Any]:
    """v1 port: send order delivered email to customer."""
    from app.orders.models import Order
    from app.users.models import CustomerProfile, NotificationPreference, User

    with _session() as session:
        order = session.get(Order, order_id)
        if not order:
            return {"skipped": True}
        cp = (
            session.query(CustomerProfile)
            .filter_by(id=order.customer_id)  # type: ignore[call-overload]
            .first()
        )
        if cp is None:
            return {"skipped": True}
        prefs = (
            session.query(NotificationPreference)
            .filter_by(user_id=cp.user_id)
            .first()
        )
        if prefs and not prefs.receive_email:
            return {"skipped": True, "reason": "Email disabled"}
        user = session.get(User, cp.user_id)
        if user is None or not user.email:
            return {"skipped": True}
        send_templated_email_task.delay(
            user.email,
            "order_delivered",
            {"order_number": order.order_number},
        )
        return {"queued": True, "to": user.email}


@celery_app.task(name="notifications.send_promotion_email")
def send_promotion_email(promotion_id: str, user_ids: list[Any]) -> dict[str, Any]:
    """v1 port: send promotion email to many users, respecting opt-outs."""
    from app.restaurants.models import Promotion
    from app.users.models import NotificationPreference, User

    with _session() as session:
        promo = session.get(Promotion, promotion_id)
        if not promo:
            return {"error": "Promotion not found"}
        queued = 0
        for uid in user_ids:
            user = session.get(User, uid)
            if not (user and user.email):
                continue
            prefs = (
                session.query(NotificationPreference)
                .filter_by(user_id=uid)  # type: ignore[call-overload]
                .first()
            )
            if prefs and not prefs.promotions_and_offers:
                continue
            send_templated_email_task.delay(
                user.email,
                "promotion",
                {"promo_name": promo.name, "discount": str(promo.discount)},
            )
            queued += 1
        return {"queued": queued}


# ---------------------------------------------------------------------------
# Restaurant notifications
# ---------------------------------------------------------------------------


@celery_app.task(name="notifications.notify_restaurant_new_order")
def notify_restaurant_new_order(order_id: str) -> dict[str, Any]:
    """v1 port: notify restaurant staff of a new order."""
    from app.orders.models import Order
    from app.users.models import RestaurantStaffProfile

    with _session() as session:
        order = session.get(Order, order_id)
        if not order:
            return {"error": "Order not found"}
        staff = (
            session.query(RestaurantStaffProfile)
            .filter_by(restaurant_id=order.restaurant_id, is_active=True)
            .all()
        )
        for s in staff:
            send_push_notification_to_user.delay(
                str(s.user_id),
                f"New Order #{order.order_number}",
                "A new order has been placed.",
                {"order_id": str(order.id), "type": "new_order"},
            )
        return {"notified": len(staff)}


@celery_app.task(name="notifications.notify_restaurant_order_status")
def notify_restaurant_order_status(
    order_id: str, old_status: str, new_status: str
) -> dict[str, Any]:
    """v1 port: notify restaurant staff of a status change."""
    from app.orders.models import Order
    from app.users.models import RestaurantStaffProfile

    with _session() as session:
        order = session.get(Order, order_id)
        if not order:
            return {"error": "Order not found"}
        staff = (
            session.query(RestaurantStaffProfile)
            .filter_by(restaurant_id=order.restaurant_id, is_active=True)
            .all()
        )
        for s in staff:
            send_push_notification_to_user.delay(
                str(s.user_id),
                f"Order #{order.order_number} -> {new_status}",
                f"Order status changed from {old_status} to {new_status}.",
                {
                    "order_id": str(order.id),
                    "type": "order_update",
                    "new_status": new_status,
                },
            )
        return {"notified": len(staff)}


@celery_app.task(name="notifications.notify_restaurant_order_cancelled")
def notify_restaurant_order_cancelled(
    order_id: str, reason: str | None = None
) -> dict[str, Any]:
    """v1 port: notify restaurant staff of a cancellation."""
    from app.orders.models import Order
    from app.users.models import RestaurantStaffProfile

    with _session() as session:
        order = session.get(Order, order_id)
        if not order:
            return {"error": "Order not found"}
        staff = (
            session.query(RestaurantStaffProfile)
            .filter_by(restaurant_id=order.restaurant_id, is_active=True)
            .all()
        )
        for s in staff:
            send_push_notification_to_user.delay(
                str(s.user_id),
                f"Order #{order.order_number} Cancelled",
                f"Reason: {reason or 'Not specified'}",
                {"order_id": str(order.id), "type": "order_cancelled"},
            )
        return {"notified": len(staff)}


# ---------------------------------------------------------------------------
# SMS
# ---------------------------------------------------------------------------


@celery_app.task(
    bind=True,
    max_retries=3,
    default_retry_delay=60,
    autoretry_for=(Exception,),
    name="notifications.send_sms_otp_task",
)
def send_sms_otp_task(self: Any, phone: str, otp: str) -> dict[str, Any]:
    """v1 port: send OTP via TextBee."""
    from app.notifications.textbee_client import TextBeeClient

    textbee = TextBeeClient()
    if not textbee.is_configured:
        return {"skipped": True, "reason": "TextBee not configured"}
    message = (
        f"Your Fudgo verification code is: {otp}. Valid for 10 minutes."
    )
    success = textbee.send_sms(phone, message)
    if not success:
        raise self.retry(exc=Exception("TextBee send returned False"))
    return {"success": True, "phone": phone}


@celery_app.task(
    bind=True,
    max_retries=3,
    default_retry_delay=60,
    autoretry_for=(Exception,),
    name="notifications.send_sms_task",
)
def send_sms_task(self: Any, phone: str, message: str) -> dict[str, Any]:
    """v1 port: generic SMS via TextBee."""
    from app.notifications.textbee_client import TextBeeClient

    textbee = TextBeeClient()
    if not textbee.is_configured:
        return {"skipped": True, "reason": "TextBee not configured"}
    success = textbee.send_sms(phone, message)
    if not success:
        raise self.retry(exc=Exception("TextBee send returned False"))
    return {"success": True, "phone": phone}
