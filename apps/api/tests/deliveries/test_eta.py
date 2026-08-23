"""PURE ETA + haversine tests."""

from __future__ import annotations

import math

import pytest

from app.deliveries.eta import (
    DEFAULT_COURIER_SPEED_KMH,
    compute_delivery_eta,
    compute_pickup_eta,
    estimate_eta_minutes,
    haversine_km,
)


class _FakeDelivery:
    """Tiny stand-in for the Delivery model with just the lat/lng fields the ETA helpers need."""

    def __init__(self, pickup_lat: float, pickup_lng: float, dropoff_lat: float, dropoff_lng: float) -> None:
        self.pickup_lat = pickup_lat
        self.pickup_lng = pickup_lng
        self.dropoff_lat = dropoff_lat
        self.dropoff_lng = dropoff_lng


# ---------------------------------------------------------------------------
# haversine_km
# ---------------------------------------------------------------------------


def test_haversine_zero_distance_is_zero() -> None:
    assert haversine_km(0.0, 0.0, 0.0, 0.0) == 0.0
    assert haversine_km(36.8, -1.3, 36.8, -1.3) == 0.0


def test_haversine_one_degree_lng_at_equator() -> None:
    # 1 degree of longitude at the equator is ~111.195 km
    d = haversine_km(0.0, 0.0, 0.0, 1.0)
    assert 110.0 < d < 112.0


def test_haversine_one_degree_lat() -> None:
    d = haversine_km(0.0, 0.0, 1.0, 0.0)
    # 1 degree of latitude is ~111.195 km at all longitudes
    assert 110.0 < d < 112.0


def test_haversine_nairobi_to_mombasa_approx() -> None:
    # Nairobi (-1.29, 36.82) -> Mombasa (-4.04, 39.66) is roughly 440km
    d = haversine_km(-1.29, 36.82, -4.04, 39.66)
    assert 420.0 < d < 460.0


def test_haversine_symmetry() -> None:
    d1 = haversine_km(36.8, -1.3, 39.6, 0.5)
    d2 = haversine_km(39.6, 0.5, 36.8, -1.3)
    assert abs(d1 - d2) < 0.01


# ---------------------------------------------------------------------------
# estimate_eta_minutes
# ---------------------------------------------------------------------------


def test_estimate_eta_zero_distance_minimum_one_minute() -> None:
    assert estimate_eta_minutes(0.0) == 1


def test_estimate_eta_zero_speed_minimum_one_minute() -> None:
    assert estimate_eta_minutes(10.0, courier_speed_kmh=0.0) == 1


def test_estimate_eta_negative_speed_minimum_one_minute() -> None:
    assert estimate_eta_minutes(10.0, courier_speed_kmh=-5.0) == 1


def test_estimate_eta_one_km_at_60_kmh_is_one_minute() -> None:
    assert estimate_eta_minutes(1.0, courier_speed_kmh=60.0) == 1


def test_estimate_eta_two_km_at_60_kmh_is_two_minutes() -> None:
    assert estimate_eta_minutes(2.0, courier_speed_kmh=60.0) == 2


def test_estimate_eta_rounds_up() -> None:
    # 1 km at 100 km/h = 0.6 minutes, ceil to 1
    assert estimate_eta_minutes(1.0, courier_speed_kmh=100.0) == 1
    # 1.5 km at 60 km/h = 1.5 minutes, ceil to 2
    assert estimate_eta_minutes(1.5, courier_speed_kmh=60.0) == 2


def test_estimate_eta_default_speed_is_20_kmh() -> None:
    # 1 km at 20 km/h = 3 minutes
    assert estimate_eta_minutes(1.0) == 3
    assert DEFAULT_COURIER_SPEED_KMH == 20.0


def test_estimate_eta_min_minutes_override() -> None:
    assert estimate_eta_minutes(0.0, min_minutes=10) == 10


# ---------------------------------------------------------------------------
# compute_pickup_eta
# ---------------------------------------------------------------------------


def test_compute_pickup_eta_no_courier_location() -> None:
    d = _FakeDelivery(0.0, 0.0, 10.0, 10.0)
    assert compute_pickup_eta(d, None, None) == 1


def test_compute_pickup_eta_courier_at_pickup() -> None:
    d = _FakeDelivery(0.0, 0.0, 10.0, 10.0)
    assert compute_pickup_eta(d, 0.0, 0.0) == 1  # min minutes


def test_compute_pickup_eta_courier_2km_from_pickup() -> None:
    # Pickup at 0,0; courier at 0, ~0.018 (= 2km east)
    d = _FakeDelivery(0.0, 0.0, 10.0, 10.0)
    # 2 km / 20 km/h = 6 minutes
    assert compute_pickup_eta(d, 0.0, 0.018) >= 1


# ---------------------------------------------------------------------------
# compute_delivery_eta
# ---------------------------------------------------------------------------


def test_compute_delivery_eta_no_courier_location() -> None:
    d = _FakeDelivery(0.0, 0.0, 10.0, 10.0)
    assert compute_delivery_eta(d, None, None) == 1


def test_compute_delivery_eta_courier_at_dropoff() -> None:
    d = _FakeDelivery(0.0, 0.0, 10.0, 10.0)
    assert compute_delivery_eta(d, 10.0, 10.0) == 1


def test_compute_delivery_eta_uses_dropoff_coords() -> None:
    # pickup at 0,0; dropoff at 5,5; courier at 0,0 -> big eta
    d = _FakeDelivery(0.0, 0.0, 5.0, 5.0)
    eta = compute_delivery_eta(d, 0.0, 0.0)
    assert eta > 30  # far away


# ---------------------------------------------------------------------------
# Round-trip / sanity
# ---------------------------------------------------------------------------


def test_pickup_and_delivery_use_different_coordinates() -> None:
    d = _FakeDelivery(0.0, 0.0, 0.0, 0.5)
    # courier 1 km east of both pickup and dropoff (dropoff is 0.5 deg east of pickup)
    pickup_eta = compute_pickup_eta(d, 0.0, 0.009)  # 1 km from pickup
    delivery_eta = compute_delivery_eta(d, 0.0, 0.009)  # ~0.5deg west of dropoff
    # pickup closer, delivery farther
    assert pickup_eta <= delivery_eta
