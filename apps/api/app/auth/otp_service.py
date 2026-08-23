"""OTP generation, hashing, and verification for email and phone channels."""

import hashlib
import secrets
from datetime import UTC, datetime, timedelta
from typing import Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import EmailVerification, PhoneVerification
from app.core.exceptions import AuthenticationError, ConflictError

OTP_KIND = Literal["email", "phone"]
OTP_TTL = timedelta(minutes=10)
OTP_MAX_ATTEMPTS = 5


def _hash(plain: str) -> str:
    return hashlib.sha256(plain.encode("utf-8")).hexdigest()


def generate_otp() -> str:
    """Cryptographically random 6-digit numeric OTP, left-padded with zeros."""
    return f"{secrets.randbelow(1_000_000):06d}"


async def _create_email_row(session: AsyncSession, email: str, otp_hash: str) -> EmailVerification:
    row = EmailVerification(
        email=email,
        otp=otp_hash,
        expires_at=datetime.now(UTC) + OTP_TTL,
    )
    session.add(row)
    await session.flush()
    return row


async def _create_phone_row(session: AsyncSession, phone: str, otp_hash: str) -> PhoneVerification:
    row = PhoneVerification(
        phone=phone,
        otp=otp_hash,
        expires_at=datetime.now(UTC) + OTP_TTL,
    )
    session.add(row)
    await session.flush()
    return row


async def create_email_otp(session: AsyncSession, email: str) -> tuple[str, EmailVerification]:
    """Generate a new OTP, persist its hash, return (plain, row)."""
    plain = generate_otp()
    row = await _create_email_row(session, email, _hash(plain))
    return plain, row


async def create_phone_otp(session: AsyncSession, phone: str) -> tuple[str, PhoneVerification]:
    """Generate a new OTP, persist its hash, return (plain, row)."""
    plain = generate_otp()
    row = await _create_phone_row(session, phone, _hash(plain))
    return plain, row


async def verify_email_otp(session: AsyncSession, email: str, plain_otp: str) -> EmailVerification:
    """Verify an email OTP. Raises AuthenticationError on any failure."""
    row = (
        await session.execute(
            select(EmailVerification)
            .where(EmailVerification.email == email, EmailVerification.is_verified.is_(False))
            .order_by(EmailVerification.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if row is None:
        raise AuthenticationError("OTP expired or not found")
    if row.is_verified:
        raise AuthenticationError("OTP already used")
    if row.attempts >= OTP_MAX_ATTEMPTS:
        raise ConflictError("OTP locked, please request a new one")
    if datetime.now(UTC) >= row.expires_at:
        raise AuthenticationError("OTP expired")
    if _hash(plain_otp) != row.otp:
        row.attempts += 1
        await session.flush()
        if row.attempts >= OTP_MAX_ATTEMPTS:
            raise ConflictError("OTP locked, please request a new one")
        raise AuthenticationError("Invalid OTP")
    row.is_verified = True
    await session.flush()
    return row


async def verify_phone_otp(session: AsyncSession, phone: str, plain_otp: str) -> PhoneVerification:
    """Verify a phone OTP. Mirrors verify_email_otp."""
    row = (
        await session.execute(
            select(PhoneVerification)
            .where(PhoneVerification.phone == phone, PhoneVerification.is_verified.is_(False))
            .order_by(PhoneVerification.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if row is None:
        raise AuthenticationError("OTP expired or not found")
    if row.is_verified:
        raise AuthenticationError("OTP already used")
    if row.attempts >= OTP_MAX_ATTEMPTS:
        raise ConflictError("OTP locked, please request a new one")
    if datetime.now(UTC) >= row.expires_at:
        raise AuthenticationError("OTP expired")
    if _hash(plain_otp) != row.otp:
        row.attempts += 1
        await session.flush()
        if row.attempts >= OTP_MAX_ATTEMPTS:
            raise ConflictError("OTP locked, please request a new one")
        raise AuthenticationError("Invalid OTP")
    row.is_verified = True
    await session.flush()
    return row
