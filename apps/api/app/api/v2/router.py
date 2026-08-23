"""v2 API router aggregator.

Includes feature routers under ``/api/v2/``.
"""

from fastapi import APIRouter

from app.auth.router import router as auth_router
from app.core.config import get_settings
from app.restaurants.router import router as restaurants_router
from app.restaurants.top_router import router as top_router
from app.users.router import router as users_router

router = APIRouter()


@router.get("/")
def api_root() -> dict[str, str]:
    """Discovery endpoint for the v2 API namespace."""
    settings = get_settings()
    return {"name": settings.PROJECT_NAME, "version": settings.VERSION}


router.include_router(auth_router, tags=["auth"])
router.include_router(users_router, tags=["users"])
router.include_router(restaurants_router, tags=["restaurants"])
router.include_router(top_router, tags=["catalog"])
