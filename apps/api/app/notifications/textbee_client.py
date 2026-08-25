"""TextBee SMS client — direct port of v1's SMSService.

v1 endpoint: https://sms.unshifter.site/api/v1/gateway/devices/{device_id}/send-sms
v1 payload: {"recipients": [phone], "message": text}
v1 auth: x-api-key header
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


class TextBeeClient:
    BASE_URL = "https://sms.unshifter.site/api/v1"

    def __init__(self) -> None:
        from app.core.config import get_settings

        s = get_settings()
        self._configured = bool(s.TEXTBEE_API_KEY and s.TEXTBEE_DEVICE_ID)

    @property
    def is_configured(self) -> bool:
        return self._configured

    def send_sms(self, phone: str, message: str) -> bool:
        """Send SMS via TextBee. Returns True on success.

        Args:
            phone: E.164 format, e.g. +254712345678
            message: SMS body (160 chars recommended)
        """
        import requests  # lazy

        from app.core.config import get_settings

        s = get_settings()
        if not self._configured:
            logger.warning(
                "TEXTBEE_API_KEY or TEXTBEE_DEVICE_ID not configured; skipping SMS"
            )
            return False

        url = f"{self.BASE_URL}/gateway/devices/{s.TEXTBEE_DEVICE_ID}/send-sms"
        try:
            response = requests.post(
                url,
                headers={
                    "x-api-key": s.TEXTBEE_API_KEY,
                    "Content-Type": "application/json",
                },
                json={"recipients": [phone], "message": message},
                timeout=10,
            )
            if 200 <= response.status_code < 300:
                logger.info(f"TextBee SMS sent to {phone}")
                return True
            logger.error(
                f"TextBee SMS failed to {phone}: "
                f"{response.status_code} {response.text[:200]}"
            )
            return False
        except requests.RequestException as e:
            logger.error(f"TextBee SMS error to {phone}: {e}")
            return False
