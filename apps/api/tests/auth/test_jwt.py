"""JWT issuance, rotation, revocation, logout-all."""

import time

import pytest

from app.auth.jwt import (
    create_access_token,
    create_password_reset_token,
    create_refresh_token,
    decode_token,
)
from app.auth.service import register_user
from app.core.config import get_settings
from app.core.exceptions import AuthenticationError
from app.users.enums import UserType


@pytest.mark.asyncio
async def test_access_token_works_on_protected_endpoint(client, make_user, db_session):
    user = await make_user(db_session, email="a@example.com")
    await db_session.commit()
    token = create_access_token(user.id)
    r = await client.get(
        "/api/v2/auth/profile", headers={"Authorization": f"Bearer {token}"}
    )
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_expired_access_token_rejected(client, make_user, db_session):
    user = await make_user(db_session, email="exp@example.com")
    await db_session.commit()
    payload = decode_token(create_access_token(user.id))
    # Force-expire by waiting past exp (we can't easily fast-forward time, so
    # instead craft a token with an iat/exp in the past).
    import datetime as _dt

    settings = get_settings()
    from jose import jwt

    expired = jwt.encode(
        {
            "sub": str(user.id),
            "jti": "deadbeef",
            "type": "access",
            "iat": int(_dt.datetime.now(_dt.UTC).timestamp()) - 7200,
            "exp": int(_dt.datetime.now(_dt.UTC).timestamp()) - 3600,
            "iss": settings.JWT_ISSUER,
            "aud": settings.JWT_AUDIENCE,
        },
        settings.JWT_SECRET,
        algorithm=settings.JWT_ALGORITHM,
    )
    r = await client.get(
        "/api/v2/auth/profile", headers={"Authorization": f"Bearer {expired}"}
    )
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_refresh_rotates_and_revokes_old(client, db_session):
    result = await register_user(
        db_session,
        user_type=UserType.customer,
        email="rot@example.com",
        phone=None,
        first_name="R",
        last_name="U",
        password="supersecret123",
        profile_data={},
    )
    await db_session.commit()
    refresh = result["tokens"]["refresh"]

    r1 = await client.post(
        "/api/v2/auth/refresh", json={"refresh": refresh}
    )
    assert r1.status_code == 200
    new_pair = r1.json()["data"]

    r2 = await client.post(
        "/api/v2/auth/refresh", json={"refresh": refresh}
    )
    assert r2.status_code == 401
    # And the new refresh also works.
    r3 = await client.post(
        "/api/v2/auth/refresh", json={"refresh": new_pair["refresh"]}
    )
    assert r3.status_code == 200


@pytest.mark.asyncio
async def test_logout_revokes_refresh(client, db_session):
    result = await register_user(
        db_session,
        user_type=UserType.customer,
        email="lo@example.com",
        phone=None,
        first_name="L",
        last_name="O",
        password="supersecret123",
        profile_data={},
    )
    await db_session.commit()
    refresh = result["tokens"]["refresh"]
    access = result["tokens"]["access"]

    r = await client.post(
        "/api/v2/auth/logout",
        json={"refresh": refresh},
        headers={"Authorization": f"Bearer {access}"},
    )
    assert r.status_code == 200

    r2 = await client.post("/api/v2/auth/refresh", json={"refresh": refresh})
    assert r2.status_code == 401


@pytest.mark.asyncio
async def test_logout_all_revokes_all_refresh(client, db_session):
    result = await register_user(
        db_session,
        user_type=UserType.customer,
        email="all@example.com",
        phone=None,
        first_name="A",
        last_name="L",
        password="supersecret123",
        profile_data={},
    )
    await db_session.commit()
    access = result["tokens"]["access"]
    refresh = result["tokens"]["refresh"]

    r = await client.post(
        "/api/v2/auth/logout-all",
        headers={"Authorization": f"Bearer {access}"},
    )
    assert r.status_code == 200

    r2 = await client.post("/api/v2/auth/refresh", json={"refresh": refresh})
    assert r2.status_code == 401

    # Even new access token decoded fails because of logout-all check.
    access2 = create_access_token(__import__("uuid").UUID(result["user"]["id"]))
    r3 = await client.get(
        "/api/v2/auth/profile", headers={"Authorization": f"Bearer {access2}"}
    )
    assert r3.status_code == 401


@pytest.mark.asyncio
async def test_wrong_signature_rejected(client, make_user, db_session):
    user = await make_user(db_session, email="sig@example.com")
    await db_session.commit()
    from jose import jwt

    import datetime as _dt

    settings = get_settings()
    bad = jwt.encode(
        {
            "sub": str(user.id),
            "jti": "x",
            "type": "access",
            "iat": int(_dt.datetime.now(_dt.UTC).timestamp()),
            "exp": int(_dt.datetime.now(_dt.UTC).timestamp()) + 60,
            "iss": settings.JWT_ISSUER,
            "aud": settings.JWT_AUDIENCE,
        },
        "wrong-secret",
        algorithm=settings.JWT_ALGORITHM,
    )
    r = await client.get(
        "/api/v2/auth/profile", headers={"Authorization": f"Bearer {bad}"}
    )
    assert r.status_code == 401