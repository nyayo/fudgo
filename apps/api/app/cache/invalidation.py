"""Cache invalidation Celery tasks. Fire from the service layer on writes.

Celery tasks run in separate (sync) worker processes that do NOT share
app.state with the API, so each task builds its own short-lived Redis
connection via ``_get_cache()`` rather than reusing the API's instance.
``set_cache`` exists so tests (and the API process, if it ever calls
these eagerly) can inject a CacheService.
"""

from __future__ import annotations

import asyncio
from typing import Any

from app.core.celery_app import celery_app

_injected_cache: Any = None


def set_cache(cache: Any) -> None:
    """Inject a CacheService (used by tests / eager mode)."""
    global _injected_cache
    _injected_cache = cache


def _get_cache() -> Any:
    if _injected_cache is not None:
        return _injected_cache
    # Build a standalone client for the worker process.
    from app.cache.cache_service import CacheService
    from app.core.config import get_settings

    try:
        from redis.asyncio import from_url

        client = from_url(
            get_settings().REDIS_URL_RESOLVED, decode_responses=True
        )
        return CacheService(client)
    except Exception:
        return None


def _task(name: str) -> Any:
    def deco(fn: Any) -> Any:
        return celery_app.task(name=name)(fn)

    return deco


def _key(namespace: str, *parts: Any) -> str:
    from app.cache.cache_service import CacheService

    return CacheService.key(namespace, *parts)


def _run(coro: Any) -> int:
    """Run the coroutine on a loop. Works from sync Celery workers AND
    from inside a running loop (eager mode in async tests) by delegating
    to a worker thread when necessary."""
    try:
        running = asyncio.get_running_loop()
    except RuntimeError:
        running = None
    if running is None:
        try:
            return int(asyncio.run(coro))
        except Exception:  # pragma: no cover
            return 0

    import concurrent.futures

    def _runner() -> int:
        return int(asyncio.run(coro))

    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
            return ex.submit(_runner).result()
    except Exception:
        return 0


@_task("cache.invalidate_menu_item")
def invalidate_menu_item(menu_item_id: str, restaurant_id: str | None = None) -> int:
    """Invalidate a menu item + its restaurant's cached reads."""
    cache = _get_cache()
    if cache is None:
        return 0

    async def _go() -> int:
        n = await cache.delete(_key("menu_item", menu_item_id))
        if restaurant_id:
            n += await cache.delete_pattern(
                f"cache:restaurant:{restaurant_id}:*"
            )
        await _close(cache)
        return n

    return _run(_go())


@_task("cache.invalidate_restaurant")
def invalidate_restaurant(restaurant_id: str) -> int:
    cache = _get_cache()
    if cache is None:
        return 0

    async def _go() -> int:
        n = await cache.delete_pattern(f"cache:restaurant:{restaurant_id}:*")
        await _close(cache)
        return n

    return _run(_go())


@_task("cache.invalidate_promotions")
def invalidate_promotions(restaurant_id: str | None = None) -> int:
    cache = _get_cache()
    if cache is None:
        return 0

    async def _go() -> int:
        if restaurant_id:
            n = await cache.delete(_key("promotion", "active", restaurant_id))
        else:
            n = await cache.delete_pattern("cache:promotion:active:*")
        await _close(cache)
        return n

    return _run(_go())


@_task("cache.invalidate_nearby")
def invalidate_nearby() -> int:
    cache = _get_cache()
    if cache is None:
        return 0

    async def _go() -> int:
        n = await cache.delete_pattern("cache:restaurant:nearby:*")
        await _close(cache)
        return n

    return _run(_go())


async def _close(cache: Any) -> None:
    client = getattr(cache, "_redis", None)
    if client is not None and _injected_cache is None:
        try:
            await client.aclose()
        except Exception:
            pass
