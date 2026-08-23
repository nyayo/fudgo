"""Delivery-domain singletons (ConnectionManager reference, etc.).

Avoids circular imports by deferring the import of :mod:`app.main` until
the singleton is first touched.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.realtime.connection_manager import ConnectionManager


_manager_ref: "ConnectionManager | None" = None


def set_connection_manager(manager: "ConnectionManager | None") -> None:
    """Called from :func:`app.main.lifespan`."""
    global _manager_ref
    _manager_ref = manager


def get_connection_manager() -> "ConnectionManager | None":
    if _manager_ref is None:
        # Best-effort late import; only used in tests that don't run the lifespan.
        try:
            from app.main import app

            return getattr(app.state, "connection_manager", None)
        except Exception:
            return None
    return _manager_ref
