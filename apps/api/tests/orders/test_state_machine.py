"""State-machine tests: can_transition() and the allowed-transitions table."""

from __future__ import annotations

import pytest

from app.orders.enums import (
    ALLOWED_TRANSITIONS,
    COURIER_CANCELLABLE_STATES,
    CUSTOMER_CANCELLABLE_STATES,
    RESTAURANT_CANCELLABLE_STATES,
    OrderStatus,
    can_transition,
)
from app.orders.exceptions import OrderInvalidTransition
from app.orders.service import transition_order, cancel_order
from app.db.session import AsyncSessionLocal
from app.orders.models import Order
from app.orders.enums import OrderStatus as _OS  # avoid linter complaining
import uuid


# ---------------------------------------------------------------------------
# can_transition
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("from_status", "to_status", "expected"),
    [
        (OrderStatus.PLACED, OrderStatus.CONFIRMED, True),
        (OrderStatus.PLACED, OrderStatus.CANCELLED, True),
        (OrderStatus.PLACED, OrderStatus.PREPARING, False),
        (OrderStatus.PLACED, OrderStatus.READY, False),
        (OrderStatus.PLACED, OrderStatus.PICKED_UP, False),
        (OrderStatus.PLACED, OrderStatus.DELIVERED, False),
        (OrderStatus.CONFIRMED, OrderStatus.PREPARING, True),
        (OrderStatus.CONFIRMED, OrderStatus.CANCELLED, True),
        (OrderStatus.CONFIRMED, OrderStatus.READY, False),
        (OrderStatus.PREPARING, OrderStatus.READY, True),
        (OrderStatus.PREPARING, OrderStatus.PICKED_UP, False),
        (OrderStatus.PREPARING, OrderStatus.CANCELLED, True),
        (OrderStatus.READY, OrderStatus.PICKED_UP, True),
        (OrderStatus.READY, OrderStatus.CANCELLED, True),
        (OrderStatus.READY, OrderStatus.DELIVERED, False),
        (OrderStatus.PICKED_UP, OrderStatus.ON_THE_WAY, True),
        (OrderStatus.PICKED_UP, OrderStatus.DELIVERED, True),
        (OrderStatus.PICKED_UP, OrderStatus.CANCELLED, False),
        (OrderStatus.ON_THE_WAY, OrderStatus.DELIVERED, True),
        (OrderStatus.DELIVERED, OrderStatus.READY, False),
        (OrderStatus.DELIVERED, OrderStatus.CANCELLED, False),
        (OrderStatus.CANCELLED, OrderStatus.PLACED, False),
        (OrderStatus.CANCELLED, OrderStatus.DELIVERED, False),
    ],
)
def test_can_transition(from_status: OrderStatus, to_status: OrderStatus, expected: bool) -> None:
    assert can_transition(from_status, to_status) is expected


def test_terminal_states_have_no_outgoing() -> None:
    assert ALLOWED_TRANSITIONS[OrderStatus.DELIVERED] == set()
    assert ALLOWED_TRANSITIONS[OrderStatus.CANCELLED] == set()


# ---------------------------------------------------------------------------
# Cancellation windows
# ---------------------------------------------------------------------------


def test_customer_can_cancel_before_preparing() -> None:
    assert OrderStatus.PLACED in CUSTOMER_CANCELLABLE_STATES
    assert OrderStatus.CONFIRMED in CUSTOMER_CANCELLABLE_STATES
    assert OrderStatus.PREPARING not in CUSTOMER_CANCELLABLE_STATES
    assert OrderStatus.DELIVERED not in CUSTOMER_CANCELLABLE_STATES


def test_restaurant_can_cancel_before_picked_up() -> None:
    assert OrderStatus.PLACED in RESTAURANT_CANCELLABLE_STATES
    assert OrderStatus.PREPARING in RESTAURANT_CANCELLABLE_STATES
    assert OrderStatus.READY in RESTAURANT_CANCELLABLE_STATES
    assert OrderStatus.PICKED_UP not in RESTAURANT_CANCELLABLE_STATES


def test_courier_can_cancel_before_picked_up() -> None:
    # Phase 5 correction: ALLOWED_TRANSITIONS has no PICKED_UP -> CANCELLED
    # edge (once the courier has the food, cancel must go via the
    # restaurant), so the courier cancel window is empty. See
    # COURIER_CANCELLABLE_STATES in app/orders/enums.py.
    assert OrderStatus.PICKED_UP not in COURIER_CANCELLABLE_STATES
    assert OrderStatus.ON_THE_WAY not in COURIER_CANCELLABLE_STATES
    assert OrderStatus.PLACED not in COURIER_CANCELLABLE_STATES
    assert OrderStatus.DELIVERED not in COURIER_CANCELLABLE_STATES
