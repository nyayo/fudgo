"""Pydantic request/response schemas for the orders + cart + payments domain.

Reuses ``AddressResponse`` from the users module (Phase 1).
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.orders.enums import OrderStatus, PaymentMethod, PaymentStatus
from app.users.schemas import AddressResponse  # reused from Phase 1


# ---------------------------------------------------------------------------
# Cart
# ---------------------------------------------------------------------------


class CartItemAddRequest(BaseModel):
    menu_item_id: UUID
    quantity: int = Field(ge=1, le=99)
    special_instructions: str | None = Field(default=None, max_length=500)


class CartItemUpdateRequest(BaseModel):
    quantity: int | None = Field(default=None, ge=1, le=99)
    special_instructions: str | None = Field(default=None, max_length=500)


class CartItemResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    menu_item_id: UUID
    menu_item_name: str
    menu_item_image_url: str | None = None
    unit_price: Decimal
    effective_unit_price: Decimal
    line_subtotal: Decimal
    quantity: int
    special_instructions: str | None = None


class CartResponse(BaseModel):
    id: UUID
    customer_id: UUID
    restaurant_id: UUID | None
    items: list[CartItemResponse]
    item_count: int
    subtotal: Decimal
    delivery_fee: Decimal
    service_fee: Decimal
    discount_amount: Decimal
    total: Decimal
    is_open_now: bool
    min_order_amount: Decimal


# ---------------------------------------------------------------------------
# Checkout
# ---------------------------------------------------------------------------


class CheckoutRequest(BaseModel):
    delivery_address_id: UUID


# ---------------------------------------------------------------------------
# Order
# ---------------------------------------------------------------------------


class OrderItemResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    menu_item_id: UUID
    name: str
    unit_price: Decimal
    effective_unit_price: Decimal
    applied_promotion_id: UUID | None = None
    applied_promotion_name: str | None = None
    applied_promotion_discount: float | None = None
    quantity: int
    line_subtotal: Decimal
    special_instructions: str | None = None


class OrderStatusHistoryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    from_status: OrderStatus | None = None
    to_status: OrderStatus
    changed_by_role: str
    note: str | None = None
    changed_at: datetime


class PaymentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    order_id: UUID
    method: PaymentMethod
    status: PaymentStatus
    amount: Decimal
    created_at: datetime
    succeeded_at: datetime | None = None
    failed_at: datetime | None = None


class OrderResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    order_number: str
    customer_id: UUID
    restaurant_id: UUID
    delivery_address: AddressResponse
    courier_id: UUID | None = None
    items: list[OrderItemResponse]
    status_history: list[OrderStatusHistoryResponse]
    subtotal: Decimal
    delivery_fee: Decimal
    service_fee: Decimal
    total_discount_amount: Decimal
    total: Decimal
    status: OrderStatus
    placed_at: datetime
    confirmed_at: datetime | None = None
    preparing_at: datetime | None = None
    ready_at: datetime | None = None
    picked_up_at: datetime | None = None
    delivered_at: datetime | None = None
    cancelled_at: datetime | None = None
    cancellation_reason: str | None = None
    estimated_delivery_at: datetime | None = None
    payment: PaymentResponse | None = None


class OrderListResponse(BaseModel):
    items: list[OrderResponse]
    count: int
    next_cursor: str | None = None


# ---------------------------------------------------------------------------
# Cancellation
# ---------------------------------------------------------------------------


class CancelOrderRequest(BaseModel):
    reason: str = Field(min_length=1, max_length=500)


# ---------------------------------------------------------------------------
# Misc
# ---------------------------------------------------------------------------


class MessageResponse(BaseModel):
    message: str
