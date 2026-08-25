"""Search service — Postgres FTS for restaurants and menu items.

The ``fts`` tsvector columns are GENERATED ALWAYS (maintained by Postgres);
queries use ``plainto_tsquery`` + ``ts_rank`` with a rating tiebreaker.
Geo filtering uses the asyncpg-safe pattern from Phase 5: WKT passed
through ``ST_GeogFromText(CAST(:pt AS text))`` — never ``::type`` casts.
"""

from __future__ import annotations

import base64
import binascii
import json
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from geoalchemy2.shape import to_shape
from shapely.geometry import Point
from sqlalchemy import String, and_, bindparam, cast, func, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.restaurants.models import MenuItem
from app.users.models import RestaurantProfile


# ---------------------------------------------------------------------------
# Cursor helpers
# ---------------------------------------------------------------------------


def encode_cursor(created_at: Any, id_: UUID) -> str:
    raw = json.dumps(
        {
            "t": created_at.isoformat()
            if hasattr(created_at, "isoformat")
            else str(created_at),
            "i": str(id_),
        }
    )
    return base64.urlsafe_b64encode(raw.encode()).decode()


def decode_cursor(cursor: str) -> tuple[datetime, UUID] | None:
    try:
        raw = base64.urlsafe_b64decode(cursor.encode()).decode()
        data = json.loads(raw)
        return datetime.fromisoformat(data["t"]), UUID(data["i"])
    except (binascii.Error, ValueError, KeyError, TypeError):
        return None


# ---------------------------------------------------------------------------
# Serialization
# ---------------------------------------------------------------------------


def _minutes(s: str) -> int | None:
    p = s.strip().split(":")
    return int(p[0]) * 60 + int(p[1]) if len(p) == 2 else None


def restaurant_is_open(hours: dict[str, Any] | str | None) -> bool:
    """Cheap open check; defaults False when hours missing/unparseable."""
    if isinstance(hours, str):
        try:
            hours = json.loads(hours)
        except Exception:
            return False
    if not isinstance(hours, dict):
        return False
    try:
        if not hours:
            return False
        now = datetime.now(UTC)
        day = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"][now.weekday()]
        window = hours.get(day)
        if not window or "-" not in str(window):
            return False
        start_s, end_s = str(window).split("-", 1)
        start, end = _minutes(start_s), _mins_safe(end_s)
        if start is None or end is None:
            return False
        cur = now.hour * 60 + now.minute
        if start <= end:
            return start <= cur <= end
        return cur >= start or cur <= end  # overnight window
    except Exception:
        return False


def _mins_safe(s: str) -> int | None:
    return _minutes(s)


def _serialize_restaurant_summary(
    r: Any, distance_km: float | None = None
) -> dict[str, Any]:
    out: dict[str, Any] = {
        "id": str(r.id),
        "restaurant_name": r.restaurant_name,
        "address": r.address,
        "rating": float(r.rating or 0),
        "rating_count": int(getattr(r, "rating_count", 0) or 0),
        "delivery_fee": float(r.delivery_fee or 0),
        "min_order_amount": float(r.min_order_amount or 0),
        "is_open": restaurant_is_open(getattr(r, "opening_hours", None)),
    }
    if distance_km is not None:
        out["distance_km"] = round(distance_km, 2)
    return out


def _serialize_item_summary(m: Any) -> dict[str, Any]:
    return {
        "id": str(m.id),
        "title": m.title,
        "price": float(m.price or 0),
        "restaurant_id": str(m.restaurant_id),
        "category_id": str(m.category_id),
        "is_available": bool(m.is_available),
    }


# ---------------------------------------------------------------------------
# Search entry points
# ---------------------------------------------------------------------------


