"""Phase 5: Payment-related enums.

PostgreSQL enum names are lowercase, no underscores (Phase 1 convention):
  - ``paymentattemptstatus``
  - ``webhookprovider``
"""

from __future__ import annotations

from enum import Enum


class PaymentAttemptStatus(str, Enum):
    INITIATED = "initiated"  # server has called the provider; awaiting callback
    REQUIRES_ACTION = "requires_action"  # (Stripe only) 3DS / SCA required
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class WebhookProvider(str, Enum):
    STRIPE = "stripe"
    MPESA = "mpesa"
