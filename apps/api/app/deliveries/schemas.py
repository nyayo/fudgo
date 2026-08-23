"""Pydantic schemas for the deliveries + courier-location domain."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.deliveries.enums import DeliveryStatus, LocationProvider


# --- request ---


class HeartbeatRequest(BaseModel):
    lat: float = Field(ge=-90.0, le=90.0)
    lng: float = Field(ge=-180.0, le=180.0)
    heading_degrees: float | None = Field(default=None, ge=0.0, lt=360.0)
    speed_kmh: float | None = Field(default=None, ge=0.0)
    accuracy_m: float | None = Field(default=None, ge=0.0)
    battery_level: int | None = Field(default=None, ge=0, le=100)
    is_available: bool = True
    source: LocationProvider = LocationProvider.GPS


class AvailabilityRequest(BaseModel):
    is_available: bool


class DeliveryTransitionRequest(BaseModel):
    note: str | None = Field(default=None, max_length=500)


class DeliveryFailRequest(BaseModel):
    reason: str = Field(min_length=1, max_length=500)


class DeliveryCancelRequest(BaseModel):
    reason: str | None = Field(default=None, max_length=500)


class DeliveryProofRequest(BaseModel):
    image_url: str | None = Field(default=None, max_length=500)
    notes: str | None = Field(default=None, max_length=500)


# --- response ---


class DeliveryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    order_id: UUID
    courier_id: UUID | None
    status: DeliveryStatus
    pickup_address: str
    pickup_lat: float
    pickup_lng: float
    dropoff_address: str
    dropoff_lat: float
    dropoff_lng: float
    assigned_at: datetime | None
    en_route_pickup_at: datetime | None
    arrived_at_pickup_at: datetime | None
    picked_up_at: datetime | None
    en_route_delivery_at: datetime | None
    delivered_at: datetime | None
    proof_image_url: str | None
    proof_notes: str | None
    failure_reason: str | None
    cancelled_reason: str | None
    created_at: datetime
    updated_at: datetime


class ETAResponse(BaseModel):
    pickup_eta_minutes: int
    delivery_eta_minutes: int
    distance_to_pickup_km: float
    distance_to_delivery_km: float
    courier_last_seen_at: datetime | None = None


class CourierLocationResponse(BaseModel):
    courier_id: UUID
    lat: float
    lng: float
    heading_degrees: float | None = None
    speed_kmh: float | None = None
    accuracy_m: float | None = None
    battery_level: int | None = None
    recorded_at: datetime
