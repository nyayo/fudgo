"""Phase 3: cart + orders + payments + order_status_history SQLModel tables.

Carts are 1:1 with ``customer_profiles.id``. There is no separate "active"
flag: a cart exists iff the customer has not checked out. Checkout deletes
the cart (cascade clears cart_items). Adding an item to a missing cart
creates a new one.

Order items are immutable snapshots — every value needed to render the
order later (name, prices, promotion name + discount percent) is captured
at order time. The FKs to ``menu_items`` and ``promotions`` are kept for
data-integrity only; reads use the snapshot fields.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    JSON,
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
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy import Enum as SAEnum
from sqlmodel import Field, Relationship, SQLModel

from app.orders.enums import OrderStatus, PaymentMethod, PaymentStatus


# ---------------------------------------------------------------------------
# Cart
# ---------------------------------------------------------------------------


class Cart(SQLModel, table=True):
    __tablename__ = "carts"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    customer_id: uuid.UUID = Field(
        foreign_key="customer_profiles.id", unique=True, index=True, nullable=False
    )

    def __getattr__(self, name: str) -> object:
        # The service layer must call _cart_with_items() to read cart contents.
        # This __getattr__ exists to keep older Pydantic attribute lookups
        # from raising AttributeError; new code should not rely on it.
        if name == "items":
            return []
        raise AttributeError(name)


class CartItem(SQLModel, table=True):
    __tablename__ = "cart_items"
    __table_args__ = (
        UniqueConstraint("cart_id", "menu_item_id", name="uq_cart_item_cart_menu"),
        Index("ix_cart_items_menu_item_id", "menu_item_id"),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    cart_id: uuid.UUID = Field(foreign_key="carts.id", nullable=False, index=True)
    menu_item_id: uuid.UUID = Field(foreign_key="menu_items.id", nullable=False)
    quantity: int = Field(default=1, nullable=False)
    special_instructions: str | None = Field(
        default=None, sa_column=Column(Text, nullable=True)
    )
    created_at: datetime = Field(
        sa_column=Column(
            DateTime(timezone=True), server_default=func.now(), nullable=False
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


# ---------------------------------------------------------------------------
# Order
# ---------------------------------------------------------------------------


# PostgreSQL enum types — lowercase, no underscores (Phase 1 convention).
_orderstatus_pg = SAEnum(
    OrderStatus,
    name="orderstatus",
    values_callable=lambda enum: [m.value for m in enum],
    create_type=True,
)
_paymentstatus_pg = SAEnum(
    PaymentStatus,
    name="paymentstatus",
    values_callable=lambda enum: [m.value for m in enum],
    create_type=True,
)
_paymentmethod_pg = SAEnum(
    PaymentMethod,
    name="paymentmethod",
    values_callable=lambda enum: [m.value for m in enum],
    create_type=True,
)


class Order(SQLModel, table=True):
    __tablename__ = "orders"
    __table_args__ = (
        Index("ix_orders_status_placed", "status", "placed_at"),
        Index("ix_orders_restaurant_status", "restaurant_id", "status"),
        Index("ix_orders_courier", "courier_id"),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    order_number: str = Field(
        max_length=32, unique=True, index=True, nullable=False
    )
    customer_id: uuid.UUID = Field(
        foreign_key="customer_profiles.id", nullable=False, index=True
    )
    restaurant_id: uuid.UUID = Field(
        foreign_key="restaurant_profiles.id", nullable=False, index=True
    )
    delivery_address_id: uuid.UUID = Field(
        foreign_key="addresses.id", nullable=False
    )
    courier_id: uuid.UUID | None = Field(
        default=None, foreign_key="courier_profiles.id", nullable=True
    )

    # Pricing snapshot.
    subtotal: Decimal = Field(
        sa_column=Column(Numeric(10, 2), nullable=False), default=Decimal("0.00")
    )
    delivery_fee: Decimal = Field(
        sa_column=Column(Numeric(10, 2), nullable=False), default=Decimal("0.00")
    )
    service_fee: Decimal = Field(
        sa_column=Column(Numeric(10, 2), nullable=False), default=Decimal("0.00")
    )
    total_discount_amount: Decimal = Field(
        sa_column=Column(Numeric(10, 2), nullable=False), default=Decimal("0.00")
    )
    total: Decimal = Field(
        sa_column=Column(Numeric(10, 2), nullable=False), default=Decimal("0.00")
    )

    status: OrderStatus = Field(
        sa_column=Column(_orderstatus_pg, nullable=False, server_default=OrderStatus.PLACED.value),
        default=OrderStatus.PLACED,
    )

    # Idempotency key. Indexed; nullable (most orders won't have one in tests).
    idempotency_key: str | None = Field(
        default=None,
        sa_column=Column(String(64), unique=True, nullable=True),
    )

    cancellation_reason: str | None = Field(
        default=None, sa_column=Column(Text, nullable=True)
    )
    cancelled_by: uuid.UUID | None = Field(
        default=None, foreign_key="users.id", nullable=True
    )

    # Status timestamps.
    placed_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    )
    confirmed_at: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    preparing_at: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    ready_at: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    picked_up_at: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    delivered_at: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    cancelled_at: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    estimated_delivery_at: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )

    # No SQLAlchemy relationships — use explicit joins in the service.
    # Adding Relationship(back_populates=...) with forward-reference types
    # triggers SQLAlchemy mapper errors; the service already drives all
    # access via raw select() and join() calls.


class OrderItem(SQLModel, table=True):
    __tablename__ = "order_items"
    __table_args__ = (Index("ix_order_items_order_id", "order_id"),)

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    order_id: uuid.UUID = Field(foreign_key="orders.id", nullable=False)
    menu_item_id: uuid.UUID = Field(foreign_key="menu_items.id", nullable=False)
    name_snapshot: str = Field(max_length=200, nullable=False)
    unit_price_snapshot: Decimal = Field(
        sa_column=Column(Numeric(10, 2), nullable=False)
    )
    effective_unit_price_snapshot: Decimal = Field(
        sa_column=Column(Numeric(10, 2), nullable=False)
    )
    applied_promotion_id: uuid.UUID | None = Field(default=None, nullable=True)
    applied_promotion_name_snapshot: str | None = Field(
        default=None, sa_column=Column(String(255), nullable=True)
    )
    applied_promotion_discount_snapshot: float | None = Field(default=None, nullable=True)
    quantity: int = Field(sa_column=Column(Integer, nullable=False))
    line_subtotal: Decimal = Field(sa_column=Column(Numeric(10, 2), nullable=False))
    special_instructions: str | None = Field(
        default=None, sa_column=Column(Text, nullable=True)
    )


class OrderStatusHistory(SQLModel, table=True):
    __tablename__ = "order_status_history"
    __table_args__ = (Index("ix_osh_order_changed", "order_id", "changed_at"),)

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    order_id: uuid.UUID = Field(foreign_key="orders.id", nullable=False)
    from_status: OrderStatus | None = Field(
        default=None,
        sa_column=Column(_orderstatus_pg, nullable=True),
    )
    to_status: OrderStatus = Field(
        sa_column=Column(_orderstatus_pg, nullable=False)
    )
    changed_by_user_id: uuid.UUID | None = Field(
        default=None, foreign_key="users.id", nullable=True
    )
    changed_by_role: str = Field(sa_column=Column(String(20), nullable=False))
    note: str | None = Field(default=None, sa_column=Column(Text, nullable=True))
    changed_at: datetime = Field(
        sa_column=Column(
            DateTime(timezone=True), server_default=func.now(), nullable=False
        )
    )


# ---------------------------------------------------------------------------
# Payment
# ---------------------------------------------------------------------------


class Payment(SQLModel, table=True):
    __tablename__ = "payments"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    order_id: uuid.UUID = Field(
        foreign_key="orders.id", unique=True, index=True, nullable=False
    )
    method: PaymentMethod = Field(
        sa_column=Column(
            _paymentmethod_pg, nullable=False, server_default=PaymentMethod.STUB.value
        ),
        default=PaymentMethod.STUB,
    )
    status: PaymentStatus = Field(
        sa_column=Column(
            _paymentstatus_pg, nullable=False, server_default=PaymentStatus.PENDING.value
        ),
        default=PaymentStatus.PENDING,
    )
    amount: Decimal = Field(sa_column=Column(Numeric(10, 2), nullable=False))
    external_reference: str | None = Field(
        default=None, sa_column=Column(String(200), nullable=True)
    )
    failure_reason: str | None = Field(
        default=None, sa_column=Column(Text, nullable=True)
    )
    created_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    )
    succeeded_at: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    failed_at: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    refunded_at: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
