"""Health endpoints.

- ``GET /health/live`` — process liveness, no DB access. Always 200.
- ``GET /health/ready`` — readiness: verifies DB by executing ``SELECT 1`` and
  writing a row into ``app_healthcheck`` (created by migration 0001). 200 on
  success, 503 envelope on failure.
- ``GET /health`` — convenience alias; checks ready, returns 200 if ready,
  otherwise the 503 envelope.
"""

from datetime import UTC, datetime

from fastapi import APIRouter, Response
from sqlalchemy import text

from app.core.envelope import error_envelope
from app.db.session import AsyncSessionLocal

router = APIRouter(tags=["health"])


@router.get("/live")
async def live() -> dict[str, str]:
    """Liveness probe — no dependencies."""
    return {"status": "ok"}


async def _check_ready() -> tuple[bool, str | None]:
    """Run a real DB round-trip: SELECT 1 + insert into app_healthcheck."""
    try:
        async with AsyncSessionLocal() as session:
            await session.execute(text("SELECT 1"))
            await session.execute(text("INSERT INTO app_healthcheck DEFAULT VALUES"))
            await session.commit()
        return True, None
    except Exception as exc:  # noqa: BLE001 - we envelope any DB failure
        return False, f"{type(exc).__name__}: {exc}"


@router.get("/ready")
async def ready(response: Response) -> dict[str, object]:
    """Readiness probe — verifies the DB is reachable + writable."""
    ok, err = await _check_ready()
    if not ok:
        response.status_code = 503
        return error_envelope(503, "Database not ready", {"db": f"error: {err}"})
    return {
        "status": "ok",
        "db": "ok",
        "checked_at": datetime.now(UTC).isoformat(),
    }


@router.get("")
@router.get("/")
async def health(response: Response) -> dict[str, object]:
    """Convenience alias for readiness (live + ready both pass)."""
    ok, err = await _check_ready()
    if not ok:
        response.status_code = 503
        return error_envelope(503, "Service not ready", {"db": f"error: {err}"})
    return {
        "status": "ok",
        "db": "ok",
        "checked_at": datetime.now(UTC).isoformat(),
    }
