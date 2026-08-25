"""In-app notification feed (Phase 6)."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Column, DateTime, Index, Text, func
from sqlmodel import Field, SQLModel


class Notification(SQLModel, table=True):
    __tablename__ = "notifications"
    __table_args__ = (
        Index("ix_notifications_user_read_created", "user_id", "is_read", "created_at"),
        Index("ix_notifications_order", "order_id"),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    user_id: uuid.UUID = Field(
        foreign_key="users.id", index=True, nullable=False
    )
    event_type: str = Field(max_length=50, nullable=False)
    message: str = Field(sa_column=Column(Text, nullable=False))
    order_id: uuid.UUID | None = Field(
        default=None, foreign_key="orders.id", index=True, nullable=True
    )
    is_read: bool = Field(default=False, nullable=False)
    redirect_url: str | None = Field(default=None, max_length=500, nullable=True)
    created_at: datetime = Field(
        sa_column=Column(
            DateTime(timezone=True),
            server_default=func.now(),
            nullable=False,
        )
    )
