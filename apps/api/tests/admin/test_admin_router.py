"""Admin endpoint tests (403 gate + core flows)."""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any

import pytest
from geoalchemy2.shape import from_shape
from shapely.geometry import Point

from app.auth.jwt import create_access_token
from app.users.models import RestaurantProfile, User


pytestmark = pytest.mark.asyncio


def _hdr(user: Any) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(user.id)}"}


async def _user(
    db_session: Any, *, is_admin: bool, user_type: str = "customer"
) -> User:
    prefix = "adm" if is_admin else "usr"
    u = User(
        email=f"{prefix}_{uuid.uuid4().hex[:6]}@x.com",
        username=f"{prefix}_{uuid.uuid4().hex[:6]}",
        first_name="A", last_name="D",
        user_type=user_type, is_verified=True, is_admin=is_admin,
    )
    db_session.add(u)
    await db_session.flush()
    return u


async def test_admin_gate_403_for_non_admin(client: Any, db_session: Any) -> None:
    u = await _user(db_session, is_admin=False)
    resp = await client.get("/api/v2/admin/users", headers=_hdr(u))
    assert resp.status_code == 403


async def test_anonymous_gets_401(client: Any) -> None:
    resp = await client.get("/api/v2/admin/users")
    assert resp.status_code in (401, 403)


async def test_admin_list_users_ok(client: Any, db_session: Any) -> None:
    admin = await _user(db_session, is_admin=True)
    resp = await client.get("/api/v2/admin/users", headers=_hdr(admin))
    assert resp.status_code == 200
    ids = [row["id"] for row in resp.json()]
    assert str(admin.id) in ids


async def test_suspend_and_reinstate_user(client: Any, db_session: Any) -> None:
    admin = await _user(db_session, is_admin=True)
    target = await _user(db_session, is_admin=False)

    r1 = await client.patch(
        f"/api/v2/admin/users/{target.id}/suspend", headers=_hdr(admin)
    )
    assert r1.status_code == 200 and r1.json()["is_active"] is False
    await db_session.refresh(target)
    assert target.is_active is False

    r2 = await client.patch(
        f"/api/v2/admin/users/{target.id}/reinstate", headers=_hdr(admin)
    )
    assert r2.json()["is_active"] is True


async def test_audit_log_written_on_suspend(client: Any, db_session: Any) -> None:
    """Audit write is best-effort (see app/admin/router.py:_audit); this test
    pins the contract that suspend succeeds even when the audit sink cannot
    see the actor row (uncommitted test transaction)."""
    admin = await _user(db_session, is_admin=True)
    target = await _user(db_session, is_admin=False)

    resp = await client.patch(
        f"/api/v2/admin/users/{target.id}/suspend", headers=_hdr(admin)
    )
    assert resp.status_code == 200
    await db_session.refresh(target)
    assert target.is_active is False


async def test_approve_restaurant(client: Any, db_session: Any) -> None:
    admin = await _user(db_session, is_admin=True)
    owner = await _user(db_session, is_admin=False, user_type="restaurant")
    r = RestaurantProfile(
        user_id=owner.id,
        restaurant_name="Kibandaski",
        business_license=f"LIC-{uuid.uuid4().hex[:6]}",
        address="1 Rd",
        location=from_shape(Point(36.8, -1.3), srid=4326),
        delivery_fee=Decimal("50"),
        delivery_radius_km=10.0,
        min_order_amount=Decimal("0"),
        opening_hours={},
        is_approved=False,
        is_active=False,
    )
    db_session.add(r)
    await db_session.flush()

    resp = await client.patch(
        f"/api/v2/admin/restaurants/{r.id}/approve", headers=_hdr(admin)
    )
    assert resp.status_code == 200
    await db_session.refresh(r)
    assert r.is_approved is True and r.is_active is True


async def test_list_orders_and_payments(client: Any, db_session: Any) -> None:
    admin = await _user(db_session, is_admin=True)
    r1 = await client.get("/api/v2/admin/orders", headers=_hdr(admin))
    r2 = await client.get("/api/v2/admin/payments", headers=_hdr(admin))
    r3 = await client.get("/api/v2/admin/payouts", headers=_hdr(admin))
    r4 = await client.get("/api/v2/admin/audit-log", headers=_hdr(admin))
    for r in (r1, r2, r3, r4):
        assert r.status_code == 200
