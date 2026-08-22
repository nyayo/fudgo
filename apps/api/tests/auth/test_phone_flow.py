"""Phone OTP flow."""

import hashlib
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app.auth.models import PhoneVerification
from app.auth.otp_service import (
    create_phone_otp,
    generate_otp,
    verify_phone_otp,
)
from app.users.enums import AuthProvider, UserType
from app.users.models import User


@pytest.mark.asyncio
async def test_request_phone_otp_happy(client, db_session):
    r = await client.post(
        "/api/v2/auth/phone/request-otp", json={"phone": "+14155551234"}
    )
    assert r.status_code == 200
    row = (
        await db_session.execute(
            select(PhoneVerification).where(
                PhoneVerification.phone == "+14155551234"
            )
        )
    ).scalar_one()
    assert row.otp


@pytest.mark.asyncio
async def test_request_phone_otp_invalid(client):
    r = await client.post(
        "/api/v2/auth/phone/request-otp", json={"phone": "not-e164"}
    )
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_verify_phone_otp_new_user(client, db_session):
    plain, _ = await create_phone_otp(db_session, "+14155550000")
    await db_session.commit()

    v = await client.post(
        "/api/v2/auth/phone/verify-otp",
        json={"phone": "+14155550000", "otp": plain},
    )
    assert v.status_code == 200
    body = v.json()
    assert body["data"]["user_exists"] is False
    assert body["data"]["requires_registration"] is True


@pytest.mark.asyncio
async def test_verify_phone_otp_existing_user(client, db_session):
    user = User(
        email="p@example.com",
        phone="+14155551111",
        username="p_user",
        first_name="P",
        last_name="U",
        user_type=UserType.customer,
        auth_provider=AuthProvider.phone,
        is_verified=True,
    )
    db_session.add(user)
    await db_session.commit()

    plain, _ = await create_phone_otp(db_session, user.phone)
    await db_session.commit()

    v = await client.post(
        "/api/v2/auth/phone/verify-otp",
        json={"phone": user.phone, "otp": plain},
    )
    assert v.status_code == 200
    body = v.json()
    assert body["data"]["user_exists"] is True
    assert "access" in body["data"]["tokens"]


@pytest.mark.asyncio
async def test_verify_phone_otp_locks_after_five_attempts(db_session):
    plain, _ = await create_phone_otp(db_session, "+14155552222")
    await db_session.commit()
    for _ in range(5):
        with pytest.raises(Exception):
            await verify_phone_otp(db_session, "+14155552222", "000000")
    row = (
        await db_session.execute(
            select(PhoneVerification).where(PhoneVerification.phone == "+14155552222")
        )
    ).scalar_one()
    assert row.attempts == 5


@pytest.mark.asyncio
async def test_verify_phone_otp_expired_rejected(db_session):
    plain = generate_otp()
    row = PhoneVerification(
        phone="+14155553333",
        otp=hashlib.sha256(plain.encode("utf-8")).hexdigest(),
        expires_at=datetime.now(UTC) - timedelta(minutes=1),
    )
    db_session.add(row)
    await db_session.commit()
    with pytest.raises(Exception) as exc:
        await verify_phone_otp(db_session, row.phone, plain)
    assert "expired" in str(exc.value).lower()