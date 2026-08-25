"""Firebase Admin SDK for FCM — v1 pattern, env-var credentials (no *.json files).

v1 leaked delivery-1d642-firebase-adminsdk-*.json into the repo; v2 reads
the service-account JSON from FIREBASE_CREDENTIALS_JSON.
"""

from __future__ import annotations

import json
import logging
from typing import Any

logger = logging.getLogger(__name__)

_initialized = False


def _ensure_initialized() -> bool:
    global _initialized
    if _initialized:
        return True
    from app.core.config import get_settings

    creds_json = get_settings().FIREBASE_CREDENTIALS_JSON
    if not creds_json:
        logger.warning(
            "FIREBASE_CREDENTIALS_JSON not configured; FCM will be a no-op"
        )
        return False
    try:
        import firebase_admin
        from firebase_admin import credentials

        cred_dict = json.loads(creds_json)
        cred = credentials.Certificate(cred_dict)
        firebase_admin.initialize_app(cred)
        _initialized = True
        return True
    except Exception as e:
        logger.error(f"Failed to initialize Firebase: {e}")
        return False


def send_fcm(
    token: str,
    title: str,
    body: str,
    data: dict[str, Any] | None = None,
) -> str | None:
    """Send one FCM message. Returns the FCM message_id, or None on failure.

    Raises firebase_admin.messaging.UnregisteredError for dead tokens so
    the caller can mark the device inactive.
    """
    if not _ensure_initialized():
        return None
    from firebase_admin import messaging

    # FCM requires string values in data
    string_data = {k: str(v) for k, v in (data or {}).items()}
    message = messaging.Message(
        notification=messaging.Notification(title=title, body=body),
        data=string_data,
        token=token,
        android=messaging.AndroidConfig(
            priority="high",
            notification=messaging.AndroidNotification(
                sound="default", channel_id="default"
            ),
        ),
        apns=messaging.APNSConfig(
            payload=messaging.APNSPayload(
                aps=messaging.Aps(sound="default", badge=1),
            ),
        ),
    )
    try:
        msg_id: str | None = messaging.send(message)
        return msg_id
    except messaging.UnregisteredError:
        raise
    except Exception as e:
        logger.error(f"FCM send error: {e}")
        raise
