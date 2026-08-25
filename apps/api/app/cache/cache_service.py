"""Redis cache-aside service."""

from __future__ import annotations

import json
import logging
from typing import Any, Awaitable, Callable

logger = logging.getLogger(__name__)


class CacheService:
    """Cache-aside pattern over redis.asyncio. Reads go through get_or_set()."""

    def __init__(self, redis_client: Any, default_ttl_s: int = 60) -> None:
        self._redis = redis_client
        self._default_ttl_s = default_ttl_s

    @staticmethod
    def key(namespace: str, *parts: Any) -> str:
        return "cache:" + namespace + ":" + ":".join(str(p) for p in parts)

    async def get(self, key: str) -> Any | None:
        try:
            raw = await self._redis.get(key)
        except Exception as e:
            logger.warning(f"cache.get failed for {key}: {e}")
            return None
        if raw is None:
            return None
        try:
            return json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return None

    async def set(self, key: str, value: Any, ttl_s: int | None = None) -> None:
        ttl = ttl_s if ttl_s is not None else self._default_ttl_s
        try:
            await self._redis.set(
                key, json.dumps(value, default=_dumps_default), ex=ttl
            )
        except Exception as e:
            logger.warning(f"cache.set failed for {key}: {e}")

    async def get_or_set(
        self,
        key: str,
        loader: Callable[[], Awaitable[Any]],
        ttl_s: int | None = None,
    ) -> Any:
        cached = await self.get(key)
        if cached is not None:
            return cached
        value = await loader()
        if value is not None:
            await self.set(key, value, ttl_s=ttl_s)
        return value

    async def delete(self, *keys: str) -> int:
        if not keys:
            return 0
        try:
            return await self._redis.delete(*keys)  # type: ignore[misc]
        except Exception as e:
            logger.warning(f"cache.delete failed for {keys}: {e}")
            return 0

    async def delete_pattern(self, pattern: str) -> int:
        deleted = 0
        try:
            async for key in self._redis.scan_iter(match=pattern, count=100):
                await self._redis.delete(key)
                deleted += 1
        except Exception as e:
            logger.warning(f"cache.delete_pattern failed for {pattern}: {e}")
        return deleted


def _dumps_default(obj: Any) -> str:
    if hasattr(obj, "isoformat"):
        return obj.isoformat()
    return str(obj)
