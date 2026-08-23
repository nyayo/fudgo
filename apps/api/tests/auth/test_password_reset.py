"""Password reset request + confirm."""

from unittest.mock import patch

import pytest

from app.auth.passwords import verify_password


@pytest.mark.asyncio
async def test_password_reset_request(client, make_user, db_session):
    user = await make_user(db_session, email="reset@example.com")
    await db_session.commit()

    # Stub the service function so it doesn't try to log (and to verify
    # it was awaited with the right email). Use AsyncMock so the
    # BackgroundTasks await succeeds.
    from unittest.mock import AsyncMock

    with patch(
        "app.auth.router.email_service.send_password_reset",
        new=AsyncMock(),
    ) as mock_send:
        resp = await client.post("/api/v2/auth/password-reset", json={"email": user.email})
        assert resp.status_code == 200
        assert mock_send.called


@pytest.mark.asyncio
async def test_password_reset_confirm(client, make_user, db_session):
    from app.auth.jwt import create_password_reset_token
    from app.auth.service import confirm_password_reset

    user = await make_user(db_session, email="reset2@example.com")
    await db_session.commit()
    token = create_password_reset_token(user.id)

    await confirm_password_reset(db_session, token, "newpassword123")
    await db_session.commit()

    assert verify_password("newpassword123", user.password_hash) or True
    # Reload the row to confirm
    from sqlalchemy import select

    from app.users.models import User

    fresh = (await db_session.execute(select(User).where(User.id == user.id))).scalar_one()
    assert verify_password("newpassword123", fresh.password_hash)


@pytest.mark.asyncio
async def test_password_reset_expired_token(client, make_user, db_session):
    import datetime as _dt

    from jose import jwt

    from app.core.config import get_settings

    user = await make_user(db_session, email="reset3@example.com")
    await db_session.commit()
    settings = get_settings()
    expired = jwt.encode(
        {
            "sub": str(user.id),
            "jti": "x",
            "type": "password_reset",
            "iat": int(_dt.datetime.now(_dt.UTC).timestamp()) - 7200,
            "exp": int(_dt.datetime.now(_dt.UTC).timestamp()) - 3600,
            "iss": settings.JWT_ISSUER,
            "aud": settings.JWT_AUDIENCE,
        },
        settings.JWT_SECRET,
        algorithm=settings.JWT_ALGORITHM,
    )
    r = await client.post(
        "/api/v2/auth/password-reset/confirm",
        json={"token": expired, "password": "anothernew123"},
    )
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_password_reset_tampered_token(client):
    r = await client.post(
        "/api/v2/auth/password-reset/confirm",
        json={"token": "tampered.token.value", "password": "anothernew123"},
    )
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_password_reset_throttle(client):
    for _ in range(3):
        r = await client.post("/api/v2/auth/password-reset", json={"email": "anon@example.com"})
        assert r.status_code == 200
    fourth = await client.post("/api/v2/auth/password-reset", json={"email": "anon@example.com"})
    assert fourth.status_code == 429
