"""Health endpoint tests against the migrated dev DB."""

from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


async def test_health_live_returns_200(client: AsyncClient) -> None:
    resp = await client.get("/health/live")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


async def test_health_ready_returns_200_and_writes_row(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    async def count(s: AsyncSession) -> int:
        result = await s.execute(text("SELECT COUNT(*) FROM app_healthcheck"))
        row = result.first()
        return int(row[0]) if row else 0

    before = await count(db_session)
    await client.get("/health/ready")
    after = await count(db_session)
    assert after == before + 1


async def test_metrics_endpoint_returns_prometheus_text(client: AsyncClient) -> None:
    resp = await client.get("/metrics")
    assert resp.status_code == 200
    assert "# HELP" in resp.text
