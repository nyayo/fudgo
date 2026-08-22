"""Notification preferences endpoints."""

import pytest
from sqlalchemy import select

from app.auth.jwt import create_access_token
from app.users.models import NotificationPreference


@pytest.mark.asyncio
async def test_get_notification_prefs_defaults(client, make_user, db_session):
    user = await make_user(db_session, email="np@example.com")
    await db_session.commit()
    headers = {"Authorization": f"Bearer {create_access_token(user.id)}"}
    r = await client.get("/api/v2/auth/notification-preferences", headers=headers)
    assert r.status_code == 200
    data = r.json()["data"]
    assert data["receive_push"] is True
    assert data["receive_email"] is True

    row = (
        await db_session.execute(
            select(NotificationPreference).where(
                NotificationPreference.user_id == user.id
            )
        )
    ).scalar_one()
    assert row is not None


@pytest.mark.asyncio
async def test_patch_notification_prefs(client, make_user, db_session):
    user = await make_user(db_session, email="np2@example.com")
    await db_session.commit()
    headers = {"Authorization": f"Bearer {create_access_token(user.id)}"}
    r = await client.patch(
        "/api/v2/auth/notification-preferences",
        headers=headers,
        json={"receive_push": False, "promotions_and_offers": False},
    )
    assert r.status_code == 200
    data = r.json()["data"]
    assert data["receive_push"] is False
    assert data["promotions_and_offers"] is False
    assert data["receive_email"] is True  # untouched