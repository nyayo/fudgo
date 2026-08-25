"""Email template render tests (PURE)."""

from __future__ import annotations

import pytest

from app.notifications.email_templates import EmailTemplates


def test_order_confirmation_structure() -> None:
    t = EmailTemplates.get(
        "order_confirmation", order_number="FUDGO-20260825-000001", total="2250.00"
    )
    assert set(t) == {"subject", "plain", "html"}
    assert "FUDGO-20260825-000001" in t["subject"]
    assert "2250.00" in t["plain"]
    assert "<html" in t["html"]
    assert "FUDGO-20260825-000001" in t["html"]


def test_order_delivered_structure() -> None:
    t = EmailTemplates.get("order_delivered", order_number="ORD-9")
    assert "ORD-9" in t["subject"]
    assert "delivered" in t["plain"].lower()


def test_promotion_structure() -> None:
    t = EmailTemplates.get("promotion", promo_name="Mango Monday", discount=20)
    assert "20" in t["subject"]
    assert "Mango Monday" in t["html"]


def test_password_reset_contains_link() -> None:
    link = "https://fudgo.com/reset?token=x"
    t = EmailTemplates.get("password_reset", reset_link=link)
    assert link in t["plain"]
    assert link in t["html"]


def test_account_locked_structure() -> None:
    t = EmailTemplates.get("account_locked", reason="fraud review")
    assert "locked" in t["subject"].lower()
    assert "fraud review" in t["plain"]


def test_unknown_template_raises() -> None:
    with pytest.raises(ValueError):
        EmailTemplates.get("does_not_exist")


def test_all_five_templates_render() -> None:
    for name in (
        "order_confirmation",
        "order_delivered",
        "promotion",
        "password_reset",
        "account_locked",
    ):
        t = EmailTemplates.get(name)
        assert all(k in t for k in ("subject", "plain", "html"))
