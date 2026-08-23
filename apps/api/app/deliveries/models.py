"""Delivery + CourierLocation SQLModel tables (Phase 4)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import (
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Field, SQLModel

from app.deliveries.enums import DeliveryStatus, LocationProvider


def _now_factory() -> datetime:
    return datetime.now(UTC)


# Reusable columns -- mirror the pattern in app/orders/models.py (no
# SQLAlchemy ``Relationship`` with forward references; the service layer
# drives access via explicit queries).


class Delivery(SQLModel, table=True):
    __tablename__ = "deliveries"
    __table_args__ = (
        UniqueConstraint("order_id", name="uq_deliveries_order_id"),
        Index("ix_deliveries_courier_status", "courier_id", "status"),
        Index("ix_deliveries_status", "status"),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    order_id: uuid.UUID = Field(
        foreign_key="orders.id", nullable=False, index=True
    )
    courier_id: uuid.UUID | None = Field(
        default=None, foreign_key="courier_profiles.id", nullable=True, index=True
    )

    status: DeliveryStatus = Field(
        default=DeliveryStatus.ASSIGNED,
        sa_column=Column(
            String(32),
            nullable=False,
            server_default=DeliveryStatus.ASSIGNED.value,
            index=True,
        ),
    )

    pickup_address: str = Field(sa_column=Column(String(500), nullable=False))
    pickup_lat: float = Field(sa_column=Column(Float, nullable=False))
    pickup_lng: float = Field(sa_column=Column(Float, nullable=False))

    dropoff_address: str = Field(sa_column=Column(String(500), nullable=False))
    dropoff_lat: float = Field(sa_column=Column(Float, nullable=False))
    dropoff_lng: float = Field(sa_column=Column(Float, nullable=False))

    assigned_at: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    en_route_pickup_at: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    arrived_at_pickup_at: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    picked_up_at: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    en_route_delivery_at: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    delivered_at: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )

    proof_image_url: str | None = Field(
        default=None, sa_column=Column(String(500), nullable=True)
    )
    proof_notes: str | None = Field(
        default=None, sa_column=Column(Text, nullable=True)
    )

    failure_reason: str | None = Field(
        default=None, sa_column=Column(String(500), nullable=True)
    )
    cancelled_reason: str | None = Field(
        default=None, sa_column=Column(String(500), nullable=True)
    )

    created_at: datetime = Field(
        default_factory=_now_factory,
        sa_column=Column(
            DateTime(timezone=True),
            server_default=func.now(),
            nullable=False,
        ),
    )
    updated_at: datetime = Field(
        default_factory=_now_factory,
        sa_column=Column(
            DateTime(timezone=True),
            server_default=func.now(),
            onupdate=func.now(),
            nullable=False,
        ),
    )


class CourierLocation(SQLModel, table=True):
    __tablename__ = "courier_locations"
    __table_args__ = (
        Index(
            "ix_courier_locations_courier_recorded",
            "courier_id",
            "recorded_at",
        ),
        Index("ix_courier_locations_recorded", "recorded_at"),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    courier_id: uuid.UUID = Field(
        foreign_key="courier_profiles.id", nullable=False, index=True
    )
    location: Any = Field(
        sa_column=Column("location"),  # populated by migration op
    )
    heading_degrees: float | None = Field(
        default=None, sa_column=Column(Float, nullable=True)
    )
    speed_kmh: float | None = Field(
        default=None, sa_column=Column(Float, nullable=True)
    )
    accuracy_m: float | None = Field(
        default=None, sa_column=Column(Float, nullable=True)
    )
    battery_level: int | None = Field(
        default=None, sa_column=Column(Integer, nullable=True)
    )
    source: LocationProvider = Field(
        default=LocationProvider.GPS,
        sa_column=Column(String(16), nullable=False, server_default=LocationProvider.GPS.value),
    )
    recorded_at: datetime = Field(
        default_factory=_now_factory,
        sa_column=Column(
            DateTime(timezone=True),
            server_default=func.now(),
            nullable=False,
            index=True,
        ),
    )
