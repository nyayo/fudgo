"""Cache invalidation task tests (eager Celery + fakeredis).

fakeredis clients are event-loop-bound, and the Celery tasks bridge from
sync to async via ``asyncio.run``. When eager Celery executes a task on
an asyncio test's already-running loop, ``asyncio.run`` would raise --
so these tests run everything inside one loop and temporarily swap in
``_run_on_running_loop`` for the task's bridge.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
from typing import Any

import pytest

fakeredis = pytest.importorskip("fakeredis")


def _run_on_running_loop(coro: Any) -> Any:
    """Bridge for eager Celery tasks when a loop is already running."""
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
        return ex.submit(asyncio.run, coro).result()


async def _with_cache(fn: Any) -> Any:
    """Create a fakeredis-backed CacheService, run fn(cache), cleanup."""
    from app.cache.cache_service import CacheService
    from app.cache.invalidation import set_cache

    from fakeredis import aioredis as fr

    cache = CacheService(fr.FakeRedis(decode_responses=True))
    set_cache(cache)
    try:
        return await fn(cache)
    finally:
        set_cache(None)


def _eager_call(task: Any, *args: Any, **kwargs: Any) -> int:
    """Invoke an eager Celery task; its _run() bridges loops itself."""
    return task.apply(args=list(args), kwargs=kwargs).get()  # type: ignore[assignment]


@pytest.fixture(autouse=True)
def _reset_injection() -> Any:
    from app.cache.invalidation import set_cache

    yield
    set_cache(None)


def test_invalidate_menu_item() -> None:
    from app.cache.invalidation import invalidate_menu_item

    async def scenario(cache: Any) -> None:
        await cache.set("cache:menu_item:mi-1", {"id": "mi-1"})
        n = _eager_call(invalidate_menu_item, "mi-1")
        assert n >= 1
        assert await cache.get("cache:menu_item:mi-1") is None

    asyncio.run(_with_cache(scenario))


def test_invalidate_menu_item_with_restaurant_pattern() -> None:
    from app.cache.invalidation import invalidate_menu_item

    async def scenario(cache: Any) -> None:
        await cache.set("cache:menu_item:mi-2", "{}")
        rest_keys = [f"cache:restaurant:r-9:{p}" for p in ("items", "detail")]
        for k in rest_keys:
            await cache.set(k, "{}")
        n = _eager_call(invalidate_menu_item, "mi-2", "r-9")
        assert n == 3
        assert await cache.get("cache:menu_item:mi-2") is None
        for k in rest_keys:
            assert await cache.get(k) is None

    asyncio.run(_with_cache(scenario))


def test_invalidate_restaurant_pattern() -> None:
    from app.cache.invalidation import invalidate_restaurant

    async def scenario(cache: Any) -> None:
        for i in range(3):
            await cache.set(f"cache:restaurant:r-1:p{i}", "{}")
        await cache.set("cache:restaurant:r-2:p0", "{}")
        n = _eager_call(invalidate_restaurant, "r-1")
        assert n == 3
        assert await cache.get("cache:restaurant:r-2:p0") is not None

    asyncio.run(_with_cache(scenario))


def test_invalidate_promotions_specific_vs_global() -> None:
    from app.cache.invalidation import invalidate_promotions

    async def scenario(cache: Any) -> None:
        await cache.set("cache:promotion:active:r-5", "{}")
        await cache.set("cache:promotion:active:global", {})
        _eager_call(invalidate_promotions, "r-5")
        assert await cache.get("cache:promotion:active:r-5") is None
        # Global untouched by restaurant-specific invalidation.
        assert await cache.get("cache:promotion:active:global") == {}

    asyncio.run(_with_cache(scenario))


def test_invalidate_nearby_pattern() -> None:
    from app.cache.invalidation import invalidate_nearby

    async def scenario(cache: Any) -> None:
        for lat in ("-1.29", "-1.30", "-1.31"):
            await cache.set(f"cache:restaurant:nearby:lat={lat}:r=5", "[]")
        n = _eager_call(invalidate_nearby)
        assert n == 3

    asyncio.run(_with_cache(scenario))


def test_tasks_noop_when_no_cache_and_no_redis() -> None:
    """With no injected cache and no reachable Redis, tasks degrade to 0."""
    from app.cache import invalidation as inv
    from app.cache.invalidation import set_cache

    set_cache(None)
    # REDIS_HOST default ('redis') doesn't resolve in CI; from_url itself
    # won't fail until connect, so force failure by pointing at an invalid
    # port via monkeypatched settings.
    from app.core.config import get_settings

    s = get_settings()
    orig_host = s.REDIS_HOST
    s.REDIS_HOST = "127.0.0.1"
    orig_port = s.REDIS_PORT
    s.REDIS_PORT = 1  # nothing listens here; connect fails fast
    try:
        assert inv.invalidate_menu_item.apply(args=["x"]).get() == 0
    finally:
        s.REDIS_HOST = orig_host
        s.REDIS_PORT = orig_port
