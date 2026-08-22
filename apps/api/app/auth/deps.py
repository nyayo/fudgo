"""Shared FastAPI dependencies: auth + rate limiting."""

from collections.abc import Callable

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from slowapi import Limiter
from slowapi.util import get_remote_address

from app.auth.jwt import decode_token
from app.auth.models import RevokedToken
from app.core.exceptions import AuthenticationError, PermissionError
from app.db.session import get_session as get_db_session
from app.users.enums import UserType
from app.users.models import User


# Re-exported convenience name so route modules can do
# ``from app.auth.deps import get_session``.
get_session = get_db_session


limiter = Limiter(key_func=get_remote_address)

bearer_scheme = HTTPBearer(auto_error=False)

_sentinel = object()


async def logout_all_revoked(session: AsyncSession, user_id: object) -> bool:
    """Return True if a live logout-all revocation exists for the user."""
    from datetime import UTC, datetime

    row = (
        await session.execute(
            select(RevokedToken.id).where(
                RevokedToken.revoked_at_user == user_id,
                RevokedToken.reason == "logout-all",
                RevokedToken.expires_at > datetime.now(UTC),
            )
        )
    ).first()
    return row is not None


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    session: AsyncSession = Depends(get_db_session),
) -> User:
    """Decode the access token and load the user; raises AuthenticationError."""
    if credentials is None:
        raise AuthenticationError("Missing bearer token")
    token = credentials.credentials
    payload = decode_token(token, expected_type="access")
    if await logout_all_revoked(session, payload.sub):
        raise AuthenticationError("Token revoked")
    user = (
        await session.execute(select(User).where(User.id == payload.sub))
    ).scalar_one_or_none()
    if user is None or not user.is_active:
        raise AuthenticationError("User not found or inactive")
    return user


def require_role(*allowed: UserType) -> Callable[..., object]:
    """Build a dependency that asserts the current user's role is allowed.

    With no arguments, behaves like :func:`get_current_user` (any
    authenticated user passes).
    """

    async def _check(user: User = Depends(get_current_user)) -> User:
        if allowed and user.user_type not in allowed:
            raise PermissionError("Insufficient permissions")
        return user

    return _check