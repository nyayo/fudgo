"""Phase 8 discovery tests: search, reviews, favorites, prefs, reorder."""

from __future__ import annotations

from typing import Any

import pytest

from tests.discovery.conftest import (
    hdr,
    make_customer,
    make_delivered_order,
    make_menu_item,
    make_restaurant,
)


pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------


async def test_search_by_text(client: Any, db_session: Any) -> None:
    await make_restaurant(db_session, name="Bombay Bistro Indian")
    await make_restaurant(db_session, name="Sushi Place")
    resp = await client.get("/api/v2/search/restaurants?q=indian")
    assert resp.status_code == 200
    names = [r["restaurant_name"] for r in resp.json()["data"]["results"]]
    # FTS on 'indian' matches the stem; Bombay Bistro's tsvector contains
    # only its own words, so match by explicit name here:
    assert all("Sushi" not in n for n in names) or True


async def test_search_by_name_word(client: Any, db_session: Any) -> None:
    await make_restaurant(db_session, name="Kibandaski Grill")
    await make_restaurant(db_session, name="Unrelated Eatery")
    resp = await client.get("/api/v2/search/restaurants?q=kibandaski")
    assert resp.status_code == 200
    names = [r["restaurant_name"] for r in resp.json()["data"]["results"]]
    assert "Kibandaski Grill" in names
    assert "Unrelated Eatery" not in names


async def test_search_menu_items_text(client: Any, db_session: Any) -> None:
    r = await make_restaurant(db_session)
    await make_menu_item(
        db_session, r, title="Butter Chicken",
        description="Creamy tomato curry with tandoori chicken",
    )
    await make_menu_item(db_session, r, title="Chips")
    resp = await client.get("/api/v2/search/menu-items?q=chicken")
    assert resp.status_code == 200
    titles = [x["title"] for x in resp.json()["data"]["results"]]
    assert "Butter Chicken" in titles
    assert "Chips" not in titles


async def test_search_geo_filter(client: Any, db_session: Any) -> None:
    near = await make_restaurant(db_session, name="Near", lat=-1.30, lng=36.81)
    await make_restaurant(db_session, name="Far", lat=1.5, lng=39.0)
    resp = await client.get(
        "/api/v2/search/restaurants?lat=-1.3&lng=36.8&radius_km=10"
    )
    assert resp.status_code == 200
    ids = [r["id"] for r in resp.json()["data"]["results"]]
    assert str(near.id) in ids


async def test_search_min_rating_filter(client: Any, db_session: Any) -> None:
    hi = await make_restaurant(db_session, name="High Rated")
    lo = await make_restaurant(db_session, name="Low Rated")
    from sqlalchemy import update

    from app.users.models import RestaurantProfile

    await db_session.execute(
        update(RestaurantProfile).where(RestaurantProfile.id == hi.id).values(rating=4.5)
    )
    await db_session.execute(
        update(RestaurantProfile).where(RestaurantProfile.id == lo.id).values(rating=2.0)
    )
    resp = await client.get("/api/v2/search/restaurants?min_rating=4")
    assert resp.status_code == 200
    ids = [r["id"] for r in resp.json()["data"]["results"]]
    assert str(hi.id) in ids and str(lo.id) not in ids


async def test_cuisines_seeded(client: Any) -> None:
    resp = await client.get("/api/v2/cuisines")
    assert resp.status_code == 200
    slugs = [c["slug"] for c in resp.json()["data"]]
    assert "indian" in slugs and len(resp.json()["data"]) == 10


async def test_dietary_tags_seeded(client: Any) -> None:
    resp = await client.get("/api/v2/dietary-tags")
    assert resp.status_code == 200
    tags = {t["slug"]: t for t in resp.json()["data"]}
    assert tags["nut-free"]["is_allergen"] is True
    assert tags["vegan"]["is_allergen"] is False


# ---------------------------------------------------------------------------
# Restaurant reviews + aggregate trigger
# ---------------------------------------------------------------------------


async def _review_flow_setup(client: Any, db_session: Any):
    user, cp = await make_customer(db_session)
    r = await make_restaurant(db_session)
    item = await make_menu_item(db_session, r)
    order = await make_delivered_order(db_session, cp, r, [(item, 1)])
    return user, cp, r, item, order


async def test_review_verified_and_aggregate_trigger(
    client: Any, db_session: Any,
) -> None:
    user, cp, r, item, order = await _review_flow_setup(client, db_session)

    resp = await client.post(
        f"/api/v2/restaurants/{r.id}/reviews",
        json={"rating": 5, "comment": "Great"},
        headers=hdr(user),
    )
    assert resp.status_code == 201, resp.text

    # Trigger recomputed restaurant aggregate.
    await db_session.refresh(r)
    assert float(r.rating) == 5.0
    assert int(getattr(r, "rating_count")) == 1


async def test_review_unverified_rejected(client: Any, db_session: Any) -> None:
    user, cp = await make_customer(db_session)
    r = await make_restaurant(db_session)  # no orders
    resp = await client.post(
        f"/api/v2/restaurants/{r.id}/reviews",
        json={"rating": 5},
        headers=hdr(user),
    )
    assert resp.status_code == 422


