"""Plunk email client — direct port of v1's PlunkEmailService.

v1 endpoint: https://api.useplunk.com/v1/send
v1 payload: {"to", "subject", "body", "type": "html"|"text"}
v1 auth: Bearer token in Authorization header
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


class PlunkClient:
    BASE_URL = "https://api.useplunk.com/v1/send"

    def __init__(self) -> None:
        from app.core.config import get_settings

        self._configured = bool(get_settings().PLUNK_API_KEY)

    @property
    def is_configured(self) -> bool:
        return self._configured

    def send_email(self, data: dict[str, Any]) -> bool:
        """Send email via Plunk. Returns True on success, False on failure.

        Args:
            data: dict with keys to_email, email_subject, email_body,
                  email_html (optional), email_type ("html" or "text",
                  default "html")
        """
        import requests  # lazy

        from app.core.config import get_settings

        s = get_settings()
        if not self._configured:
            logger.warning("PLUNK_API_KEY not configured; skipping email send")
            return False

        to_email = data.get("to_email")
        subject = data.get("email_subject")
        body = data.get("email_body")
        html_body = data.get("email_html")
        email_type = data.get("email_type", "html")

        if not all([to_email, subject, body]):
            logger.error(f"Missing required email fields: {list(data.keys())}")
            return False

        try:
            response = requests.post(
                self.BASE_URL,
                headers={
                    "Authorization": f"Bearer {s.PLUNK_API_KEY}",
                    "Content-Type": "application/json",
                },
                json={
                    "to": to_email,
                    "subject": subject,
                    "body": html_body if html_body else body,
                    "type": email_type,
                },
                timeout=10,
            )
            if 200 <= response.status_code < 300:
                logger.info(f"Plunk email sent to {to_email}: {subject}")
                return True
            logger.error(
                f"Plunk email failed to {to_email}: "
                f"{response.status_code} {response.text[:200]}"
            )
            return False
        except requests.RequestException as e:
            logger.error(f"Plunk email error to {to_email}: {e}")
            return False
