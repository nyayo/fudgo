"""M-Pesa Daraja STK Push client.

Tests use :class:`FakeMpesaClient` to avoid hitting the real network.

The real client uses ``httpx.AsyncClient`` (already in deps) and the
``Lipa Na M-Pesa Online`` STK Push flow.

PCI compliance: M-Pesa tokenizes via the customer's phone (STK Push PIN
entered on the phone, not in our app). The server never sees the PIN.
"""

from __future__ import annotations

import base64
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, Protocol

import httpx

from app.core.config import get_settings


class MpesaClientError(Exception):
    """Base for all M-Pesa client errors."""


class MpesaInvalidPhone(MpesaClientError):
    pass


class MpesaRequestFailed(MpesaClientError):
    pass


class MpesaClient(Protocol):
    """Protocol so tests can swap in :class:`FakeMpesaClient`."""

    @property
    def is_configured(self) -> bool: ...

    async def stk_push(
        self,
        amount_kes: Decimal,
        phone_e164: str,
        account_reference: str,
        transaction_desc: str,
    ) -> dict[str, Any]: ...


class RealMpesaClient:
    """Production M-Pesa Daraja STK Push client."""

    BASE_URL_SANDBOX = "https://sandbox.safaricom.co.ke"
    BASE_URL_PRODUCTION = "https://api.safaricom.co.ke"

    def __init__(self) -> None:
        self.base_url = (
            self.BASE_URL_SANDBOX
            if get_settings().MPESA_ENVIRONMENT == "sandbox"
            else self.BASE_URL_PRODUCTION
        )

    @property
    def is_configured(self) -> bool:
        return bool(
            get_settings().MPESA_CONSUMER_KEY
            and get_settings().MPESA_CONSUMER_SECRET
            and get_settings().MPESA_SHORTCODE
            and get_settings().MPESA_PASSKEY
        )

    async def _get_access_token(self, client: httpx.AsyncClient) -> str:
        credentials = base64.b64encode(
            f"{get_settings().MPESA_CONSUMER_KEY}:{get_settings().MPESA_CONSUMER_SECRET}".encode()
        ).decode()
        resp = await client.get(
            f"{self.base_url}/oauth/v1/generate",
            params={"grant_type": "client_credentials"},
            headers={"Authorization": f"Basic {credentials}"},
            timeout=get_settings().MPESA_API_TIMEOUT_S,
        )
        resp.raise_for_status()
        return resp.json()["access_token"]  # type: ignore[no-any-return]

    def _make_password(self, timestamp: str) -> str:
        raw = f"{get_settings().MPESA_SHORTCODE}{get_settings().MPESA_PASSKEY}{timestamp}"
        return base64.b64encode(raw.encode()).decode()

    async def stk_push(
        self,
        amount_kes: Decimal,
        phone_e164: str,
        account_reference: str,
        transaction_desc: str,
    ) -> dict[str, Any]:
        if not self.is_configured:
            raise MpesaRequestFailed("M-Pesa is not configured")

        phone = phone_e164.lstrip("+")
        timestamp = datetime.now(UTC).strftime("%Y%m%d%H%M%S")
        password = self._make_password(timestamp)
        amount_int = int(amount_kes)  # Daraja: integer KES only

        async with httpx.AsyncClient() as client:
            token = await self._get_access_token(client)
            resp = await client.post(
                f"{self.base_url}/mpesa/stkpush/v1/processrequest",
                json={
                    "BusinessShortCode": get_settings().MPESA_SHORTCODE,
                    "Password": password,
                    "Timestamp": timestamp,
                    "TransactionType": "CustomerBuyGoodsOnline",
                    "Amount": amount_int,
                    "PartyA": phone,
                    "PartyB": get_settings().MPESA_SHORTCODE,
                    "PhoneNumber": phone,
                    "CallBackURL": get_settings().MPESA_STK_PUSH_CALLBACK_URL,
                    "AccountReference": account_reference,
                    "TransactionDesc": transaction_desc,
                },
                headers={"Authorization": f"Bearer {token}"},
                timeout=get_settings().MPESA_API_TIMEOUT_S,
            )
            resp.raise_for_status()
            return resp.json()  # type: ignore[no-any-return]


class FakeMpesaClient:
    """In-memory M-Pesa client for tests."""

    def __init__(
        self,
        *,
        configured: bool = True,
        next_checkout_id: str = "ws_CO_TEST_123",
        next_merchant_id: str = "ws_MR_TEST_123",
    ) -> None:
        self.configured = configured
        self._next_checkout_id = next_checkout_id
        self._next_merchant_id = next_merchant_id
        self._counter = 0
        self.calls: list[dict[str, Any]] = []
        self.responses: list[dict[str, Any]] = []

    @property
    def is_configured(self) -> bool:
        return self.configured

    def queue_response(self, response: dict[str, Any]) -> None:
        self.responses.append(response)

    async def stk_push(
        self,
        amount_kes: Decimal,
        phone_e164: str,
        account_reference: str,
        transaction_desc: str,
    ) -> dict[str, Any]:
        if not self.configured:
            raise MpesaRequestFailed("M-Pesa not configured (test)")
        if not phone_e164.startswith("+"):
            raise MpesaInvalidPhone(f"Phone must start with +: {phone_e164!r}")
        self.calls.append(
            {
                "amount_kes": int(amount_kes),
                "phone": phone_e164.lstrip("+"),
                "account_reference": account_reference,
                "transaction_desc": transaction_desc,
            }
        )
        if self.responses:
            return self.responses.pop(0)
        self._counter += 1
        return {
            "MerchantRequestID": f"{self._next_merchant_id}_{self._counter}",
            "CheckoutRequestID": f"{self._next_checkout_id}_{self._counter}",
            "ResponseCode": "0",
            "ResponseDescription": "Success. Request accepted for processing",
        }


def get_mpesa_client() -> MpesaClient:
    import os

    if os.environ.get("FUDGO_PAYMENTS_FAKE") == "1":
        return FakeMpesaClient()
    return RealMpesaClient()
