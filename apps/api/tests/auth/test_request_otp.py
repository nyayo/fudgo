"""POST /auth/request-otp."""

import pytest
from sqlalchemy import select

from app.auth.models import EmailVerification
from tests.helpers import assert_success


@pytest.mark.asyncio
async def test_request_otp_happy_path(client, db_session):
    response = await client.post("/api/v2/auth/request-otp", json={"email": "test@example.com"})
    assert response.status_code == 200
    body = response.json()
    assert_success(body, {"message"})

    row = (
        await db_session.execute(
            select(EmailVerification).where(EmailVerification.email == "test@example.com")
        )
    ).scalar_one()
    assert row.otp  # hash stored, not the plain OTP
    assert row.is_verified is False
    assert row.attempts == 0


@pytest.mark.asyncio
async def test_request_otp_throttle(client):
    payloads = [{"email": "throttle@example.com"} for _ in range(5)]
    for payload in payloads:
        r = await client.post("/api/v2/auth/request-otp", json=payload)
        assert r.status_code == 200
    sixth = await client.post("/api/v2/auth/request-otp", json={"email": "throttle@example.com"})
    assert sixth.status_code == 429


@pytest.mark.asyncio
async def test_request_otp_invalid_email(client):
    r = await client.post("/api/v2/auth/request-otp", json={"email": "not-an-email"})
    assert r.status_code == 422
