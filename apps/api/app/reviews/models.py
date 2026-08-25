"""Phase 8 discovery models: taxonomy, reviews, helpful votes, favorites."""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID as PG_UUID
from sqlalchemy import Table
from sqlmodel import Field, SQLModel


# ---------------------------------------------------------------------------
# Taxonomy M2M tables (declared early so metadata ordering works)
# ---------------------------------------------------------------------------

restaurant_cuisines = Table(
    "restaurant_cuisines",
    SQLModel.metadata,
    Column(
        "restaurant_id",
        PG_UUID(as_uuid=True),
        ForeignKey("restaurant_profiles.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column(
        "cuisine_id",
        PG_UUID(as_uuid=True),
        ForeignKey("cuisines.id", ondelete="CASCADE"),
        primary_key=True,
    ),
)

menu_item_dietary_tags = Table(
    "menu_item_dietary_tags",
    SQLModel.metadata,
    Column(
        "menu_item_id",
        PG_UUID(as_uuid=True),
        ForeignKey("menu_items.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column(
        "dietary_tag_id",
        PG_UUID(as_uuid=True),
        ForeignKey("dietary_tags.id", ondelete="CASCADE"),
        primary_key=True,
    ),
)

customer_favorite_restaurants = Table(
    "customer_favorite_restaurants",
    SQLModel.metadata,
    Column(
        "customer_id",
        PG_UUID(as_uuid=True),
        ForeignKey("customer_profiles.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column(
        "restaurant_id",
        PG_UUID(as_uuid=True),
        ForeignKey("restaurant_profiles.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column(
        "added_at",
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    ),
)

customer_favorite_menu_items = Table(
    "customer_favorite_menu_items",
    SQLModel.metadata,
    Column(
        "customer_id",
        PG_UUID(as_uuid=True),
        ForeignKey("customer_profiles.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column(
        "menu_item_id",
        PG_UUID(as_uuid=True),
        ForeignKey("menu_items.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column(
        "added_at",
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    ),
)


class Cuisine(SQLModel, table=True):
    __tablename__ = "cuisines"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    slug: str = Field(max_length=50, unique=True, index=True)
    name: str = Field(max_length=100, nullable=False)
    icon_url: str | None = Field(default=None, max_length=500, nullable=True)
    display_order: int = Field(default=0, nullable=False)
    is_active: bool = Field(default=True, nullable=False)
    created_at: datetime = Field(
        sa_column=Column(
            DateTime(timezone=True), server_default=func.now(), nullable=False
        )
    )


class DietaryTag(SQLModel, table=True):
    __tablename__ = "dietary_tags"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    slug: str = Field(max_length=50, unique=True, index=True)
    name: str = Field(max_length=100, nullable=False)
    icon_url: str | None = Field(default=None, max_length=500, nullable=True)
    is_allergen: bool = Field(default=False, nullable=False)
    is_active: bool = Field(default=True, nullable=False)
    created_at: datetime = Field(
        sa_column=Column(
            DateTime(timezone=True), server_default=func.now(), nullable=False
        )
    )


def _review_common() -> dict[str, Any]:
    return {}


class RestaurantReview(SQLModel, table=True):
    __tablename__ = "restaurant_reviews"
    __table_args__ = (
        UniqueConstraint(
            "customer_id",
            "restaurant_id",
            name="uq_restaurant_review_customer_restaurant",
        ),
        Index(
            "ix_restaurant_reviews_restaurant_created",
            "restaurant_id",
            "created_at",
        ),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    customer_id: uuid.UUID = Field(foreign_key="customer_profiles.id", nullable=False)
    restaurant_id: uuid.UUID = Field(
        foreign_key="restaurant_profiles.id", nullable=False
    )
    order_id: uuid.UUID = Field(foreign_key="orders.id", nullable=False)

    rating: int = Field(nullable=False)
    comment: str | None = Field(
        default=None, sa_column=Column(Text, nullable=True)
    )
    photo_urls: list[Any] = Field(
        default_factory=list,
        sa_column=Column(JSONB, nullable=False, server_default="[]"),
    )

    response: str | None = Field(
        default=None, sa_column=Column(Text, nullable=True)
    )
    response_at: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    responder_user_id: uuid.UUID | None = Field(
        default=None, foreign_key="users.id", nullable=True
    )

    is_hidden: bool = Field(default=False, nullable=False, index=True)
    hidden_by_user_id: uuid.UUID | None = Field(
        default=None, foreign_key="users.id", nullable=True
    )
    hidden_reason: str | None = Field(
        default=None, max_length=500, nullable=True
    )

    created_at: datetime = Field(
        sa_column=Column(
            DateTime(timezone=True),
            server_default=func.now(),
            nullable=False,
            index=True,
        )
    )
    updated_at: datetime = Field(
        sa_column=Column(
            DateTime(timezone=True),
            server_default=func.now(),
            onupdate=func.now(),
            nullable=False,
        )
    )


class MenuItemReview(SQLModel, table=True):
    __tablename__ = "menu_item_reviews"
    __table_args__ = (
        UniqueConstraint(
            "customer_id",
            "menu_item_id",
            name="uq_menu_item_review_customer_menu_item",
        ),
        Index(
            "ix_menu_item_reviews_menu_item_created",
            "menu_item_id",
            "created_at",
        ),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    customer_id: uuid.UUID = Field(foreign_key="customer_profiles.id", nullable=False)
    menu_item_id: uuid.UUID = Field(foreign_key="menu_items.id", nullable=False)
    order_id: uuid.UUID = Field(foreign_key="orders.id", nullable=False)

    rating: int = Field(nullable=False)
    comment: str | None = Field(
        default=None, sa_column=Column(Text, nullable=True)
    )
    photo_urls: list[Any] = Field(
        default_factory=list,
        sa_column=Column(JSONB, nullable=False, server_default="[]"),
    )
    is_hidden: bool = Field(default=False, nullable=False, index=True)
    hidden_by_user_id: uuid.UUID | None = Field(
        default=None, foreign_key="users.id", nullable=True
    )
    hidden_reason: str | None = Field(
        default=None, max_length=500, nullable=True
    )
    created_at: datetime = Field(
        sa_column=Column(
            DateTime(timezone=True),
            server_default=func.now(),
            nullable=False,
            index=True,
        )
    )
    updated_at: datetime = Field(
        sa_column=Column(
            DateTime(timezone=True),
            server_default=func.now(),
            onupdate=func.now(),
            nullable=False,
        )
    )


class CourierReview(SQLModel, table=True):
    __tablename__ = "courier_reviews"
    __table_args__ = (
        UniqueConstraint(
            "customer_id", "delivery_id", name="uq_courier_review_customer_delivery"
        ),
        Index("ix_courier_reviews_courier_created", "courier_id", "created_at"),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    customer_id: uuid.UUID = Field(foreign_key="customer_profiles.id", nullable=False)
    courier_id: uuid.UUID = Field(foreign_key="courier_profiles.id", nullable=False)
    delivery_id: uuid.UUID = Field(foreign_key="deliveries.id", nullable=False)
    order_id: uuid.UUID = Field(foreign_key="orders.id", nullable=False)

    rating: int = Field(nullable=False)
    comment: str | None = Field(
        default=None, sa_column=Column(Text, nullable=True)
    )
    is_hidden: bool = Field(default=False, nullable=False, index=True)
    hidden_by_user_id: uuid.UUID | None = Field(
        default=None, foreign_key="users.id", nullable=True
    )
    hidden_reason: str | None = Field(
        default=None, max_length=500, nullable=True
    )
    created_at: datetime = Field(
        sa_column=Column(
            DateTime(timezone=True),
            server_default=func.now(),
            nullable=False,
            index=True,
        )
    )
    updated_at: datetime = Field(
        sa_column=Column(
            DateTime(timezone=True),
            server_default=func.now(),
            onupdate=func.now(),
            nullable=False,
        )
    )


class ReviewHelpfulVote(SQLModel, table=True):
    __tablename__ = "review_helpful_votes"
    __table_args__ = (
        UniqueConstraint(
            "review_id", "user_id", "review_type", name="uq_review_helpful_vote"
        ),
        Index("ix_review_helpful_votes_review", "review_id", "review_type"),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    user_id: uuid.UUID = Field(foreign_key="users.id", nullable=False)
    review_id: uuid.UUID = Field(nullable=False)  # polymorphic FK
    review_type: str = Field(max_length=20, nullable=False)
    created_at: datetime = Field(
        sa_column=Column(
            DateTime(timezone=True), server_default=func.now(), nullable=False
        )
    )
