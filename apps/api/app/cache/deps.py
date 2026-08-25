"""FastAPI dependency providing the CacheService from app.state.

Returns None when the cache is not configured (no Redis), so endpoints
degrade gracefully to direct DB reads.
"""

from __future__ import annotations

from typing import Any

from fastapi import Request


async def get_cache(request: Request) -> Any | None:
    cache = getattr(request.app.state, "cache", None)
    if cache is None:
        return None
    from app.core.config import get_settings

    if not get_settings().CACHE_ENABLED:
        return None
    return cache
