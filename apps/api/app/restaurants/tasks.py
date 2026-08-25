"""Promotion lifecycle tasks — port of v1's restaurants/tasks.py."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Callable

from app.core.celery_app import celery_app


def _task(name: str) -> Callable[[Callable[..., Any]], Any]:
    def deco(fn: Callable[..., Any]) -> Any:
        return celery_app.task(name=name)(fn)

    return deco


def _now() -> datetime:
    return datetime.now(UTC)


def _maker() -> Any:
    from app.db.sync_session import get_sync_session_maker

    return get_sync_session_maker()


@_task("restaurants.activate_promotion")
def activate_promotion(promotion_id: str) -> str:
    return _set_active(promotion_id, True)


@_task("restaurants.deactivate_promotion")
def deactivate_promotion(promotion_id: str) -> str:
    return _set_active(promotion_id, False)


def _set_active(promotion_id: str, active: bool) -> str:
    from app.restaurants.models import Promotion

    with _maker() as session:
        promo = session.get(Promotion, promotion_id)
        if not promo:
            return "Promotion not found"
        promo.is_active = active
        session.commit()
    verb = "Activated" if active else "Deactivated"
    return f"{verb} promotion {promotion_id}"


@_task("restaurants.check_expired_promotions")
def check_expired_promotions() -> int:
    """Beat schedule: hourly. Deactivate promotions past end_date."""
    from app.restaurants.models import Promotion

    now = _now()
    with _maker() as session:
        expired = (
            session.query(Promotion)
            .filter(
                Promotion.end_date < now,
                Promotion.is_active == True,  # noqa: E712
            )
            .all()
        )
        for promo in expired:
            promo.is_active = False
        session.commit()
        return len(expired)


@_task("restaurants.check_scheduled_promotions")
def check_scheduled_promotions() -> int:
    """Beat schedule: hourly. Activate promotions whose start_date passed."""
    from app.restaurants.models import Promotion

    now = _now()
    with _maker() as session:
        scheduled = (
            session.query(Promotion)
            .filter(
                Promotion.start_date <= now,
                Promotion.is_active == False,  # noqa: E712
                Promotion.end_date > now,
            )
            .all()
        )
        for promo in scheduled:
            promo.is_active = True
        session.commit()
        return len(scheduled)
