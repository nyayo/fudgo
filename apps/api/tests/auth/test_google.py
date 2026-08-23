"""Google OAuth flow (with verify_google_id_token monkeypatched)."""

from unittest.mock import patch

import pytest
from sqlalchemy import select

from app.core.exceptions import AuthenticationError
from app.users.models import User
from tests.helpers import assert_success


@pytest.fixture
def fake_claims():
    return {
        "sub": "google-sub-1",
        "email": "g@example.com",
        "email_verified": True,
        "given_name": "G",
        "family_name": "U",
    }


@pytest.mark.asyncio
async def test_google_signin_new_user_creates_account(client, db_session, fake_claims):
    with patch("app.auth.router.verify_google_id_token", return_value=fake_claims):
        r = await client.post(
            "/api/v2/auth/google",
            json={"id_token": "fake", "user_type": "customer"},
        )
    assert r.status_code == 200
    body = r.json()
    assert_success(body, {"access", "refresh", "user", "can_link_google"})

    user = (
        await db_session.execute(select(User).where(User.email == "g@example.com"))
    ).scalar_one()
    assert user.auth_provider.value == "google"
    assert user.google_id == "google-sub-1"


@pytest.mark.asyncio
async def test_google_signin_existing_google_user(client, db_session, make_user):
    user = await make_user(
        db_session,
        email="gexist@example.com",
        auth_provider=__import__("app.users.enums", fromlist=["AuthProvider"]).AuthProvider.google,
    )
    user.google_id = "google-sub-existing"
    await db_session.commit()

    with patch(
        "app.auth.router.verify_google_id_token",
        return_value={
            "sub": "google-sub-existing",
            "email": "gexist@example.com",
            "email_verified": True,
        },
    ):
        r = await client.post(
            "/api/v2/auth/google",
            json={"id_token": "fake"},
        )
    assert r.status_code == 200
    body = r.json()
    assert body["data"]["user"]["id"] == str(user.id)


@pytest.mark.asyncio
async def test_google_signin_provider_switch(client, db_session, make_user):
    await make_user(db_session, email="conflict@example.com")  # auth_provider=email

    with patch(
        "app.auth.router.verify_google_id_token",
        return_value={
            "sub": "different",
            "email": "conflict@example.com",
            "email_verified": True,
        },
    ):
        r = await client.post("/api/v2/auth/google", json={"id_token": "fake"})
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_google_signin_invalid_token(client):
    with patch(
        "app.auth.router.verify_google_id_token",
        side_effect=AuthenticationError("Invalid Google ID token"),
    ):
        r = await client.post("/api/v2/auth/google", json={"id_token": "bad"})
    assert r.status_code == 401
