"""Restaurant staff CRUD + isolation."""

import pytest

from app.auth.jwt import create_access_token
from app.users.enums import UserType


@pytest.mark.asyncio
async def test_customer_cannot_manage_staff(client, make_user, db_session):
    user = await make_user(db_session, email="cust@example.com", user_type=UserType.customer)
    await db_session.commit()
    headers = {"Authorization": f"Bearer {create_access_token(user.id)}"}
    r = await client.get("/api/v2/users/staff", headers=headers)
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_restaurant_owner_can_create_and_list_staff(client, make_user, db_session):
    owner = await make_user(db_session, email="owner@example.com", user_type=UserType.restaurant)
    from app.users.models import RestaurantProfile

    db_session.add(
        RestaurantProfile(
            user_id=owner.id,
            restaurant_name="R",
            business_license="LIC-1",
            address="1 Main St",
            location=__import__("geoalchemy2").shape.from_shape(
                __import__("shapely.geometry", fromlist=["Point"]).Point(0, 0), srid=4326
            ),
        )
    )
    await db_session.commit()

    headers = {"Authorization": f"Bearer {create_access_token(owner.id)}"}
    create = await client.post(
        "/api/v2/users/staff",
        headers=headers,
        json={
            "email": "staff@example.com",
            "first_name": "S",
            "last_name": "T",
            "phone": "+14155550200",
            "password": "supersecret123",
            "role": "manager",
        },
    )
    assert create.status_code == 200

    listing = await client.get("/api/v2/users/staff", headers=headers)
    assert listing.status_code == 200
    assert len(listing.json()["data"]) == 1


@pytest.mark.asyncio
async def test_cross_restaurant_staff_access_forbidden(client, make_user, db_session):
    from app.users.models import RestaurantProfile

    a = await make_user(db_session, email="oa@example.com", user_type=UserType.restaurant)
    b = await make_user(db_session, email="ob@example.com", user_type=UserType.restaurant)
    rest_a = RestaurantProfile(
        user_id=a.id,
        restaurant_name="A",
        business_license="LA",
        address="1 A St",
        location=__import__("geoalchemy2").shape.from_shape(
            __import__("shapely.geometry", fromlist=["Point"]).Point(0, 0), srid=4326
        ),
    )
    rest_b = RestaurantProfile(
        user_id=b.id,
        restaurant_name="B",
        business_license="LB",
        address="1 B St",
        location=__import__("geoalchemy2").shape.from_shape(
            __import__("shapely.geometry", fromlist=["Point"]).Point(0, 0), srid=4326
        ),
    )
    db_session.add_all([rest_a, rest_b])
    await db_session.commit()
    await db_session.refresh(rest_a)
    await db_session.refresh(rest_b)

    # A creates staff
    create = await client.post(
        "/api/v2/users/staff",
        headers={"Authorization": f"Bearer {create_access_token(a.id)}"},
        json={
            "email": "shared@example.com",
            "first_name": "S",
            "last_name": "T",
            "phone": "+14155550300",
            "password": "supersecret123",
            "role": "waiter",
        },
    )
    assert create.status_code == 200
    staff_id = create.json()["data"]["id"]

    # B tries to delete A's staff
    r = await client.delete(
        f"/api/v2/users/staff/{staff_id}",
        headers={"Authorization": f"Bearer {create_access_token(b.id)}"},
    )
    assert r.status_code == 404
