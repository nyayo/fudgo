"""POST /auth/register."""

import pytest
from sqlalchemy import select

from app.users.enums import UserType
from app.users.models import (
    CourierProfile,
    CustomerProfile,
    NotificationPreference,
    RestaurantProfile,
    User,
)
from tests.helpers import assert_success


@pytest.mark.asyncio
async def test_register_customer(client, db_session):
    r = await client.post(
        "/api/v2/auth/register",
        json={
            "user_type": "customer",
            "email": "c1@example.com",
            "first_name": "C",
            "last_name": "One",
            "password": "supersecret123",
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert_success(body, {"access", "refresh", "user", "can_link_google"})
    assert body["data"]["can_link_google"] is True

    user = (
        await db_session.execute(select(User).where(User.email == "c1@example.com"))
    ).scalar_one()
    assert user.user_type == UserType.customer
    assert user.is_verified is False
    profile = (
        await db_session.execute(select(CustomerProfile).where(CustomerProfile.user_id == user.id))
    ).scalar_one()
    assert profile.user_id == user.id
    pref = (
        await db_session.execute(
            select(NotificationPreference).where(NotificationPreference.user_id == user.id)
        )
    ).scalar_one()
    assert pref.receive_push is True


@pytest.mark.asyncio
async def test_register_courier(client, db_session):
    r = await client.post(
        "/api/v2/auth/register",
        json={
            "user_type": "courier",
            "email": "cou@example.com",
            "first_name": "Co",
            "last_name": "U",
            "password": "supersecret123",
            "profile_data": {"vehicle_type": "motorcycle"},
        },
    )
    assert r.status_code == 200
    user = (
        await db_session.execute(select(User).where(User.email == "cou@example.com"))
    ).scalar_one()
    prof = (
        await db_session.execute(select(CourierProfile).where(CourierProfile.user_id == user.id))
    ).scalar_one()
    assert prof.vehicle_type.value == "motorcycle"


@pytest.mark.asyncio
async def test_register_restaurant(client, db_session):
    r = await client.post(
        "/api/v2/auth/register",
        json={
            "user_type": "restaurant",
            "email": "rest@example.com",
            "first_name": "R",
            "last_name": "U",
            "password": "supersecret123",
            "profile_data": {
                "restaurant_name": "Mama's",
                "business_license": "LIC-001",
                "address": "1 Main St",
                "location": [36.8, -1.3],
            },
        },
    )
    assert r.status_code == 200
    user = (
        await db_session.execute(select(User).where(User.email == "rest@example.com"))
    ).scalar_one()
    prof = (
        await db_session.execute(
            select(RestaurantProfile).where(RestaurantProfile.user_id == user.id)
        )
    ).scalar_one()
    assert prof.restaurant_name == "Mama's"


@pytest.mark.asyncio
async def test_register_missing_first_name(client):
    r = await client.post(
        "/api/v2/auth/register",
        json={
            "user_type": "customer",
            "email": "x@example.com",
            "last_name": "U",
            "password": "supersecret123",
        },
    )
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_register_duplicate_email(client, make_user, db_session):
    user = await make_user(db_session, email="dup@example.com")
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


@pytest.mark.asyncio
async def test_register_username_collision(client, db_session):
    base = "collision@example.com"
    for i in range(3):
        r = await client.post(
            "/api/v2/auth/register",
            json={
                "user_type": "customer",
                "email": base,
                "first_name": "C",
                "last_name": "U",
                "password": "supersecret123",
            },
        )
        # second and third should 409
        if i == 0:
            assert r.status_code == 200
        else:
            assert r.status_code == 409
    users = (await db_session.execute(select(User).where(User.email == base))).scalars().all()
    assert len(users) == 1


@pytest.mark.asyncio
async def test_register_phone_sets_verified(client, db_session):
    r = await client.post(
        "/api/v2/auth/register",
        json={
            "user_type": "customer",
            "phone": "+14155557777",
            "first_name": "P",
            "last_name": "V",
            "password": "supersecret123",
        },
    )
    assert r.status_code == 200
    user = (await db_session.execute(select(User).where(User.phone == "+14155557777"))).scalar_one()
    assert user.is_verified is True
