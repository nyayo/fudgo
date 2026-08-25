"""M-Pesa B2C client tests (mocked httpx)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.payouts.mpesa_b2c_client import MpesaB2CClient, MpesaB2CError


@pytest.fixture(autouse=True)
def _configured(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.core.config import get_settings

    s = get_settings()
    monkeypatch.setenv("MPESA_CONSUMER_KEY", "ck")
    monkeypatch.setenv("MPESA_CONSUMER_SECRET", "cs")
    monkeypatch.setenv("MPESA_SHORTCODE", "123456")
    monkeypatch.setenv("MPESA_PASSKEY", "pk")
    s.MPESA_CONSUMER_KEY = "ck"
    s.MPESA_CONSUMER_SECRET = "cs"
    s.MPESA_SHORTCODE = "123456"
    s.MPESA_PASSKEY = "pk"


def test_not_configured_when_keys_empty() -> None:
    from app.core.config import get_settings

    get_settings().MPESA_CONSUMER_KEY = ""
    c = MpesaB2CClient()
    assert c.is_configured is False
    with pytest.raises(MpesaB2CError):
        c.b2c_payment("+254700000000", 100, "occ")


def _mock_httpx(token: str = "tok", b2c: dict | None = None, status: int = 200):
    token_resp = MagicMock(status_code=200)
    token_resp.json.return_value = {"access_token": token}
    final = MagicMock(status_code=status)
    final.json.return_value = b2c or {
        "ResponseCode": "0",
        "ConversationID": "CONV-1",
        "ResponseDescription": "Accept the service request successfully.",
    }
    final.text = "ok"

    client_cm = MagicMock()
    client_cm.__enter__.return_value.get.return_value = token_resp
    client_cm.__enter__.return_value.post.return_value = final
    return patch("httpx.Client", return_value=client_cm)


def test_b2c_success_payload_and_response() -> None:
    with _mock_httpx() as m:
        out = MpesaB2CClient().b2c_payment("+254700000001", 500, "Order X payout")
    assert out["ConversationID"] == "CONV-1"
    post_kwargs = (
        m.return_value.__enter__.return_value.post.call_args.kwargs
    )
    body = post_kwargs["json"]
    assert body["Amount"] == 500
    assert body["PartyA"] == "254700000001"  # + stripped
    assert body["CommandID"] == "BusinessPayment"
    assert body["Occasion"].startswith("Order X")


def test_b2c_http_error_raises() -> None:
    token_resp = MagicMock(status_code=200)
    token_resp.json.return_value = {"access_token": "t"}
    final = MagicMock(status_code=500)
    final.text = "boom"
    client_cm = MagicMock()
    client_cm.__enter__.return_value.get.return_value = token_resp
    client_cm.__enter__.return_value.post.return_value = final
    with patch("httpx.Client", return_value=client_cm):
        with pytest.raises(MpesaB2CError, match="B2C failed"):
            MpesaB2CClient().b2c_payment("+254700000001", 100, "x")


def test_b2c_rejected_response_code_raises() -> None:
    with _mock_httpx(b2c={"ResponseCode": "1", "ResponseDescription": "no"}):
        with pytest.raises(MpesaB2CError, match="B2C rejected"):
            MpesaB2CClient().b2c_payment("+254700000001", 100, "x")


def test_security_credential_is_base64_of_shortcode_passkey_ts() -> None:
    import base64

    c = MpesaB2CClient()
    decoded = base64.b64decode(c._security_credential()).decode()
    assert decoded.startswith("123456pk")
