"""Stub push service: Phase 6 swaps for FCM/APNs."""

import logging
from uuid import UUID

logger = logging.getLogger("fudgo.auth.push")


async def register(user_id: UUID, registration_id: str, platform: str) -> None:
    """Phase 1 stub. Phase 6 wires FCM/APNs."""
    logger.info(
        "push device register",
        extra={
            "user_id": str(user_id),
            "registration_id": registration_id,
            "platform": platform,
        },
    )


async def unregister(user_id: UUID, registration_id: str) -> None:
    logger.info(
        "push device unregister",
        extra={"user_id": str(user_id), "registration_id": registration_id},
    )


async def send(user_id: UUID, title: str, body: str) -> None:
    logger.info("push send", extra={"user_id": str(user_id), "title": title, "body": body})
