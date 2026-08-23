"""Auth-domain tables: email/phone OTP verifications and revoked refresh tokens."""

import uuid
from datetime import datetime

from sqlalchemy import Column, DateTime, Index, func
from sqlmodel import Field, SQLModel


class EmailVerification(SQLModel, table=True):
    __tablename__ = "email_verifications"
    __table_args__ = (Index("ix_email_verifications_email_is_verified", "email", "is_verified"),)

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    email: str = Field(index=True, nullable=False)
    otp: str = Field(nullable=False)  # sha256 hex digest of the plain OTP
    expires_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), nullable=False, index=True)
    )
    is_verified: bool = Field(default=False, nullable=False)
    attempts: int = Field(default=0, nullable=False)
    created_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    )


class PhoneVerification(SQLModel, table=True):
    __tablename__ = "phone_verifications"
    __table_args__ = (Index("ix_phone_verifications_phone_is_verified", "phone", "is_verified"),)

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    phone: str = Field(index=True, nullable=False)
    otp: str = Field(nullable=False)
    expires_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), nullable=False, index=True)
    )
    is_verified: bool = Field(default=False, nullable=False)
    attempts: int = Field(default=0, nullable=False)
    created_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    )


class RevokedToken(SQLModel, table=True):
    """Refresh-token blacklist.

    Two record shapes:
    - rotation/logout: ``jti`` set, ``revoked_at_user`` NULL.
    - logout-all: ``jti`` is the literal ``logout-all:<user_id>``, and
      ``revoked_at_user`` carries the user id so the refresh path can reject
      any token issued before the logout-all.
    """

    __tablename__ = "revoked_tokens"
    __table_args__ = (Index("ix_revoked_tokens_user_expires", "revoked_at_user", "expires_at"),)

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    jti: str = Field(nullable=False, unique=True, index=True)
    revoked_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    )
    expires_at: datetime = Field(sa_column=Column(DateTime(timezone=True), nullable=False))
    reason: str = Field(default="logout", nullable=False)
    revoked_at_user: uuid.UUID | None = Field(default=None, nullable=True)
