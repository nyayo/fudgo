"""Admin dependencies: get_current_admin + audit-log writer."""

from __future__ import annotations

from typing import Any

from fastapi import Depends, HTTPException, status

from app.auth.deps import get_current_user
from app.notifications.enums import AuditLogAction
from app.users.models import User


async def get_current_admin(
    user: User = Depends(get_current_user),
) -> User:
    if not user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin role required",
        )
    return user


def _celery_task(name: str) -> Any:
    def deco(fn):  # type: ignore[no-untyped-def]
        from app.core.celery_app import celery_app

        return celery_app.task(name=name)(fn)

    return deco


@_celery_task("admin.write_audit_log")
def write_audit_log_task(**kwargs: Any) -> dict[str, Any]:
    write_audit_log_sync(**kwargs)
    return {"written": True}


def write_audit_log_sync(
    actor_user_id: str,
    action: AuditLogAction | str,
    target_type: str,
    target_id: str,
    details: dict[str, Any] | None = None,
    ip_address: str | None = None,
    user_agent: str | None = None,
) -> None:
    """Sync audit write (safe from Celery eager mode and tests)."""
    from app.db.sync_session import get_sync_session_maker
    from app.notifications.models_payouts import AuditLog

    maker = get_sync_session_maker()
    with maker() as session:
        session.add(
            AuditLog(
                actor_user_id=actor_user_id,
                action=action.value if hasattr(action, "value") else action,
                target_type=target_type[:50],
                target_id=target_id[:100],
                details=details or {},
                ip_address=ip_address[:64] if ip_address else None,
                user_agent=user_agent[:500] if user_agent else None,
            )
        )
        session.commit()


def queue_audit_log(
    actor_user_id: str,
    action: AuditLogAction | str,
    target_type: str,
    target_id: str,
    details: dict[str, Any] | None = None,
    ip_address: str | None = None,
    user_agent: str | None = None,
) -> None:
    """Queue the audit write via Celery (sync fallback in eager mode)."""
    try:
        write_audit_log_task.delay(  # type: ignore[attr-defined]
            actor_user_id=actor_user_id,
            action=action.value if hasattr(action, "value") else action,
            target_type=target_type,
            target_id=target_id,
            details=details or {},
            ip_address=ip_address,
            user_agent=user_agent,
        )
    except Exception:
        write_audit_log_sync(
            actor_user_id, action, target_type, target_id,
            details, ip_address, user_agent,
        )
