"""Sync SQLAlchemy engine for Celery workers.

Celery tasks are synchronous; the asyncpg engine doesn't fit. We keep a
separate sync engine (psycopg2) that talks to the same database. Both
engines never share a connection.

FastAPI route handlers use :func:`app.db.session.get_session` (async).
Celery tasks use :func:`app.db.sync_session.get_sync_session` (sync).
Never mix them in the same code path.
"""

from __future__ import annotations

import os
from typing import Any

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

_sync_engine: Any = None
_sync_session_maker: Any = None


def _build_database_url_sync() -> str:
    """Build a psycopg2 URL from the async DATABASE_URL.

    Converts ``postgresql+asyncpg://`` -> ``postgresql+psycopg2://``.
    """
    from app.core.config import get_settings

    settings = get_settings()
    if settings.DATABASE_URL_SYNC:
        return settings.DATABASE_URL_SYNC
    return settings.DATABASE_URL.replace("+asyncpg", "+psycopg2")


def get_sync_engine() -> Any:
    global _sync_engine
    if _sync_engine is None:
        _sync_engine = create_engine(
            _build_database_url_sync(),
            pool_pre_ping=True,
            pool_size=5,
            max_overflow=10,
            future=True,
        )
    return _sync_engine


def get_sync_session_maker() -> Any:
    global _sync_session_maker
    if _sync_session_maker is None:
        _sync_session_maker = sessionmaker(
            bind=get_sync_engine(),
            autoflush=False,
            autocommit=False,
            expire_on_commit=False,
        )
    return _sync_session_maker
