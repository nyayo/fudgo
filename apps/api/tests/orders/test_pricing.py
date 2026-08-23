"""Pure pricing tests for Phase 3. No DB, no FastAPI."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest

from app.orders.pricing import (
    compute_cart_subtotal,
    compute_cart_total,
    compute_discount_amount,
    compute_service_fee,
    generate_order_number,
    price_cart_line,
)
from app.restaurants.models import MenuItem, Promotion


def _promo(
    discount: float,
    *,
    start_offset: int = -1,
    end_offset: int = 1,
    is_active: bool = True,
) -> Promotion:
    now = datetime.now(UTC)
    return Promotion(
        id=uuid4(),
        restaurant_id=uuid4(),
        name="p",
        description="",
        discount=discount,
        start_date=now + timedelta(hours=start_offset),
        end_date=now + timedelta(hours=end_offset),
        is_active=is_active,
    )


def _item(price: str) -> MenuItem:
    return MenuItem(
        id=uuid4(),
        restaurant_id=uuid4(),
        category_id=uuid4(),
        title="x",
        description="",
        price=Decimal(price),
    )


# ---------------------------------------------------------------------------
# price_cart_line
# ---------------------------------------------------------------------------


def test_price_cart_line_no_promo() -> None:
    item = _item("1000.00")
    unit_pre, line_total, applied = price_cart_line(item, [], 3)
    assert unit_pre == Decimal("1000.00")
    assert line_total == Decimal("3000.00")
    assert applied is None


def test_price_cart_line_with_promo() -> None:
    item = _item("1500.00")
    promo = _promo(20.0)
    unit_pre, line_total, applied = price_cart_line(item, [promo], 2)
    assert unit_pre == Decimal("1500.00")
    assert line_total == Decimal("2400.00")
    assert applied is promo


def test_price_cart_line_quantity_one() -> None:
    item = _item("100.00")
    _, line_total, _ = price_cart_line(item, [], 1)
    assert line_total == Decimal("100.00")


def test_price_cart_line_inactive_promo_ignored() -> None:
    item = _item("100.00")
    promo = _promo(50.0, is_active=False)
    _, line_total, applied = price_cart_line(item, [promo], 1)
    assert line_total == Decimal("100.00")
    assert applied is None


# ---------------------------------------------------------------------------
# compute_cart_subtotal
# ---------------------------------------------------------------------------


def test_compute_cart_subtotal_empty() -> None:
    assert compute_cart_subtotal([]) == Decimal("0.00")


def test_compute_cart_subtotal_sums() -> None:
    assert compute_cart_subtotal(
        [Decimal("10.00"), Decimal("20.00"), Decimal("30.00")]
    ) == Decimal("60.00")


def test_compute_cart_subtotal_quantizes() -> None:
    # 0.1 + 0.2 = 0.30 (not 0.30000000000000004)
    assert compute_cart_subtotal([Decimal("0.10"), Decimal("0.20")]) == Decimal("0.30")


# ---------------------------------------------------------------------------
# compute_service_fee
# ---------------------------------------------------------------------------


def test_compute_service_fee_default_rate() -> None:
    assert compute_service_fee(Decimal("1000.00")) == Decimal("100.00")


def test_compute_service_fee_zero_subtotal() -> None:
    assert compute_service_fee(Decimal("0.00")) == Decimal("0.00")


def test_compute_service_fee_custom_rate() -> None:
    assert compute_service_fee(Decimal("100.00"), rate=Decimal("0.05")) == Decimal("5.00")


# ---------------------------------------------------------------------------
# compute_cart_total
# ---------------------------------------------------------------------------


def test_compute_cart_total_components() -> None:
    total = compute_cart_total(
        subtotal=Decimal("1000.00"),
        delivery_fee=Decimal("50.00"),
        service_fee=Decimal("100.00"),
    )
    assert total == Decimal("1150.00")


# ---------------------------------------------------------------------------
# compute_discount_amount
# ---------------------------------------------------------------------------


def test_compute_discount_amount_zero_when_no_discount() -> None:
    pre = [Decimal("100.00"), Decimal("200.00")]
    post = [Decimal("100.00"), Decimal("200.00")]
    assert compute_discount_amount(pre, post) == Decimal("0.00")


def test_compute_discount_amount_sums_diff() -> None:
    pre = [Decimal("100.00"), Decimal("200.00")]
    post = [Decimal("80.00"), Decimal("180.00")]
    assert compute_discount_amount(pre, post) == Decimal("40.00")


def test_compute_discount_amount_empty() -> None:
    assert compute_discount_amount([], []) == Decimal("0.00")


# ---------------------------------------------------------------------------
# generate_order_number
# ---------------------------------------------------------------------------


def test_generate_order_number_format() -> None:
    when = datetime(2026, 8, 23, 10, 30, 0, tzinfo=UTC)
    num = generate_order_number(sequence=42, when=when)
    assert num == "FUDGO-20260823-000042"


def test_generate_order_number_pads_to_six() -> None:
    when = datetime(2026, 1, 1, tzinfo=UTC)
    num = generate_order_number(sequence=1, when=when)
    assert num.endswith("-000001")
    num2 = generate_order_number(sequence=123456, when=when)
    assert num2.endswith("-123456")


def test_generate_order_number_uses_now_when_no_when() -> None:
    num = generate_order_number(sequence=7)
    # Should look like FUDGO-YYYYMMDD-000007
    parts = num.split("-")
    assert len(parts) == 3
    assert len(parts[1]) == 8 and parts[1].isdigit()
    assert parts[2] == "000007"
