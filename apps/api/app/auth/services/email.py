"""Stub email service: Phase 6 swaps for real SMTP/Plunk."""

import logging

logger = logging.getLogger("fudgo.auth.email")


async def send_otp(email: str, code: str) -> None:
    """Phase 1 stub. Phase 6 will wire SMTP/Plunk."""
    logger.info("OTP email", extra={"to": email, "code": code})


async def send_password_reset(email: str, link: str) -> None:
    """Phase 1 stub. Phase 6 will wire SMTP/Plunk."""
    logger.info("password reset email", extra={"to": email, "link": link})
