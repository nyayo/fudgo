"""Payout fee math tests (PURE)."""

from __future__ import annotations

from decimal import Decimal

from app.payouts.pricing import (
    compute_courier_net,
    compute_platform_fee,
    compute_restaurant_net,
)


def test_platform_fee_15pct() -> None:
    assert compute_platform_fee(Decimal("1000.00"), 0.15) == Decimal("150.00")


def test_platform_fee_rounding_half_up() -> None:
    # 100.05 * 0.15 = 15.0075 -> 15.01
    assert compute_platform_fee(Decimal("100.05"), 0.15) == Decimal("15.01")


def test_restaurant_net() -> None:
    gross = Decimal("2250.00")
    net = compute_restaurant_net(gross, 0.15)
    assert net == Decimal("1912.50")
    assert net + compute_platform_fee(gross, 0.15) == gross


def test_courier_net_10pct_of_delivery_fee() -> None:
    assert compute_courier_net(Decimal("50.00"), 0.10) == Decimal("5.00")


def test_zero_amounts() -> None:
    assert compute_restaurant_net(Decimal("0.00"), 0.15) == Decimal("0.00")
    assert compute_courier_net(Decimal("0.00"), 0.10) == Decimal("0.00")
