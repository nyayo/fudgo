"""State machine tests: OrderStatus.PENDING_PAYMENT transitions."""

from __future__ import annotations

import pytest

from app.orders.enums import ALLOWED_TRANSITIONS, OrderStatus, can_transition
from app.payments.enums import PaymentAttemptStatus


def test_pending_payment_to_placed_valid() -> None:
    assert can_transition(OrderStatus.PENDING_PAYMENT, OrderStatus.PLACED)


def test_pending_payment_to_cancelled_valid() -> None:
    assert can_transition(OrderStatus.PENDING_PAYMENT, OrderStatus.CANCELLED)


@pytest.mark.parametrize("to_status", [
    OrderStatus.CONFIRMED,
    OrderStatus.PREPARING,
    OrderStatus.READY,
    OrderStatus.PICKED_UP,
    OrderStatus.ON_THE_WAY,
    OrderStatus.DELIVERED,
])
def test_pending_payment_skipping_states_invalid(to_status: OrderStatus) -> None:
    assert not can_transition(OrderStatus.PENDING_PAYMENT, to_status)


def test_placed_back_to_pending_payment_invalid() -> None:
    """No going back from PLACED to PENDING_PAYMENT."""
    assert not can_transition(OrderStatus.PLACED, OrderStatus.PENDING_PAYMENT)


def test_pending_payment_in_allowed_transitions_table() -> None:
    assert OrderStatus.PENDING_PAYMENT in ALLOWED_TRANSITIONS
    assert ALLOWED_TRANSITIONS[OrderStatus.PENDING_PAYMENT] == {
        OrderStatus.PLACED,
        OrderStatus.CANCELLED,
    }


# ---------------------------------------------------------------------------
# PaymentAttemptStatus values
# ---------------------------------------------------------------------------


def test_payment_attempt_status_values() -> None:
    assert PaymentAttemptStatus.INITIATED.value == "initiated"
    assert PaymentAttemptStatus.REQUIRES_ACTION.value == "requires_action"
    assert PaymentAttemptStatus.SUCCEEDED.value == "succeeded"
    assert PaymentAttemptStatus.FAILED.value == "failed"
    assert PaymentAttemptStatus.CANCELLED.value == "cancelled"


def test_order_status_pending_payment_value() -> None:
    assert OrderStatus.PENDING_PAYMENT.value == "pending_payment"
