"""User profile: GET, PATCH, isolation, role-specific fields."""

import pytest

from app.auth.jwt import create_access_token


@pytest.mark.asyncio
async def test_get_profile_includes_role_profile(client, make_user, db_session):
    from sqlalchemy import select

    from app.users.models import CustomerProfile

    user = await make_user(db_session, email="gp@example.com")
    db_session.add(CustomerProfile(user_id=user.id))
    await db_session.commit()

    headers = {"Authorization": f"Bearer {create_access_token(user.id)}"}
    r = await client.get("/api/v2/auth/profile", headers=headers)
    assert r.status_code == 200
    data = r.json()["data"]
    assert data["email"] == user.email
    assert "profile" in data


@pytest.mark.asyncio
async def test_patch_profile_top_level(client, make_user, db_session):
    user = await make_user(db_session, email="pp@example.com")
    await db_session.commit()
    headers = {"Authorization": f"Bearer {create_access_token(user.id)}"}
    r = await client.patch(
        "/api/v2/auth/profile",
        headers=headers,
        json={"first_name": "Updated", "last_name": "Name"},
    )
    assert r.status_code == 200
    assert r.json()["data"]["first_name"] == "Updated"


@pytest.mark.asyncio
async def test_patch_profile_role_specific(client, make_user, db_session):
    from app.users.enums import UserType
    from app.users.models import CourierProfile

    user = await make_user(
        db_session,
        email="pr@example.com",
        user_type=UserType.courier,
    )
    profile = CourierProfile(
        user_id=user.id, vehicle_type=__import__("app.users.enums", fromlist=["VehicleType"]).VehicleType.bike
    )
    db_session.add(profile)
    await db_session.commit()

    headers = {"Authorization": f"Bearer {create_access_token(user.id)}"}
    r = await client.patch(
        "/api/v2/auth/profile",
        headers=headers,
        json={"profile_data": {"vehicle_type": "car"}},
    )
    assert r.status_code == 200
    assert r.json()["data"]["profile"]["vehicle_type"] == "car"


@pytest.mark.asyncio
async def test_unauthenticated_profile_rejected(client):
    r = await client.get("/api/v2/auth/profile")
    assert r.status_code == 401