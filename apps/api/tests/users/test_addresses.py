"""Address CRUD + PostGIS round-trip."""

import pytest
from geoalchemy2.shape import to_shape
from sqlalchemy import select

from app.auth.jwt import create_access_token
from app.users.models import Address


@pytest.mark.asyncio
async def test_address_create_and_postgis_round_trip(client, make_user, db_session):
    user = await make_user(db_session, email="addr@example.com")
    await db_session.commit()
    headers = {"Authorization": f"Bearer {create_access_token(user.id)}"}
    r = await client.post(
        "/api/v2/users/addresses",
        headers=headers,
        json={
            "label": "Home",
            "street": "1 Main",
            "city": "Nairobi",
            "phone": "+14155550100",
            "location": {"type": "Point", "coordinates": [36.8, -1.3]},
        },
    )
    assert r.status_code == 200
    body = r.json()["data"]
    assert body["location"] == [36.8, -1.3]

    row = (
        await db_session.execute(
            select(Address).where(Address.user_id == user.id)
        )
    ).scalar_one()
    geom = to_shape(row.location)
    assert abs(geom.x - 36.8) < 1e-6
    assert abs(geom.y - (-1.3)) < 1e-6


@pytest.mark.asyncio
async def test_address_list_isolation(client, make_user, db_session):
    a = await make_user(db_session, email="a@example.com")
    b = await make_user(db_session, email="b@example.com")
    await db_session.commit()

    for u in (a, b):
        await client.post(
            "/api/v2/users/addresses",
            headers={"Authorization": f"Bearer {create_access_token(u.id)}"},
            json={
                "label": "X",
                "street": "S",
                "city": "C",
                "phone": "+14155550001",
                "location": {"type": "Point", "coordinates": [0, 0]},
            },
        )

    r_a = await client.get(
        "/api/v2/users/addresses",
        headers={"Authorization": f"Bearer {create_access_token(a.id)}"},
    )
    assert r_a.status_code == 200
    assert len(r_a.json()["data"]) == 1


@pytest.mark.asyncio
async def test_address_delete_only_own(client, make_user, db_session):
    from sqlalchemy import select

    a = await make_user(db_session, email="aa@example.com")
    b = await make_user(db_session, email="bb@example.com")
    address = Address(
        user_id=a.id,
        label="X",
        street="S",
        city="C",
        phone="+14155550001",
        location=__import__("geoalchemy2").shape.from_shape(
            __import__("shapely.geometry", fromlist=["Point"]).Point(0, 0), srid=4326
        ),
    )
    db_session.add(address)
    await db_session.commit()
    await db_session.refresh(address)
    addr_id = address.id

    # b cannot delete a's address
    r = await client.delete(
        f"/api/v2/users/addresses/{addr_id}",
        headers={"Authorization": f"Bearer {create_access_token(b.id)}"},
    )
    assert r.status_code == 404

    # a can
    r2 = await client.delete(
        f"/api/v2/users/addresses/{addr_id}",
        headers={"Authorization": f"Bearer {create_access_token(a.id)}"},
    )
    assert r2.status_code == 200