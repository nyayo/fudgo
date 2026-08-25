"""M-Pesa B2C client — closes Phase 5's 'M-Pesa refund is stubbed' gap.

Same Daraja OAuth as the C2B STK Push, but posts to the B2C endpoint.
"""

from __future__ import annotations

import base64
import logging
from typing import Any
from datetime import UTC, datetime

from app.core.config import get_settings

logger = logging.getLogger(__name__)


class MpesaB2CError(Exception):
    pass


class MpesaB2CClient:
    BASE_URL_SANDBOX = "https://sandbox.safaricom.co.ke"
    BASE_URL_PRODUCTION = "https://api.safaricom.co.ke"

    def __init__(self) -> None:
        s = get_settings()
        self.base_url = (
            self.BASE_URL_SANDBOX
            if s.MPESA_ENVIRONMENT == "sandbox"
            else self.BASE_URL_PRODUCTION
        )

    @property
    def is_configured(self) -> bool:
        s = get_settings()
        return bool(
            s.MPESA_CONSUMER_KEY and s.MPESA_SHORTCODE and s.MPESA_PASSKEY
        )

    def _security_credential(self) -> str:
        """Base64(SHORTCODE + PASSKEY + timestamp) — same as C2B."""
        s = get_settings()
        raw = f"{s.MPESA_SHORTCODE}{s.MPESA_PASSKEY}{self._timestamp()}"
        return base64.b64encode(raw.encode()).decode()

    def _timestamp(self) -> str:
        return datetime.now(UTC).strftime("%Y%m%d%H%M%S")

    def b2c_payment(
        self,
        phone_e164: str,
        amount_kes: int,
        occasion: str,
        remarks: str = "Fudgo payout",
        initiator_name: str | None = None,
    ) -> dict[str, Any]:
        """Send a B2C payment. Sync (called from Celery tasks).

        Returns the Daraja response dict; raises MpesaB2CError on failure.
        """
        import requests  # lazy

        s = get_settings()
        if not self.is_configured:
            raise MpesaB2CError("M-Pesa B2C not configured")

        phone = phone_e164.lstrip("+")
        # B2C requires an initiator name + security credential from the
        # Daraja cert; v1 used the shortcode + passkey combo which works
        # on sandbox. Production needs the real InitiatorName + cert.
        initiator = initiator_name or "testapi"

        with __import__("httpx").Client(timeout=15) as client:
            token_resp = client.get(
                f"{self.base_url}/oauth/v1/generate",
                params={"grant_type": "client_credentials"},
                headers={
                    "Authorization": "Basic "
                    + base64.b64encode(
                        f"{s.MPESA_CONSUMER_KEY}:{s.MPESA_CONSUMER_SECRET}".encode()
                    ).decode()
                },
            )
            token_resp.raise_for_status()
            token = token_resp.json()["access_token"]

            resp = client.post(
                f"{self.base_url}/mpesa/b2c/v1/paymentrequest",
                headers={"Authorization": f"Bearer {token}"},
                json={
                    "InitiatorName": initiator,
                    "SecurityCredential": self._security_credential(),
                    "CommandID": "BusinessPayment",
                    "Amount": int(amount_kes),
                    "PartyA": phone,
                    "PartyB": s.MPESA_SHORTCODE,
                    "Remarks": remarks[:100],
                    "QueueTimeOutURL": s.MPESA_STK_PUSH_CALLBACK_URL,
                    "ResultURL": s.MPESA_STK_PUSH_CALLBACK_URL,
                    "Occasion": occasion[:100],
                },
            )
            if resp.status_code >= 400:
                raise MpesaB2CError(
                    f"B2C failed: {resp.status_code} {resp.text[:300]}"
                )
            data: dict[str, Any] = resp.json()
            if data.get("ResponseCode") != "0":
                raise MpesaB2CError(
                    f"B2C rejected: {data.get('ResponseDescription', 'unknown')}"
                )
            return data
