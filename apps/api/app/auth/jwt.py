"""JWT issuance/verification for the Fudgo API.

Access tokens: short-lived (JWT_ACCESS_TTL_MINUTES), ``type=access``.
Refresh tokens: long-lived (JWT_REFRESH_TTL_DAYS), ``type=refresh``, carry a
``jti`` that is blacklisted in ``revoked_tokens`` on rotation/logout.
Password-reset tokens: 30 minutes, ``type=password_reset``, carry only ``sub``.
"""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from jose import JWTError, jwt
from pydantic import BaseModel

from app.core.config import get_settings
from app.core.exceptions import AuthenticationError

TokenType = Literal["access", "refresh", "password_reset"]


class TokenPayload(BaseModel):
    sub: uuid.UUID
    jti: str
    type: TokenType
    iat: int
    exp: int
    iss: str
    aud: str


def _encode(user_id: uuid.UUID, token_type: TokenType, ttl: timedelta, jti: str) -> str:
    settings = get_settings()
    now = datetime.now(UTC)
    claims: dict[str, Any] = {
        "sub": str(user_id),
        "jti": jti,
        "type": token_type,
        "iat": int(now.timestamp()),
        "exp": int((now + ttl).timestamp()),
        "iss": settings.JWT_ISSUER,
        "aud": settings.JWT_AUDIENCE,
    }
    token: str = jwt.encode(claims, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)
    return token


def create_access_token(user_id: uuid.UUID, claims: dict[str, Any] | None = None) -> str:
    """Create a signed access token. ``claims`` is reserved for Phase 2+ extras."""
    del claims  # not embedded yet; access tokens stay minimal
    settings = get_settings()
    return _encode(
        user_id, "access", timedelta(minutes=settings.JWT_ACCESS_TTL_MINUTES), uuid.uuid4().hex
    )


def create_refresh_token(user_id: uuid.UUID, jti: str | None = None) -> str:
    """Create a signed refresh token with the supplied (or a new) jti."""
    settings = get_settings()
    return _encode(
        user_id, "refresh", timedelta(days=settings.JWT_REFRESH_TTL_DAYS), jti or uuid.uuid4().hex
    )


def create_password_reset_token(user_id: uuid.UUID) -> str:
    """Create a 30-minute password-reset token."""
    return _encode(user_id, "password_reset", timedelta(minutes=30), uuid.uuid4().hex)


def decode_token(token: str, expected_type: TokenType | None = None) -> TokenPayload:
    """Decode + validate a token; raises AuthenticationError on any failure."""
    settings = get_settings()
    try:
        raw = jwt.decode(
            token,
            settings.JWT_SECRET,
            algorithms=[settings.JWT_ALGORITHM],
            issuer=settings.JWT_ISSUER,
            audience=settings.JWT_AUDIENCE,
        )
        payload = TokenPayload.model_validate(raw)
    except (JWTError, ValueError) as exc:
        raise AuthenticationError("Invalid or expired token") from exc
    if expected_type is not None and payload.type != expected_type:
        raise AuthenticationError("Invalid or expired token")
    return payload
