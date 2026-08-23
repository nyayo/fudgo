"""Restaurant, Promotion, MenuCategory, MenuItem models.

All tables: id UUID PK default uuid_generate_v4(), created_at timestamptz
default now(), updated_at where applicable. PostGIS is used for the
restaurant profile's ``location`` (already on users.RestaurantProfile);
this module adds the marketing/menu-side tables.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import Column, DateTime, ForeignKey, Index, Table, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlmodel import Field, SQLModel

from app.users.models import RestaurantProfile, User


# ---------------------------------------------------------------------------
# M2M association table
# ---------------------------------------------------------------------------

menu_item_promotions = Table(
    "menu_item_promotions",
    SQLModel.metadata,
    Column("item_id", PG_UUID(as_uuid=True), ForeignKey("menu_items.id", ondelete="CASCADE"), primary_key=True),
    Column("promotion_id", PG_UUID(as_uuid=True), ForeignKey("promotions.id", ondelete="CASCADE"), primary_key=True),
)


# ---------------------------------------------------------------------------
# Enums (postgresql names: lowercase, no underscores, per Phase 1 precedent)
# ---------------------------------------------------------------------------

DISCOUNT_TYPES = ("percentage",)
VEHICLE_KINDS = ("menu_item", "menu_category", "promotion")


# ---------------------------------------------------------------------------
# Promotion
# ---------------------------------------------------------------------------


class Promotion(SQLModel, table=True):
    __tablename__ = "promotions"
    __table_args__ = (
        Index("ix_promotions_restaurant_active", "restaurant_id", "is_active"),
        Index("ix_promotions_dates", "start_date", "end_date"),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    restaurant_id: uuid.UUID = Field(
        foreign_key="restaurant_profiles.id", nullable=False, index=True
    )
    name: str = Field(max_length=255, nullable=False)
    description: str = Field(max_length=225, default="", nullable=False)
    discount: float = Field(nullable=False)
    banner_url: str | None = Field(default=None, nullable=True)
    start_date: datetime = Field(
        sa_column=Column(DateTime(timezone=True), nullable=False)
    )
    end_date: datetime = Field(
        sa_column=Column(DateTime(timezone=True), nullable=False)
    )
    is_active: bool = Field(default=True, nullable=False)
    created_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    )


# ---------------------------------------------------------------------------
# MenuCategory
# ---------------------------------------------------------------------------


class MenuCategory(SQLModel, table=True):
    __tablename__ = "menu_categories"
    __table_args__ = (
        UniqueConstraint("restaurant_id", "name", name="uq_menu_categories_restaurant_name"),
        Index("ix_menu_categories_restaurant_position", "restaurant_id", "position"),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    restaurant_id: uuid.UUID = Field(
        foreign_key="restaurant_profiles.id", nullable=False, index=True
    )
    name: str = Field(max_length=255, nullable=False)
    description: str = Field(default="", nullable=False)
    position: int = Field(default=0, nullable=False)
    is_active: bool = Field(default=True, nullable=False)
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


class MenuCategoryImage(SQLModel, table=True):
    __tablename__ = "menu_category_images"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    category_id: uuid.UUID = Field(
        foreign_key="menu_categories.id", ondelete="CASCADE", nullable=False, index=True
    )
    image_url: str = Field(nullable=False)
    alt_text: str = Field(default="", nullable=False)
    created_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    )


# ---------------------------------------------------------------------------
# MenuItem
# ---------------------------------------------------------------------------


class MenuItem(SQLModel, table=True):
    __tablename__ = "menu_items"
    __table_args__ = (
        UniqueConstraint("restaurant_id", "title", name="uq_menu_items_restaurant_title"),
        Index("ix_menu_items_category_id", "category_id"),
        Index("ix_menu_items_restaurant_available", "restaurant_id", "is_available"),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    restaurant_id: uuid.UUID = Field(
        foreign_key="restaurant_profiles.id", nullable=False, index=True
    )
    category_id: uuid.UUID = Field(
        foreign_key="menu_categories.id", ondelete="CASCADE", nullable=False
    )
    title: str = Field(max_length=255, nullable=False)
    description: str = Field(default="", nullable=False)
    price: Decimal = Field(default=Decimal("0.00"), nullable=False, max_digits=10, decimal_places=2)
    is_available: bool = Field(default=True, nullable=False, index=True)
    is_featured: bool = Field(default=False, nullable=False, index=True)
    prep_time_minutes: int | None = Field(default=None, nullable=True)
    allergens: str = Field(default="", nullable=False)
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


class MenuItemImage(SQLModel, table=True):
    __tablename__ = "menu_item_images"
    __table_args__ = (
        Index("ix_menu_item_images_item_position", "menu_item_id", "position"),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    menu_item_id: uuid.UUID = Field(
        foreign_key="menu_items.id", ondelete="CASCADE", nullable=False, index=True
    )
    image_url: str = Field(nullable=False)
    alt_text: str = Field(default="", nullable=False)
    position: int = Field(default=0, nullable=False)
    created_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    )
