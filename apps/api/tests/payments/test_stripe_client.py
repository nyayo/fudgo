"""Stripe webhook signature + FakeStripeClient unit tests.

Signature verification uses REAL HMAC SHA-256 (matching Stripe's
``t=<ts>,v1=<hex>`` scheme) so we're testing the actual algorithm.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from decimal import Decimal

import pytest

from app.payments.stripe_client import (
    FakeStripeClient,
    StripeInvalidRequest,
)


TEST_SECRET = "whsec_test_secret"


def _make_signature(payload: bytes, secret: str = TEST_SECRET, ts: int | None = None) -> str:
    """Build a Stripe-style ``t=...,v1=...`` signature header."""
    timestamp = ts or int(time.time())
    signed_payload = f"{timestamp}.".encode() + payload
    v1 = hmac.new(secret.encode(), signed_payload, hashlib.sha256).hexdigest()
    return f"t={timestamp},v1={v1}"


@pytest.fixture(autouse=True)
def _secret(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", TEST_SECRET)
    # get_settings() is lru_cached; the app may already have built the
    # singleton with an empty secret. Patch the cached instance directly.
    from app.core.config import get_settings

    get_settings().STRIPE_WEBHOOK_SECRET = TEST_SECRET


# ---------------------------------------------------------------------------
# Signature verification
# ---------------------------------------------------------------------------


def test_valid_signature_accepted() -> None:
    fake = FakeStripeClient()
    body = json.dumps({"id": "evt_1", "type": "ping"}).encode()
    sig = _make_signature(body)
    event = fake.verify_webhook_signature(body, sig)
    assert event["type"] == "ping"


def test_tampered_body_rejected() -> None:
    fake = FakeStripeClient()
    body = json.dumps({"id": "evt_1", "type": "ping"}).encode()
    sig = _make_signature(body)
    tampered = body.replace(b"ping", b"pong")
    with pytest.raises(StripeInvalidRequest):
        fake.verify_webhook_signature(tampered, sig)


def test_wrong_secret_rejected() -> None:
    fake = FakeStripeClient()
    body = b"{}"
    sig = _make_signature(body, secret="whsec_wrong_secret")
    with pytest.raises(StripeInvalidRequest):
        fake.verify_webhook_signature(body, sig)


def test_missing_signature_rejected() -> None:
    fake = FakeStripeClient()
    with pytest.raises(StripeInvalidRequest):
        fake.verify_webhook_signature(b"{}", "")


def test_malformed_signature_header_rejected() -> None:
    fake = FakeStripeClient()
    for bad in ["garbage", "v1=abc", "t=", "v1=", "x=1,y=2"]:
        with pytest.raises(StripeInvalidRequest):
            fake.verify_webhook_signature(b"{}", bad)


def test_expired_timestamp_rejected() -> None:
    fake = FakeStripeClient()
    old_ts = int(time.time()) - 3600  # 1 hour ago
    body = b"{}"
    sig = _make_signature(body, ts=old_ts)
    with pytest.raises(StripeInvalidRequest):
        fake.verify_webhook_signature(body, sig)


def test_invalid_json_payload_rejected() -> None:
    fake = FakeStripeClient()
    body = b"not-json"
    sig = _make_signature(body)
    with pytest.raises(StripeInvalidRequest):
        fake.verify_webhook_signature(body, sig)


# ---------------------------------------------------------------------------
# FakeStripeClient API surface
# ---------------------------------------------------------------------------


async def test_create_payment_intent_converts_to_minor_units() -> None:
    fake = FakeStripeClient()
    result = await fake.create_payment_intent(
        amount=Decimal("2250.00"),
        currency="KES",
        metadata={"order_id": "o1"},
        idempotency_key="key-1",
    )
    assert result["status"] == "requires_payment_method"
    assert fake.calls[0]["amount_minor"] == 225000  # 2250.00 * 100
    assert fake.calls[0]["currency"] == "kes"
    assert fake.calls[0]["idempotency_key"] == "key-1"


async def test_create_payment_intent_unique_ids() -> None:
    fake = FakeStripeClient()
    r1 = await fake.create_payment_intent(
        amount=Decimal("10"), currency="usd", metadata={}, idempotency_key="k1"
    )
    r2 = await fake.create_payment_intent(
        amount=Decimal("10"), currency="usd", metadata={}, idempotency_key="k2"
    )
    assert r1["id"] != r2["id"]
    assert r1["client_secret"] != r2["client_secret"]


async def test_create_refund_full_amount_by_default() -> None:
    fake = FakeStripeClient()
    await fake.create_refund(payment_intent_id="pi_123")
    assert fake.calls[0]["op"] == "create_refund"
    assert fake.calls[0]["amount_minor"] is None
    assert fake.calls[0]["payment_intent"] == "pi_123"


async def test_create_refund_partial_amount() -> None:
    fake = FakeStripeClient()
    await fake.create_refund(
        payment_intent_id="pi_123",
        amount=Decimal("5.00"),
        idempotency_key="rk-1",
    )
    assert fake.calls[0]["amount_minor"] == 500
    assert fake.calls[0]["idempotency_key"] == "rk-1"


async def test_not_configured_raises() -> None:
    fake = FakeStripeClient(configured=False)
    assert fake.is_configured is False
    with pytest.raises(StripeInvalidRequest):
        await fake.create_payment_intent(
            amount=Decimal("10"), currency="usd", metadata={}, idempotency_key="k"
        )


async def test_queued_response_is_returned_once() -> None:
    fake = FakeStripeClient()
    fake.queue_response({"id": "pi_custom", "client_secret": "cs", "status": "ok"})
    r1 = await fake.create_payment_intent(
        amount=Decimal("10"), currency="usd", metadata={}, idempotency_key="k1"
    )
    assert r1["id"] == "pi_custom"
    # Next call falls back to default generation.
    r2 = await fake.create_payment_intent(
        amount=Decimal("10"), currency="usd", metadata={}, idempotency_key="k2"
    )
    assert r2["id"].startswith("pi_test_")
