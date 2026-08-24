"""Orders + payments + cart domain for the Fudgo platform.

Phase 3 slice. Public read filtering rules (verified by tests, not by
runtime guards alone):

- Restaurants: ``is_approved=True AND is_active=True`` -> 404, not 403
- Categories/items: ``is_active=True``
- Promotions: ``is_active=True AND start_date <= now < end_date``
"""

from __future__ import annotations

from enum import Enum


class OrderStatus(str, Enum):
    PENDING_PAYMENT = "pending_payment"  # NEW Phase 5: order created, awaiting payment webhook
    PLACED = "placed"
    CONFIRMED = "confirmed"
    PREPARING = "preparing"
    READY = "ready"
    PICKED_UP = "picked_up"
    ON_THE_WAY = "on_the_way"
    DELIVERED = "delivered"
    CANCELLED = "cancelled"


class PaymentStatus(str, Enum):
    PENDING = "pending"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    REFUNDED = "refunded"


class PaymentMethod(str, Enum):
    STUB = "stub"
    CARD = "card"
    MPESA = "mpesa"
    CASH = "cash"


# ---------------------------------------------------------------------------
# State machine
# ---------------------------------------------------------------------------

# Allowed transitions. CANCELLED is reachable from any pre-PICKED_UP state
# for restaurant, and from PLACED/CONFIRMED/PREPARING/READY for customer,
# and from PICKED_UP and back to PICKED_UP for courier (courier can cancel
# between accept and pickup only).
ALLOWED_TRANSITIONS: dict[OrderStatus, set[OrderStatus]] = {
    OrderStatus.PENDING_PAYMENT: {OrderStatus.PLACED, OrderStatus.CANCELLED},  # NEW Phase 5
    OrderStatus.PLACED: {
        OrderStatus.CONFIRMED,
        OrderStatus.CANCELLED,
    },
    OrderStatus.CONFIRMED: {
        OrderStatus.PREPARING,
        OrderStatus.CANCELLED,
    },
    OrderStatus.PREPARING: {
        OrderStatus.READY,
        OrderStatus.CANCELLED,
    },
    OrderStatus.READY: {
        OrderStatus.PICKED_UP,
        OrderStatus.CANCELLED,
    },
    OrderStatus.PICKED_UP: {
        OrderStatus.ON_THE_WAY,
        OrderStatus.DELIVERED,
    },
    OrderStatus.ON_THE_WAY: {OrderStatus.DELIVERED},
    OrderStatus.DELIVERED: set(),
    OrderStatus.CANCELLED: set(),
}


# Customer can cancel only before PREPARING.
CUSTOMER_CANCELLABLE_STATES: frozenset[OrderStatus] = frozenset(
    {OrderStatus.PLACED, OrderStatus.CONFIRMED}
)

# Restaurant can cancel any state before PICKED_UP.
RESTAURANT_CANCELLABLE_STATES: frozenset[OrderStatus] = frozenset(
    {OrderStatus.PLACED, OrderStatus.CONFIRMED, OrderStatus.PREPARING, OrderStatus.READY}
)

# Courier can cancel between accept and PICKED_UP. Since the courier only
# becomes attached to the order on the READY -> PICKED_UP transition, the
# window is effectively just PICKED_UP. We allow PICKED_UP and ON_THE_WAY
# here as a generous "before pickup" window.
COURIER_CANCELLABLE_STATES: frozenset[OrderStatus] = frozenset(
    {OrderStatus.PICKED_UP, OrderStatus.ON_THE_WAY}
)


def can_transition(from_status: OrderStatus, to_status: OrderStatus) -> bool:
    return to_status in ALLOWED_TRANSITIONS.get(from_status, set())
