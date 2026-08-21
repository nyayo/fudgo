"""Health endpoint tests against the migrated dev DB."""

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


async def test_health_live_returns_200(client: AsyncClient) -> None:
    resp = await client.get("/health/live")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


async def test_health_ready_returns_200_and_writes_row(
    client: AsyncClient, session: AsyncSession
) -> None:
    async def count() -> int:
        result = await session.execute(text("SELECT COUNT(*) FROM app_healthcheck"))
        row = result.first()
        return int(row[0]) if row else 0

    before = await count()
    await client.get("/health/ready")
    after = await count()
    assert after == before + 1


async def test_envelope_shape_on_error(client: AsyncClient) -> None:
    resp = await client.get("/db/does-not-exist")
    body = resp.json()
    assert resp.status_code == 404
    assert body["success"] is False
    assert set(body["error"].keys()) >= {"code", "message", "details"}


async def test_metrics_endpoint_returns_prometheus_text(client: AsyncClient) -> None:
    resp = await client.get("/metrics")
    assert resp.status_code == 200
    assert "# HELP" in resp.text


@pytest.mark.anyio
async def test_health_live_via_get(client: AsyncClient) -> None:
    """Smoke: ensure the route is also on the API router for convenience."""
    resp = await client.get("/health/live")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}
