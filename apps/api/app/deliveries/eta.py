"""PURE ETA + haversine helpers.

No DB. No IO. Pure functions so they can be unit-tested without
spinning up Postgres.
"""

from __future__ import annotations

import math
from datetime import datetime
from typing import Any

# Defaults match the brief's "configurable via app.core.config" stub.
DEFAULT_COURIER_SPEED_KMH: float = 20.0
EARTH_RADIUS_KM: float = 6371.0088


def haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Great-circle distance in kilometres."""
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lambda = math.radians(lng2 - lng1)
    a = (
        math.sin(d_phi / 2.0) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2.0) ** 2
    )
    c = 2.0 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))
    return EARTH_RADIUS_KM * c


def estimate_eta_minutes(
    distance_km: float,
    courier_speed_kmh: float = DEFAULT_COURIER_SPEED_KMH,
    *,
    min_minutes: int = 1,
) -> int:
    """Convert ``distance_km`` at ``courier_speed_kmh`` into ETA minutes.

    Guards against zero / negative speed by returning ``min_minutes``.
    """
    if distance_km <= 0:
        return min_minutes
    if courier_speed_kmh <= 0:
        return min_minutes
    minutes = (distance_km / courier_speed_kmh) * 60.0
    return max(min_minutes, int(math.ceil(minutes)))


def _delivery_pickup_coords(delivery: Any) -> tuple[float, float]:
    return (float(delivery.pickup_lat), float(delivery.pickup_lng))


def _delivery_dropoff_coords(delivery: Any) -> tuple[float, float]:
    return (float(delivery.dropoff_lat), float(delivery.dropoff_lng))


def compute_pickup_eta(
    delivery: Any,
    courier_lat: float | None,
    courier_lng: float | None,
    *,
    courier_speed_kmh: float = DEFAULT_COURIER_SPEED_KMH,
) -> int:
    """Courier -> restaurant pickup. Returns >=1 minute even at 0 km."""
    if courier_lat is None or courier_lng is None:
        return 1
    plat, plng = _delivery_pickup_coords(delivery)
    dist = haversine_km(courier_lat, courier_lng, plat, plng)
    return estimate_eta_minutes(dist, courier_speed_kmh)


def compute_delivery_eta(
    delivery: Any,
    courier_lat: float | None,
    courier_lng: float | None,
    *,
    courier_speed_kmh: float = DEFAULT_COURIER_SPEED_KMH,
) -> int:
    """Courier -> customer drop-off."""
    if courier_lat is None or courier_lng is None:
        return 1
    dlat, dlng = _delivery_dropoff_coords(delivery)
    dist = haversine_km(courier_lat, courier_lng, dlat, dlng)
    return estimate_eta_minutes(dist, courier_speed_kmh)


def latest_recorded_at(
    recorded_at: datetime | None, fallback: datetime | None = None
) -> datetime | None:
    return recorded_at or fallback