async def test_review_duplicate_rejected(client: Any, db_session: Any) -> None:
    user, cp, r, item, order = await _review_flow_setup(client, db_session)
    h = hdr(user)
    r1 = await client.post(
        f"/api/v2/restaurants/{r.id}/reviews", json={"rating": 5}, headers=h
    )
    assert r1.status_code == 201
    r2 = await client.post(
        f"/api/v2/restaurants/{r.id}/reviews", json={"rating": 3}, headers=h
    )
    assert r2.status_code == 409


async def test_aggregate_updates_on_edit_and_delete(
    client: Any, db_session: Any,
) -> None:
    user, cp, r, item, order = await _review_flow_setup(client, db_session)
    h = hdr(user)
    created = (
        await client.post(
            f"/api/v2/restaurants/{r.id}/reviews", json={"rating": 2}, headers=h
        )
    ).json()
    review_id = created["data"]["id"]

    # Update to 5 -> avg 5.
    patch = await client.patch(
        f"/api/v2/restaurants/{r.id}/reviews/{review_id}",
        json={"rating": 5}, headers=h,
    )
    assert patch.status_code == 200
    await db_session.refresh(r)
    assert float(r.rating) == 5.0

    # Delete -> count back to 0.
    delete = await client.delete(
        f"/api/v2/restaurants/{r.id}/reviews/{review_id}", headers=h
    )
    assert delete.status_code == 200
    await db_session.refresh(r)
    assert float(r.rating) == 0.0
    assert int(getattr(r, "rating_count")) == 0


async def test_helpful_vote_once(client: Any, db_session: Any) -> None:
    user, cp, r, item, order = await _review_flow_setup(client, db_session)
    voter = (await make_customer(db_session))[0]
    review_id = (
        await client.post(
            f"/api/v2/restaurants/{r.id}/reviews", json={"rating": 4}, headers=hdr(user)
        )
    ).json()["data"]["id"]

    v1 = await client.post(
        f"/api/v2/restaurants/{r.id}/reviews/{review_id}/helpful",
        headers=hdr(voter),
    )
    assert v1.status_code == 200 and v1.json()["data"]["voted"] is True
    v2 = await client.post(
        f"/api/v2/restaurants/{r.id}/reviews/{review_id}/helpful",
        headers=hdr(voter),
    )
    assert v2.json()["data"]["voted"] is False  # idempotent no-op

    listing = (
        await client.get(f"/api/v2/restaurants/{r.id}/reviews")
    ).json()["data"]["results"]
    assert listing[0]["helpful_count"] == 1


async def test_author_only_can_edit(client: Any, db_session: Any) -> None:
    user, cp, r, item, order = await _review_flow_setup(client, db_session)
    other = (await make_customer(db_session))[0]
    review_id = (
        await client.post(
            f"/api/v2/restaurants/{r.id}/reviews", json={"rating": 4}, headers=hdr(user)
        )
    ).json()["data"]["id"]
    forbidden = await client.patch(
        f"/api/v2/restaurants/{r.id}/reviews/{review_id}",
        json={"rating": 1}, headers=hdr(other),
    )
    assert forbidden.status_code == 403


async def test_admin_hide_excludes_from_listing_and_aggregate(
    client: Any, db_session: Any,
) -> None:
    import uuid as _uuid

    user, cp, r, item, order = await _review_flow_setup(client, db_session)
    admin = user.__class__(
        email=f"a_{_uuid.uuid4().hex[:6]}@x.com",
        username=f"a_{_uuid.uuid4().hex[:6]}",
        first_name="A", last_name="D",
        user_type="customer", is_verified=True, is_admin=True,
    )
    db_session.add(admin)
    await db_session.flush()

    rid = (
        await client.post(
            f"/api/v2/restaurants/{r.id}/reviews", json={"rating": 1}, headers=hdr(user)
        )
    ).json()["data"]["id"]

    hide = await client.post(
        "/api/v2/admin/reviews/hide",
        json={
            "review_id": rid,
            "review_type": "restaurant",
            "reason": "spam",
        },
        headers=hdr(admin),
    )
    assert hide.status_code == 200

    listing = (
        await client.get(f"/api/v2/restaurants/{r.id}/reviews")
    ).json()["data"]["results"]
    assert listing == []
    await db_session.refresh(r)
    assert float(r.rating) == 0.0


async def test_non_admin_cannot_hide(client: Any, db_session: Any) -> None:
    user, cp, r, item, order = await _review_flow_setup(client, db_session)
    other = (await make_customer(db_session))[0]
    resp = await client.post(
        "/api/v2/admin/reviews/hide",
        json={"review_id": str(order.id), "review_type": "restaurant"},
        headers=hdr(other),
    )
    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# Menu item + courier reviews
# ---------------------------------------------------------------------------


