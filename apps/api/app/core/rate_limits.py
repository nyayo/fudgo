"""Centralized rate limits (Phase 7).

slowapi consumes these. Keying: authenticated user_id when available,
else client IP.
"""

from __future__ import annotations

from typing import Any

from slowapi.util import get_remote_address


def get_user_or_ip_key(request: Any) -> str:
    """Use the authenticated user_id if available, else the IP address."""
    user = getattr(request.state, "user", None)
    if user is not None and getattr(user, "id", None):
        return f"user:{user.id}"
    return f"ip:{get_remote_address(request)}"


# Default: 60 req/min per user
DEFAULT_LIMIT = "60/minute"

# Per-endpoint overrides
AUTH_STRICT = "5/minute"  # /auth/login, /auth/register
AUTH_RELAXED = "30/minute"  # /auth/refresh
PAYMENT_STRICT = "10/minute"  # /orders/{id}/pay, /payments/{id}/refund
COURIER_HEARTBEAT = "20/minute"  # /courier/heartbeat (slowapi min unit is minute)
SEARCH_RELAXED = "30/minute"  # /restaurants/nearby
