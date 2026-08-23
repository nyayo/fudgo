"""Envelope shape: every error returns {success:false, error:{code,message,details}}."""

import pytest


@pytest.mark.asyncio
async def test_validation_error_envelope(client):
    r = await client.post("/api/v2/auth/request-otp", json={"email": "bad"})
    assert r.status_code == 422
    body = r.json()
    assert body["success"] is False
    assert body["error"]["code"] == 422
    assert isinstance(body["error"]["message"], str)
    assert isinstance(body["error"]["details"], dict)


@pytest.mark.asyncio
async def test_auth_error_envelope(client, make_user, db_session):
    await make_user(db_session, email="ae@example.com")
    await db_session.commit()
    r = await client.get("/api/v2/auth/profile", headers={"Authorization": "Bearer not-a-token"})
    assert r.status_code == 401
    body = r.json()
    assert body["success"] is False
    assert body["error"]["code"] == 401


@pytest.mark.asyncio
async def test_not_found_envelope(client, make_user, db_session):
    from app.auth.jwt import create_access_token

    user = await make_user(db_session, email="nf@example.com")
    await db_session.commit()
    r = await client.delete(
        "/api/v2/users/addresses/00000000-0000-0000-0000-000000000000",
        headers={"Authorization": f"Bearer {create_access_token(user.id)}"},
    )
    assert r.status_code == 404
    body = r.json()
    assert body["success"] is False
    assert body["error"]["code"] == 404


@pytest.mark.asyncio
async def test_conflict_envelope(client, make_user, db_session):
    user = await make_user(db_session, email="c@example.com")
    await db_session.commit()
    r = await client.post(
        "/api/v2/auth/register",
        json={
            "user_type": "customer",
            "email": user.email,
            "first_name": "X",
            "last_name": "Y",
            "password": "supersecret123",
        },
    )
    assert r.status_code == 409
    body = r.json()
    assert body["success"] is False
    assert body["error"]["code"] == 409
