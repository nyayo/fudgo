"""Payout fee math — PURE functions."""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal


def compute_platform_fee(gross: Decimal, percent: float) -> Decimal:
    return (gross * Decimal(str(percent))).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )


def compute_restaurant_net(gross: Decimal, platform_fee_percent: float) -> Decimal:
    """Restaurant receives order.total minus the platform cut."""
    fee = compute_platform_fee(gross, platform_fee_percent)
    return (gross - fee).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def compute_courier_net(delivery_fee: Decimal, courier_percent: float) -> Decimal:
    """Courier receives a percentage of the delivery fee (platform keeps rest)."""
    net = delivery_fee * Decimal(str(courier_percent))
    return net.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
