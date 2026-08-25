"""Phase 6: Payout + PayoutAttempt + AuditLog SQLModel tables."""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    Column,
    DateTime,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Field, SQLModel

from app.notifications.enums import (
    AuditLogAction,
    PayoutAttemptStatus,
    PayoutMethod,
    PayoutStatus,
)


class Payout(SQLModel, table=True):
    __tablename__ = "payouts"
    __table_args__ = (
        Index("ix_payouts_restaurant_status", "restaurant_id", "status"),
        Index("ix_payouts_courier_status", "courier_id", "status"),
        Index("ix_payouts_status_scheduled", "status", "scheduled_at"),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    # XOR: restaurant payout (order-linked) OR courier payout (delivery-linked)
    order_id: uuid.UUID | None = Field(
        default=None, foreign_key="orders.id", index=True, nullable=True
    )
    delivery_id: uuid.UUID | None = Field(
        default=None, foreign_key="deliveries.id", index=True, nullable=True
    )
    restaurant_id: uuid.UUID | None = Field(
        default=None, foreign_key="restaurant_profiles.id", index=True, nullable=True
    )
    courier_id: uuid.UUID | None = Field(
        default=None, foreign_key="courier_profiles.id", index=True, nullable=True
    )

    method: str = Field(
        default=PayoutMethod.MPESA_B2C.value,
        max_length=20,
        nullable=False,
    )
    status: PayoutStatus = Field(
        default=PayoutStatus.SCHEDULED,
        sa_column=Column(
            String(20),
            nullable=False,
            server_default=PayoutStatus.SCHEDULED.value,
            index=True,
        ),
    )

    gross_amount: Decimal = Field(
        sa_column=Column(Numeric(10, 2), nullable=False)
    )
    platform_fee: Decimal = Field(
        default=Decimal("0.00"), sa_column=Column(Numeric(10, 2), nullable=False)
    )
    net_amount: Decimal = Field(sa_column=Column(Numeric(10, 2), nullable=False))

    mpesa_phone_e164: str | None = Field(default=None, max_length=20, nullable=True)
    mpesa_occasion: str | None = Field(default=None, max_length=100, nullable=True)

    scheduled_at: datetime = Field(
        sa_column=Column(
            DateTime(timezone=True), server_default=func.now(), nullable=False
        )
    )
    processed_at: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    completed_at: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    failed_at: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    failure_reason: str | None = Field(
        default=None, max_length=500, nullable=True
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


class PayoutAttempt(SQLModel, table=True):
    __tablename__ = "payout_attempts"
    __table_args__ = (
        Index("ix_payout_attempts_payout", "payout_id"),
        Index("ix_payout_attempts_status", "status"),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    payout_id: uuid.UUID = Field(foreign_key="payouts.id", nullable=False)
    attempt_number: int = Field(default=1, nullable=False)
    status: PayoutAttemptStatus = Field(
        default=PayoutAttemptStatus.INITIATED,
        sa_column=Column(
            String(20),
            nullable=False,
            server_default=PayoutAttemptStatus.INITIATED.value,
        ),
    )

    mpesa_transaction_id: str | None = Field(
        default=None, max_length=200, nullable=True, index=True
    )
    mpesa_conversation_id: str | None = Field(
        default=None, max_length=200, nullable=True
    )
    request_payload: dict[str, Any] | None = Field(
        default=None, sa_column=Column(JSONB, nullable=True)
    )
    response_payload: dict[str, Any] | None = Field(
        default=None, sa_column=Column(JSONB, nullable=True)
    )
    error_code: str | None = Field(default=None, max_length=50, nullable=True)
    error_message: str | None = Field(default=None, max_length=500, nullable=True)

    initiated_at: datetime = Field(
        sa_column=Column(
            DateTime(timezone=True), server_default=func.now(), nullable=False
        )
    )
    completed_at: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    failed_at: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )


class AuditLog(SQLModel, table=True):
    __tablename__ = "audit_log"
    __table_args__ = (
        Index("ix_audit_log_actor_created", "actor_user_id", "created_at"),
        Index("ix_audit_log_action_target", "action", "target_type", "target_id"),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    actor_user_id: uuid.UUID = Field(
        foreign_key="users.id", index=True, nullable=False
    )
    action: AuditLogAction = Field(
        sa_column=Column(String(50), nullable=False),
    )
    target_type: str = Field(max_length=50, nullable=False)
    target_id: str = Field(max_length=100, nullable=False)
    details: dict[str, Any] = Field(
        default_factory=dict, sa_column=Column(JSONB, nullable=False)
    )
    ip_address: str | None = Field(default=None, max_length=64, nullable=True)
    user_agent: str | None = Field(default=None, max_length=500, nullable=True)
    created_at: datetime = Field(
        sa_column=Column(
            DateTime(timezone=True),
            server_default=func.now(),
            nullable=False,
            index=True,
        )
    )
