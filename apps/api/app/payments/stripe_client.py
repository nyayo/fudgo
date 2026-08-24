"""Stripe client -- async wrapper around the (sync) stripe library.

Tests use :class:`FakeStripeClient` (below) to avoid hitting the real
network. Real-API calls go through ``stripe.PaymentIntent.create`` and
``stripe.Refund.create`` wrapped in ``asyncio.to_thread`` so the event
loop isn't blocked.

PCI compliance: the client never sees card numbers, CVVs, or full PANs.
Stripe.js / Stripe Elements tokenizes the customer card on the client
side; the backend only receives a ``payment_intent.id`` + ``client_secret``
which we return to the client to confirm the PaymentIntent.
"""

from __future__ import annotations

import asyncio
from decimal import Decimal
from typing import Any, Protocol

from app.core.config import get_settings
from app.payments import enums as _enums, models as _models, schemas as _schemas  # noqa: F401


class StripeClientError(Exception):
    """Base for all Stripe client errors raised by this module."""


class StripeCardDeclined(StripeClientError):
    pass


class StripeInvalidRequest(StripeClientError):
    pass


class StripeClient(Protocol):
    """Protocol so tests can swap in :class:`FakeStripeClient`."""

    @property
    def is_configured(self) -> bool: ...

    async def create_payment_intent(
        self,
        amount: Decimal,
        currency: str,
        metadata: dict[str, Any],
        idempotency_key: str,
    ) -> dict[str, Any]: ...

    async def retrieve_payment_intent(
        self, payment_intent_id: str
    ) -> dict[str, Any]: ...

    async def create_refund(
        self,
        payment_intent_id: str,
        amount: Decimal | None = None,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]: ...

    def verify_webhook_signature(
        self, payload: bytes, signature: str
    ) -> dict[str, Any]: ...


