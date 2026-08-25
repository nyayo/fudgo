"""Phase 6 enums: payouts + audit log. Lowercase no-underscore PG names."""

from __future__ import annotations

from enum import Enum


class PayoutStatus(str, Enum):
    SCHEDULED = "scheduled"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class PayoutAttemptStatus(str, Enum):
    INITIATED = "initiated"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class PayoutMethod(str, Enum):
    MPESA_B2C = "mpesa_b2c"
    STRIPE_CONNECT = "stripe_connect"  # future


class AuditLogAction(str, Enum):
    USER_SUSPENDED = "user_suspended"
    USER_REINSTATED = "user_reinstated"
    RESTAURANT_APPROVED = "restaurant_approved"
    RESTAURANT_SUSPENDED = "restaurant_suspended"
    PAYMENT_REFUNDED_MANUALLY = "payment_refunded_manually"
    PAYOUT_TRIGGERED_MANUALLY = "payout_triggered_manually"
    PAYOUT_CANCELLED = "payout_cancelled"
    ORDER_CANCELLED_MANUALLY = "order_cancelled_manually"
    NOTIFICATION_BROADCAST = "notification_broadcast"
