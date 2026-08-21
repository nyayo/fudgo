"""HTTP middleware: request context (request_id) and response timing.

- ``RequestContextMiddleware`` generates a uuid4 ``request_id`` per request,
  binds it into structlog's contextvars (so all logs in that request carry it),
  and mirrors it back as the ``X-Request-Id`` response header.
- ``TimingMiddleware`` logs each completed request's method, path, status, and
  duration in milliseconds.

Both subclasses of ``BaseHTTPMiddleware`` use the exact ``Request``/``Response``
protocol that starlette expects (``Callable[[Request], Awaitable[Response]]``)
rather than the looser ``Callable[[Request], Response]`` annotation typed
mistakenly in an earlier draft.
"""

import time
import uuid
from collections.abc import Awaitable, Callable

import structlog.contextvars
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response


class RequestContextMiddleware(BaseHTTPMiddleware):
    """Bind a unique request_id into structlog contextvars for every request."""

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        request_id = request.headers.get("x-request-id") or str(uuid.uuid4())
        structlog.contextvars.bind_contextvars(
            request_id=request_id,
            method=request.method,
            path=request.url.path,
        )
        response = await call_next(request)
        structlog.contextvars.clear_contextvars()
        response.headers.setdefault("X-Request-Id", request_id)
        return response


class TimingMiddleware(BaseHTTPMiddleware):
    """Log request duration in milliseconds once the response is complete."""

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        logger = structlog.get_logger("timing")
        start = time.perf_counter()
        response = await call_next(request)
        duration_ms = round((time.perf_counter() - start) * 1000, 2)
        await logger.ainfo(
            "request complete",
            method=request.method,
            path=request.url.path,
            status=response.status_code,
            duration_ms=duration_ms,
        )
        return response