async def search_restaurants(
    session: AsyncSession,
    *,
    q: str | None = None,
    cuisine_slugs: list[str] | None = None,
    dietary_slugs: list[str] | None = None,
    min_rating: float | None = None,
    lat: float | None = None,
    lng: float | None = None,
    radius_km: float | None = None,
    cursor: str | None = None,
    limit: int | None = None,
) -> tuple[list[dict[str, Any]], str | None]:
    s = get_settings()
    lim = min(limit or s.SEARCH_RESULTS_DEFAULT_LIMIT, s.SEARCH_RESULTS_MAX_LIMIT)

    stmt = select(RestaurantProfile).where(
        RestaurantProfile.is_approved == True,  # noqa: E712
        RestaurantProfile.is_active == True,  # noqa: E712
    )

    rank_col = None
    if q:
        ts_query = func.plainto_tsquery("english", q)
        fts_col = func.to_tsvector("english", text("restaurant_profiles.fts"))
        # The column is already tsvector; reference it via literal SQL and
        # use the @@ operator through raw comparison.
        stmt = stmt.where(text("restaurant_profiles.fts @@ plainto_tsquery('english', :q)").bindparams(bindparam("q")))
        stmt = stmt.params(q=q)
        rank_col = func.ts_rank(text("restaurant_profiles.fts"), ts_query).label("rank")

    if cuisine_slugs:
        stmt = stmt.where(
            text(
                "EXISTS (SELECT 1 FROM restaurant_cuisines rc "
                "JOIN cuisines c ON c.id = rc.cuisine_id "
                "WHERE rc.restaurant_id = restaurant_profiles.id "
                "AND c.slug = ANY(:slugs))"
            ).bindparams(bindparam("slugs"))
        )
        stmt = stmt.params(slugs=cuisine_slugs)

    if min_rating is not None:
        stmt = stmt.where(RestaurantProfile.rating >= float(min_rating))

    distance_m_expr = None
    if lat is not None and lng is not None and radius_km is not None:
        point_wkt = Point(lng, lat).wkt
        geo = func.ST_GeogFromText(cast(point_wkt, String))
        distance_m_expr = func.ST_Distance(RestaurantProfile.location, geo).label(
            "distance_m"
        )
        stmt = stmt.where(
            func.ST_DWithin(
                RestaurantProfile.location, geo, float(radius_km) * 1000
            )
        )

    if cursor:
        decoded = decode_cursor(cursor)
        if decoded is not None:
            last_ts, last_id = decoded
            stmt = stmt.where(
                or_(
                    RestaurantProfile.created_at < last_ts,
                    and_(
                        RestaurantProfile.created_at == last_ts,
                        RestaurantProfile.id < last_id,
                    ),
                )
            )

    if rank_col is not None:
        stmt = stmt.order_by(rank_col.desc(), RestaurantProfile.rating.desc())
    elif distance_m_expr is not None:
        stmt = stmt.order_by(distance_m_expr.asc())
    else:
        stmt = stmt.order_by(
            RestaurantProfile.rating.desc(), RestaurantProfile.id.desc()
        )

    rows = (await session.execute(stmt.limit(lim))).scalars().all()

    results: list[dict[str, Any]] = []
    for r in rows:
        dist: float | None = None
        if lat is not None and lng is not None and r.location is not None:
            rp = to_shape(r.location)
            from app.deliveries.tasks import _haversine_km

            dist = _haversine_km(lat, lng, rp.y, rp.x)
        results.append(_serialize_restaurant_summary(r, dist))

    next_cursor = (
        encode_cursor(rows[-1].created_at, rows[-1].id)
        if rows and len(rows) == lim
        else None
    )
    return results, next_cursor


