"""v2 API router aggregator.

Phase 0 ships a single root discovery endpoint. Later phases will import their
feature routers here and ``include_router`` them under ``API_V2_PREFIX``.
"""

from fastapi import APIRouter

from app.core.config import get_settings

router = APIRouter()


@router.get("/")
def api_root() -> dict[str, str]:
    """Discovery endpoint for the v2 API namespace."""
    settings = get_settings()
    return {"name": settings.PROJECT_NAME, "version": settings.VERSION}


# Phase 1+: from app.features.auth.router import router as auth_router
# router.include_router(auth_router, prefix="/auth", tags=["auth"])
