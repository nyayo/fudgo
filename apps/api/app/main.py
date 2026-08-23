"""FastAPI application factory.

Assembles the app: lifespan (logging/metrics init + engine disposal), ordered
middleware, and exception handlers that always serialize into the v1 envelope.
Exported both as ``create_app()`` for tests and as the module-level ``app``
that uvicorn/asgi servers bind to.
"""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi.errors import RateLimitExceeded
from sqlalchemy.exc import SQLAlchemyError
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.v2.router import router as api_v2_router
from app.auth.deps import limiter
from app.core.config import get_settings
from app.core.envelope import error_envelope
from app.core.exceptions import AppError
from app.core.logging import configure_logging
from app.core.middleware import RequestContextMiddleware, TimingMiddleware
from app.db.session import engine
from app.health.router import router as health_router
from app.observability.metrics import setup_metrics

logger = structlog.get_logger("fudgo.api")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:  # noqa: ARG001
    """Startup: configure logging + metrics. Shutdown: dispose engine."""
    settings = get_settings()
    configure_logging()
    logger.info(
        "fudgo-api starting",
        environment=settings.ENVIRONMENT,
        host=settings.HOST,
        port=settings.PORT,
        db_host=settings.DB_HOST,
        version=settings.VERSION,
    )
    yield
    await engine.dispose()
    logger.info("fudgo-api shutdown complete")


def _register_exception_handlers(app: FastAPI) -> None:
    """All handlers serialize into the v1 error envelope."""

    @app.exception_handler(AppError)
    async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:  # noqa: ARG001
        return JSONResponse(
            status_code=exc.code,
            content=error_envelope(exc.code, exc.message, exc.details),
        )

    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(
        request: Request,  # noqa: ARG001
        exc: StarletteHTTPException,
    ) -> JSONResponse:
        details: dict[str, object] = {"detail": exc.detail} if isinstance(exc.detail, dict) else {}
        return JSONResponse(
            status_code=exc.status_code,
            content=error_envelope(exc.status_code, str(exc.detail), details),
        )

    @app.exception_handler(RequestValidationError)
    async def validation_handler(
        request: Request,  # noqa: ARG001
        exc: RequestValidationError,
    ) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content=error_envelope(422, "Validation error", {"errors": exc.errors()}),
        )

    @app.exception_handler(SQLAlchemyError)
    async def sqlalchemy_handler(request: Request, exc: SQLAlchemyError) -> JSONResponse:  # noqa: ARG001
        logger.exception("database error", exc_info=exc)
        return JSONResponse(
            status_code=500,
            content=error_envelope(500, "Internal server error"),
        )

    @app.exception_handler(Exception)
    async def unhandled_handler(request: Request, exc: Exception) -> JSONResponse:  # noqa: ARG001
        logger.exception("unhandled error", exc_info=exc)
        return JSONResponse(
            status_code=500,
            content=error_envelope(500, "Internal server error"),
        )


def create_app() -> FastAPI:
    """Build and return the configured FastAPI instance."""
    settings = get_settings()
    configure_logging()

    app = FastAPI(
        title=settings.PROJECT_NAME,
        version=settings.VERSION,
        description=(
            "Food-delivery backend v2, reimplementing the Django/DRF v1 "
            "(https://github.com/nyayo/Fudz_api) on FastAPI + SQLModel + PostGIS."
        ),
        contact={"name": "Fudz", "url": "https://github.com/nyayo/Fudz_api_v2"},
        lifespan=lifespan,
    )

    # Middleware (last added runs first for requests, so order here is reversed
    # to put request-context first logically — both needed for structlog).
    app.add_middleware(TimingMiddleware)
    app.add_middleware(RequestContextMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"] if settings.CORS_ALLOW_ALL_ORIGINS else settings.CORS_ALLOWED_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    _register_exception_handlers(app)

    app.include_router(health_router, prefix="/health")
    app.include_router(api_v2_router, prefix=settings.API_V2_PREFIX)

    configure_logging()
    setup_metrics(app)

    # slowapi integration
    app.state.limiter = limiter

    @app.exception_handler(RateLimitExceeded)
    async def rate_limit_handler(  # type: ignore[no-untyped-def]
        request: Request, exc: RateLimitExceeded
    ) -> JSONResponse:
        return JSONResponse(
            status_code=429,
            content=error_envelope(429, "Too many requests", {"limit": str(exc.detail)}),
        )

    return app


app = create_app()
