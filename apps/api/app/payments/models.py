"""Phase 5 payment models: PaymentAttempt + PaymentWebhookEvent + Payment columns."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Field, SQLModel

from app.payments.enums import PaymentAttemptStatus, WebhookProvider


def _now_factory() -> datetime:
    return datetime.now(UTC)


class PaymentAttempt(SQLModel, table=True):
    __tablename__ = "payment_attempts"
    __table_args__ = (
        # UNIQUE on (payment_id, idempotency_key) — same client key + same
        # payment = same attempt. The (payment_id) and (status) indexes support
        # the "latest attempt for this payment" + "all PENDING attempts"
        # queries.
        UniqueConstraint(
            "payment_id", "idempotency_key",
            name="uq_payment_attempts_payment_idempotency_key",
        ),
        Index("ix_payment_attempts_payment", "payment_id"),
        Index("ix_payment_attempts_status", "status"),
        Index(
            "ix_payment_attempts_stripe_payment_intent",
            "stripe_payment_intent_id",
        ),
        Index(
            "ix_payment_attempts_mpesa_checkout_request",
            "mpesa_checkout_request_id",
        ),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    payment_id: uuid.UUID = Field(
        foreign_key="payments.id", nullable=False
    )
    attempt_number: int = Field(default=1, nullable=False)

    method: str = Field(default="stub", max_length=16, nullable=False)
    status: PaymentAttemptStatus = Field(
        default=PaymentAttemptStatus.INITIATED,
        sa_column=Column(
            String(32),
            nullable=False,
            server_default=PaymentAttemptStatus.INITIATED.value,
        ),
    )

    # Provider-specific identifiers
    stripe_payment_intent_id: str | None = Field(
        default=None, max_length=200, nullable=True
    )
    stripe_client_secret: str | None = Field(
        default=None, max_length=500, nullable=True
    )
    mpesa_checkout_request_id: str | None = Field(
        default=None, max_length=200, nullable=True
    )
    mpesa_merchant_request_id: str | None = Field(
        default=None, max_length=200, nullable=True
    )
    mpesa_phone_e164: str | None = Field(
        default=None, max_length=20, nullable=True
    )

    # Request payload sent to the provider (for audit/debug; sanitized).
    request_payload: dict[str, Any] | None = Field(
        default=None, sa_column=Column(JSONB, nullable=True)
    )

    succeeded_at: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    failed_at: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    failure_reason: str | None = Field(
        default=None, sa_column=Column(Text, nullable=True)
    )

    # Idempotency-Key from the client (also indexed via UniqueConstraint above).
    idempotency_key: str | None = Field(
        default=None, sa_column=Column(String(64), nullable=True)
    )

    created_at: datetime = Field(
        default_factory=_now_factory,
        sa_column=Column(
            DateTime(timezone=True), server_default=func.now(), nullable=False
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


class PaymentWebhookEvent(SQLModel, table=True):
    __tablename__ = "payment_webhook_events"
    __table_args__ = (
        UniqueConstraint(
            "provider", "event_id", name="uq_webhook_provider_event_id"
        ),
        Index("ix_payment_webhook_events_received_at", "received_at"),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    provider: WebhookProvider = Field(
        sa_column=Column(
            String(16),
            nullable=False,
            server_default=WebhookProvider.STRIPE.value,
        ),
    )
    event_id: str = Field(max_length=200, nullable=False)
    event_type: str = Field(max_length=100, nullable=False)
    payload: dict[str, Any] = Field(
        sa_column=Column(JSONB, nullable=False)
    )
    received_at: datetime = Field(
        default_factory=_now_factory,
        sa_column=Column(
            DateTime(timezone=True), server_default=func.now(), nullable=False
        ),
    )
    processed_at: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    error: str | None = Field(
        default=None, sa_column=Column(Text, nullable=True)
    )