async def search_menu_items(
    session: AsyncSession,
    *,
    q: str | None = None,
    restaurant_id: UUID | None = None,
    dietary_slugs: list[str] | None = None,
    price_max: float | None = None,
    only_available: bool = True,
    cursor: str | None = None,
    limit: int | None = None,
) -> tuple[list[dict[str, Any]], str | None]:
    s = get_settings()
    lim = min(limit or s.SEARCH_RESULTS_DEFAULT_LIMIT, s.SEARCH_RESULTS_MAX_LIMIT)

    stmt = select(MenuItem)
    if only_available:
        stmt = stmt.where(MenuItem.is_available == True)  # noqa: E712

    if q:
        stmt = stmt.where(
            text("menu_items.fts @@ plainto_tsquery('english', :mq)").bindparams(
                bindparam("mq")
            )
        )
        stmt = stmt.params(mq=q)

    if restaurant_id is not None:
        stmt = stmt.where(MenuItem.restaurant_id == restaurant_id)

    if price_max is not None:
        stmt = stmt.where(MenuItem.price <= float(price_max))

    if dietary_slugs:
        stmt = stmt.where(
            text(
                "EXISTS (SELECT 1 FROM menu_item_dietary_tags mt "
                "JOIN dietary_tags dt ON dt.id = mt.dietary_tag_id "
                "WHERE mt.menu_item_id = menu_items.id "
                "AND dt.slug = ANY(:slugs))"
            ).bindparams(bindparam("slugs"))
        )
        stmt = stmt.params(slugs=dietary_slugs)

    if cursor:
        decoded = decode_cursor(cursor)
        if decoded is not None:
            last_ts, last_id = decoded
            stmt = stmt.where(
                or_(
                    MenuItem.created_at < last_ts,
                    and_(MenuItem.created_at == last_ts, MenuItem.id < last_id),
                )
            )

    rows = (
        await session.execute(
            stmt.order_by(MenuItem.created_at.desc(), MenuItem.id.desc()).limit(lim)
        )
    ).scalars().all()

    results = [_serialize_item_summary(m) for m in rows]
    next_cursor = (
        encode_cursor(rows[-1].created_at, rows[-1].id)
        if rows and len(rows) == lim
        else None
    )
    return results, next_cursor


async def search_global(
    session: AsyncSession, q: str, limit: int | None = None
) -> dict[str, Any]:
    restaurants, _ = await search_restaurants(session, q=q, limit=limit)
    items, _ = await search_menu_items(session, q=q, limit=limit)
    return {"restaurants": restaurants, "menu_items": items}


async def get_popular_nearby(
    session: AsyncSession,
    cache: Any,
    lat: float,
    lng: float,
    radius_km: float = 5.0,
) -> list[dict[str, Any]]:
    """Top 10 most-ordered-from restaurants in the last 7 days within radius."""
    s = get_settings()
    key = (
        f"cache:search:popular:lat={round(lat, 3)}:"
        f"lng={round(lng, 3)}:r={round(radius_km, 1)}"
    )

    async def _load() -> list[dict[str, Any]]:
        cutoff = datetime.now(UTC) - timedelta(days=s.SEARCH_TRENDING_WINDOW_DAYS)
        point_wkt = Point(lng, lat).wkt
        rows = (
            await session.execute(
                text(
                    "SELECT rp.id::text AS id, rp.restaurant_name, rp.rating, "
                    "rp.rating_count, "
                    "COUNT(o.id) AS order_count, "
                    "rp.opening_hours::text AS opening_hours "
                    "FROM orders o "
                    "JOIN restaurant_profiles rp ON rp.id = o.restaurant_id "
                    "WHERE o.status = 'delivered' AND o.placed_at >= :cutoff "
                    "AND rp.is_approved AND rp.is_active "
                    "AND ST_DWithin(rp.location, "
                    "ST_GeogFromText(CAST(:pt AS text)), :radius_m) "
                    "GROUP BY rp.id "
                    "ORDER BY order_count DESC, rp.rating DESC "
                    "LIMIT 10"
                ),
                {"cutoff": cutoff, "pt": point_wkt, "radius_m": radius_km * 1000},
            )
        ).mappings().all()
        return [
            {
                "id": row["id"],
                "restaurant_name": row["restaurant_name"],
                "rating": float(row["rating"] or 0),
                "rating_count": int(row["rating_count"] or 0),
                "order_count": int(row["order_count"]),
                "is_open": restaurant_is_open(row["opening_hours"]),
            }
            for row in rows
        ]

    if cache is None:
        return await _load()
    return await cache.get_or_set(key, _load, ttl_s=s.SEARCH_POPULAR_TTL_S)


from datetime import timedelta  # noqa: E402  (kept at bottom to avoid cycles)
