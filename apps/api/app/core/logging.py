"""structlog JSON logging configuration.

All application logs render as JSON lines. Stdlib ``logging`` is redirected
through structlog's ``stdilb`` bridge so third-party loggers (uvicorn,
sqlalchemy, alembic) merge into the same structured stream with the same
processors. ``merge_contextvars`` injects any bound context (notably
``request_id`` set by ``RequestContextMiddleware``).
"""

import logging

import structlog
from structlog.contextvars import merge_contextvars
from structlog.processors import TimeStamper, add_log_level, format_exc_info

from app.core.config import get_settings


def configure_logging() -> None:
    """Idempotently configure structlog + stdlib redirect."""
    settings = get_settings()
    level = settings.LOG_LEVEL.upper()

    structlog.configure(
        processors=[
            merge_contextvars,
            add_log_level,
            structlog.stdlib.PositionalArgumentsFormatter(),
            TimeStamper(fmt="iso"),
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        wrapper_class=structlog.stdlib.BoundLogger,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )

    formatter = structlog.stdlib.ProcessorFormatter(
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            format_exc_info,
            structlog.processors.JSONRenderer(),
        ],
    )

    handler = logging.StreamHandler()
    handler.setFormatter(formatter)

    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level)

    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        logging.getLogger(name).setLevel(level)


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    """Return a named structlog logger."""
    return structlog.get_logger(name)  # type: ignore[no-any-return]
