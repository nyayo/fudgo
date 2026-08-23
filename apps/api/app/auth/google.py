"""Google OAuth ID-token verification.

Phase 1 expects ``GOOGLE_CLIENT_ID`` to be set so audience is checked. Tests
monkeypatch :func:`verify_google_id_token` to avoid hitting Google.
"""

from typing import Any, cast

from google.auth.transport import requests as google_requests
from google.oauth2 import id_token

from app.core.config import get_settings
from app.core.exceptions import AuthenticationError


def verify_google_id_token(id_token_str: str) -> dict[str, Any]:
    """Verify a Google ID token and return its claims dict.

    Raises :class:`AuthenticationError` if verification fails for any reason.
    """
    settings = get_settings()
    try:
        # google.oauth2.id_token.verify_oauth2_token is loosely typed upstream
        # (returns Any). We cast at the boundary to keep our function's return
        # type honest.
        claims = id_token.verify_oauth2_token(
            id_token_str,
            google_requests.Request(),
            audience=settings.GOOGLE_CLIENT_ID or None,
        )
    except Exception as exc:  # google.auth raises broad exception types
        raise AuthenticationError("Invalid Google ID token") from exc
    if not claims.get("email"):
        raise AuthenticationError("Google account missing email")
    return cast(dict[str, Any], claims)
