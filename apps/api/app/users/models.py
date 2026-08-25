"""User-domain tables: users, per-role profiles, addresses, preferences, devices."""

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from geoalchemy2 import Geography
from sqlalchemy import Column, DateTime, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Field, Relationship, SQLModel

from app.users.enums import (
    AuthProvider,
    DevicePlatform,
    StaffRole,
    UserType,
    VehicleType,
)


def geog_point(nullable: bool = True, **kwargs: Any) -> Column[Any]:
    """Geography POINT srid=4326 column helper (meter-based distances, v1 parity)."""
    return Column(Geography(geometry_type="POINT", srid=4326), nullable=nullable, **kwargs)


class User(SQLModel, table=True):
    __tablename__ = "users"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    email: str | None = Field(default=None, unique=True, index=True, nullable=True)
    phone: str | None = Field(default=None, unique=True, index=True, nullable=True)
    username: str = Field(unique=True, index=True, nullable=False)
    first_name: str = Field(default="", nullable=False)
    last_name: str = Field(default="", nullable=False)
    user_type: UserType = Field(nullable=False, index=True)
    auth_provider: AuthProvider = Field(default=AuthProvider.email, nullable=False, index=True)
    is_verified: bool = Field(default=False, nullable=False, index=True)
    is_admin: bool = Field(default=False, nullable=False, index=True)
    is_active: bool = Field(default=True, nullable=False)
    is_staff: bool = Field(default=False, nullable=False)
    is_superuser: bool = Field(default=False, nullable=False)
    google_id: str | None = Field(default=None, unique=True, nullable=True)
    password_hash: str | None = Field(default=None, nullable=True)
    last_login: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    created_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    )
    updated_at: datetime = Field(
        sa_column=Column(
            DateTime(timezone=True),
            server_default=func.now(),
            onupdate=func.now(),
            nullable=False,
        )
    )


class CustomerProfile(SQLModel, table=True):
    __tablename__ = "customer_profiles"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    user_id: uuid.UUID = Field(foreign_key="users.id", unique=True, index=True, nullable=False)
    current_location: Any | None = Field(default=None, sa_column=geog_point(nullable=True))
    date_of_birth: date | None = Field(default=None, nullable=True)
    order_stats: dict[str, Any] = Field(
        default_factory=dict, sa_column=Column(JSONB, nullable=False, server_default="{}")
    )
    # Phase 8: dietary preferences + allergens (validated against
    # dietary_tags.slug on write; preferences exclude is_allergen tags).
    dietary_preferences: list[Any] = Field(
        default_factory=list, sa_column=Column(JSONB, nullable=False, server_default="[]")
    )
    allergens: list[Any] = Field(
        default_factory=list, sa_column=Column(JSONB, nullable=False, server_default="[]")
    )


class CourierProfile(SQLModel, table=True):
    __tablename__ = "courier_profiles"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    user_id: uuid.UUID = Field(foreign_key="users.id", unique=True, index=True, nullable=False)
    vehicle_type: VehicleType = Field(nullable=False)
    license_number: str | None = Field(default=None, nullable=True)
    is_available: bool = Field(default=True, nullable=False, index=True)
    is_approved: bool = Field(default=False, nullable=False, index=True)
    current_location: Any | None = Field(default=None, sa_column=geog_point(nullable=True))
    performance_stats: dict[str, Any] = Field(
        default_factory=dict, sa_column=Column(JSONB, nullable=False, server_default="{}")
    )
    rating: Decimal = Field(default=Decimal("0"), nullable=False)
    rating_count: int = Field(default=0, nullable=False)
    total_deliveries: int = Field(default=0, nullable=False, index=True)
    earnings_balance: Decimal = Field(default=Decimal("0"), nullable=False)
    last_heartbeat_at: datetime | None = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True), nullable=True, index=True),
    )


class RestaurantProfile(SQLModel, table=True):
    __tablename__ = "restaurant_profiles"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    user_id: uuid.UUID = Field(foreign_key="users.id", unique=True, index=True, nullable=False)
    restaurant_name: str = Field(nullable=False)
    business_license: str = Field(unique=True, nullable=False)
    address: str = Field(nullable=False)
    location: Any = Field(sa_column=geog_point(nullable=False))
    opening_hours: dict[str, Any] = Field(
        default_factory=dict, sa_column=Column(JSONB, nullable=False, server_default="{}")
    )
    rating: Decimal = Field(default=Decimal("0"), nullable=False, index=True)
    rating_count: int = Field(default=0, nullable=False)
    is_approved: bool = Field(default=False, nullable=False)
    is_active: bool = Field(default=True, nullable=False)
    # Phase 3: delivery configuration
    delivery_fee: Decimal = Field(
        default=Decimal("0.00"), max_digits=10, decimal_places=2, nullable=False
    )
    delivery_radius_km: float = Field(default=5.0, nullable=False)
    min_order_amount: Decimal = Field(
        default=Decimal("0.00"), max_digits=10, decimal_places=2, nullable=False
    )


class RestaurantStaffProfile(SQLModel, table=True):
    __tablename__ = "restaurant_staff_profiles"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    user_id: uuid.UUID = Field(foreign_key="users.id", unique=True, index=True, nullable=False)
    restaurant_id: uuid.UUID = Field(
        foreign_key="restaurant_profiles.id", nullable=False, index=True
    )
    role: StaffRole = Field(nullable=False)
    is_active: bool = Field(default=True, nullable=False)
    date_joined: datetime = Field(
        sa_column=Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    )


class Address(SQLModel, table=True):
    __tablename__ = "addresses"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    user_id: uuid.UUID = Field(foreign_key="users.id", index=True, nullable=False)
    label: str = Field(nullable=False)
    street: str = Field(nullable=False)
    city: str = Field(nullable=False)
    phone: str = Field(nullable=False)
    location: Any = Field(sa_column=geog_point(nullable=False))
    created_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    )


class NotificationPreference(SQLModel, table=True):
    __tablename__ = "notification_preferences"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    user_id: uuid.UUID = Field(foreign_key="users.id", unique=True, index=True, nullable=False)
    receive_push: bool = Field(default=True, nullable=False)
    receive_email: bool = Field(default=True, nullable=False)
    promotions_and_offers: bool = Field(default=True, nullable=False)
    new_restaurants: bool = Field(default=True, nullable=False)
    review_reminders: bool = Field(default=True, nullable=False)


class Device(SQLModel, table=True):
    __tablename__ = "devices"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    user_id: uuid.UUID = Field(foreign_key="users.id", index=True, nullable=False)
    registration_id: str = Field(sa_column=Column(Text, nullable=False, index=True))
    platform: DevicePlatform = Field(nullable=False)
    active: bool = Field(default=True, nullable=False)
    created_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    )
    updated_at: datetime = Field(
        sa_column=Column(
            DateTime(timezone=True),
            server_default=func.now(),
            onupdate=func.now(),
            nullable=False,
        )
    )
