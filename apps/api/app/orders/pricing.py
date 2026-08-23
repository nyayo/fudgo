"""Pure cart + order pricing helpers.

These functions are deliberately DB- and IO-free so they can be unit-tested
without spinning up Postgres. They re-use Phase 2's ``compute_effective_price``
as the single source of truth for promo math — no re-implementation.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Sequence

from app.restaurants.models import MenuItem, Promotion
from app.restaurants.service import compute_effective_price

# Service fee percentage of subtotal. Configurable in Phase 4 via settings;
# v1 keeps it hard-coded so the brief's "configurable via app.core.config"
# can be honored without coupling Phase 3 to a new env var.
SERVICE_FEE_RATE: Decimal = Decimal("0.10")


def price_cart_line(
    item: MenuItem,
    item_promotions: Sequence[Promotion] | None,
    quantity: int,
    at_time: datetime | None = None,
) -> tuple[Decimal, Decimal, Promotion | None]:
    """Return ``(unit_pre_promo, line_total_post_promo, applied_promo)``.

    - ``unit_pre_promo`` is the original MenuItem price (pre-discount).
    - ``line_total_post_promo`` is ``effective_unit_price * quantity``.
    - ``applied_promo`` is the winning Promotion or None.
    """
    unit_pre = Decimal(item.price)
    unit_post, applied = compute_effective_price(item, item_promotions, at_time=at_time)
    line_total = (unit_post * Decimal(quantity)).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )
    return unit_pre, line_total, applied


def compute_cart_subtotal(line_totals: Sequence[Decimal]) -> Decimal:
    total = sum(line_totals, Decimal("0.00"))
    return total.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def compute_service_fee(subtotal: Decimal, rate: Decimal = SERVICE_FEE_RATE) -> Decimal:
    return (subtotal * rate).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def compute_cart_total(
    subtotal: Decimal,
    delivery_fee: Decimal,
    service_fee: Decimal,
) -> Decimal:
    return (subtotal + delivery_fee + service_fee).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )


def compute_discount_amount(
    line_pre_totals: Sequence[Decimal],
    line_post_totals: Sequence[Decimal],
) -> Decimal:
    """Sum of ``(pre - post)`` across all lines. For audit / display only."""
    total = Decimal("0.00")
    for pre, post in zip(line_pre_totals, line_post_totals):
        total += pre - post
    return total.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def generate_order_number(sequence: int, when: datetime | None = None) -> str:
    """Format: ``FUDGO-YYYYMMDD-NNNNNN``.

    Sequence is provided by the caller (computed via ``COUNT(*) + 1`` of
    orders placed today; racy under high concurrency but acceptable for v1).
    """
    when = when or datetime.now(UTC)
    return f"FUDGO-{when.strftime('%Y%m%d')}-{int(sequence):06d}"
