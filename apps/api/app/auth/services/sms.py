"""Stub SMS service: Phase 6 swaps for Textbee."""

import logging

logger = logging.getLogger("fudgo.auth.sms")


async def send_otp(phone: str, code: str) -> None:
    """Phase 1 stub. Phase 6 will wire Textbee."""
    logger.info("OTP sms", extra={"to": phone, "code": code})
