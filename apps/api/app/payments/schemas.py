"""Pydantic v2 request/response schemas for the payments domain."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.orders.enums import PaymentMethod, PaymentStatus
from app.payments.enums import PaymentAttemptStatus, WebhookProvider


# --- requests ---


class InitiatePaymentRequest(BaseModel):
    method: Literal["card", "mpesa"]  # STUB and CASH not exposed
    phone: str | None = Field(
        default=None,
        max_length=20,
        description="E.164 phone number; required when method=mpesa",
    )


class RefundRequest(BaseModel):
    """No body for v1: full refund only."""


# --- responses ---


class PaymentAttemptResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    payment_id: UUID
    attempt_number: int
    method: str
    status: PaymentAttemptStatus
    stripe_payment_intent_id: str | None
    stripe_client_secret: str | None
    mpesa_checkout_request_id: str | None
    mpesa_merchant_request_id: str | None
    mpesa_phone_e164: str | None
    succeeded_at: datetime | None
    failed_at: datetime | None
    failure_reason: str | None
    idempotency_key: str | None
    created_at: datetime
    updated_at: datetime


class PaymentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    order_id: UUID
    method: PaymentMethod
    status: PaymentStatus
    amount: str  # Decimal as string for client-side safety
    currency: str
    external_reference: str | None
    failure_reason: str | None
    created_at: datetime
    succeeded_at: datetime | None
    failed_at: datetime | None
    refunded_at: datetime | None


class InitiatePaymentResponse(BaseModel):
    """Response to POST /orders/{id}/pay."""
    payment: PaymentResponse
    attempt: PaymentAttemptResponse


class OrderPaymentStatusResponse(BaseModel):
    payment: PaymentResponse
    latest_attempt: PaymentAttemptResponse | None


class WebhookAck(BaseModel):
    """Internal acknowledgment shape (not in OpenAPI — webhooks return 200 OK)."""
    received: bool = True


class WebhookProviderInfo(BaseModel):
    name: Literal["stripe", "mpesa"]


class WebhookEventSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    provider: WebhookProvider
    event_id: str
    event_type: str
    received_at: datetime
    processed_at: datetime | None
    error: str | None
