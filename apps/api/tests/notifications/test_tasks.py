"""Notification task tests (Celery eager mode, mocked providers)."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pytest


# NOTE: sync Celery-eager tests here must NOT carry pytest.mark.asyncio.


# ---------------------------------------------------------------------------
# send_email_task / send_templated_email_task
# ---------------------------------------------------------------------------


def test_send_email_task_success() -> None:
    from app.notifications.tasks import send_email_task

    with patch(
        "app.notifications.plunk_client.PlunkClient.send_email",
        return_value=True,
    ) as m:
        result = send_email_task.apply(
            args=[{"to_email": "a@b.com", "email_subject": "s", "email_body": "b"}]
        ).get()
    assert result == {"success": True, "to_email": "a@b.com"}
    m.assert_called_once()


def test_send_email_task_skips_unconfigured() -> None:
    from app.core.config import get_settings
    from app.notifications.tasks import send_email_task

    get_settings().PLUNK_API_KEY = ""
    with patch("requests.post") as mock:
        result = send_email_task.apply(
            args=[{"to_email": "a@b.com", "email_subject": "s", "email_body": "b"}]
        ).get()
        mock.assert_not_called()
    assert result == {"skipped": True, "reason": "Plunk not configured"}


def test_send_templated_email_renders_then_sends() -> None:
    from app.core.config import get_settings
    from app.notifications.tasks import send_templated_email_task

    get_settings().PLUNK_API_KEY = "pk_test_123"
    with patch(
        "app.notifications.plunk_client.PlunkClient.send_email",
        return_value=True,
    ) as m:
        result = send_templated_email_task.apply(
            args=["a@b.com", "order_confirmation",
                  {"order_number": "ORD-1", "total": "100.00"}]
        ).get()
    assert result["success"] is True
    sent = m.call_args.args[0]
    assert "<html" in sent["email_html"]
    assert "ORD-1" in sent["email_subject"]


# ---------------------------------------------------------------------------
# SMS tasks
# ---------------------------------------------------------------------------


def test_send_sms_otp_formats_message() -> None:
    from app.notifications.tasks import send_sms_otp_task

    with patch(
        "app.notifications.textbee_client.TextBeeClient.is_configured",
        new_callable=lambda: property(lambda self: True),
    ), patch(
        "app.notifications.textbee_client.TextBeeClient.send_sms",
        return_value=True,
    ) as m:
        result = send_sms_otp_task.apply(args=["+254711", "123456"]).get()
    assert result["success"] is True
    msg = m.call_args.args[1]
    assert "123456" in msg and "10 minutes" in msg


def test_send_sms_task_generic() -> None:
    from app.notifications.tasks import send_sms_task

    with patch(
        "app.notifications.textbee_client.TextBeeClient.is_configured",
        new_callable=lambda: property(lambda self: True),
    ), patch(
        "app.notifications.textbee_client.TextBeeClient.send_sms",
        return_value=True,
    ) as m:
        result = send_sms_task.apply(args=["+254711", "hello"]).get()
    assert result == {"success": True, "phone": "+254711"}
    assert m.call_args.args == ("+254711", "hello")


# ---------------------------------------------------------------------------
# Helpers + transaction hooks (delay calls asserted)
# ---------------------------------------------------------------------------


class _FakeOrder:
    id = "o-1"
    order_number = "ORD-1"

    class customer:  # type: ignore[no-untyped-def]
        user: Any = None


def test_helper_send_order_notification() -> None:
    from app.notifications.helpers import send_order_notification

    order = MagicMock()
    order.id = "o-1"
    order.order_number = "ORD-1"
    user = MagicMock()
    user.id = "u-1"
    with patch(
        "app.notifications.tasks.send_push_notification_to_user.delay"
    ) as d:
        send_order_notification(user, "Delivered", order)
    assert d.call_args.args[0] == "u-1"
    assert "Delivered" in d.call_args.args[1]
    assert d.call_args.args[3]["order_id"] == "o-1"


def test_helper_notify_new_promotion_fans_out() -> None:
    from app.notifications.helpers import notify_new_promotion

    promo = MagicMock()
    promo.id = "p-1"
    promo.name = "Mango"
    promo.discount = 20
    with patch(
        "app.notifications.tasks.send_fcm_to_multiple_users.delay"
    ) as fcm, patch(
        "app.notifications.tasks.send_promotion_email.delay"
    ) as em:
        notify_new_promotion(promo, ["u1", "u2"])
    assert fcm.call_args.args[0] == ["u1", "u2"]
    assert em.call_args.args[0] == "p-1"


def test_hook_on_order_status_changed_delivered() -> None:
    from app.notifications.transaction_hooks import on_order_status_changed

    order = MagicMock()
    order.id = "o-9"
    order.customer.user = None  # no customer user attached -> skip push only
    with patch(
        "app.notifications.tasks.notify_restaurant_order_status.delay"
    ) as st, patch(
        "app.notifications.tasks.send_order_delivered_email.delay"
    ) as em:
        on_order_status_changed(order, "on_the_way", "delivered")
    em.assert_called_once_with("o-9")
    st.assert_called_once()


def test_hook_on_order_status_changed_cancelled_includes_reason() -> None:
    from app.notifications.transaction_hooks import on_order_status_changed

    order = MagicMock()
    order.id = "o-9"
    order.customer.user = None
    with patch(
        "app.notifications.tasks.notify_restaurant_order_cancelled.delay"
    ) as cancel:
        on_order_status_changed(order, "placed", "cancelled", reason="oops")
    cancel.assert_called_once_with("o-9", reason="oops")


def test_hook_on_order_placed_fires_two() -> None:
    from app.notifications.transaction_hooks import on_order_placed

    order = MagicMock()
    order.id = "o-2"
    with patch(
        "app.notifications.tasks.send_order_confirmation_email.delay"
    ) as e1, patch(
        "app.notifications.tasks.notify_restaurant_new_order.delay"
    ) as e2:
        on_order_placed(order)
    e1.assert_called_once_with("o-2")
    e2.assert_called_once_with("o-2")
