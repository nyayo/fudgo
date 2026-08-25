"""CacheService tests (fakeredis-backed)."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

fakeredis = pytest.importorskip("fakeredis")


@pytest.fixture
def r() -> Any:
    from fakeredis import aioredis as fr

    return fr.FakeRedis(decode_responses=True)


@pytest.fixture
def cache(r: Any) -> Any:
    from app.cache.cache_service import CacheService

    return CacheService(r, default_ttl_s=60)


async def test_get_set_delete_roundtrip(cache: Any) -> None:
    k = cache.key("menu_item", "abc")
    assert await cache.get(k) is None
    await cache.set(k, {"id": "abc", "price": "10.00"})
    assert await cache.get(k) == {"id": "abc", "price": "10.00"}
    assert await cache.delete(k) == 1
    assert await cache.get(k) is None


async def test_get_or_set_populates_on_miss(cache: Any) -> None:
    calls = 0

    async def loader() -> dict[str, int]:
        nonlocal calls
        calls += 1
        return {"v": 1}

    k = cache.key("thing", "1")
    first = await cache.get_or_set(k, loader)
    second = await cache.get_or_set(k, loader)
    assert first == second == {"v": 1}
    assert calls == 1  # second call served from cache


async def test_get_or_set_none_not_cached(cache: Any) -> None:
    calls = 0

    async def loader() -> None:
        nonlocal calls
        calls += 1
        return None

    k = cache.key("missing", "x")
    assert await cache.get_or_set(k, loader) is None
    assert await cache.get_or_set(k, loader) is None
    assert calls == 2  # never cached


async def test_ttl_expiry(cache: Any, r: Any) -> None:
    k = cache.key("ttl", "short")
    await cache.set(k, {"a": 1}, ttl_s=1)
    ttl = await r.ttl(k)
    assert 0 < ttl <= 1


async def test_delete_pattern_uses_scan(cache: Any) -> None:
    for i in range(5):
        await cache.set(f"cache:restaurant:r1:items:{i}", {"i": i})
    await cache.set("cache:restaurant:r2:items:0", {"keep": True})
    deleted = await cache.delete_pattern("cache:restaurant:r1:*")
    assert deleted == 5
    assert await cache.get("cache:restaurant:r2:items:0") == {"keep": True}


async def test_corrupt_json_returns_none(cache: Any, r: Any) -> None:
    k = cache.key("corrupt", "k")
    await r.set(k, "{not-json")
    assert await cache.get(k) is None


async def test_redis_failure_returns_none_gracefully(cache: Any) -> None:
    class _Broken:
        async def get(self, key: str) -> None:
            raise ConnectionError("redis down")

        def __getattr__(self, name: str) -> Any:
            async def _fail(*a: Any, **k: Any) -> None:
                raise ConnectionError("redis down")

            return _fail

    from app.cache.cache_service import CacheService

    broken = CacheService(_Broken())  # type: ignore[arg-type]
    assert await broken.get("cache:any:key") is None
    await broken.set("cache:any:key", {"x": 1})  # must not raise
    assert await broken.delete("cache:any:key") == 0
    assert await broken.delete_pattern("cache:*") == 0


async def test_key_namespacing() -> None:
    from app.cache.cache_service import CacheService

    assert (
        CacheService.key("menu_item", "abc-123")
        == "cache:menu_item:abc-123"
    )
    assert (
        CacheService.key("restaurant", "nearby", "lat=-1.3", "r=5")
        == "cache:restaurant:nearby:lat=-1.3:r=5"
    )


async def test_delete_empty_args(cache: Any) -> None:
    assert await cache.delete() == 0
