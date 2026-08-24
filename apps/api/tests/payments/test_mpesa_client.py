"""M-Pesa client unit tests (FakeMpesaClient; no real Daraja calls)."""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.payments.mpesa_client import (
    FakeMpesaClient,
    MpesaInvalidPhone,
    MpesaRequestFailed,
)


async def test_stk_push_happy_path() -> None:
    fake = FakeMpesaClient()
    result = await fake.stk_push(
        amount_kes=Decimal("2250"),
        phone_e164="+254712345678",
        account_reference="FUDGO-20260823-000001",
        transaction_desc="Fudgo order FUDGO-X",
    )
    assert result["ResponseCode"] == "0"
    assert result["CheckoutRequestID"].startswith("ws_CO_TEST_")


async def test_stk_push_strips_plus_prefix() -> None:
    fake = FakeMpesaClient()
    await fake.stk_push(
        amount_kes=Decimal("100"),
        phone_e164="+254712345678",
        account_reference="ref",
        transaction_desc="d",
    )
    # The recorded phone has the + stripped (Daraja wants 2547XXXXXXXX).
    assert fake.calls[0]["phone"] == "254712345678"


async def test_stk_push_amount_is_integer_kes() -> None:
    fake = FakeMpesaClient()
    await fake.stk_push(
        amount_kes=Decimal("2250.99"),
        phone_e164="+254712345678",
        account_reference="ref",
        transaction_desc="d",
    )
    # Daraja doesn't support minor units; int() truncates.
    assert fake.calls[0]["amount_kes"] == 2250


async def test_stk_push_requires_plus_prefix() -> None:
    fake = FakeMpesaClient()
    with pytest.raises(MpesaInvalidPhone):
        await fake.stk_push(
            amount_kes=Decimal("100"),
            phone_e164="254712345678",  # missing +
            account_reference="ref",
            transaction_desc="d",
        )


async def test_stk_push_not_configured_raises() -> None:
    fake = FakeMpesaClient(configured=False)
    with pytest.raises(MpesaRequestFailed):
        await fake.stk_push(
            amount_kes=Decimal("100"),
            phone_e164="+254712345678",
            account_reference="ref",
            transaction_desc="d",
        )


async def test_stk_push_records_all_calls() -> None:
    fake = FakeMpesaClient()
    for i in range(3):
        await fake.stk_push(
            amount_kes=Decimal(f"{i + 1}"),
            phone_e164="+254712345678",
            account_reference=f"r{i}",
            transaction_desc="d",
        )
    assert len(fake.calls) == 3
    assert [c["account_reference"] for c in fake.calls] == ["r0", "r1", "r2"]


async def test_stk_push_unique_checkout_ids() -> None:
    fake = FakeMpesaClient()
    r1 = await fake.stk_push(
        amount_kes=Decimal("1"), phone_e164="+254700000001",
        account_reference="a", transaction_desc="d",
    )
    r2 = await fake.stk_push(
        amount_kes=Decimal("1"), phone_e164="+254700000002",
        account_reference="b", transaction_desc="d",
    )
    assert r1["CheckoutRequestID"] != r2["CheckoutRequestID"]
    assert r1["MerchantRequestID"] != r2["MerchantRequestID"]


async def test_stk_push_queued_failure_response() -> None:
    fake = FakeMpesaClient()
    fake.queue_response({
        "MerchantRequestID": "ws_MR_X",
        "CheckoutRequestID": "ws_CO_X",
        "ResponseCode": "1",
        "ResponseDescription": "Request cancelled by user",
    })
    result = await fake.stk_push(
        amount_kes=Decimal("100"), phone_e164="+254712345678",
        account_reference="r", transaction_desc="d",
    )
    assert result["ResponseCode"] == "1"
