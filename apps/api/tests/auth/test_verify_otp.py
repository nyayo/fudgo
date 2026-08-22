"""POST /auth/verify-otp."""

import hashlib
from datetime import UTC, datetime, timedelta

import pytest

from app.auth.models import EmailVerification
from app.auth.otp_service import (
    generate_otp,
    verify_email_otp,
    create_email_otp,
)
from sqlalchemy import select


@pytest.mark.asyncio
async def test_verify_otp_no_user_yet_returns_requires_registration(client):
    # Create OTP row directly via the service so we have a known plain OTP.
    from app.db.session import AsyncSessionLocal

    async with AsyncSessionLocal() as session:
        plain, _ = await create_email_otp(session, "fresh@example.com")
        await session.commit()

    verify = await client.post(
        "/api/v2/auth/verify-otp",
        json={"email": "fresh@example.com", "otp": plain},
    )
    assert verify.status_code == 200
    body = verify.json()
    assert body["success"] is True
    assert body["data"]["user_exists"] is False
    assert body["data"]["requires_registration"] is True


@pytest.mark.asyncio
async def test_verify_otp_existing_user_returns_tokens(client, make_user, db_session):
    user = await make_user(db_session, email="exists@example.com")
    await db_session.commit()
    plain, _ = await create_email_otp(db_session, user.email)
    await db_session.commit()

    verify = await client.post(
        "/api/v2/auth/verify-otp", json={"email": user.email, "otp": plain}
    )
    assert verify.status_code == 200
    body = verify.json()
    assert body["data"]["user_exists"] is True
    assert "access" in body["data"]["tokens"]
    assert "refresh" in body["data"]["tokens"]


@pytest.mark.asyncio
async def test_verify_otp_can_use_access_to_call_profile(client, make_user, db_session):
    user = await make_user(db_session, email="profile@example.com")
    await db_session.commit()
    plain, _ = await create_email_otp(db_session, user.email)
    await db_session.commit()

    verify = await client.post(
        "/api/v2/auth/verify-otp", json={"email": user.email, "otp": plain}
    )
    access = verify.json()["data"]["tokens"]["access"]

    profile = await client.get(
        "/api/v2/auth/profile",
        headers={"Authorization": f"Bearer {access}"},
    )
    assert profile.status_code == 200
    assert profile.json()["data"]["email"] == user.email


@pytest.mark.asyncio
async def test_verify_otp_wrong_attempts_increment(db_session):
    plain, _ = await create_email_otp(db_session, "attempts@example.com")
    await db_session.commit()
    with pytest.raises(Exception) as exc:
        await verify_email_otp(db_session, "attempts@example.com", "000000")
    assert "Invalid OTP" in str(exc.value)

    row = (
        await db_session.execute(
            select(EmailVerification).where(
                EmailVerification.email == "attempts@example.com"
            )
        )
    ).scalar_one()
    assert row.attempts == 1


@pytest.mark.asyncio
async def test_verify_otp_locks_after_five_attempts(db_session):
    plain, _ = await create_email_otp(db_session, "lock@example.com")
    await db_session.commit()
    # Five wrong attempts → 6th should lock.
    for _ in range(5):
        with pytest.raises(Exception):
            await verify_email_otp(db_session, "lock@example.com", "000000")
    row = (
        await db_session.execute(
            select(EmailVerification).where(
                EmailVerification.email == "lock@example.com"
            )
        )
    ).scalar_one()
    assert row.attempts == 5
    # Now even the right OTP gets rejected as locked.
    with pytest.raises(Exception) as exc:
        await verify_email_otp(db_session, "lock@example.com", plain)
    assert "locked" in str(exc.value).lower()


@pytest.mark.asyncio
async def test_verify_otp_expired_rejected(db_session):
    plain = generate_otp()
    row = EmailVerification(
        email="exp@example.com",
        otp=hashlib.sha256(plain.encode("utf-8")).hexdigest(),
        expires_at=datetime.now(UTC) - timedelta(minutes=1),
    )
    db_session.add(row)
    await db_session.commit()
    with pytest.raises(Exception) as exc:
        await verify_email_otp(db_session, "exp@example.com", plain)
    assert "expired" in str(exc.value).lower()