"""WebSocket JWT validation.

Browsers cannot set custom headers on the WebSocket handshake, so the
access token is passed as a ``?token=`` query parameter. Validation uses
the same secret + algorithm as the HTTP-side JWT verification.
"""

from __future__ import annotations

from typing import Any

from fastapi import WebSocket
from jose import JWTError, jwt

from app.core.config import get_settings


def decode_ws_token(token: str) -> dict[str, Any] | None:
    """Decode a JWT issued by the HTTP-side auth. Returns the claims or None."""
    if not token:
        return None
    settings = get_settings()
    try:
        payload = jwt.decode(
            token,
            settings.JWT_SECRET,
            algorithms=[settings.JWT_ALGORITHM],
        )
        return payload  # type: ignore[no-any-return]
    except JWTError:
        return None


def extract_token(websocket: WebSocket) -> str | None:
    """Get the ``?token=`` from the WebSocket handshake URL."""
    return websocket.query_params.get("token")


async def authenticate_websocket(
    websocket: WebSocket,
) -> dict[str, Any] | None:
    """Validate ?token=...; returns claims or None."""
    token = extract_token(websocket)
    if not token:
        return None
    return decode_ws_token(token)