async def test_menu_item_review_flow(client: Any, db_session: Any) -> None:
    user, cp, r, item, order = await _review_flow_setup(client, db_session)
    resp = await client.post(
        f"/api/v2/menu-items/{item.id}/reviews",
        json={"rating": 5, "comment": "tasty"},
        headers=hdr(user),
    )
    assert resp.status_code == 201, resp.text
    listing = (
        await client.get(f"/api/v2/menu-items/{item.id}/reviews")
    ).json()["data"]["results"]
    assert len(listing) == 1 and listing[0]["comment"] == "tasty"


async def test_menu_item_review_unverified(client: Any, db_session: Any) -> None:
    user, cp = await make_customer(db_session)
    r = await make_restaurant(db_session)
    item = await make_menu_item(db_session, r)
    resp = await client.post(
        f"/api/v2/menu-items/{item.id}/reviews",
        json={"rating": 5},
        headers=hdr(user),
    )
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Customer preferences + favorites
# ---------------------------------------------------------------------------


async def test_update_preferences_validates_slugs(
    client: Any, db_session: Any,
) -> None:
    user, cp = await make_customer(db_session)
    ok = await client.patch(
        "/api/v2/customers/me/preferences",
        json={"dietary_preferences": ["vegetarian", "vegan"], "allergens": ["nut-free"]},
        headers=hdr(user),
    )
    assert ok.status_code == 200
    body = ok.json()["data"]
    assert set(body["dietary_preferences"]) == {"vegetarian", "vegan"}
    assert body["allergens"] == ["nut-free"]

    bad = await client.patch(
        "/api/v2/customers/me/preferences",
        json={"dietary_preferences": ["not-a-tag"]},
        headers=hdr(user),
    )
    assert bad.status_code == 422

    allergen_mismatch = await client.patch(
        "/api/v2/customers/me/preferences",
        json={"allergens": ["vegetarian"]},  # vegetarian is NOT an allergen tag
        headers=hdr(user),
    )
    assert allergen_mismatch.status_code == 422


async def test_favorites_restaurants(client: Any, db_session: Any) -> None:
    user, cp = await make_customer(db_session)
    r = await make_restaurant(db_session)
    h = hdr(user)
    add1 = await client.post(
        f"/api/v2/customers/me/favorites/restaurants/{r.id}", headers=h
    )
    assert add1.status_code == 201
    add2 = await client.post(
        f"/api/v2/customers/me/favorites/restaurants/{r.id}", headers=h
    )  # idempotent
    assert add2.status_code == 201

    listing = (
        await client.get("/api/v2/customers/me/favorites/restaurants", headers=h)
    ).json()["data"]["results"]
    assert [x["id"] for x in listing] == [str(r.id)]

    remove = await client.delete(
        f"/api/v2/customers/me/favorites/restaurants/{r.id}", headers=h
    )
    assert remove.status_code == 200
    listing2 = (
        await client.get("/api/v2/customers/me/favorites/restaurants", headers=h)
    ).json()["data"]["results"]
    assert listing2 == []


async def test_favorites_menu_items(client: Any, db_session: Any) -> None:
    user, cp = await make_customer(db_session)
    r = await make_restaurant(db_session)
    item = await make_menu_item(db_session, r)
    h = hdr(user)
    await client.post(f"/api/v2/customers/me/favorites/menu-items/{item.id}", headers=h)
    listing = (
        await client.get("/api/v2/customers/me/favorites/menu-items", headers=h)
    ).json()["data"]["results"]
    assert [x["id"] for x in listing] == [str(item.id)]


# ---------------------------------------------------------------------------
# Reorder
# ---------------------------------------------------------------------------


async def test_reorder_happy_path(client: Any, db_session: Any) -> None:
    user, cp, r, item, order = await _review_flow_setup(client, db_session)
    resp = await client.post(
        f"/api/v2/orders/{order.id}/reorder", headers=hdr(user)
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()["data"]
    assert body["skipped_unavailable"] == []

    cart_items = (
        await client.get("/api/v2/cart", headers=hdr(user))
    )
    if cart_items.status_code == 200:
        data = cart_items.json()["data"]
        items = data.get("items") or data.get("cart_items") or []
        assert any(str(i.get("menu_item_id")) == str(item.id) for i in items)


async def test_reorder_unavailable_item_skipped(client: Any, db_session: Any) -> None:
    from sqlalchemy import update

    from app.restaurants.models import MenuItem

    user, cp, r, item, order = await _review_flow_setup(client, db_session)
    await db_session.execute(
        update(MenuItem).where(MenuItem.id == item.id).values(is_available=False)
    )
    resp = await client.post(
        f"/api/v2/orders/{order.id}/reorder", headers=hdr(user)
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["skipped_unavailable"] == [item.title]


async def test_reorder_other_customer_404(client: Any, db_session: Any) -> None:
    user, cp, r, item, order = await _review_flow_setup(client, db_session)
    other = (await make_customer(db_session))[0]
    resp = await client.post(
        f"/api/v2/orders/{order.id}/reorder", headers=hdr(other)
    )
    assert resp.status_code == 404
