"""Delivery-domain enums + state machine.

State machine:

    ASSIGNED -> EN_ROUTE_PICKUP -> ARRIVED_AT_PICKUP -> PICKED_UP
                                                       -> EN_ROUTE_DELIVERY -> DELIVERED
    Any non-terminal -> CANCELLED
    Any non-terminal -> FAILED

Terminal: DELIVERED, FAILED, CANCELLED.
"""

from __future__ import annotations

from enum import Enum


class DeliveryStatus(str, Enum):
    ASSIGNED = "assigned"
    EN_ROUTE_PICKUP = "en_route_pickup"
    ARRIVED_AT_PICKUP = "arrived_at_pickup"
    PICKED_UP = "picked_up"
    EN_ROUTE_DELIVERY = "en_route_delivery"
    DELIVERED = "delivered"
    FAILED = "failed"
    CANCELLED = "cancelled"


ALLOWED_DELIVERY_TRANSITIONS: dict[DeliveryStatus, set[DeliveryStatus]] = {
    DeliveryStatus.ASSIGNED: {
        DeliveryStatus.EN_ROUTE_PICKUP,
        DeliveryStatus.CANCELLED,
        DeliveryStatus.FAILED,
    },
    DeliveryStatus.EN_ROUTE_PICKUP: {
        DeliveryStatus.ARRIVED_AT_PICKUP,
        DeliveryStatus.CANCELLED,
        DeliveryStatus.FAILED,
    },
    DeliveryStatus.ARRIVED_AT_PICKUP: {
        DeliveryStatus.PICKED_UP,
        DeliveryStatus.CANCELLED,
        DeliveryStatus.FAILED,
    },
    DeliveryStatus.PICKED_UP: {
        DeliveryStatus.EN_ROUTE_DELIVERY,
        DeliveryStatus.FAILED,
    },
    DeliveryStatus.EN_ROUTE_DELIVERY: {
        DeliveryStatus.DELIVERED,
        DeliveryStatus.FAILED,
    },
    DeliveryStatus.DELIVERED: set(),
    DeliveryStatus.FAILED: set(),
    DeliveryStatus.CANCELLED: set(),
}


class LocationProvider(str, Enum):
    GPS = "gps"
    NETWORK = "network"
    MANUAL = "manual"


def can_transition_delivery(
    from_status: DeliveryStatus, to_status: DeliveryStatus
) -> bool:
    return to_status in ALLOWED_DELIVERY_TRANSITIONS.get(from_status, set())