class RealStripeClient:
    """Production Stripe client backed by the official ``stripe`` library."""

    def __init__(self) -> None:
        # Lazy import -- the stripe library may not be installed in tests.
        self._stripe: Any = None
        try:
            import stripe

            if get_settings().STRIPE_SECRET_KEY:
                stripe.api_key = get_settings().STRIPE_SECRET_KEY
            self._stripe = stripe
        except ImportError:
            pass

    @property
    def is_configured(self) -> bool:
        return bool(self._stripe) and bool(get_settings().STRIPE_SECRET_KEY)

    async def create_payment_intent(
        self,
        amount: Decimal,
        currency: str,
        metadata: dict[str, Any],
        idempotency_key: str,
    ) -> dict[str, Any]:
        if not self.is_configured:
            raise StripeInvalidRequest("Stripe is not configured")
        amount_minor = int(amount * 100)
        return await asyncio.to_thread(
            self._stripe.PaymentIntent.create,
            amount=amount_minor,
            currency=currency.lower(),
            metadata=metadata,
            idempotency_key=idempotency_key,
        )

    async def retrieve_payment_intent(
        self, payment_intent_id: str
    ) -> dict[str, Any]:
        if not self.is_configured:
            raise StripeInvalidRequest("Stripe is not configured")
        return await asyncio.to_thread(self._stripe.PaymentIntent.retrieve, payment_intent_id)

    async def create_refund(
        self,
        payment_intent_id: str,
        amount: Decimal | None = None,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        if not self.is_configured:
            raise StripeInvalidRequest("Stripe is not configured")
        kwargs: dict[str, Any] = {"payment_intent": payment_intent_id}
        if amount is not None:
            kwargs["amount"] = int(amount * 100)
        if idempotency_key:
            kwargs["idempotency_key"] = idempotency_key
        return await asyncio.to_thread(self._stripe.Refund.create, **kwargs)

    def verify_webhook_signature(
        self, payload: bytes, signature: str
    ) -> dict[str, Any]:
        if not self.is_configured:
            raise StripeInvalidRequest("Stripe is not configured")
        try:
            return self._stripe.Webhook.construct_event(  # type: ignore[no-any-return]
                payload, signature, get_settings().STRIPE_WEBHOOK_SECRET
            )
        except Exception as exc:  # noqa: BLE001 -- wrap any stripe exception
            raise StripeInvalidRequest(str(exc)) from exc


class FakeStripeClient:
    """In-memory Stripe client for tests.

    Records every call so tests can assert the right metadata + idempotency
    key was sent, and what responses were returned.
    """

    def __init__(
        self,
        *,
        configured: bool = True,
        next_payment_intent_id: str = "pi_test_123",
        next_client_secret: str = "pi_test_123_secret_abc",
        next_refund_id: str = "re_test_456",
    ) -> None:
        self.configured = configured
        self._next_pi_id = next_payment_intent_id
        self._next_secret = next_client_secret
        self._next_refund_id = next_refund_id
        self.calls: list[dict[str, Any]] = []
        self.responses: list[dict[str, Any]] = []
        # Default: each create_payment_intent call gets a new ID
        self._pi_counter = 0
        self._refund_counter = 0

    @property
    def is_configured(self) -> bool:
        return self.configured

    def queue_response(self, response: dict[str, Any]) -> None:
        """Queue a custom response to be returned by the next call."""
        self.responses.append(response)

    async def create_payment_intent(
        self,
        amount: Decimal,
        currency: str,
        metadata: dict[str, Any],
        idempotency_key: str,
    ) -> dict[str, Any]:
        if not self.configured:
            raise StripeInvalidRequest("Stripe is not configured (test)")
        self.calls.append(
            {
                "op": "create_payment_intent",
                "amount_minor": int(amount * 100),
                "currency": currency.lower(),
                "metadata": metadata,
                "idempotency_key": idempotency_key,
            }
        )
        if self.responses:
            return self.responses.pop(0)
        self._pi_counter += 1
        return {
            "id": f"pi_test_{self._pi_counter}",
            "client_secret": f"pi_test_{self._pi_counter}_secret_abc",
            "status": "requires_payment_method",
        }

    async def retrieve_payment_intent(
        self, payment_intent_id: str
    ) -> dict[str, Any]:
        self.calls.append(
            {"op": "retrieve_payment_intent", "id": payment_intent_id}
        )
        return {"id": payment_intent_id, "status": "succeeded"}

    async def create_refund(
        self,
        payment_intent_id: str,
        amount: Decimal | None = None,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        if not self.configured:
            raise StripeInvalidRequest("Stripe is not configured (test)")
        self.calls.append(
            {
                "op": "create_refund",
                "payment_intent": payment_intent_id,
                "amount_minor": int(amount * 100) if amount is not None else None,
                "idempotency_key": idempotency_key,
            }
        )
        if self.responses:
            return self.responses.pop(0)
        self._refund_counter += 1
        return {
            "id": f"re_test_{self._refund_counter}",
            "status": "succeeded",
        }

    def verify_webhook_signature(
        self, payload: bytes, signature: str
    ) -> dict[str, Any]:
        """Real signature verification using ``hmac.new(...).hexdigest()``
        matching the Stripe ``Stripe-Signature`` scheme: ``t=<ts>,v1=<hex>``.

        Tests build the signature with the same algorithm + the test secret
        in ``STRIPE_WEBHOOK_SECRET``.
        """
        import hashlib
        import hmac
        import time as _t

        if not self.configured:
            raise StripeInvalidRequest("Stripe is not configured (test)")

        if not signature:
            raise StripeInvalidRequest("Missing signature")

        # Parse "t=<ts>,v1=<hex>" (allow multiple v1 entries; Stripe accepts
        # multiple signing secrets in rotation).
        parts: dict[str, list[str]] = {}
        for chunk in signature.split(","):
            k, _, v = chunk.partition("=")
            parts.setdefault(k.strip(), []).append(v.strip())
        ts_list = parts.get("t", [])
        sigs = parts.get("v1", [])
        if not ts_list or not sigs:
            raise StripeInvalidRequest("Malformed signature header")

        ts = ts_list[0]
        signed_payload = f"{ts}.".encode() + payload
        expected = hmac.new(
            get_settings().STRIPE_WEBHOOK_SECRET.encode(),
            signed_payload,
            hashlib.sha256,
        ).hexdigest()
        if not any(
            hmac.compare_digest(expected, candidate) for candidate in sigs
        ):
            raise StripeInvalidRequest("Signature mismatch")

        # Check timestamp is recent (within 5 minutes).
        try:
            ts_int = int(ts)
        except ValueError as exc:
            raise StripeInvalidRequest("Bad timestamp") from exc
        if abs(int(_t.time()) - ts_int) > 300:
            raise StripeInvalidRequest("Timestamp too old")

        # Parse payload as JSON
        import json

        try:
            event = json.loads(payload.decode("utf-8"))
        except Exception as exc:
            raise StripeInvalidRequest("Invalid JSON") from exc
        return event  # type: ignore[no-any-return]  # type: ignore[no-any-return]


def get_stripe_client() -> StripeClient:
    """Factory: returns the FakeStripeClient in tests, RealStripeClient in prod.

    Detection: if STRIPE_SECRET_KEY is set to a value starting with ``sk_test_``
    and the env var ``FUDGO_PAYMENTS_FAKE`` is set, use the fake. Otherwise,
    use the real client.
    """
    import os

    if os.environ.get("FUDGO_PAYMENTS_FAKE") == "1":
        return FakeStripeClient()
    return RealStripeClient()
