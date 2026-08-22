"""Device registration + test-notification (stub)."""

from unittest.mock import patch

import pytest

from app.auth.jwt import create_access_token


@pytest.mark.asyncio
async def test_register_device(client, make_user, db_session):
    from unittest.mock import AsyncMock, patch

    user = await make_user(db_session, email="d@example.com")
    await db_session.commit()
    headers = {"Authorization": f"Bearer {create_access_token(user.id)}"}
    with patch(
        "app.auth.router.push_service.register", new=AsyncMock()
    ) as mock_reg:
        r = await client.post(
            "/api/v2/auth/devices",
            headers=headers,
            json={"registration_id": "fcm-token-1", "platform": "android"},
        )
        assert r.status_code == 200
        assert mock_reg.called


@pytest.mark.asyncio
async def test_test_notification(client, make_user, db_session):
    from unittest.mock import AsyncMock, patch

    user = await make_user(db_session, email="d2@example.com")
    await db_session.commit()
    headers = {"Authorization": f"Bearer {create_access_token(user.id)}"}
    with patch(
        "app.auth.router.push_service.send", new=AsyncMock()
    ) as mock_send:
        r = await client.post("/api/v2/auth/test-notification", headers=headers)
        assert r.status_code == 200
        assert mock_send.called


@pytest.mark.asyncio
async def test_delete_device(client, make_user, db_session):
    from app.users.enums import DevicePlatform
    from app.users.models import Device

    user = await make_user(db_session, email="d3@example.com")
    device = Device(
        user_id=user.id,
        registration_id="fcm-2",
        platform=DevicePlatform.android,
    )
    db_session.add(device)
    await db_session.commit()
    headers = {"Authorization": f"Bearer {create_access_token(user.id)}"}
    r = await client.delete(
        f"/api/v2/auth/devices/{device.id}", headers=headers
    )
    assert r.status_code == 200