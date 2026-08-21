"""Application exception hierarchy.

Every domain error is an :class:`AppError` carrying an HTTP ``code``, a human
``message``, and an optional ``details`` mapping. The handler registered in
``app/main.py`` serializes these into the v1 error envelope.
"""

from typing import Any


class AppError(Exception):
    """Base class for all handled application errors."""

    code: int = 500
    message: str = "Internal server error"

    def __init__(
        self,
        message: str | None = None,
        code: int | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        if message is not None:
            self.message = message
        if code is not None:
            self.code = code
        self.details = details
        super().__init__(self.message)


class NotFoundError(AppError):
    """404 — the requested resource does not exist."""

    code = 404
    message = "Not found"


class ValidationError(AppError):
    """422 — caller supplied invalid data."""

    code = 422
    message = "Validation error"


class AuthenticationError(AppError):
    """401 — missing or invalid credentials."""

    code = 401
    message = "Authentication failed"


class PermissionError(AppError):
    """403 — authenticated but not allowed."""

    code = 403
    message = "Permission denied"


class ConflictError(AppError):
    """409 — the operation conflicts with current state."""

    code = 409
    message = "Conflict"


class RateLimitError(AppError):
    """429 — too many requests."""

    code = 429
    message = "Rate limit exceeded"


class InternalError(AppError):
    """500 — unexpected server-side failure."""

    code = 500
    message = "Internal server error"
