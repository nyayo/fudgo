"""Tests for the pure compute_effective_price function."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

from app.restaurants.models import MenuItem, Promotion
from app.restaurants.service import compute_effective_price


def _promo(discount: float, *, hours_offset_start: int = -1, hours_offset_end: int = 1, is_active: bool = True) -> Promotion:
    now = datetime.now(UTC)
    return Promotion(
        id=uuid4(),
        restaurant_id=uuid4(),
        name="p",
        description="",
        discount=discount,
        start_date=now + timedelta(hours=hours_offset_start),
        end_date=now + timedelta(hours=hours_offset_end),
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


def test_no_promotions_returns_full_price() -> None:
    item = _item("1000.00")
    price, applied = compute_effective_price(item, [])
    assert price == Decimal("1000.00")
    assert applied is None


def test_single_active_promotion_applies() -> None:
    item = _item("1500.00")
    promo = _promo(20.0)
    price, applied = compute_effective_price(item, [promo])
    assert price == Decimal("1200.00")
    assert applied is promo


def test_inactive_promotion_ignored() -> None:
    item = _item("100.00")
    promo = _promo(50.0, is_active=False)
    price, applied = compute_effective_price(item, [promo])
    assert price == Decimal("100.00")
    assert applied is None


def test_highest_discount_wins() -> None:
    item = _item("1000.00")
    p20 = _promo(20.0)
    p30 = _promo(30.0)
    price, applied = compute_effective_price(item, [p20, p30])
    assert price == Decimal("700.00")
    assert applied is p30


def test_expired_promotion_ignored() -> None:
    """start in the past, end in the past -> not currently active."""
    item = _item("100.00")
    promo = _promo(50.0, hours_offset_start=-2, hours_offset_end=-1)
    price, applied = compute_effective_price(item, [promo])
    assert price == Decimal("100.00")
    assert applied is None


def test_at_time_pinned_to_past() -> None:
    """at_time=now; promotion ended yesterday -> ignored."""
    item = _item("100.00")
    yesterday = datetime.now(UTC) - timedelta(days=1)
    promo = Promotion(
        id=uuid4(),
        restaurant_id=uuid4(),
        name="p",
        description="",
        discount=50.0,
        start_date=yesterday - timedelta(hours=2),
        end_date=yesterday - timedelta(hours=1),
        is_active=True,
    )
    price, applied = compute_effective_price(item, [promo])
    assert price == Decimal("100.00")
    assert applied is None


def test_at_time_pinned_to_past_with_active_promo() -> None:
    item = _item("100.00")
    promo = Promotion(
        id=uuid4(),
        restaurant_id=uuid4(),
        name="p",
        description="",
        discount=25.0,
        start_date=datetime.now(UTC) - timedelta(hours=1),
        end_date=datetime.now(UTC) + timedelta(hours=1),
        is_active=True,
    )
    when = datetime.now(UTC) - timedelta(minutes=30)
    price, applied = compute_effective_price(item, [promo], at_time=when)
    assert price == Decimal("75.00")
    assert applied is promo
