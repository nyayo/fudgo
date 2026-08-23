"""PURE delivery state-machine tests."""

from __future__ import annotations

import pytest

from app.deliveries.enums import (
    ALLOWED_DELIVERY_TRANSITIONS,
    DeliveryStatus,
    LocationProvider,
    can_transition_delivery,
)


# ---------------------------------------------------------------------------
# can_transition_delivery
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("from_status", "to_status", "expected"),
    [
        # ASSIGNED
        (DeliveryStatus.ASSIGNED, DeliveryStatus.EN_ROUTE_PICKUP, True),
        (DeliveryStatus.ASSIGNED, DeliveryStatus.CANCELLED, True),
        (DeliveryStatus.ASSIGNED, DeliveryStatus.FAILED, True),
        (DeliveryStatus.ASSIGNED, DeliveryStatus.ARRIVED_AT_PICKUP, False),
        (DeliveryStatus.ASSIGNED, DeliveryStatus.PICKED_UP, False),
        (DeliveryStatus.ASSIGNED, DeliveryStatus.DELIVERED, False),
        # EN_ROUTE_PICKUP
        (DeliveryStatus.EN_ROUTE_PICKUP, DeliveryStatus.ARRIVED_AT_PICKUP, True),
        (DeliveryStatus.EN_ROUTE_PICKUP, DeliveryStatus.CANCELLED, True),
        (DeliveryStatus.EN_ROUTE_PICKUP, DeliveryStatus.FAILED, True),
        (DeliveryStatus.EN_ROUTE_PICKUP, DeliveryStatus.PICKED_UP, False),
        (DeliveryStatus.EN_ROUTE_PICKUP, DeliveryStatus.DELIVERED, False),
        # ARRIVED_AT_PICKUP
        (DeliveryStatus.ARRIVED_AT_PICKUP, DeliveryStatus.PICKED_UP, True),
        (DeliveryStatus.ARRIVED_AT_PICKUP, DeliveryStatus.CANCELLED, True),
        (DeliveryStatus.ARRIVED_AT_PICKUP, DeliveryStatus.FAILED, True),
        (DeliveryStatus.ARRIVED_AT_PICKUP, DeliveryStatus.EN_ROUTE_DELIVERY, False),
        # PICKED_UP
        (DeliveryStatus.PICKED_UP, DeliveryStatus.EN_ROUTE_DELIVERY, True),
        (DeliveryStatus.PICKED_UP, DeliveryStatus.FAILED, True),
        (DeliveryStatus.PICKED_UP, DeliveryStatus.DELIVERED, False),
        (DeliveryStatus.PICKED_UP, DeliveryStatus.CANCELLED, False),
        # EN_ROUTE_DELIVERY
        (DeliveryStatus.EN_ROUTE_DELIVERY, DeliveryStatus.DELIVERED, True),
        (DeliveryStatus.EN_ROUTE_DELIVERY, DeliveryStatus.FAILED, True),
        (DeliveryStatus.EN_ROUTE_DELIVERY, DeliveryStatus.PICKED_UP, False),
        # DELIVERED
        (DeliveryStatus.DELIVERED, DeliveryStatus.FAILED, False),
        (DeliveryStatus.DELIVERED, DeliveryStatus.CANCELLED, False),
        (DeliveryStatus.DELIVERED, DeliveryStatus.PICKED_UP, False),
        # FAILED
        (DeliveryStatus.FAILED, DeliveryStatus.PICKED_UP, False),
        (DeliveryStatus.FAILED, DeliveryStatus.DELIVERED, False),
        # CANCELLED
        (DeliveryStatus.CANCELLED, DeliveryStatus.PICKED_UP, False),
        (DeliveryStatus.CANCELLED, DeliveryStatus.DELIVERED, False),
    ],
)
def test_can_transition_delivery(
    from_status: DeliveryStatus, to_status: DeliveryStatus, expected: bool
) -> None:
    assert can_transition_delivery(from_status, to_status) is expected


def test_terminal_states_have_no_outgoing() -> None:
    assert ALLOWED_DELIVERY_TRANSITIONS[DeliveryStatus.DELIVERED] == set()
    assert ALLOWED_DELIVERY_TRANSITIONS[DeliveryStatus.FAILED] == set()
    assert ALLOWED_DELIVERY_TRANSITIONS[DeliveryStatus.CANCELLED] == set()


def test_assert_transition_delivery_raises_on_invalid() -> None:
    from app.deliveries.exceptions import DeliveryInvalidTransition
    from app.deliveries.service import assert_transition_delivery

    with pytest.raises(DeliveryInvalidTransition):
        assert_transition_delivery(DeliveryStatus.ASSIGNED, DeliveryStatus.DELIVERED)


def test_assert_transition_delivery_passes_on_valid() -> None:
    from app.deliveries.service import assert_transition_delivery

    assert_transition_delivery(DeliveryStatus.ASSIGNED, DeliveryStatus.EN_ROUTE_PICKUP)


def test_all_states_have_entries() -> None:
    """Sanity check: every enum value has a transition entry."""
    for status in DeliveryStatus:
        assert status in ALLOWED_DELIVERY_TRANSITIONS


# ---------------------------------------------------------------------------
# LocationProvider
# ---------------------------------------------------------------------------


def test_location_provider_values() -> None:
    assert LocationProvider.GPS.value == "gps"
    assert LocationProvider.NETWORK.value == "network"
    assert LocationProvider.MANUAL.value == "manual"
